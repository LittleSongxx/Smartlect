#!/usr/bin/env bash
# 四档双发压测（node1 发起，node2/3 k6 打 node1）
# 档位：每台 50/100/200/400 VU = 总 100/200/400/800 VU，HOLD=100s
set -uo pipefail
EV=/opt/cluster/evidence/loadtest-$(date +%Y%m%d-%H%M)
mkdir -p "$EV"
TS_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "$TS_START" > "$EV/window.txt"
echo "evidence dir: $EV"

for VUS_PER in 50 100 200 400; do
  TOTAL=$((VUS_PER*2))
  echo "===== tier VUS_PER=$VUS_PER (total $TOTAL) start $(date +%T) ====="
  ssh root@172.19.34.202 "k6 run --summary-trend-stats='avg,med,p(90),p(95),p(99),max' -e BASE=http://172.21.131.151:80 -e VUS=$VUS_PER -e HOLD=100s /root/browse.js" > "$EV/k6-${VUS_PER}-node2.log" 2>&1 &
  P2=$!
  ssh root@172.19.34.203 "k6 run --summary-trend-stats='avg,med,p(90),p(95),p(99),max' -e BASE=http://172.21.131.151:80 -e VUS=$VUS_PER -e HOLD=100s /root/browse.js" > "$EV/k6-${VUS_PER}-node3.log" 2>&1 &
  P3=$!
  wait $P2 $P3
  for f in "$EV/k6-${VUS_PER}-node2.log" "$EV/k6-${VUS_PER}-node3.log"; do
    echo "-- $(basename "$f") --"
    grep -E "^ +http_reqs " "$f"
    grep -E "^ +http_req_duration" "$f"
    grep -E "^ +http_req_failed" "$f"
  done
  echo "-- node load after tier --"
  uptime
  ssh root@172.19.34.202 uptime
  ssh root@172.19.34.203 uptime
done
TS_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "$TS_END" >> "$EV/window.txt"
echo "window: $TS_START -> $TS_END (saved for export-ramp-csv.py)"
