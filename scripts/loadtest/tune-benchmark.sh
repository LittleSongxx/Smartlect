#!/usr/bin/env bash
# 调优基准测试台（node1 执行）——固定负载，让每个参数变体可横向比较
#
# 设计要点（都是踩过坑之后加的约束）：
#   · 用修好的 k6 脚本：loadProduct 发 pageNo（旧脚本发 page= 导致每个请求都在校验层被打回），
#     并且同时统计「传输层错误」与「业务错误」——只看 HTTP 码会把 200+status:error 当成功。
#   · 每轮先跑一次预热负载：JVM 未热时首档 p95 会比稳态高一个数量级（实测 2477ms vs 43ms）。
#   · 每档之间不重启，避免冷启动污染比较。
#
# 用法：bash tune-benchmark.sh <变体标签> [结果文件]
#   例：bash tune-benchmark.sh "pool=8"
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 节点拓扑的单一事实源在 deploy/cluster/nodes.env；本目录是发压/测量工具，
# 用环境变量可覆盖，默认按仓库相对路径解析。
# nodes.env 的位置随部署形态不同（仓库里在 deploy/cluster/，服务器上在 /opt/cluster/）：
# 按优先级逐个探测，避免换个地方跑就 "unbound variable"。
for candidate in "${CLUSTER_NODES_ENV:-}" "$HERE/../../deploy/cluster/nodes.env" \
                 "/opt/cluster/nodes.env" "$HERE/../nodes.env"; do
  [ -n "$candidate" ] && [ -f "$candidate" ] && { NODES_ENV="$candidate"; break; }
done
# shellcheck source=/dev/null
source "$NODES_ENV"
LAUNCHER_IP="${LAUNCHER_IP:-172.17.40.108}"
SSH4="ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@$LAUNCHER_IP"
LABEL="${1:?usage: tune-benchmark.sh <variant-label> [results-file]}"
RESULTS="${2:-/opt/cluster/evidence/tuning-results.tsv}"
BASE="${LOADTEST_BASE:-https://smartlect.cn}"
BROWSE_TIERS="${BROWSE_TIERS:-400 800 1200 1600}"
BROWSE_HOLD="${BROWSE_HOLD:-45}"
ORDER_VUS="${ORDER_VUS:-10}"
ORDER_HOLD="${ORDER_HOLD:-60}"
EV="/opt/cluster/evidence/tuning-$(date +%Y%m%d-%H%M)"
mkdir -p "$EV"

log() { echo "[tune $(date +%T)] $*"; }

browse_tier() { # $1=vus
  local vus="$1" out="$EV/$LABEL-browse-$vus.json"
  $SSH4 "cd /root/loadtest && k6 run -e VUS=$vus -e HOLD=${BROWSE_HOLD}s -e BASE=$BASE -e LABEL=$LABEL -e OUT=/tmp/k6.json browse-k6.js" 2>&1 | grep '^\[loadgen\]'
  $SSH4 "cat /tmp/k6.json" > "$out"
  # CPU 不在这里取：负载结束后的采样只反映回落后的空转（曾把 47% 的峰值记成 3%）。
  # 三节点的 resource-sampler.py 全程在跑，按时间窗回查才有意义。
  python3 - "$out" "$LABEL" "$RESULTS" <<'PY'
import json, sys
path, label, results = sys.argv[1:4]
d = json.load(open(path))
l = d["latency_ms"]
with open(results, "a") as fh:
    fh.write("\t".join([label, d["kind"], str(d["vus"]), f'{d["qps"]:.1f}',
                        f'{l["p50"]:.1f}', f'{l["p95"]:.1f}', f'{l["p99"]:.1f}',
                        f'{d["error_rate"]*100:.2f}%', str(d.get("business_errors", 0))]) + "\n")
PY
}

log "=== 变体 [$LABEL] 开始 ==="
[ -f "$RESULTS" ] || echo -e "变体\t场景\t并发\treq_s\tp50\tp95\tp99\t传输层错误\t业务错误" > "$RESULTS"

