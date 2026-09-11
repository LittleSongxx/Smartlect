"""Bounded recommendation functions over Java facts; no independent Agent or commerce writes."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import math
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from smartlect.ads.analytics import to_cents
from smartlect.commerce import CommerceError
from smartlect.events import canonical
from smartlect.knowledge import tokens
from smartlect.state import StateError, _actor

ROUTES = ('content', 'category', 'copurchase', 'popular', 'newest')
FEATURES = ('content', 'category', 'copurchase', 'popularity', 'newness', 'preference', 'affordability')
MAX_PRODUCTS = 50
MAX_RERANK_SKUS = 12
ALGORITHM_VERSION = 'sku-rank-paid-units-v1'


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    query: str = Field(default='', max_length=200, description='名称/规格软匹配；商品ID用product_id，不填此处')
    product_id: str | None = Field(default=None, min_length=1, max_length=64, description='用户指定的真实商品ID；仅缩小授权范围')
    category_id: str | None = Field(default=None, min_length=1, max_length=64, description='仅已知真实类目ID，未知省略，不能猜')
    max_price_cents: int | None = Field(default=None, ge=0, le=100000000)
    min_price_cents: int = Field(default=0, ge=0, le=100000000)
    quantity: int = Field(default=1, ge=1, le=999)
    limit: int = Field(default=4, ge=1, le=8)
    required_terms: list[str] = Field(default_factory=list, max_length=16, description='名称/规格必须包含的文字；不是商品ID')
    excluded_terms: list[str] = Field(default_factory=list, max_length=20)
    excluded_product_ids: list[str] = Field(default_factory=list, max_length=64)
    excluded_sku_keys: list[str] = Field(default_factory=list, max_length=64)


def _fold(text):
    return unicodedata.normalize('NFKC', text).casefold()


def constraints(request, preferences=()):
    request = request if isinstance(request, RecommendationRequest) else RecommendationRequest.model_validate(request)
    result = request.model_dump()
    for key in ('required_terms', 'excluded_terms', 'excluded_product_ids', 'excluded_sku_keys'):
        if any(not value.strip() or len(value) > 128 for value in result[key]):
            raise StateError('invalid_recommendation_constraint', 422)
    # Only explicit saved restrictions become default hard constraints. Inferred
    # preferences remain ranking signals; current request restrictions take priority.
    for preference in preferences:
        if preference.get('source') != 'explicit':
            continue
        if preference.get('preference_key') == 'budget_max_cents' and result['max_price_cents'] is None:
            value = preference.get('value')
            if type(value) is int and 0 <= value <= 100000000:
                result['max_price_cents'] = value
        if preference.get('preference_key') == 'avoid' and 'excluded_terms' not in request.model_fields_set:
            value = preference.get('value')
            if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
                result['excluded_terms'] = list(value)
    if result['max_price_cents'] is not None and result['min_price_cents'] > result['max_price_cents']:
        raise StateError('invalid_price_interval', 422)
    return result


def scope_filter(product_scope):
    if not isinstance(product_scope, dict) or set(product_scope) != {'include', 'exclude'}:
        raise StateError('product_scope_required', 403)
    included, excluded = product_scope['include'], product_scope['exclude']
    if included is not None and (not isinstance(included, list) or len(included) > 5000):
        raise StateError('invalid_product_scope', 403)
    if not isinstance(excluded, list) or len(excluded) > 5000:
        raise StateError('invalid_product_scope', 403)
    if any(not isinstance(value, str) or not value or len(value) > 64 for value in [*(included or []), *excluded]):
        raise StateError('invalid_product_scope', 403)
    return None if included is None else frozenset(included), frozenset(excluded)


def in_scope(product_id, product_scope):
    included, excluded = product_scope
    return product_id not in excluded and (included is None or product_id in included)


def eligible_skus(snapshot, stocks, request, *, product_scope, allowed_sku_keys=None):
    """Extracted from F2 tools.search_skus; exact per-SKU stock, never totalStocks."""
    catalog = {row['productId']: row for row in snapshot.get('products', [])}
    stock_rows = {}
    duplicate_stock = set()
    for row in stocks:
        key = (row.get('productId'), row.get('propertyValueIdHash'))
        if key in stock_rows:
            duplicate_stock.add(key)
        stock_rows[key] = row.get('stock')
    properties = {(row['productId'], row['propertyValueId']): row for row in snapshot.get('propertyValues', [])}
    cards, removed, seen = [], Counter(), set()
    for sku in snapshot.get('skus', []):
        product_id, digest, value_ids = sku.get('productId'), sku.get('propertyValueIdHash'), sku.get('propertyValueIds')
        if any(not isinstance(value, str) or not value for value in (product_id, digest, value_ids)):
            removed['invalid_sku'] += 1
            continue
        key = product_id + ':' + digest
        if key in seen:
            removed['duplicate_sku'] += 1
            continue
        seen.add(key)
        if not in_scope(product_id, product_scope) or allowed_sku_keys is not None and key not in allowed_sku_keys:
            removed['scope_or_candidate_denied'] += 1
            continue
        product = catalog.get(product_id)
        if not product or type(product.get('status')) is not int or product['status'] != 1:
            removed['not_on_sale'] += 1
            continue
        stock = stock_rows.get((product_id, digest))
        if (product_id, digest) in duplicate_stock or type(stock) is not int or stock < request['quantity']:
            removed['stock_unavailable'] += 1
            continue
        try:
            if type(sku.get('price')) not in {int, str, Decimal}:
                raise ValueError()
            price = to_cents(str(sku['price']))
        except ValueError:
            removed['invalid_price'] += 1
            continue
        if (price < request['min_price_cents'] or request['max_price_cents'] is not None
                and price > request['max_price_cents']):
            removed['price_constraint'] += 1
            continue
        if product_id in request['excluded_product_ids'] or key in request['excluded_sku_keys']:
            removed['explicit_exclusion'] += 1
            continue
        if request['category_id'] is not None and product.get('categoryId') != request['category_id']:
            removed['category_constraint'] += 1
            continue
        property_rows = [properties.get((product_id, value_id)) for value_id in value_ids.split('-')]
        if any(row is None or not isinstance(row.get('propertyValue'), str) for row in property_rows):
            removed['unknown_specification'] += 1
            continue
        specification = '/'.join(row['propertyValue'] for row in property_rows)
        text = _fold(str(product.get('productName') or '') + ' ' + specification)
        if (any(_fold(term) not in text for term in request['required_terms']) or
                any(_fold(term) in text for term in request['excluded_terms'])):
            removed['term_constraint'] += 1
            continue
        cards.append({**sku, 'price': str(sku['price']), 'price_cents': price, 'stock': stock,
            'productName': product.get('productName') or '', 'categoryId': product.get('categoryId'),
            'cover': product.get('cover'), 'specification': specification, 'sku_key': key})
    return cards, dict(removed)


def merge_candidates(route_rows, *, product_scope, limit=MAX_PRODUCTS):
    merged = {}
    for route in ROUTES:
        seen = set()
        for rank, row in enumerate(route_rows.get(route, []), 1):
            product_id = row if isinstance(row, str) else row.get('productId')
            if not isinstance(product_id, str) or not product_id or product_id in seen or not in_scope(product_id, product_scope):
                continue
            seen.add(product_id)
            if product_id not in merged and len(merged) >= limit:
                continue
            merged.setdefault(product_id, {})[route] = rank
    return merged


def rank_skus(cards, request, routes, weights, preferences=(), *, paid_products=None):
    query = set(tokens(request['query']))
    likes = []
    for preference in preferences:
        key, value = preference.get('preference_key'), preference.get('value')
        if key in {'likes', 'purpose', 'categories'}:
            likes.extend(value if isinstance(value, list) else [value] if isinstance(value, str) else [])
    results = []
    for card in cards:
        sources = routes.get(card['productId'], {})
        payment = (paid_products or {}).get(card['productId'])
        paid_units = payment['paidUnits'] if payment else None
        text = card['productName'] + ' ' + card['specification']
        content_score = len(query & set(tokens(text))) / max(len(query), 1)
        maximum = request['max_price_cents']
        features = {'content': content_score,
            'category': float(request['category_id'] is not None and card['categoryId'] == request['category_id']),
            'copurchase': 1 / sources['copurchase'] if 'copurchase' in sources else 0,
            'popularity': min(math.log1p(paid_units) / math.log(1001), 1) if paid_units is not None else 0,
            'newness': 1 / sources['newest'] if 'newest' in sources else 0,
            'preference': sum(_fold(term) in _fold(text) for term in likes if isinstance(term, str) and term) / max(len(likes), 1),
            'affordability': max(0, 1 - card['price_cents'] / maximum) if maximum else 0}
        contributions = {key: round(features[key] * weights[key], 6) for key in FEATURES}
        reasons = []
        if features['content']:
            reasons.append('商品名称或规格匹配本次查询')
        if features['category']:
            reasons.append('匹配指定类目')
        if features['copurchase']:
            reasons.append('曾与您关注的商品一起购买')
        if paid_units:
            reasons.append('已有' + str(paid_units) + '件确认付款（含后续退款订单）')
        if features['newness']:
            reasons.append('按上架时间为您推荐')
        if features['preference']:
            reasons.append('商品名称或规格匹配已记录的用途、喜好或关注品类')
        if maximum is not None:
            reasons.append('当前规格符合您的单价预算')
        results.append({**card, 'features': {key: round(value, 6) for key, value in features.items()},
            'feature_contributions': contributions, 'rule_score': round(sum(contributions.values()), 6),
            'candidate_routes': sources, 'popularity_evidence': payment, 'reasons': reasons})
    return sorted(results, key=lambda card: (-card['rule_score'], card['price_cents'], card['sku_key']))


def validate_rerank(value, cards):
    keys = [card['sku_key'] for card in cards]
    supplied = value.get('sku_keys') if isinstance(value, dict) else value
    if (not isinstance(supplied, list) or any(not isinstance(key, str) for key in supplied)
            or len(supplied) != len(keys) or set(supplied) != set(keys)):
        raise ValueError('rerank_must_permute_same_candidates')
    if len(set(supplied)) != len(supplied):
        raise ValueError('invalid_rerank_keys')
    return supplied


class RecommendationService:
    def __init__(self, commerce, strategy_store):
        self.commerce, self.strategies = commerce, strategy_store

    async def _snapshot(self, product_ids, request, scope, *, allowed_sku_keys=None):
        product_ids = [product_id for product_id in dict.fromkeys(product_ids) if in_scope(product_id, scope)][:MAX_PRODUCTS]
        if not product_ids:
            return [], {}
        snapshot = await self.commerce.request('product', '/internal/product/snapshotBatch', data={'productIds': product_ids})
        skus = [sku for sku in snapshot.get('skus', []) if sku.get('productId') in product_ids
                and (allowed_sku_keys is None or str(sku.get('productId')) + ':' + str(sku.get('propertyValueIdHash')) in allowed_sku_keys)]
        if not skus:
            return [], {'no_sku': len(product_ids)}
        if len(skus) > 500:
            raise StateError('recommendation_sku_capacity_exceeded', 503)
        stocks = await self.commerce.request('stock', '/internal/stock/getBatch', data=[{
            'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']} for sku in skus])
        return eligible_skus({**snapshot, 'skus': skus}, stocks, request, product_scope=scope, allowed_sku_keys=allowed_sku_keys)

    async def recommend(self, actor, request, *, preferences=(), seed_product_id=None, subject_key=None,
                        semantic_rerank=None, product_scope=None):
        kind, _, _ = _actor(actor)
        if 'shopping:read' not in getattr(actor, 'permissions', ()) and not (
                kind == 'merchant' and 'admin:legacy' in getattr(actor, 'permissions', ())):
            raise StateError('permission_denied', 403)
        scope, request = scope_filter(product_scope), constraints(request, preferences)
        if request['product_id'] is not None:
            requested = frozenset([request['product_id']])
            scope = (requested if scope[0] is None else scope[0] & requested, scope[1])
        if seed_product_id is not None and (not isinstance(seed_product_id, str) or not seed_product_id or len(seed_product_id) > 64):
            raise StateError('invalid_seed_product_id', 422)
        assignment = await asyncio.to_thread(self.strategies.assign, actor, subject_key=subject_key)
        config, errors = assignment['config'], {}
        quotas = config['quotas']
        category = request['category_id']  # Saved category preferences are text, not Java catalog IDs.
        recall_scope = {'excludeProductIds': sorted(scope[1] | set(request['excluded_product_ids']))}
        if len(recall_scope['excludeProductIds']) > 5000:
            raise StateError('recommendation_scope_capacity_exceeded', 422)
        if scope[0] is not None:
            recall_scope['productIds'] = sorted(scope[0])

        async def recall(route, *, category_id=None):
            if not quotas[route]:
                return []
            try:
                if route == 'copurchase':
                    if seed_product_id is None or not in_scope(seed_product_id, scope):
                        return []
                    return await self.commerce.request('order', '/internal/order/commerce/coPurchaseProductIds',
                        data={'productId': seed_product_id, 'limit': quotas[route], **recall_scope})
                if route == 'popular':
                    return await self.commerce.request('order', '/internal/order/commerce/popularProducts',
                        data={'limit': quotas[route], **recall_scope})
                if route == 'category' and category_id is None:
                    return []
                query = {'keyword': request['query'] if route == 'content' else '', 'limit': quotas[route], **recall_scope}
                if category_id is not None:
                    query['categoryId'] = category_id
                return await self.commerce.request('product', '/internal/product/commerce/searchOnSale', data=query)
            except CommerceError:
                errors[route] = 'commerce_unavailable'
                return []

        content, popular, newest, copurchase = await asyncio.gather(recall('content', category_id=category),
            recall('popular', category_id=category), recall('newest', category_id=category), recall('copurchase'))
        if category is None:
            category = next((row.get('categoryId') for row in content if in_scope(row.get('productId'), scope)), None)
        category_rows = await recall('category', category_id=category)
        route_rows = dict(content=content, category=category_rows, copurchase=copurchase, popular=popular, newest=newest)
        merged = merge_candidates(route_rows, product_scope=scope)
        paid_products = {}
        for row in popular:
            try:
                if (type(row.get('paidUnits')) is not int or row['paidUnits'] < 0
                        or row.get('basis') != 'confirmed_payment_units_v1'
                        or datetime.fromisoformat(row['observedAt'].replace('Z', '+00:00')).tzinfo is None):
                    continue
                paid_products[row['productId']] = {key: row[key] for key in ('paidUnits', 'basis', 'observedAt')}
            except (KeyError, TypeError, ValueError, AttributeError):
                continue  # Unknown payment evidence gets no sales claim or popularity contribution.
        cards, initial_removed = await self._snapshot(merged, request, scope)
        ranked = rank_skus(cards, request, merged, config['weights'], preferences, paid_products=paid_products)[:MAX_RERANK_SKUS]
        mode = 'rule' if config['ranking'] == 'rule' else 'content_rule'
        ranked_keys = [card['sku_key'] for card in ranked]
        rerank_error = None
        if config['ranking'] == 'content' and semantic_rerank is not None and len(ranked) > 1:
            payload = {'query': request['query'], 'hard_constraints': request,
                       'candidates': [{key: card[key] for key in ('sku_key', 'productName', 'specification', 'price_cents',
                                                               'categoryId', 'features')} for card in ranked]}
            try:
                order = await asyncio.wait_for(semantic_rerank(payload), timeout=15)
                ranked_keys = validate_rerank(order, ranked)
                mode = 'content_llm'
            except StateError:
                raise  # Lease/identity fencing must never be softened into a ranking fallback.
            except Exception:
                mode, rerank_error = 'content_rule_fallback', 'semantic_rerank_unavailable_or_invalid'
        elif config['ranking'] == 'content':
            rerank_error = 'semantic_rerank_not_configured' if semantic_rerank is None else 'insufficient_candidates'
        # No recall after ranking: Java refreshes exactly the previously eligible SKU keys.
        refreshed, final_removed = await self._snapshot([card['productId'] for card in ranked], request, scope,
                                                        allowed_sku_keys=set(ranked_keys))
        scored = rank_skus(refreshed, request, merged, config['weights'], preferences, paid_products=paid_products)
        if mode == 'content_llm':
            by_key = {card['sku_key']: card for card in scored}
            scored = [by_key[key] for key in ranked_keys if key in by_key]
        observed_at = datetime.now(timezone.utc).isoformat()
        selected = scored[:request['limit']]
        for position, card in enumerate(selected, 1):
            card.update(rank=position, observed_at=observed_at, strategy_version=assignment['strategy_version'],
                        assignment_id=assignment['assignment_id'], ranking_mode=mode, algorithm_version=ALGORITHM_VERSION)
        public_assignment = {key: value for key, value in assignment.items() if key != 'config'}
        return {'items': selected, 'algorithm_version': ALGORITHM_VERSION, 'assignment': public_assignment, 'assignment_id': assignment['assignment_id'],
                'experiment_id': assignment['experiment_id'], 'strategy_version': assignment['strategy_version'],
                'ranking_mode': mode, 'observed_at': observed_at,
                'candidate_snapshot_hash': sha256(canonical([{'sku_key': card['sku_key'], 'price_cents': card['price_cents'],
                    'stock': card['stock']} for card in ranked]).encode()).hexdigest(),
                'diagnostics': {'route_counts': {key: sum(in_scope(row if isinstance(row, str) else row.get('productId'), scope)
                    for row in rows) for key, rows in route_rows.items()},
                    'route_errors': errors, 'merged_products': len(merged), 'eligible_skus': len(cards),
                    'rerank_candidate_keys': [card['sku_key'] for card in ranked], 'rerank_error': rerank_error,
                    'initial_filtered': initial_removed, 'final_filtered': final_removed,
                    'final_revalidation': bool(ranked), 'empty_reason': 'no_eligible_sku' if not selected else None}}
