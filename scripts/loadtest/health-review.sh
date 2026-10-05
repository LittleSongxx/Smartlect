#!/usr/bin/env bash
# 单节点运行体检（在任一应用节点执行，只读）
#
# 用途：快速回答"这台机器上跑的东西有没有明显毛病"——分批启动时间、错误日志、
# JVM 堆与线程、连接池、以及配置与规格是否匹配。
set -uo pipefail
ROOT=/opt/smartlect
PORTS="gateway:18080 admin:18101 cart:18102 pay:18103 order:18104 user:18105 product:18106 coupon:18107 stock:18108"

echo "===== $(hostname) ====="
echo "规格: $(nproc) 核 / $(awk '/MemTotal/{printf "%.1f", $2/1048576}' /proc/meminfo)G  负载: $(cut -d' ' -f1-3 /proc/loadavg)"
echo "应用服务: $(systemctl is-active smartlect-apps 2>/dev/null || echo n/a)  进程: $(pgrep -fc '\-jar /opt/smartlect' 2>/dev/null || echo 0)"

echo
echo "--- 各服务启动时间（判断是否同一批/Smoke 后是否重启过） ---"
for spec in $PORTS; do
  name="${spec%%:*}"; port="${spec##*:}"
  # 只统计本机在跑的服务
  pid=$(ss -lntp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $NF}' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  [ -z "$pid" ] && continue
  started=$(ps -o lstart= -p "$pid" 2>/dev/null | xargs)
  printf "  %-8s pid=%-8s 启动于 %s\n" "$name" "$pid" "$started"
done

echo
echo "--- 配置与规格匹配检查 ---"
env_val() { grep -oP "^$1=\K.*" "$ROOT/run/runtime.env" 2>/dev/null | head -1; }
printf "  SMARTLECT_JAVA_PROCESSORS=%s  XMS=%s  XMX=%s  （本机 %s 核）\n" \
  "$(env_val SMARTLECT_JAVA_PROCESSORS)" "$(env_val SMARTLECT_JAVA_XMS)" \
  "$(env_val SMARTLECT_JAVA_XMX)" "$(nproc)"
printf "  SMARTLECT_DB_POOL_MAX_SIZE=%s（默认 4）  APP_SERVICES=%s\n" \
  "$(env_val SMARTLECT_DB_POOL_MAX_SIZE)" "$(env_val SMARTLECT_APP_SERVICES)"

echo
echo "--- 运行期错误（排除停机瞬间的 Nacos 关闭噪音） ---"
for spec in $PORTS; do
  name="${spec%%:*}"
  log="$ROOT/run/logs/smartlect-$name.log"
  [ -f "$log" ] || continue
  total=$(grep -c " ERROR " "$log" 2>/dev/null); total=${total:-0}
  noise=$(grep " ERROR " "$log" 2>/dev/null | grep -c "Nacos\|ShutdownHook\|NotifyCenter"); noise=${noise:-0}
  oom=$(grep -ciE "OutOfMemoryError|GC overhead limit" "$log" 2>/dev/null); oom=${oom:-0}
  printf "  %-8s ERROR=%-4s(其中停机噪音 %-3s) OOM=%s\n" "$name" "$total" "$noise" "$oom"
done

echo
echo "--- 连接池与线程（actuator，取当前值） ---"
for spec in $PORTS; do
  name="${spec%%:*}"; port="${spec##*:}"
  body=$(curl -s -m 3 "http://127.0.0.1:$port/actuator/prometheus" 2>/dev/null) || continue
  [ -z "$body" ] && continue
  hik=$(printf '%s' "$body" | awk '/^hikaricp_connections_active/{a=$2} /^hikaricp_connections_max/{m=$2} /^hikaricp_connections_pending/{p=$2} END{printf "%s/%s 排队%s", a, m, p}')
  jvm=$(printf '%s' "$body" | awk '/^jvm_threads_live_threads/{t=$2} /^jvm_memory_used_bytes\{area="heap"/{gsub(/[^0-9.]/,"",$2); h+=$2} END{printf "线程%s 堆%.0fMB", t, h/1048576}')
  printf "  %-8s Hikari=%s  %s\n" "$name" "$hik" "$jvm"
done

echo
echo "--- 容器 ---"
docker ps --format "  {{.Names}}  {{.Status}}" 2>/dev/null | sort
