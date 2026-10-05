#!/usr/bin/env bash
# postOrder 长耗时排查（node1 执行）
#
# 做法：跑固定并发的下单负载 → 确认负载确实在跑（按订单服务请求计数增量判定）→
# 对三个 order 副本同时取线程转储 → 聚合"请求线程卡在哪一帧"。
#
# 为什么用线程转储而不是看指标：JRE 环境（非 JDK）没有 jstack，而 SIGQUIT(kill -3)
# 会把完整线程栈写进服务日志，零依赖。指标只能告诉我们"慢"，线程栈能告诉我们"卡在哪"。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODES_ENV="${CLUSTER_NODES_ENV:-}"
for candidate in "$NODES_ENV" "$HERE/../../deploy/cluster/nodes.env" "$HERE/../nodes.env" /opt/cluster/nodes.env; do
  [ -n "$candidate" ] && [ -f "$candidate" ] && { NODES_ENV="$candidate"; break; }
done
# shellcheck source=/dev/null
source "$NODES_ENV"
LAUNCHER_IP="${LAUNCHER_IP:-172.17.40.108}"
SSH4="ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 root@$LAUNCHER_IP"
VUS="${1:-5}"
HOLD="${2:-90}"

order_count() { # $1=ip
  curl -s -m 5 "http://$1:18104/actuator/prometheus" 2>/dev/null \
    | awk '/http_server_requests_seconds_count.*postOrder/{s+=$2} END{printf "%.0f", s+0}'
}

log() { echo "[po $(date +%T)] $*"; }

log "启动下单负载 $VUS 并发 × ${HOLD}s"
# 把发起 ssh 本身放后台：远端进程持有通道时，这条 ssh 要等几十秒才返回，
# 会让我们在负载已经结束之后才开始"等起量"（实测等了 104 秒，白等一整轮）。
$SSH4 "cd /root/loadtest && setsid nohup python3 loadgen.py order --base https://smartlect.cn --vus $VUS --hold $HOLD \
  --max-orders 400 --admin http://$NODE1_IP:18101 --product http://$NODE1_IP:18106 --stock http://$NODE1_IP:18108 \
  --pay http://$NODE1_IP:18103 --secrets /root/loadtest/secrets.env --json /tmp/po.json \
  > /tmp/po.log 2>&1 < /dev/null &" >/dev/null 2>&1 &
sleep 8   # 给 k6 起量留出时间，之后按计数判定

log "等待负载起量（以 postOrder 计数增长为判据）…"
prev=$(order_count "$NODE1_IP"); ready=0
for _ in $(seq 1 25); do
  sleep 3
  now=$(order_count "$NODE1_IP")
  if [ "$(( now - prev ))" -gt 0 ]; then ready=1; break; fi
  prev=$now
done
if [ "$ready" -ne 1 ]; then log "负载未起量，终止"; $SSH4 "tail -3 /tmp/po.log"; exit 1; fi
log "负载已起量 ✓，进入稳态观察"

# 单次转储几乎必然抓到空闲：并发低时每个副本几秒才来一个请求，而转储是瞬时快照。
# 连抓多轮，只要有一轮抓到"正在处理"的线程就能定位（多轮结果叠加在一起看）。
DUMP_ROUNDS="${DUMP_ROUNDS:-4}"
for round in $(seq 1 "$DUMP_ROUNDS"); do
  log "第 $round/$DUMP_ROUNDS 轮转储"
  for ip in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    if [ "$ip" = "$NODE1_IP" ]; then
      kill -3 "$(pgrep -f 'run/apps/order' | head -1)" 2>/dev/null
    else
      ssh $CLUSTER_SSH_OPTS "root@$ip" "kill -3 \$(pgrep -f 'run/apps/order' | head -1)" 2>/dev/null
    fi
  done
  sleep 4
done
log "转储完成（共 $DUMP_ROUNDS 轮 × 3 副本）"
log "取负载结果"
$SSH4 "grep '^\[loadgen\]' /tmp/po.log | tail -1"
log "转储落在各节点的 run/logs/smartlect-order.log，分析用 thread-dump-summary.py"
