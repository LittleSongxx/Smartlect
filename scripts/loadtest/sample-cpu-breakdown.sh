#!/usr/bin/env bash
# CPU 分解 + 磁盘 I/O 采样（在目标节点本地执行，只读）
#
# 用途：区分"算力不足"与"阻塞等待"。负载高但 CPU 空闲（user+sys 低、iowait 高或 idle 高）
# 说明进程在等 I/O 或等锁，而不是在算。2026-10-06 node2 的 load 9.85 / CPU 27% 就是这个特征。
set -uo pipefail
SECONDS_TO_SAMPLE="${1:-5}"

read -r u1 n1 s1 i1 w1 h1 q1 < <(awk '/^cpu /{print $2, $3, $4, $5, $6, $7, $8}' /proc/stat)
read -r r1 w_1 < <(awk '/ vda /{print $4+$8, $10}' /proc/diskstats)
sleep "$SECONDS_TO_SAMPLE"
read -r u2 n2 s2 i2 w2 h2 q2 < <(awk '/^cpu /{print $2, $3, $4, $5, $6, $7, $8}' /proc/stat)
read -r r2 w_2 < <(awk '/ vda /{print $4+$8, $10}' /proc/diskstats)

awk -v u1="$u1" -v n1="$n1" -v s1="$s1" -v i1="$i1" -v w1="$w1" -v h1="$h1" -v q1="$q1" \
    -v u2="$u2" -v n2="$n2" -v s2="$s2" -v i2="$i2" -v w2="$w2" -v h2="$h2" -v q2="$q2" '
BEGIN {
  t = (u2+n2+s2+i2+w2+h2+q2) - (u1+n1+s1+i1+w1+h1+q1)
  if (t <= 0) { print "  采样窗口无效"; exit }
  printf "  user=%.0f%% sys=%.0f%% iowait=%.1f%% idle=%.0f%% steal=%.1f%%  load=%s\n", \
    100*(u2-u1)/t, 100*(s2-s1)/t, 100*(w2-w1)/t, 100*(i2-i1)/t, 100*(q2-q1)/t, "?"
}'
printf "  磁盘 I/O: 读 %d 次/秒  写 %d 次/秒\n" "$(( (r2 - r1) / SECONDS_TO_SAMPLE ))" "$(( (w_2 - w_1) / SECONDS_TO_SAMPLE ))"
printf "  loadavg: %s\n" "$(cut -d' ' -f1-3 /proc/loadavg)"
