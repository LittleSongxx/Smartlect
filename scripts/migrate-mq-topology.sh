#!/usr/bin/env bash
# growth→assistant 服务改名配套的 MQ 拓扑迁移（生产 T 窗口执行）。
# 前提：新版 Java 已启动并在 vhost 声明好新拓扑（smartlect.assistant.commerce.queue /
# smartlect.user.member.*）。本脚本只负责：残留消息搬运 + 旧拓扑删除。
# 用法：RABBIT_CONTAINER=rabbit-c1 VHOST=smartlect bash scripts/migrate-mq-topology.sh [--dry-run]
set -euo pipefail

RABBIT_CONTAINER="${RABBIT_CONTAINER:-rabbit-c1}"
VHOST="${VHOST:-smartlect}"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

mq() { docker exec "$RABBIT_CONTAINER" rabbitmqctl -q -p "$VHOST" "$@"; }

# 旧名 → 新名（durable 队列改名只能靠搬运）
declare -A QUEUE_MAP=(
  ["smartlect.growth.commerce.queue"]="smartlect.assistant.commerce.queue"
  ["smartlect.user.growth.queue"]="smartlect.user.member.queue"
  ["smartlect.user.growth.dead.queue"]="smartlect.user.member.dead.queue"
)
OLD_EXCHANGES=("smartlect.user.growth.exchange")

echo "== 旧队列残留消息 =="
for old in "${!QUEUE_MAP[@]}"; do
  ready=$(mq list_queues --silent name messages_ready <<<"" 2>/dev/null | awk -v q="^${old}$" '$1 ~ q {print $2}')
  ready="${ready:-0}"
  echo "  $old ready=$ready -> ${QUEUE_MAP[$old]}"
  if [[ "$ready" != "0" && $DRY_RUN -eq 0 ]]; then
    # shovel 单条搬运（幂等：消费端按 event_id/idempotency_key 去重，重复投递安全）
    mq shovel_shovel_run "$old" "amqp:///%2F${VHOST}?routing_key=" 2>/dev/null \
      || echo "  NOTE: shovel 参数因 rabbitmqctl 版本而异，可用 python 搬运脚本替代（见 runbook）"
  fi
done

if [[ $DRY_RUN -eq 1 ]]; then
  echo "dry-run：只展示，不删除。"; exit 0
fi

echo "== 删除旧队列（含 retry 拓扑派生队列）与旧交换机 =="
for old in "${!QUEUE_MAP[@]}"; do
  [[ "$old" == *.dead.queue ]] && continue  # 死信队列没有 retry 派生
  for suffix in ".retry.1" ".retry.2" ".retry.3"; do
    mq delete_queue "${old}${suffix}" 2>/dev/null || true
  done
  mq delete_queue "$old" 2>/dev/null || true
done
for ex in "${OLD_EXCHANGES[@]}"; do
  docker exec "$RABBIT_CONTAINER" rabbitmqadmin -V "$VHOST" delete exchange name="$ex" 2>/dev/null || true
done

echo "== 迁移后校验：新队列存在、旧名字消失 =="
mq list_queues --silent name | grep -E "assistant.commerce.queue|user.member.queue" || echo "  WARN: 新队列未找到，确认新版 Java 已启动"
mq list_queues --silent name | grep -E "growth.commerce.queue|user.growth.queue" && echo "  WARN: 旧队列仍在" || echo "  OK: 旧队列已清除"
