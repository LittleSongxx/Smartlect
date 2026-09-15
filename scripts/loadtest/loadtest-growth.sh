#!/usr/bin/env bash
# AI 层压测套件：chat 1/2/4/8 VU（node2 单发，真 LLM）+ control 25/50/100/200 VU（双发）
set -uo pipefail
EV=/opt/cluster/evidence/loadtest-$(date +%Y%m%d-%H%M)-growth
mkdir -p "$EV"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$EV/window.txt"

echo "===== chat sweep (node2, live LLM) ====="
for VUS in 1 2 4 8; do
  echo "--- chat VUS=$VUS start $(date +%T) ---"
  ssh root@172.19.34.202 "k6 run --summary-trend-stats='avg,med,p(90),p(95),max' -e BASE=http://172.21.131.151 -e VUS=$VUS -e HOLD=90s /root/growth-chat.js" > "$EV/chat-$VUS.log" 2>&1
  grep -E "agent_run_duration_s|^ +http_req_duration|http_req_failed\.\.|checks" "$EV/chat-$VUS.log" | head -6
  grep -E "http429|agent_run_outcome" "$EV/chat-$VUS.log" | grep -E "^\s+(✓|✗)|count=|█" | head -8
  grep -E "agent_run_outcome" "$EV/chat-$VUS.log" | tail -5
  uptime
done

echo "===== control sweep (node2+3 dual) ====="
for VUS_PER in 25 50 100 200; do
  echo "--- control VUS_PER=$VUS_PER (total $((VUS_PER*2))) start $(date +%T) ---"
  ssh root@172.19.34.202 "k6 run --summary-trend-stats='avg,med,p(90),p(95),max' -e BASE=http://172.21.131.151 -e VUS=$VUS_PER -e HOLD=60s /root/growth-control.js" > "$EV/ctl-$VUS_PER-node2.log" 2>&1 &
  P2=$!
  ssh root@172.19.34.203 "k6 run --summary-trend-stats='avg,med,p(90),p(95),max' -e BASE=http://172.21.131.151 -e VUS=$VUS_PER -e HOLD=60s /root/growth-control.js" > "$EV/ctl-$VUS_PER-node3.log" 2>&1 &
  P3=$!
  wait $P2 $P3
  for f in "$EV/ctl-$VUS_PER-node2.log" "$EV/ctl-$VUS_PER-node3.log"; do
    echo "-- $(basename "$f") --"
    grep -E "^ +http_reqs " "$f"
    grep -E "^ +http_req_duration" "$f"
    grep -E "^ +http_req_failed" "$f"
  done
  uptime; ssh root@172.19.34.202 uptime
done
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$EV/window.txt"
echo "window: $(cat "$EV/window.txt" | tr '\n' ' ')"
