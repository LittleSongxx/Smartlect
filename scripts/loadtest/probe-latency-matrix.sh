#!/usr/bin/env bash
# 副本延迟隔离测试（在任一节点执行）
#
# 目的：把"某个副本慢"拆成两种可能——(a) 该副本服务本身慢，(b) 从某处访问它慢。
# 做法：从每台机器分别打每个副本同样的 20 次请求，看延迟矩阵的哪一行/列异常。
set -uo pipefail
NODES="172.21.131.151 172.19.34.202 172.19.34.203"
REQ=20

probe_local() { # $1=目标IP
  local total=0
  for _ in $(seq 1 $REQ); do
    t=$(curl -s -o /dev/null -m 10 -w "%{time_total}" "http://$1:18106/product/loadCategory" 2>/dev/null || echo 10)
    total=$(awk -v a="$total" -v b="$t" 'BEGIN{print a+b}')
  done
  awk -v s="$total" -v n="$REQ" 'BEGIN{printf "%.1f", s/n*1000}'
}

echo "延迟矩阵（单位 ms，行=发起机器，列=目标 product 副本；每格 $REQ 次均值）"
printf "%-18s" "发起\\目标"
for t in $NODES; do printf "%-18s" "$t"; done; echo
for src in $NODES; do
  printf "%-18s" "$src"
  for dst in $NODES; do
    if [ "$src" = "$(hostname -I | awk '{print $1}')" ]; then
      printf "%-18s" "$(probe_local "$dst")"
    else
      printf "%-18s" "$(ssh -o BatchMode=yes -o ConnectTimeout=8 "root@$src" "$(declare -f probe_local); NODES='$NODES' REQ=$REQ probe_local $dst" 2>/dev/null || echo n/a)"
    fi
  done
  echo
done
