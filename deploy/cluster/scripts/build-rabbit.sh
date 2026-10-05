#!/usr/bin/env bash
# RabbitMQ 3 节点 quorum 集群：从当前单机 broker 导出拓扑 → 新集群导入
#
# 设计取舍：**不迁移单机数据卷**。集群成员用全新卷（节点名从 rabbit@<容器ID> 变成
# rabbit@smartlect-nodeN，mnesia 数据本来就不可复用），拓扑走 export/import_definitions。
# 单机卷 smartlect_rabbit 原样保留，回退时 docker start 即恢复旧 broker。
#
# 前置：apps 已停（维护窗口），旧单机 rabbitmq 容器仍在运行（用于导出 defs）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
OLD="${OLD_RABBIT_CONTAINER:-smartlect-rabbitmq-1}"
VHOST="${SMARTLECT_RABBIT_VHOST:-smartlect}"
log() { echo "[build-rabbit $(date +%T)] $*"; }
remote() { ssh $CLUSTER_SSH_OPTS "root@$1" "$2"; }

# 1) 导出单机拓扑（users/vhosts/permissions/exchanges/queues/bindings/policies）
DEFS="$CL/rabbit/defs.json"
if docker inspect -f '{{.State.Running}}' "$OLD" 2>/dev/null | grep -q true; then
  log "exporting definitions from $OLD ..."
  docker exec "$OLD" rabbitmqctl export_definitions /tmp/defs.json
  docker cp "$OLD:/tmp/defs.json" "$DEFS"
  QUEUE_N=$(docker exec "$OLD" rabbitmqctl list_queues -p "$VHOST" --silent name | wc -l)
  log "exported: $(stat -c%s "$DEFS") bytes, $QUEUE_N queues in vhost $VHOST"
else
  [ -s "$DEFS" ] || { echo "$OLD not running and no cached defs.json; cannot proceed"; exit 1; }
  log "reusing existing $DEFS"
fi

# 2) 停旧 broker 释放 5672/15672（容器保留，回退用）
log "stopping single-node broker $OLD (container kept for rollback)..."
docker stop "$OLD" >/dev/null

# 3) 三节点拉起
cd "$CL/rabbit"
log "starting rabbit-c1 (seed, host network)..."
docker compose -f compose.c1.yaml --env-file .env up -d --wait --wait-timeout 180
for n in 2 3; do
  eval "ip=\$NODE${n}_IP"
  log "starting rabbit-c$n on $ip..."
  remote "$ip" "cd $CL/rabbit && docker compose -f compose.c$n.yaml --env-file .env up -d --wait --wait-timeout 180"
done

# 4) c2/c3 加入集群
for n in 2 3; do
  eval "name=\$NODE${n}_NAME"
  log "joining rabbit-c$n -> rabbit@$NODE1_NAME ..."
  remote "$(eval echo \$NODE${n}_IP)" "for i in \$(seq 1 20); do
      docker exec rabbit-c$n rabbitmqctl stop_app >/dev/null 2>&1
      docker exec rabbit-c$n rabbitmqctl reset >/dev/null 2>&1
      docker exec rabbit-c$n rabbitmqctl join_cluster rabbit@$NODE1_NAME >/dev/null 2>&1 && \
        docker exec rabbit-c$n rabbitmqctl start_app >/dev/null 2>&1 && exit 0
      sleep 5
    done; echo 'join failed for rabbit-c$n'; exit 1"
done

# 5) 集群状态断言（3 节点 running、无分区）
log "cluster status:"
docker exec rabbit-c1 rabbitmqctl cluster_status --formatter=json > "$CL/evidence/rabbit-cluster-status.json"
python3 - "$CL/evidence/rabbit-cluster-status.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
run = s["running_nodes"]
names = sorted(run if isinstance(run, list) else run.values())
assert len(names) == 3, f"expect 3 running nodes, got {names}"
print("running_nodes:", names)
assert not s.get("partitions"), f"partitions present: {s.get('partitions')}"
PY

# 6) 导入拓扑并断言队列数
log "importing definitions..."
docker exec rabbit-c1 rabbitmqctl import_definitions /defs/defs.json
sleep 3
N_QUEUES=$(docker exec rabbit-c1 rabbitmqctl list_queues -p "$VHOST" --silent name | wc -l)
EXPECTED=$(python3 -c "import json,sys; d=json.load(open('$DEFS')); print(len([q for q in d.get('queues',[]) if q.get('vhost')=='$VHOST']))")
log "queues after import: $N_QUEUES (definitions declared $EXPECTED)"
[ "$N_QUEUES" -eq "$EXPECTED" ] || { echo "queue import incomplete: $N_QUEUES != $EXPECTED"; exit 1; }
docker exec rabbit-c1 rabbitmqctl list_queues -p "$VHOST" --silent name type | awk '{print $2}' | sort | uniq -c

# 7) 抽查 quorum 副本跨三节点
Q=$(docker exec rabbit-c1 rabbitmqctl list_queues -p "$VHOST" --silent name | sed -n 1p)
log "quorum members of '$Q':"
docker exec rabbit-c1 rabbitmqctl quorum_status "$Q" --formatter=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ", [m["Name"] for m in d.get("RaftMembers",[]) if m.get("State")=="member"])' || true
log "rabbit cluster READY"
