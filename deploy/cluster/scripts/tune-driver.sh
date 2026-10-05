#!/usr/bin/env bash
# 串行跑两个调优变体（node1 执行）
#
# 为什么串行且都重跑：变体之间要重启服务（env 变化），而重启会让 JIT 归零。
# 只重跑其中一个、拿它跟"上一个还带着负载热度的变体"比，结论会是错的
# ——2026-10-06 就踩过：pool 8→10 看似把吞吐砍半，其实是冷热差异。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for candidate in "$HERE/../../deploy/cluster/nodes.env" "/opt/cluster/nodes.env"; do
  [ -f "$candidate" ] && { NODES_ENV="$candidate"; break; }
done
# shellcheck source=/dev/null
source "$NODES_ENV"
RT=/opt/smartlect/run/runtime.env
RESULTS=/opt/cluster/evidence/tuning-results.tsv

set_pool() { # $1=池大小
  for ip in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    if [ "$ip" = "$NODE1_IP" ]; then
      sed -i "s/^SMARTLECT_DB_POOL_MAX_SIZE=.*/SMARTLECT_DB_POOL_MAX_SIZE=$1/" "$RT"
    else
      ssh $CLUSTER_SSH_OPTS "root@$ip" "sed -i 's/^SMARTLECT_DB_POOL_MAX_SIZE=.*/SMARTLECT_DB_POOL_MAX_SIZE=$1/' $RT"
    fi
  done
  echo "[driver] 已把连接池设为 $1，重启三节点…"
  ( systemctl restart smartlect-apps ) &
  ssh $CLUSTER_SSH_OPTS "root@$NODE2_IP" "systemctl restart smartlect-apps" &
  ssh $CLUSTER_SSH_OPTS "root@$NODE3_IP" "systemctl restart smartlect-apps" &
  wait
  sleep 15
  (cd /opt/smartlect && /usr/bin/python3 scripts/runtime.py apps-check 2>&1 | tail -1)
}

run_variant() { # $1=标签
  echo "[driver] === 跑变体 $1 ==="
  bash "$HERE/tune-benchmark.sh" "$1" "$RESULTS"
}

rm -f "$RESULTS"
set_pool 10
run_variant "V1-pool10"
set_pool 8
run_variant "V0-pool8"
echo "[driver] 两个变体完成，结果在 $RESULTS"
