"""Shopping-only catalog retrieve. Hard-constraint misses stay empty; no popular fill."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import uuid

from smartlect.catalog_gate import _fold, eligible_skus, in_scope, scope_filter
from smartlect.commerce import CommerceError
from smartlect.events import canonical
from smartlect.knowledge import tokens
from smartlect.recommendation.service import MAX_PRODUCTS, MAX_RERANK_SKUS, validate_rerank
from smartlect.shopping_mission import (empty_mission, has_hard_constraints, retrieval_variants,
                                        shopping_request, validate_sku_key)
from smartlect.state import StateError, _actor

STRATEGY_VERSION = 'shopping-constraint-v2'
ALGORITHM_VERSION = 'shopping-constraint-retrieve-v2'
SHOPPING_FEATURES = ('content', 'category', 'preference', 'affordability')


def rank_shopping_skus(cards, request, preferences=()):
    query = set(tokens(request.get('query') or ''))
    likes = []
    for preference in preferences:
        key, value = preference.get('preference_key'), preference.get('value')
        if key in {'likes', 'purpose', 'categories'}:
            likes.extend(value if isinstance(value, list) else [value] if isinstance(value, str) else [])
    results = []
    for card in cards:
        text = card['productName'] + ' ' + card['specification']
        content_score = len(query & set(tokens(text))) / max(len(query), 1)
        maximum = request.get('max_price_cents')
        features = {
            'content': content_score,
            'category': float(request.get('category_id') is not None and card['categoryId'] == request['category_id']),
            'preference': sum(_fold(term) in _fold(text) for term in likes if isinstance(term, str) and term) / max(len(likes), 1),
            'affordability': max(0, 1 - card['price_cents'] / maximum) if maximum else 0,
        }
        contributions = {key: round(features[key], 6) for key in SHOPPING_FEATURES}
        reasons = []
        if features['content']:
            reasons.append('商品名称或规格匹配本次查询')
        if features['category']:
            reasons.append('匹配指定类目')
        if features['preference']:
            reasons.append('商品名称或规格匹配已记录的用途、喜好或关注品类')
        if maximum is not None:
            reasons.append('当前规格符合您的单价预算')
        results.append({**card, 'features': {key: round(value, 6) for key, value in features.items()},
            'feature_contributions': contributions, 'rule_score': round(sum(contributions.values()), 6),
            'candidate_routes': {'content': 1}, 'reasons': reasons})
    return sorted(results, key=lambda card: (-card['rule_score'], card['price_cents'], card['sku_key']))


def comparison_table(cards):
    keys = [card['sku_key'] for card in cards]
    fields = (
        ('productName', '商品'),
        ('specification', '规格'),
        ('price_cents', '价格'),
        ('stock', '库存'),
    )
    rows = []
    for field, label in fields:
        values = {card['sku_key']: card.get(field) for card in cards}
        rows.append({'field': field, 'label': label, 'values': values,
                     'differ': len(set(canonical(value) for value in values.values())) > 1})
    return {
        'sku_keys': keys,
        'columns': [{key: card.get(key) for key in ('sku_key', 'productName', 'specification')} for card in cards],
        'rows': rows,
    }


class ShoppingRetrieve:
    def __init__(self, commerce):
        self.commerce = commerce

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

    async def _search_on_sale(self, request, scope, keyword, *, category_id=None, limit=MAX_PRODUCTS, errors=None):
        errors = {} if errors is None else errors
        recall_scope = {'excludeProductIds': sorted(scope[1] | set(request.get('excluded_product_ids') or []))}
        if len(recall_scope['excludeProductIds']) > 5000:
            raise StateError('recommendation_scope_capacity_exceeded', 422)
        if scope[0] is not None:
            recall_scope['productIds'] = sorted(scope[0])
        query = {'keyword': keyword or '', 'limit': limit, **recall_scope}
        if category_id is not None:
            query['categoryId'] = category_id
        try:
            return await self.commerce.request('product', '/internal/product/commerce/searchOnSale', data=query)
        except CommerceError:
            errors['content'] = 'commerce_unavailable'
            return []

    def _product_ids(self, rows, request):
        ids = []
        if request.get('product_id'):
            ids.append(request['product_id'])
        for row in rows:
            product_id = row if isinstance(row, str) else (row or {}).get('productId')
            if isinstance(product_id, str) and product_id:
                ids.append(product_id)
        return ids

    async def _rerank(self, ranked, request, semantic_rerank):
        mode, rerank_error, ranked_keys = 'content_rule', None, [card['sku_key'] for card in ranked]
        if semantic_rerank is not None and len(ranked) > 1:
            payload = {'query': request.get('query') or '', 'hard_constraints': request,
                       'candidates': [{key: card[key] for key in ('sku_key', 'productName', 'specification', 'price_cents',
                                                               'categoryId', 'features')} for card in ranked]}
            try:
                order = await asyncio.wait_for(semantic_rerank(payload), timeout=15)
                ranked_keys = validate_rerank(order, ranked)
                mode = 'content_llm'
            except StateError:
                raise
            except Exception:
                mode, rerank_error = 'content_rule_fallback', 'semantic_rerank_unavailable_or_invalid'
        elif semantic_rerank is None:
            rerank_error = 'semantic_rerank_not_configured' if len(ranked) > 1 else 'insufficient_candidates'
        return ranked_keys, mode, rerank_error

    def _finish(self, selected, *, ranked, cards, mode, rerank_error, initial_removed, final_removed,
                empty_reason, extras=None, variants=(), browse=False, relaxed=False, errors=None):
        assignment_id = uuid.uuid4().hex
        observed_at = datetime.now(timezone.utc).isoformat()
        for position, card in enumerate(selected, 1):
            card.update(rank=position, observed_at=observed_at, strategy_version=STRATEGY_VERSION,
                        assignment_id=assignment_id, ranking_mode=mode, algorithm_version=ALGORITHM_VERSION)
        result = {
            'items': selected, 'algorithm_version': ALGORITHM_VERSION, 'assignment_id': assignment_id,
            'experiment_id': None, 'strategy_version': STRATEGY_VERSION, 'ranking_mode': mode,
            'observed_at': observed_at,
            'candidate_snapshot_hash': sha256(canonical([{'sku_key': card['sku_key'], 'price_cents': card['price_cents'],
                'stock': card['stock']} for card in ranked]).encode()).hexdigest(),
            'diagnostics': {
                'variants': list(variants), 'browse_newest': browse, 'recall_relaxed': relaxed,
                'popular_used': False, 'copurchase_used': False,
                'route_errors': errors or {}, 'eligible_skus': len(cards),
                'rerank_candidate_keys': [card['sku_key'] for card in ranked], 'rerank_error': rerank_error,
                'initial_filtered': initial_removed, 'final_filtered': final_removed,
                'final_revalidation': bool(ranked), 'empty_reason': empty_reason,
            },
        }
        if extras:
            result.update(extras)
        return result

    async def recommend(self, actor, request, *, mission=None, preferences=(), product_scope=None, semantic_rerank=None):
        kind, _, _ = _actor(actor)
        if 'shopping:read' not in getattr(actor, 'permissions', ()) and not (
                kind == 'merchant' and 'admin:legacy' in getattr(actor, 'permissions', ())):
            raise StateError('permission_denied', 403)
        mission = mission or empty_mission()
        request = shopping_request(request, mission)
        scope = scope_filter(product_scope)
        if request['product_id'] is not None:
            requested = frozenset([request['product_id']])
            scope = (requested if scope[0] is None else scope[0] & requested, scope[1])
        hard = has_hard_constraints(request, mission)
        variants = retrieval_variants(request, mission)
        errors, rows, browse, relaxed = {}, [], False, False
        if variants:
            for variant in variants:
                rows.extend(await self._search_on_sale(request, scope, variant, category_id=request['category_id'], errors=errors))
        if not rows:
            # Recall and eligibility are separate concerns. Every hard slot in this
            # design is a post-filter predicate on the snapshot, so empty-keyword
            # recall plus the eligibility gate is filtered enumeration — never
            # popular fill. `hard` only names the empty_reason; it no longer blocks
            # recall (budget-only requests used to be the one hard slot with no
            # recall path at all).
            if request['product_id'] or request['category_id']:
                rows.extend(await self._search_on_sale(request, scope, '', category_id=request['category_id'], errors=errors))
            else:
                browse, relaxed = not hard, hard
                rows.extend(await self._search_on_sale(request, scope, '', errors=errors))
        product_ids = self._product_ids(rows, request)
        cards, initial_removed = await self._snapshot(product_ids, request, scope)
        if not cards and (request.get('required_terms') or request.get('category_id')):
            extra = await self._search_on_sale(request, scope, '', category_id=request['category_id'], errors=errors)
            extra_ids = self._product_ids(extra, request)
            if extra_ids and set(extra_ids) != set(product_ids):
                cards, initial_removed = await self._snapshot(extra_ids, request, scope)
        if not cards:
            return self._finish([], ranked=[], cards=cards, mode='content_rule', rerank_error=None,
                                initial_removed=initial_removed, final_removed={},
                                empty_reason='hard_constraint_unsatisfied' if hard else 'no_eligible_sku',
                                variants=variants, browse=browse, relaxed=relaxed, errors=errors)
        ranked = rank_shopping_skus(cards, request, preferences)[:MAX_RERANK_SKUS]
        ranked_keys, mode, rerank_error = await self._rerank(ranked, request, semantic_rerank)
        refreshed, final_removed = await self._snapshot([card['productId'] for card in ranked], request, scope,
                                                        allowed_sku_keys=set(ranked_keys))
        scored = rank_shopping_skus(refreshed, request, preferences)
        if mode == 'content_llm':
            by_key = {card['sku_key']: card for card in scored}
            scored = [by_key[key] for key in ranked_keys if key in by_key]
        selected = scored[:request['limit']]
        return self._finish(selected, ranked=ranked, cards=cards, mode=mode,
                            rerank_error=rerank_error, initial_removed=initial_removed, final_removed=final_removed,
                            empty_reason='hard_constraint_unsatisfied' if hard and not selected else (
                                None if selected else 'no_eligible_sku'),
                            variants=variants, browse=browse, relaxed=relaxed, errors=errors)

    async def compare(self, actor, request, *, mission=None, preferences=(), product_scope=None, semantic_rerank=None):
        kind, _, _ = _actor(actor)
        if 'shopping:read' not in getattr(actor, 'permissions', ()) and not (
                kind == 'merchant' and 'admin:legacy' in getattr(actor, 'permissions', ())):
            raise StateError('permission_denied', 403)
        mission = mission or empty_mission()
        params = dict(request or {})
        sku_keys = []
        for key in params.get('sku_keys') or []:
            item = validate_sku_key(key)
            if item not in sku_keys:
                sku_keys.append(item)
        if params.get('sku_keys') and not 2 <= len(sku_keys) <= 4:
            raise StateError('invalid_compare_sku_keys', 422)
        targets = list(params.get('comparison_targets') or mission.get('comparison_targets') or [])[:4]
        request = shopping_request(params, mission)
        scope = scope_filter(product_scope)
        errors, missing, cards = {}, [], []
        if sku_keys:
            product_ids = [key.split(':', 1)[0] for key in sku_keys]
            found, _ = await self._snapshot(product_ids, request, scope, allowed_sku_keys=set(sku_keys))
            by_key = {card['sku_key']: card for card in found}
            for key in sku_keys:
                if key in by_key:
                    cards.append(by_key[key])
                else:
                    missing.append(key)
        else:
            seen = set()
            for target in targets:
                rows = await self._search_on_sale(request, scope, target, category_id=request.get('category_id'),
                                                  limit=8, errors=errors)
                found, _ = await self._snapshot(self._product_ids(rows, request), request, scope)
                ranked = rank_shopping_skus(found, {**request, 'query': target}, preferences)
                card = next((item for item in ranked if item['sku_key'] not in seen), None)
                if card:
                    seen.add(card['sku_key'])
                    cards.append(card)
                else:
                    missing.append(target)
        cards = cards[:4]
        extras = {
            'comparison': comparison_table(cards),
            'comparison_complete': len(cards) >= 2 and not missing,
            'missing_targets': missing,
        }
        if not cards:
            return self._finish([], ranked=[], cards=[], mode='content_rule', rerank_error=None,
                                initial_removed={}, final_removed={},
                                empty_reason='hard_constraint_unsatisfied', extras=extras, errors=errors)
        ranked_keys, mode, rerank_error = await self._rerank(cards, request, semantic_rerank)
        refreshed, final_removed = await self._snapshot([card['productId'] for card in cards], request, scope,
                                                        allowed_sku_keys=set(ranked_keys))
        by_key = {card['sku_key']: card for card in refreshed}
        selected = [by_key[key] for key in ranked_keys if key in by_key]
        extras['comparison'] = comparison_table(selected)
        extras['comparison_complete'] = len(selected) >= 2 and not missing and len(selected) == len(cards)
        if len(selected) < len(cards):
            extras['missing_targets'] = missing + [card['sku_key'] for card in cards if card['sku_key'] not in by_key]
        return self._finish(selected, ranked=cards, cards=cards, mode=mode,
                            rerank_error=rerank_error, initial_removed={}, final_removed=final_removed,
                            empty_reason=None if selected else 'hard_constraint_unsatisfied', extras=extras,
                            errors=errors)
