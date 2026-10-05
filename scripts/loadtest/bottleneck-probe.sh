#!/usr/bin/env bash
# 瓶颈归因（node1 执行）：加载中同时采 Redis、Tomcat 线程池、MySQL 连接数
#
# 目的：定位"CPU 没打满但延迟爆炸"的真凶。浏览链路的候选瓶颈按嫌疑排序：
#   Redis（单线程，缓存链路必经）> Tomcat 线程池（默认 200）> MySQL（本次采样已排除）
set -euo pipefail
SECONDS_TO_RUN="${1:-60}"
INTERVAL="${2:-6}"

redis_stat() {
  docker exec smartlect-redis-1 sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning info stats' 2>/dev/null \
    | awk -F: '/instantaneous_ops_per_sec/{print $2}' | tr -d '\r'
}
redis_cpu() { docker stats --no-stream --format '{{.CPUPerc}}' smartlect-redis-1 2>/dev/null; }
mysql_conn() {
  docker exec smartlect-mysql-1 bash -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SELECT COUNT(*) FROM information_schema.processlist"' 2>/dev/null
}
tomcat() {
  curl -s -m 3 "http://127.0.0.1:$1/actuator/prometheus" 2>/dev/null \
    | awk -F' ' '/^executor_active_threads|^executor_queued_tasks/{printf "%s=%s ", $1, $2}'
}

echo "时间      Redis_ops/s  Redis_CPU  MySQL连接  product线程池/队列"
deadline=$(( $(date +%s) + SECONDS_TO_RUN ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  printf "%s  %-11s %-10s %-9s %s\n" \
    "$(date +%T)" "$(redis_stat)" "$(redis_cpu)" "$(mysql_conn)" "$(tomcat 18106)"
  sleep "$INTERVAL"
done
