#!/usr/bin/env bash
# 边加载边测：三节点 CPU + 各网关/商品副本的请求增量（node1 执行）
#
# 为什么要一起测：只测 CPU 不知道"谁在干活"，只测请求数不知道"谁累"。
# 2026-10-05 就是只看了平均 CPU 才漏掉 node2 单点饱和（均值 76% vs 另两台 20%）。
#
# 用法：bash probe-balance.sh <并发> <秒数>
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
SSH4="ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 root@$LAUNCHER_IP"
VUS="${1:-400}"
HOLD="${2:-60}"
BASE="${LOADTEST_BASE:-https://smartlect.cn}"

count() { curl -s -m 5 "http://$1:$2/actuator/prometheus" 2>/dev/null | awk '/^http_server_requests_seconds_count/{s+=$2} END{printf "%.0f", s+0}'; }
self_cpu() { awk '/^cpu /{t=$2+$3+$4+$5+$6+$7+$8; i=$5+$6; print t, i}' /proc/stat; }
remote_cpu() { # $1=ip  3 秒平均
  ssh $CLUSTER_SSH_OPTS "root@$1" 'a=$(awk "/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8, \$5+\$6}" /proc/stat); sleep 3; b=$(awk "/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8, \$5+\$6}" /proc/stat); set -- $a $b; awk -v t1=$1 -v i1=$2 -v t2=$3 -v i2=$4 "BEGIN{printf \"%.0f\", 100*(1-(i2-i1)/(t2-t1))}"'
}

echo "[probe] $VUS 并发 × ${HOLD}s  基线快照…"
b_g1=$(count "$NODE1_IP" 18080); b_g2=$(count "$NODE2_IP" 18080); b_g3=$(count "$NODE3_IP" 18080)
b_p1=$(count "$NODE1_IP" 18106); b_p2=$(count "$NODE2_IP" 18106); b_p3=$(count "$NODE3_IP" 18106)

$SSH4 "cd /root/loadtest && setsid nohup k6 run -e VUS=$VUS -e HOLD=${HOLD}s -e BASE=$BASE -e OUT=/tmp/probe.json browse-k6.js > /tmp/probe-k6.log 2>&1 < /dev/null &" >/dev/null 2>&1
sleep 20   # 等负载起量

echo "[probe] 加载中采样…"
s1=$(self_cpu)
for i in 1 2 3 4; do
  c2=$(remote_cpu "$NODE2_IP"); c3=$(remote_cpu "$NODE3_IP")
  a=$(self_cpu); set -- $s1 $a
  c1=$(awk -v t1=$1 -v i1=$2 -v t2=$3 -v i2=$4 'BEGIN{printf "%.0f", 100*(1-(i2-i1)/(t2-t1))}')
  s1=$a
  echo "  CPU: node1=${c1}% node2=${c2}% node3=${c3}%"
  sleep 6
done

sleep 10
echo "[probe] 负载期间请求增量："
printf "  网关   node1=%s node2=%s node3=%s\n" "$(( $(count "$NODE1_IP" 18080) - b_g1 ))" "$(( $(count "$NODE2_IP" 18080) - b_g2 ))" "$(( $(count "$NODE3_IP" 18080) - b_g3 ))"
printf "  商品   node1=%s node2=%s node3=%s\n" "$(( $(count "$NODE1_IP" 18106) - b_p1 ))" "$(( $(count "$NODE2_IP" 18106) - b_p2 ))" "$(( $(count "$NODE3_IP" 18106) - b_p3 ))"
echo "[probe] 负载结果："
$SSH4 "grep '^\[loadgen\]' /tmp/probe-k6.log | tail -1"