# 预热协议：**按累计请求数**而不是按时长。
#
# 为什么：JIT 的完成度取决于"被调用过多少次"，不取决于跑了多久。固定时长预热会让
# 两个变体处在不同的编译进度上——同一份 pool=8 配置，初测（前序数小时测试已热透）
# 860 req/s vs 复测（重启后按时间预热）525 req/s，差 64%，而参数差异只有 ±3%。
# 按请求数预热让所有变体从同一个起点开始，参数差异才可读。
#
# WARMUP_REQUESTS：累计请求数门槛。取值是"够用就好"的折中——门槛越高越接近真实热态，
# 但按 400 并发约 196 req/s 算，6 万请求 ≈ 5 分钟/变体，20 万要 17 分钟，两轮就 35 分钟。
# **关键是各变体用同一个值**（可比的来源是一致性，不是数值大小）；要更保守就调大它。
# WARMUP_MAX_ROUNDS：兜底上限，防止永远到不了。
WARMUP_REQUESTS="${WARMUP_REQUESTS:-60000}"
WARMUP_VUS="${WARMUP_VUS:-400}"
log "预热：累计到 ${WARMUP_REQUESTS} 请求（每轮 ${WARMUP_VUS} 并发 × 30s）"
accumulated=0
for round in $(seq 1 "${WARMUP_MAX_ROUNDS:-12}"); do
  $SSH4 "cd /root/loadtest && k6 run -e VUS=$WARMUP_VUS -e HOLD=30s -e BASE=$BASE -e OUT=/tmp/k6-warm.json browse-k6.js" >/dev/null 2>&1
  round_reqs=$($SSH4 "python3 -c \"import json;print(json.load(open('/tmp/k6-warm.json'))['requests'])\"")
  accumulated=$(( accumulated + round_reqs ))
  log "  预热第 $round 轮：本轮 $round_reqs 请求，累计 $accumulated / $WARMUP_REQUESTS"
  [ "$accumulated" -ge "$WARMUP_REQUESTS" ] && { log "  已达预热门槛，开始测量"; break; }
done

for vus in $BROWSE_TIERS; do
  log "浏览 $vus 并发 × ${BROWSE_HOLD}s"
  browse_tier "$vus"
done

# 跑交易前先补库存：demo 夹具 40 个 SKU 原库存合计仅 580 件，一轮 10 并发×60s 就能打空，
# 打空后的轮次会全线 no_stock，被误读成"系统高负载失败"（2026-10-06 就是这么误判的）。
# 单量也用 --max-orders 封顶，保证各变体之间的样本量一致。
log "交易闭环：先补库存到每 SKU $TOPUP_STOCK 件"
bash "$(dirname "$HERE")/deploy/cluster/scripts/stock-control.sh" topup 2>/dev/null || \
  bash /opt/cluster/scripts/stock-control.sh topup 2>/dev/null || echo "  （stock-control 不可用，跳过）"
log "交易闭环 $ORDER_VUS 并发 × ${ORDER_HOLD}s"
out="$EV/$LABEL-order-$ORDER_VUS.json"
$SSH4 "cd /root/loadtest && python3 loadgen.py order --base $BASE --vus $ORDER_VUS --hold $ORDER_HOLD --admin http://$NODE1_IP:18101 --product http://$NODE1_IP:18106 --stock http://$NODE1_IP:18108 --pay http://$NODE1_IP:18103 --secrets /root/loadtest/secrets.env --max-orders ${ORDER_CAP:-300} --json /tmp/lg.json" 2>&1 | grep '^\[loadgen\]'
$SSH4 "cat /tmp/lg.json" > "$out"
python3 - "$out" "$LABEL" "$RESULTS" <<'PY'
import json, sys
path, label, results = sys.argv[1:4]
d = json.load(open(path))
l = d["latency_ms"]
with open(results, "a") as fh:
    fh.write("\t".join([label, "order", str(d["vus"]), f'{d["qps"]:.2f}',
                        f'{l["p50"]:.1f}', f'{l["p95"]:.1f}', f'{l["p99"]:.1f}',
                        f'{d["error_rate"]*100:.2f}%', str(d.get("business_errors", 0))]) + "\n")
PY

log "=== 变体 [$LABEL] 完成，证据 $EV ==="
log "累计结果：$RESULTS"
