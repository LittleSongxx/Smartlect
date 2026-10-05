#!/usr/bin/env bash
# 单机天花板探针（node1 执行）：在一档高压负载下同时采集各层指标，定位真正的约束
#
# 为什么必须"同时采全部层"：单机 832 req/s 时 CPU 只用 24.7%，说明约束不在 CPU。
# 逐层看一遍才知道是谁：发压机自己？MySQL？连接池？nginx？Tomcat 线程？GC？
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODES_ENV=""
for candidate in "$HERE/../../deploy/cluster/nodes.env" /opt/cluster/nodes.env; do
  [ -f "$candidate" ] && { NODES_ENV="$candidate"; break; }
done
# shellcheck source=/dev/null
source "$NODES_ENV"
LAUNCHER_IP="${LAUNCHER_IP:-172.17.40.108}"
SSH4="ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 root@$LAUNCHER_IP"
VUS="${1:-1200}"
HOLD="${2:-70}"
BASE="${LOADTEST_BASE:-https://smartlect.cn}"

log() { echo "[ceiling $(date +%T)] $*"; }

cpu_breakdown() { # 本地
  read -r u1 n1 s1 i1 w1 h1 q1 < <(awk '/^cpu /{print $2, $3, $4, $5, $6, $7, $8}' /proc/stat)
  sleep 4
  read -r u2 n2 s2 i2 w2 h2 q2 < <(awk '/^cpu /{print $2, $3, $4, $5, $6, $7, $8}' /proc/stat)
  awk -v u1="$u1" -v n1="$n1" -v s1="$s1" -v i1="$i1" -v w1="$w1" -v h1="$h1" -v q1="$q1" \
      -v u2="$u2" -v n2="$n2" -v s2="$s2" -v i2="$i2" -v w2="$w2" -v h2="$h2" -v q2="$q2" 'BEGIN{
    t=(u2+n2+s2+i2+w2+h2+q2)-(u1+n1+s1+i1+w1+h1+q1)
    printf "user=%.0f%% sys=%.0f%% iowait=%.1f%% idle=%.0f%% steal=%.0f%%", \
      100*(u2-u1)/t, 100*(s2-s1)/t, 100*(w2-w1)/t, 100*(i2-i1)/t, 100*(q2-q1)/t }'
}
haproxy_metric() { # $1=ip $2=port $3=metric-regex
  curl -s -m 3 "http://$1:$2/actuator/prometheus" 2>/dev/null | awk -v pat="$3" '$0 ~ pat {s+=$2} END{printf "%.0f", s+0}'
}

log "启动 $VUS 并发 × ${HOLD}s"
$SSH4 "cd /root/loadtest && setsid nohup k6 run -e VUS=$VUS -e HOLD=${HOLD}s -e BASE=$BASE -e OUT=/tmp/ceil.json browse-k6.js > /tmp/ceil.log 2>&1 < /dev/null &" >/dev/null 2>&1 &
sleep 10

