#!/usr/bin/env bash
# Redis 1 主（node1 容器，集群期已监听内网 6379）+ 2 副本（node2/3）+ 3 Sentinel
#
# 前置：
#   - deploy/cluster/compose.node1.yaml 已叠加并 up（node1 redis 绑到内网 + 补 masterauth）
#   - gen-cluster-env.sh 已生成 .env
#   - /opt/cluster 下各组件目录已分发到 node2/node3
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
log() { echo "[build-redis $(date +%T)] $*"; }

remote() { ssh $CLUSTER_SSH_OPTS "root@$1" "$2"; }

# 1) 两副本
for pair in "$NODE2_IP $NODE2_NAME" "$NODE3_IP $NODE3_NAME"; do
  set -- $pair; ip=$1
  log "starting redis-replica on $ip..."
  remote "$ip" "cd $CL/redis && REPLICA_ANNOUNCE_IP=$ip docker compose -f compose.replica.yaml --env-file .env up -d --wait --wait-timeout 120"
done

sleep 5
PW=$(grep -oP '^REDIS_PASSWORD=\K.*' "$CL/sentinel/.env")
for pair in "$NODE2_IP $NODE2_NAME" "$NODE3_IP $NODE3_NAME"; do
  set -- $pair; ip=$1
  link=$(remote "$ip" "docker exec redis-replica redis-cli -a '$PW' --no-auth-warning info replication | grep master_link_status")
  log "replica $ip: $link"
  case "$link" in *up*) ;; *) echo "replica on $ip not synced: $link"; exit 1;; esac
done

# 2) 三 Sentinel（配置就地生成：含密码，不入库；目录挂载供 sentinel CONFIG REWRITE）
gen_conf() { # $1=announce-ip  $2=conf 目录名
  local dir="$CL/sentinel/$2"
  mkdir -p "$dir"
  cat > "$dir/sentinel.conf" <<EOF
port $SENTINEL_PORT
sentinel resolve-hostnames no
sentinel announce-ip $1
sentinel announce-port $SENTINEL_PORT
sentinel monitor mymaster $NODE1_IP $REDIS_PORT 2
sentinel auth-pass mymaster $PW
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 30000
sentinel parallel-syncs mymaster 1
EOF
  chmod -R 777 "$dir"
}

log "starting sentinel on $NODE1_IP..."
gen_conf "$NODE1_IP" conf-node1
cd "$CL/sentinel" && SENTINEL_CONF_DIR=conf-node1 docker compose -f compose.sentinel.yaml --env-file .env up -d --wait --wait-timeout 120

for pair in "$NODE2_IP conf-node2" "$NODE3_IP conf-node3"; do
  set -- $pair; ip=$1; dir=$2
  log "starting sentinel on $ip..."
  # 远端生成同款配置（只有 announce-ip 不同），再拉起
  remote "$ip" "mkdir -p $CL/sentinel/$dir && cat > $CL/sentinel/$dir/sentinel.conf <<'EOF'
port $SENTINEL_PORT
sentinel resolve-hostnames no
sentinel announce-ip $ip
sentinel announce-port $SENTINEL_PORT
sentinel monitor mymaster $NODE1_IP $REDIS_PORT 2
sentinel auth-pass mymaster $PW
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 30000
sentinel parallel-syncs mymaster 1
EOF
chmod -R 777 $CL/sentinel/$dir && cd $CL/sentinel && SENTINEL_CONF_DIR=$dir docker compose -f compose.sentinel.yaml --env-file .env up -d --wait --wait-timeout 120"
done

# 3) 断言
sleep 5
MASTER=$(docker exec redis-sentinel redis-cli -p "$SENTINEL_PORT" sentinel get-master-addr-by-name mymaster | head -1)
OTHERS=$(docker exec redis-sentinel redis-cli -p "$SENTINEL_PORT" sentinel master mymaster | grep -A1 num-other-sentinels | tail -1)
REPLICAS=$(docker exec redis-sentinel redis-cli -p "$SENTINEL_PORT" sentinel master mymaster | grep -A1 num-slaves | tail -1)
log "sentinel master=$MASTER other-sentinels=$OTHERS replicas=$REPLICAS"
[ "$MASTER" = "$NODE1_IP" ] || { echo "unexpected master: $MASTER"; exit 1; }
[ "$OTHERS" = "2" ] || { echo "sentinel quorum incomplete ($OTHERS/2)"; exit 1; }
[ "$REPLICAS" = "2" ] || { echo "expected 2 replicas, got $REPLICAS"; exit 1; }
log "redis 1m2s + 3 sentinels READY"
