"""Derive inferred likes/categories/purpose from Java browse and order history."""
import asyncio

from smartlect.commerce import CommerceError
from smartlect.state import StateError

INTEREST_TERMS = (
    '零食', '雪饼', '饼干', '糕点', '小吃', '奶糕',
    '汽水', '可乐', '饮料', '碳酸',
    '文具', '中性笔', '公仔', '毛绒', '玩偶', '玩具',
    '车充', '充电器', '耳机', '电脑', '手机',
    '摆件', '收纳', '项链', '唇釉', '毛衣', '床垫',
    '香水', '吉他', '生鲜',
)

CATEGORY_WORDS = {
    '20021': '生鲜', '20022': '零食', '20023': '饮料',
    '20033': '车充', '20019': '摆件', '20011': '项链',
    '20012': '美妆', '20016': '床垫', '20003': '耳机',
    '20007': '毛衣', '20028': '吉他', '20015': '香水',
    '88409': '玩具', '20001': '手机', '20002': '电脑',
}


def derive_inferred_preferences(products, *, order_names=()):
    likes, categories = [], []
    seen_like, seen_cat = set(), set()
    names = []
    for product in products or ():
        if not isinstance(product, dict):
            continue
        name = product.get('productName') or product.get('product_name') or ''
        if isinstance(name, str) and name:
            names.append(name)
        word = CATEGORY_WORDS.get(str(product.get('categoryId') or product.get('category_id') or ''))
        if word and word not in seen_cat:
            seen_cat.add(word)
            categories.append(word)
        for term in INTEREST_TERMS:
            if term in name and term not in seen_like:
                seen_like.add(term)
                likes.append(term)
    for name in order_names or ():
        if not isinstance(name, str):
            continue
        for term in INTEREST_TERMS:
            if term in name and term not in seen_like:
                seen_like.add(term)
                likes.append(term)
    if not likes and not categories:
        return {}
    purpose = '、'.join((likes or categories)[:3])
    result = {}
    if likes:
        result['likes'] = likes[:20]
    if categories:
        result['categories'] = categories[:20]
    if purpose:
        result['purpose'] = purpose[:500]
    return result


async def collect_behavior_snapshot(commerce, actor):
    browse = await commerce.request(
        'user', '/internal/user/commerce/browseHistoryIds',
        actor=actor, data={'userId': actor.actor_id, 'limit': 20})
    orders = await commerce.request(
        'order', '/internal/order/commerce/listOrders',
        actor=actor, data={'userId': actor.actor_id, 'limit': 30})
    browse_ids = [item for item in (browse or []) if isinstance(item, str) and item]
    order_ids, order_names = [], []
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        for item in order.get('items') or []:
            if not isinstance(item, dict):
                continue
            product_id = item.get('productId')
            if product_id:
                order_ids.append(str(product_id))
            name = item.get('productName')
            if isinstance(name, str) and name:
                order_names.append(name)
    ids = []
    for product_id in [*browse_ids, *order_ids]:
        if product_id not in ids:
            ids.append(product_id)
        if len(ids) >= 20:
            break
    if not ids:
        return [], order_names
    snapshot = await commerce.request(
        'product', '/internal/product/snapshotBatch', data={'productIds': ids})
    products = snapshot.get('products') if isinstance(snapshot, dict) else []
    return list(products or []), order_names


async def sync_behavior_preferences(commerce, memory, actor):
    if getattr(actor, 'subject_type', None) != 'user' or memory is None:
        return []
    try:
        products, order_names = await collect_behavior_snapshot(commerce, actor)
        values = derive_inferred_preferences(products, order_names=order_names)
        if not values:
            return []
        apply = getattr(memory, 'apply_behavior_inference', None)
        if not callable(apply):
            return []
        ids = [row.get('productId') for row in products if isinstance(row, dict) and row.get('productId')]
        return await asyncio.to_thread(apply, actor, values, product_ids=ids)
    except (CommerceError, StateError):
        return []
