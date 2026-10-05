#!/usr/bin/env bash
# 三节点 CPU 采样（node1 执行，加载中运行）：为瓶颈归因提供资源证据。
# 用法：bash sample-fleet-cpu.sh <采样秒数> <间隔秒数> <输出文件>
set -uo pipefail
DURATION="${1:-60}"
INTERVAL="${2:-10}"
OUT="${3:-/opt/cluster/evidence/fleet-cpu.txt}"
NODES="node1:172.21.131.151 node2:172.19.34.202 node3:172.19.34.203"

read_cpu() { awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5+$6}' /proc/stat; }

{
  echo "时间 $(date +%T)  采样 ${DURATION}s / 间隔 ${INTERVAL}s"
  echo "标签       CPU%   load1  内存%"
  declare -A prev
  for spec in $NODES; do prev[${spec%%:*}]=$(read_cpu); done
  end=$(( $(date +%s) + DURATION ))
  while [ "$(date +%s)" -lt "$end" ]; do
    sleep "$INTERVAL"
    for spec in $NODES; do
      name="${spec%%:*}"; ip="${spec##*:}"
      if [ "$name" = "node1" ]; then
        cur=$(read_cpu)
        set -- ${prev[$name]} $cur
        total=$(( $3 - $1 )); idle=$(( $4 - $2 ))
        prev[$name]="$cur"
        printf "%-8s %5.1f  %5s  %5s\n" "$name" "$(awk -v t=$total -v i=$idle 'BEGIN{printf (t>0)?100*(1-i/t):0}')" \
          "$(cut -d' ' -f1 /proc/loadavg)" "$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf 100*(t-a)/t}' /proc/meminfo)"
      else
        ssh -o BatchMode=yes -o ConnectTimeout=5 root@$ip 'awk -v p1=0 "/^cpu /{t=\$2+\$3+\$4+\$5+\$6+\$7+\$8; i=\$5+\$6; print t, i}" /proc/stat | {
          read t i; sleep 3
          read t2 i2 < <(awk "/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8, \$5+\$6}" /proc/stat)
          awk -v a=$t -v b=$i -v c=$t2 -v d=$i2 "BEGIN{printf \"%5.1f\", 100*(1-(d-b)/(c-a))}"
        }; printf "  %5s  %5s\n" "$(cut -d" " -f1 /proc/loadavg | head -c4)" "$(awk "/MemTotal/{t=\$2}/MemAvailable/{a=\$2}END{printf 100*(t-a)/t}" /proc/meminfo)"' 2>/dev/null \
          | sed "s/^/$(printf '%-8s' "$name")/"
      fi
    done
  done
} | tee "$OUT"
