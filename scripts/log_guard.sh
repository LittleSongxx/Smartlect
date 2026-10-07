#!/usr/bin/env bash
# 日志闸门：防止日志把根分区写满（起因见 docs/改动记录/2026-10-07/线上故障-配置请求风暴.md）。
#
# 任何单文件超过 LIMIT 就地 truncate——保留文件句柄与写入位置，进程无需重启；
# 删除已轮转的 *.log.*；根分区占用超 THRESHOLD 时额外收敛 Nacos 容器内的日志。
#
# 服务器上由 /etc/cron.d/smartlect-log-guard 每 5 分钟调用一次：
#   echo "*/5 * * * * root /opt/smartlect/scripts/log_guard.sh" > /etc/cron.d/smartlect-log-guard
set -u

ROOT=${SMARTLECT_ROOT:-/opt/smartlect}
LIMIT=$((50 * 1024 * 1024))
THRESHOLD=70

for f in "$ROOT"/run/logs/*.log "$ROOT"/run/logs/*/*.log; do
    [ -f "$f" ] || continue
    size=$(stat -c%s "$f" 2>/dev/null || echo 0)
    [ "$size" -gt "$LIMIT" ] && truncate -s 0 "$f"
done
find "$ROOT"/run/logs -type f -name "*.log.*" -delete 2>/dev/null

avail=$(df --output=pcent / | tail -1 | tr -dc "0-9")
if [ "${avail:-0}" -gt "$THRESHOLD" ]; then
    docker exec nacos-c1 sh -c 'for f in /home/nacos/logs/*.log /home/nacos/logs/*.log.*; do [ -f "$f" ] && truncate -s 0 "$f"; done' 2>/dev/null
fi