# 确认负载起量（本机网关计数在涨）
cnt() { curl -s -m 5 http://127.0.0.1:18080/actuator/prometheus 2>/dev/null | awk '/^http_server_requests_seconds_count/{s+=$2} END{printf "%.0f", s+0}'; }
prev=$(cnt); ready=0
for _ in $(seq 1 12); do sleep 3; now=$(cnt); if [ "$((now - prev))" -gt 50 ]; then ready=1; break; fi; prev=$now; done
[ "$ready" -ne 1 ] && { log "负载未起量"; $SSH4 "tail -3 /tmp/ceil.log"; exit 1; }
log "负载已起量，进入稳态，开始采集"

echo "========== 高压档各层指标 =========="
echo "--- node1 CPU 分解（8 核）---"
printf "  %s\n" "$(cpu_breakdown)"
echo "--- 发压机 node4 CPU（排除压测机自己成为瓶颈）---"
printf "  %s\n" "$(ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes root@$LAUNCHER_IP 'read -r u1 n1 s1 i1 w1 h1 q1 < <(awk "/^cpu /{print \$2,\$3,\$4,\$5,\$6,\$7,\$8}" /proc/stat); sleep 4; read -r u2 n2 s2 i2 w2 h2 q2 < <(awk "/^cpu /{print \$2,\$3,\$4,\$5,\$6,\$7,\$8}" /proc/stat); awk -v u1=$u1 -v s1=$s1 -v i1=$i1 -v w1=$w1 -v u2=$u2 -v s2=$s2 -v i2=$i2 -v w2=$w2 -v n1=$n1 -v n2=$n2 -v h1=$h1 -v h2=$h2 -v q1=$q1 -v q2=$q2 "BEGIN{t=(u2+n2+s2+i2+w2+h2+q2)-(u1+n1+s1+i1+w1+h1+q1); printf \"user=%.0f%% sys=%.0f%% idle=%.0f%%\", 100*(u2-u1)/t, 100*(s2-s1)/t, 100*(i2-i1)/t}"')"
echo "--- MySQL 容器 ---"
printf "  %s\n" "$(docker stats --no-stream --format 'CPU={{.CPUPerc}} MEM={{.MemUsage}}' smartlect-mysql-1 2>/dev/null)"
printf "  连接数=%s  运行中线程=%s  慢查询=%s\n" \
  "$(haproxy_metric 127.0.0.1 13306 x 2>/dev/null || docker exec smartlect-mysql-1 bash -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SELECT COUNT(*) FROM information_schema.processlist"' 2>/dev/null)" \
  "$(docker exec smartlect-mysql-1 bash -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SELECT COUNT(*) FROM information_schema.processlist WHERE command<>\"Sleep\""' 2>/dev/null)" \
  "$(docker exec smartlect-mysql-1 bash -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SHOW GLOBAL STATUS LIKE \"Slow_queries\""' 2>/dev/null | awk '{print $2}')"
echo "--- 各 Java 服务的连接池（active/max 排队 等连接max）---"
for spec in gateway:18080 admin:18101 cart:18102 pay:18103 order:18104 user:18105 product:18106 coupon:18107 stock:18108; do
  name="${spec%%:*}"; port="${spec##*:}"
  line=$(curl -s -m 3 "http://127.0.0.1:$port/actuator/prometheus" 2>/dev/null | awk '
    /^hikaricp_connections_active/{a+=$2} /^hikaricp_connections_max/{m+=$2}
    /^hikaricp_connections_pending/{p+=$2} /^hikaricp_connections_acquire_seconds_max/{if($2>q)q=$2}
    END{if(m>0) printf "active=%.0f/%.0f 排队=%.0f 等连接max=%.0fms", a, m, p, q*1000}')
  [ -n "$line" ] && printf "  %-9s %s\n" "$name" "$line"
done
echo "--- nginx（入口）---"
printf "  worker 数=%s  当前连接=%s\n" "$(pgrep -c 'nginx: worker')" "$(ss -tan state established '( sport = :443 )' | wc -l)"
echo "--- Redis ---"
printf "  %s\n" "$(docker exec smartlect-redis-1 sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning info stats' 2>/dev/null | awk -F: '/instantaneous_ops_per_sec/{printf "ops/s=%s", $2}' | tr -d '\r')"
echo "--- Tomcat 线程（product/order，busy/max 与排队）---"
for spec in product:18106 order:18104; do
  name="${spec%%:*}"; port="${spec##*:}"
  printf "  %-8s %s\n" "$name" "$(curl -s -m 3 "http://127.0.0.1:$port/actuator/prometheus" 2>/dev/null | awk '/^executor_active_threads/{a+=$2} /^executor_queued_tasks/{q+=$2} END{printf "活跃=%s 排队=%s", a, q}')"
done

sleep 8
echo "--- 负载结果 ---"
$SSH4 "grep '^\[loadgen\]' /tmp/ceil.log | tail -1"
