#!/usr/bin/env bash
# 按机器角色与规格设置 JVM / 连接池参数（在每台应用节点各自执行）
#
# 规则不是拍脑袋，是"只改有证据的部分"：
#   · 连接池：所有节点统一 8。证据——order 服务出现 hikaricp acquire 超时 5000ms、
#     单连接被占用 18.1s、超时累计 34 次，并连带 68 次支付成功处理失败与 101 次
#     Outbox 投递失败。原值 4 不够用。
#   · 副本节点的 JVM：PROCESSORS 1→2、XMX 320m→512m。证据——这两个节点是 2026-10-05
#     从 2c8g 升到 4c8g 的，参数还停在 2 核时代；而它们正是压测暴露出的瓶颈
#     （load average 7.2 / 2 核）。参数跟着规格走，避免下次改配置再漂移。
#   · 主节点的 JVM：**不动**。证据——8 核实测 CPU 均值 24.7%/峰值 71.3%、无 OOM、
#     无 GC 告警。没有证据就不改，避免"顺手调参"引入新变量。
#
# 用法：bash apply-sizing.sh [--dry-run]
set -euo pipefail
RT="${RUNTIME_ENV:-/opt/smartlect/run/runtime.env}"
DRY="${1:-}"

POOL=8   # 17 个 Java 实例 × 8 = 136 + nacos/assistant ≈ 20，仍在 MySQL max_connections=200 内

set_env() {
  local key="$1" value="$2"
  if [ "$DRY" = "--dry-run" ]; then printf "  [dry-run] %s=%s\n" "$key" "$value"; return; fi
  if grep -q "^${key}=" "$RT"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$RT"
  else
    echo "${key}=${value}" >> "$RT"
  fi
}

# 副本节点靠 SMARTLECT_APP_SERVICES 识别（主节点不设这个键，跑全部服务）
IS_REPLICA=$(grep -c "^SMARTLECT_APP_SERVICES=" "$RT" || true)

echo "[$(hostname)] $(nproc) 核 / $(awk '/MemTotal/{printf "%d", $2/1048576}' /proc/meminfo)G 角色=$([ "$IS_REPLICA" -gt 0 ] && echo 副本 || echo 主节点)"

set_env SMARTLECT_DB_POOL_MAX_SIZE "$POOL"
if [ "$IS_REPLICA" -gt 0 ]; then
  set_env SMARTLECT_JAVA_PROCESSORS 2
  set_env SMARTLECT_JAVA_XMS 256m
  set_env SMARTLECT_JAVA_XMX 512m
else
  echo "  主节点 JVM 参数保持不变（无证据支持改动）"
fi
[ "$DRY" = "--dry-run" ] || { chmod 600 "$RT"; echo "  已写入 $RT（生效需 systemctl restart smartlect-apps）"; }
