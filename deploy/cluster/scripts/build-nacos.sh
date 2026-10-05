#!/usr/bin/env bash
# Nacos 3 节点集群（node1 执行）
#
# 关键约束：集群成员与单机实例**共用同一个 smartlect_nacos 库**，两者绝不能同时在线
# （两个独立 Nacos 读写同一份持久化数据会互相破坏），所以必须先停单机容器。
# 从 standalone 切到 cluster 不需要迁移配置数据——库里已经有。
#
# 前置：mysql 已监听内网 13306（deploy/cluster/compose.node1.yaml），gen-cluster-env.sh 已跑。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
OLD="${OLD_NACOS_CONTAINER:-smartlect-nacos-1}"
log() { echo "[build-nacos $(date +%T)] $*"; }
remote() { ssh $CLUSTER_SSH_OPTS "root@$1" "$2"; }

if docker inspect -f '{{.State.Running}}' "$OLD" 2>/dev/null | grep -q true; then
  log "stopping single-node nacos $OLD (container kept for rollback)..."
  docker stop "$OLD" >/dev/null
fi

log "starting nacos-c1/c2/c3 (cluster mode)..."
# 集群模式单成员过不了 readiness 仲裁：三成员先全部拉起，再统一轮询
cd "$CL/nacos"
NACOS_NODE_NAME="$NODE1_NAME" NACOS_NODE_SLOT=1 docker compose -f compose.cluster.yaml --env-file .env up -d
for n in 2 3; do
  eval "ip=\$NODE${n}_IP"; eval "name=\$NODE${n}_NAME"
  remote "$ip" "cd $CL/nacos && NACOS_NODE_NAME=$name NACOS_NODE_SLOT=$n docker compose -f compose.cluster.yaml --env-file .env up -d"
done

log "waiting for raft election + readiness (up to 3 min)..."
ok=0
for _ in $(seq 1 36); do
  ok=0
  for ip in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    curl -fsS -m 3 "http://$ip:8848/nacos/v1/console/health/readiness" >/dev/null 2>&1 && ok=$((ok+1))
  done
  [ "$ok" -eq 3 ] && break
  sleep 5
done
log "readiness pass: $ok/3 (expect 3)"

mkdir -p "$CL/evidence"
{
  for ip in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    printf "%s readiness: " "$ip"; curl -s -m 3 "http://$ip:8848/nacos/v1/console/health/readiness" || echo -n "(unreachable)"; echo
  done
} | tee "$CL/evidence/nacos-readiness.txt"

if [ "$ok" -ne 3 ]; then
  echo "--- nacos-c1 last log lines ---"
  docker logs nacos-c1 2>&1 | tail -20
  exit 1
fi

log "member list (nacos-c1 log):"
docker logs nacos-c1 2>&1 | grep -iE "cluster|member|leader" | tail -5 || true
log "nacos cluster READY"
