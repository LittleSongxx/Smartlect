#!/usr/bin/env bash
# 压测期 demo 库存管理（node1 执行）
#
# 交易闭环每下 1 单消耗 1 件库存，而 demo 夹具在 evals 里共用：直接把库存打空会污染
# 评测夹具。所以这里用"快照 → 临时扩容 → 测完按原值还原"的方式，全程可逆。
#
# 用法：bash stock-control.sh snapshot|topup|restore
set -euo pipefail
EV=/opt/cluster/evidence
SNAP="$EV/sku_stock-before.txt"
AFTER="$EV/sku_stock-after.txt"
TOPUP="${TOPUP_STOCK:-200000}"
mkdir -p "$EV"

mysql_q() { # $1=库 $2=SQL文件或-e表达式
  docker exec -i smartlect-mysql-1 bash -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N "$@"' -- "$@"
}

dump() {
  docker exec smartlect-mysql-1 bash -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N smartlect_stock -e "SELECT product_id, property_value_id_hash, stock FROM sku_stock ORDER BY product_id, property_value_id_hash"'
}

case "${1:?usage: stock-control.sh snapshot|topup|restore}" in
  snapshot)
    dump > "$SNAP"
    echo "[stock] 原值快照: $(wc -l < "$SNAP") 行, 总库存 $(awk '{s+=$3} END {print s+0}' "$SNAP")"
    ;;
  topup)
    [ -s "$SNAP" ] || { echo "先跑 snapshot"; exit 1; }
    dump > "$EV/sku_stock-topup-pre.txt"
    docker exec smartlect-mysql-1 bash -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -uroot smartlect_stock -e \"UPDATE sku_stock SET stock = $TOPUP\""
    echo "[stock] 已扩容到每 SKU $TOPUP 件, 合计 $(awk '{s+=$3} END {print s+0}' "$EV/sku_stock-topup-pre.txt") -> $(($(wc -l < "$SNAP") * TOPUP))"
    ;;
  restore)
    [ -s "$SNAP" ] || { echo "没有原值快照，拒绝还原"; exit 1; }
    dump > "$AFTER"
    # 按快照逐行还原。property_value_id_hash 是十六进制串，必须加引号——MySQL 会把
    # 无引号的 32 位十六进制当标识符，报 "Unknown column '<hash>'"。
    awk -F'\t' '{printf "UPDATE sku_stock SET stock=%s WHERE product_id=\"%s\" AND property_value_id_hash=\"%s\";\n", $3, $1, $2}' "$SNAP" \
      | docker exec -i smartlect-mysql-1 bash -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot smartlect_stock'
    dump > "$EV/sku_stock-restored.txt"
    echo "[stock] 已按原值还原"
    echo "  还原前(压测后): $(awk '{s+=$3} END {print s+0}' "$AFTER")"
    echo "  还原后        : $(awk '{s+=$3} END {print s+0}' "$EV/sku_stock-restored.txt")"
    diff -q "$SNAP" "$EV/sku_stock-restored.txt" >/dev/null && echo "  与原快照逐行一致 ✓" || echo "  ⚠ 与原快照不一致"
    ;;
  *) echo "unknown action: $1"; exit 2;;
esac
