#!/usr/bin/env bash
# 对比三个 product 副本的分端点服务端耗时（node1 执行，只读）
#
# 用途：判别"某副本慢"是**全端点**还是**特定端点**——前者指向该副本的资源问题
# （CPU/GC/连接池/Redis 客户端），后者指向具体功能（如批量快照走了慢查询）。
set -uo pipefail
for ip in 172.21.131.151 172.19.34.202 172.19.34.203; do
  echo "--- product@$ip ---"
  curl -s -m 6 "http://$ip:18106/actuator/prometheus" 2>/dev/null | awk '
    /^http_server_requests_seconds_count/ {
      match($0, /uri="[^"]+"/); uri = substr($0, RSTART+5, RLENGTH-6); cnt[uri] += $2
      next
    }
    /^http_server_requests_seconds_sum/ {
      match($0, /uri="[^"]+"/); uri = substr($0, RSTART+5, RLENGTH-6); sum[uri] += $2
      next
    }
    /^http_server_requests_seconds_max/ {
      match($0, /uri="[^"]+"/); uri = substr($0, RSTART+5, RLENGTH-6)
      if ($2 > mx[uri]) mx[uri] = $2
      next
    }
    END {
      for (u in cnt) if (cnt[u] > 20) printf "  %-44s %6d 次  均值 %7.0fms  最大 %7.0fms\n", u, cnt[u], sum[u]/cnt[u]*1000, mx[u]*1000
    }' | head -8
done
