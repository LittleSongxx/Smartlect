#!/usr/bin/env bash
# 集群终态验证 + 证据采集（node1 执行；只读，不改任何状态）
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
EV="$CL/evidence"
mkdir -p "$EV"
log() { echo "[verify $(date +%T)] $*"; }
remote() { ssh $CLUSTER_SSH_OPTS "root@$1" "$2"; }
VHOST="${SMARTLECT_RABBIT_VHOST:-smartlect}"

log "== RabbitMQ =="
docker exec rabbit-c1 rabbitmqctl cluster_status --formatter=json > "$EV/rabbit-cluster-status.json"
python3 - "$EV/rabbit-cluster-status.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
run = s["running_nodes"]
print("running:", sorted(run if isinstance(run, list) else run.values()))
print("partitions:", s.get("partitions") or "none")
PY
docker exec rabbit-c1 rabbitmqctl list_queues -p "$VHOST" --silent name messages | sort > "$EV/rabbit-queues.txt"
echo "queues: $(wc -l < "$EV/rabbit-queues.txt")"
echo "queued messages total: $(awk '{s+=$2} END {print s+0}' "$EV/rabbit-queues.txt")"

log "== Redis =="
PW=$(grep -oP '^REDIS_PASSWORD=\K.*' "$CL/sentinel/.env")
docker exec smartlect-redis-1 redis-cli -a "$PW" --no-auth-warning info replication \
  | grep -E '^(role|connected_slaves|slave[0-9])' | tee "$EV/redis-replication.txt"
for ip in "$NODE2_IP" "$NODE3_IP"; do
  echo "-- replica $ip --" >> "$EV/redis-replication.txt"
  remote "$ip" "docker exec redis-replica redis-cli -a '$PW' --no-auth-warning info replication | grep -E '^(role|master_host|master_link_status)'" >> "$EV/redis-replication.txt"
done
cat "$EV/redis-replication.txt"
docker exec redis-sentinel redis-cli -p "$SENTINEL_PORT" sentinel master mymaster \
  | grep -E '^(ip|port|flags|num-slaves|num-other-sentinels|down-after)' | tee -a "$EV/redis-replication.txt"

log "== Nacos =="
{
  for ip in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    printf "%s readiness: " "$ip"; curl -s -m 3 "http://$ip:8848/nacos/v1/console/health/readiness" || echo -n "(unreachable)"; echo
  done
} | tee "$EV/nacos-readiness.txt"

log "== 应用侧 =="
if [ -d /opt/smartlect ]; then
  (cd /opt/smartlect && /usr/bin/python3 scripts/runtime.py apps-check 2>&1 | tail -5) | tee "$EV/apps-check.txt" || true
fi
log "evidence saved to $EV"
