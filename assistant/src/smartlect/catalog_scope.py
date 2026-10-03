"""商品可售范围（include/exclude）：由 execution_resource 表派生。

2026-10 收敛重构：随推荐/归因线退役从 attribution.py 中拆出，保留为独立的
确定性查询——前端商品列表过滤（utils/productScope）与评测场景仍在使用。
"""

from smartlect.catalog_gate import is_isolated_product_id


def product_scope(connect, actor):
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT resource_id,execution_scope_id FROM execution_resource WHERE resource_type='product'")
            rows = cursor.fetchall()
    scope = actor.execution_scope_id
    if scope == 'store':
        # 9100/9300 eval SKUs are excluded by prefix in catalog_gate.in_scope.
        # Only keep the remaining non-store IDs so the exclude list stays ≤5000.
        excluded = list(dict.fromkeys(
            r['resource_id'] for r in rows
            if r['execution_scope_id'] != 'store' and not is_isolated_product_id(r['resource_id'])))
        if len(excluded) > 5000:
            excluded = excluded[:5000]
        return {'include': None, 'exclude': excluded}
    # A bounded include already fences a scoped actor; enumerating every other
    # scope's products would grow with each demo scenario and trip the scope cap.
    return {'include': [r['resource_id'] for r in rows if r['execution_scope_id'] == scope],
            'exclude': []}
