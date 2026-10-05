#!/usr/bin/env bash
# 双发压机阶梯（node1 执行）：两台并发压测机合起来打，突破单台发压机的算力上限
#
# 为什么需要：单台 4 核发压机在 node1 跑到 1217 req/s 时自身 CPU 已 72%——再往上测到的
# 就是"发压机的极限"而不是"服务器的极限"。两台同时发，总 VU 翻倍。
#
# 口径说明（合并两台的结果时）：
#   · QPS 直接相加（精确）
#   · 百分位不能相加——两台各自的 p95 分别列出，并给出两者中的最大值作为保守上界
#   · 两台同时启动会有 1-2 秒偏差，阶梯每档 60s 足以摊平
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODES_ENV="${CLUSTER_NODES_ENV:-}"
for candidate in "$NODES_ENV" "$HERE/../../deploy/cluster/nodes.env" "/opt/cluster/nodes.env"; do
  [ -n "$candidate" ] && [ -f "$candidate" ] && { NODES_ENV="$candidate"; break; }
done
# shellcheck source=/dev/null
source "$NODES_ENV"
GEN_A_IP="${GEN_A_IP:-172.17.40.108}"   # node4
GEN_B_IP="${GEN_B_IP:-$NODE3_IP}"       # node3（原应用副本，已停用）
GEN_A_KEY=/root/.ssh/id_ed25519
GEN_B_OPTS="$CLUSTER_SSH_OPTS"
BASE="${LOADTEST_BASE:-https://smartlect.cn}"
HOLD="${HOLD:-60}"
TIERS="${TIERS:-400 800 1200 1600}"     # 每台发压机的 VU 数；总量 = ×2
EV="/opt/cluster/evidence/dual-$(date +%Y%m%d-%H%M)"
mkdir -p "$EV"
RESULTS="$EV/dual-results.tsv"
TSV_HEADER=$'每台VU\t总VU\t总QPS\treqA\treqB\tp95_A\tp95_B\tp95上界\t错误A\t错误B\tnode1CPU'

log() { echo "[dual $(date +%T)] $*"; }
cpu1() { read -r u1 n1 s1 i1 w1 h1 q1 < <(awk '/^cpu /{print $2,$3,$4,$5,$6,$7,$8}' /proc/stat); sleep 4; read -r u2 n2 s2 i2 w2 h2 q2 < <(awk '/^cpu /{print $2,$3,$4,$5,$6,$7,$8}' /proc/stat); awk -v u1=$u1 -v n1=$n1 -v s1=$s1 -v i1=$i1 -v w1=$w1 -v h1=$h1 -v q1=$q1 -v u2=$u2 -v n2=$n2 -v s2=$s2 -v i2=$i2 -v w2=$w2 -v h2=$h2 -v q2=$q2 'BEGIN{t=(u2+n2+s2+i2+w2+h2+q2)-(u1+n1+s1+i1+w1+h1+q1); printf "%.0f", 100*(t-(i2-i1))/t}'; }

run_both() { # $1=每台 VU
  local vus="$1"
  ssh -i "$GEN_A_KEY" -o BatchMode=yes -o ConnectTimeout=10 root@"$GEN_A_IP" \
    "cd /root/loadtest && k6 run -e VUS=$vus -e HOLD=${HOLD}s -e BASE=$BASE -e LABEL=A -e OUT=/tmp/dualA.json browse-k6.js > /tmp/dualA.log 2>&1" &
  local pidA=$!
  ssh $GEN_B_OPTS root@"$GEN_B_IP" \
    "cd /root/loadtest && k6 run -e VUS=$vus -e HOLD=${HOLD}s -e BASE=$BASE -e LABEL=B -e OUT=/tmp/dualB.json browse-k6.js > /tmp/dualB.log 2>&1" &
  local pidB=$!
  sleep 20
  local c1; c1=$(cpu1)
  wait $pidA $pidB
  echo "$c1" > /tmp/dual-cpu1.txt
}

log "=== 双发压机阶梯开始（发压：$GEN_A_IP + $GEN_B_IP）==="
echo "$TSV_HEADER" > "$RESULTS"

log "预热（每台 300 并发 × 60s）"
run_both 300

for vus in $TIERS; do
  log "每台 $vus 并发（总量 $((vus * 2))）× ${HOLD}s"
  run_both "$vus"
  ssh -i "$GEN_A_KEY" -o BatchMode=yes root@"$GEN_A_IP" "cat /tmp/dualA.json" > "$EV/dualA-$vus.json"
  ssh $GEN_B_OPTS root@"$GEN_B_IP" "cat /tmp/dualB.json" > "$EV/dualB-$vus.json"
  python3 - "$EV/dualA-$vus.json" "$EV/dualB-$vus.json" "$vus" "$(cat /tmp/dual-cpu1.txt)" "$RESULTS" <<'PY'
import json, sys
fa, fb, vus, cpu1, results = sys.argv[1:6]
a, b = json.load(open(fa)), json.load(open(fb))
total_qps = a["qps"] + b["qps"]
p95a, p95b = a["latency_ms"]["p95"], b["latency_ms"]["p95"]
row = [vus, str(int(vus) * 2), f"{total_qps:.1f}", str(a["requests"]), str(b["requests"]),
       f"{p95a:.0f}", f"{p95b:.0f}", f"{max(p95a, p95b):.0f}",
       f'{a["error_rate"]*100:.2f}%', f'{b["error_rate"]*100:.2f}%', cpu1]
print(f"  合并: 总 {total_qps:.1f} req/s | p95 A={p95a:.0f}ms B={p95b:.0f}ms | node1 CPU={cpu1}%")
with open(results, "a") as fh:
    fh.write("\t".join(row) + "\n")
PY
done

log "=== 完成，结果表 ==="
column -t -s$'\t' "$RESULTS"
