"""Deterministic rules and fake-Java safety contracts; no DB or real model calls."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from smartlect.provider import ProviderError
from smartlect.recommendation.service import (RecommendationRequest, RecommendationService, constraints,
    eligible_skus, in_scope, merge_candidates, rank_skus, scope_filter, validate_rerank)
from smartlect.recommendation.store import DEFAULT_STRATEGIES, bucket_for, strategy_config
from smartlect.state import StateError


class FakeStrategies:
    def __init__(self, version='content-v1'):
        self.version = version
        self.subject_keys = []

    def assign(self, actor, *, subject_key=None):
        self.subject_keys.append(subject_key)
        return {'assignment_id': 'assigned-fixture', 'experiment_id': 'fixture-experiment', 'group': 'treatment',
                'bucket': 72, 'strategy_version': self.version, 'experiment_revision': 1,
                'config': deepcopy(DEFAULT_STRATEGIES[self.version])}


class FakeCommerce:
    def __init__(self):
        self.calls = []
        self.products = {
            'content': dict(productId='content', productName='轻便键盘', categoryId='desk', status=1, totalSale=0),
            'popular': dict(productId='popular', productName='基础键盘', categoryId='desk', status=1, totalSale=10000),
            'new': dict(productId='new', productName='轻便鼠标', categoryId='desk', status=1, totalSale=0),
            'paired': dict(productId='paired', productName='键盘便携包', categoryId='desk', status=1, totalSale=0),
            'outside': dict(productId='outside', productName='其他分支键盘', categoryId='desk', status=1, totalSale=100000),
        }
        self.prices = {key: Decimal('100.00') for key in self.products}
        self.stocks = {key: 10 for key in self.products}
        self.paid_units = {'popular': 10000, 'outside': 100000}

    async def request(self, service, path, *, data=None, **kwargs):
        self.calls.append((service, path, deepcopy(data)))
        def scoped(keys):
            return [key for key in keys if ('productIds' not in data or key in data['productIds'])
                    and key not in data.get('excludeProductIds', [])][:data['limit']]
        if path.endswith('/searchOnSale'):
            if data.get('keyword'):
                keys = ['content']
            elif data.get('categoryId'):
                keys = ['content', 'popular', 'new']
            else:
                keys = ['new', 'popular', 'content', 'outside']
            if data.get('categoryId'):
                keys = [key for key in keys if self.products[key]['categoryId'] == data['categoryId']]
            return [deepcopy(self.products[key]) for key in scoped(keys)]
        if path.endswith('/popularProducts'):
            keys = sorted(self.paid_units, key=lambda key: (-self.paid_units[key], key))
            return [dict(productId=key, paidUnits=self.paid_units[key], basis='confirmed_payment_units_excluding_refunds',
                         observedAt='2026-09-09T00:00:00Z') for key in scoped(keys)]
        if path.endswith('/coPurchaseProductIds'):
            return scoped(['outside', 'paired'])
        if path.endswith('/snapshotBatch'):
            keys = data['productIds']
            return {'products': [deepcopy(self.products[key]) for key in keys],
                'skus': [dict(productId=key, propertyValueIdHash='hash-' + key, propertyValueIds='v' + key,
                              price=self.prices[key], sort=0) for key in keys],
                'propertyValues': [dict(productId=key, propertyValueId='v' + key, propertyName='颜色', propertyValue='黑色') for key in keys],
                'totalStocks': {key: 999 for key in keys}}
        if path.endswith('/getBatch'):
            return [dict(productId=row['productId'], propertyValueIdHash=row['propertyValueIdHash'],
                         stock=self.stocks[row['productId']]) for row in data]
        raise AssertionError('Unexpected Java endpoint ' + path)


class RecommendationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(subject_type='user', actor_id='alice', execution_scope_id='isolated', permissions=('shopping:read',))
        self.scope = {'include': ['content', 'popular', 'new', 'paired', 'seed'], 'exclude': ['outside']}
        self.commerce = FakeCommerce()

    async def test_multiroute_rules_content_and_same_real_features_choose_different_order(self):
        results = []
        for version in ('rules-v1', 'content-v1'):
            service = RecommendationService(self.commerce, FakeStrategies(version))
            results.append(await service.recommend(self.actor, {'query': '轻便键盘', 'limit': 4},
                seed_product_id='seed', product_scope=self.scope, subject_key='trusted-browser-subject'))
        rule, content = results
        self.assertEqual((rule['ranking_mode'], content['ranking_mode']), ('rule', 'content_rule'))
        self.assertEqual(rule['items'][0]['productId'], 'popular')
        self.assertEqual(content['items'][0]['productId'], 'content')
        self.assertIn('copurchase', next(item for item in content['items'] if item['productId'] == 'paired')['candidate_routes'])
        for result in results:
            self.assertEqual(result['assignment_id'], 'assigned-fixture')
            self.assertTrue(result['diagnostics']['final_revalidation'])
            self.assertTrue(all(item['productId'] != 'outside' for item in result['items']))
            for item in result['items']:
                self.assertAlmostEqual(item['rule_score'], sum(item['feature_contributions'].values()), places=5)
                self.assertEqual(item['price_cents'], 10000)
                self.assertEqual(item['stock'], 10)
                self.assertTrue(item['reasons'])
        for _, path, data in self.commerce.calls:
            if path.endswith('/snapshotBatch'):
                self.assertNotIn('outside', data['productIds'])

    async def test_requested_product_narrows_every_java_route_and_final_candidates(self):
        service = RecommendationService(self.commerce, FakeStrategies())
        for selected, expected in [('content', {'content'}), ('outside', set())]:
            self.commerce.calls.clear()
            result = await service.recommend(self.actor, {'product_id': selected, 'limit': 8},
                seed_product_id='seed', product_scope=self.scope)
            self.assertEqual({card['productId'] for card in result['items']}, expected)
            for _, path, params in self.commerce.calls:
                if path.endswith(('/searchOnSale', '/popularProducts', '/coPurchaseProductIds')):
                    self.assertEqual(set(params['productIds']), expected)
                elif path.endswith('/snapshotBatch'):
                    self.assertLessEqual(set(params['productIds']), expected)
        result = await service.recommend(self.actor, {'product_id': 'outside'},
            product_scope={'include': None, 'exclude': ['outside']})
        self.assertEqual(result['items'], [])

    async def test_semantic_order_is_same_batch_then_price_stock_and_scope_are_rechecked(self):
        shown = []
        async def rerank(payload):
            shown.extend(payload['candidates'])
            keys = [item['sku_key'] for item in reversed(payload['candidates'])]
            self.commerce.stocks[keys[0].split(':')[0]] = 0
            self.commerce.prices[keys[1].split(':')[0]] = Decimal('999.00')
            return {'sku_keys': keys}
        result = await RecommendationService(self.commerce, FakeStrategies()).recommend(self.actor,
            {'query': '轻便键盘', 'max_price_cents': 20000, 'limit': 4}, seed_product_id='seed',
            semantic_rerank=rerank, product_scope=self.scope)
        self.assertEqual(result['ranking_mode'], 'content_llm')
        self.assertEqual(len(shown), 4)
        self.assertEqual(len(result['items']), 2)
        self.assertTrue({item['sku_key'] for item in result['items']} <= {item['sku_key'] for item in shown})
        self.assertTrue(all(item['stock'] > 0 and item['price_cents'] <= 20000 for item in result['items']))
        self.assertEqual(result['diagnostics']['final_filtered'], {'stock_unavailable': 1, 'price_constraint': 1})
        self.assertEqual(sum(path.endswith('/searchOnSale') for _, path, _ in self.commerce.calls), 3)

    async def test_invalid_or_failed_semantic_output_falls_back_without_recalls_or_new_skus(self):
        for response in (["outside:invented"], ProviderError('synthetic_unavailable')):
            self.commerce.calls.clear()
            async def rerank(payload):
                if isinstance(response, Exception):
                    raise response
                return response
            result = await RecommendationService(self.commerce, FakeStrategies()).recommend(self.actor,
                {'query': '轻便键盘'}, product_scope=self.scope, semantic_rerank=rerank)
            self.assertEqual(result['ranking_mode'], 'content_rule_fallback')
            self.assertEqual(result['items'][0]['productId'], 'content')
            self.assertEqual(sum(path.endswith('/snapshotBatch') for _, path, _ in self.commerce.calls), 2)
            self.assertNotIn('outside:invented', [item['sku_key'] for item in result['items']])

    async def test_unknown_or_zero_sku_stock_has_no_product_total_fallback(self):
        self.commerce.stocks = {key: 0 for key in self.commerce.stocks}
        result = await RecommendationService(self.commerce, FakeStrategies()).recommend(self.actor,
            {'query': '键盘'}, product_scope=self.scope)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics']['empty_reason'], 'no_eligible_sku')
        self.assertGreater(result['diagnostics']['initial_filtered']['stock_unavailable'], 0)
        with self.assertRaisesRegex(StateError, 'product_scope_required'):
            await RecommendationService(self.commerce, FakeStrategies()).recommend(self.actor, {'query': '键盘'})

    async def test_budget_category_terms_and_quantity_are_hard_constraints(self):
        prefs = [{'preference_key': 'budget_max_cents', 'value': 5000, 'source': 'explicit'}]
        service = RecommendationService(self.commerce, FakeStrategies())
        self.assertEqual((await service.recommend(self.actor, {'query': '键盘'}, preferences=prefs, product_scope=self.scope))['items'], [])
        result = await service.recommend(self.actor, {'query': '键盘', 'max_price_cents': 12000,
            'category_id': 'desk', 'required_terms': ['轻便', '键盘'], 'quantity': 2}, preferences=prefs, product_scope=self.scope)
        self.assertEqual([item['productId'] for item in result['items']], ['content'])
        empty = await service.recommend(self.actor, {'query': '键盘', 'excluded_terms': ['黑色']}, product_scope=self.scope)
        self.assertEqual(empty['items'], [])
        avoid = [{'preference_key': 'avoid', 'value': [f'未出现的规格{i}' for i in range(19)] + ['黑色'], 'source': 'explicit'}]
        empty = await service.recommend(self.actor, RecommendationRequest(query='键盘'), preferences=avoid, product_scope=self.scope)
        self.assertEqual(empty['items'], [])  # The twentieth saved restriction remains a hard gate.

    async def test_saved_text_categories_score_preferences_without_filtering_catalog_ids(self):
        self.commerce.products['content']['productName'] = '数码轻便键盘'
        preferences = [{'preference_key': 'categories', 'value': ['数码'], 'source': 'explicit'}]
        service = RecommendationService(self.commerce, FakeStrategies())
        result = await service.recommend(self.actor, {'query': '键盘'}, preferences=preferences, product_scope=self.scope)
        items = {item['productId']: item for item in result['items']}
        self.assertEqual(set(items), {'content', 'popular', 'new'})
        self.assertGreater(items['content']['features']['preference'], 0)
        self.assertEqual(items['popular']['features']['preference'], 0)
        self.assertTrue(all(data.get('categoryId') != '数码' for _, path, data in self.commerce.calls
                            if path.endswith('/searchOnSale')))
        explicit = await service.recommend(self.actor, {'query': '键盘', 'category_id': 'other-category'},
                                           preferences=preferences, product_scope=self.scope)
        self.assertEqual(explicit['items'], [])

    async def test_scope_filters_before_recall_limit_and_new_payment_changes_popularity(self):
        service = RecommendationService(self.commerce, FakeStrategies('rules-v1'))
        request = {'category_id': 'desk', 'excluded_product_ids': ['content']}
        quotas = dict(content=1, category=1, copurchase=1, popular=1, newest=1)
        with patch.dict(DEFAULT_STRATEGIES['rules-v1']['quotas'], quotas):
            before = await service.recommend(self.actor, request, product_scope=self.scope, seed_product_id='seed')
            self.assertEqual(before['items'][0]['productId'], 'popular')
            self.assertIn('paired', [item['productId'] for item in before['items']])
            self.commerce.paid_units.update(popular=1, new=2000)
            after = await service.recommend(self.actor, request, product_scope=self.scope, seed_product_id='seed')
            first = after['items'][0]
            self.assertEqual(first['productId'], 'new')
            self.assertEqual(first['popularity_evidence'], {'paidUnits': 2000,
                'basis': 'confirmed_payment_units_excluding_refunds', 'observedAt': '2026-09-09T00:00:00Z'})
            self.assertNotIn('totalSale', first)
            unknown = next(item for item in after['items'] if item['productId'] == 'paired')
            self.assertIsNone(unknown['popularity_evidence'])
            self.assertFalse(any('确认付款' in reason for reason in unknown['reasons']))
            for _, path, data in self.commerce.calls:
                if path.endswith(('/searchOnSale', '/popularProducts', '/coPurchaseProductIds')):
                    self.assertEqual(set(data['productIds']), set(self.scope['include']))
                    self.assertEqual(set(data['excludeProductIds']), {'outside', 'content'})
            empty = await service.recommend(self.actor, request, product_scope={'include': [], 'exclude': []})
            self.assertEqual(empty['items'], [])


class RecommendationRuleTests(unittest.TestCase):
    def test_unset_vs_explicit_empty_constraint_survives_recommendation_boundary(self):
        saved = [f'禁止规格{i}' for i in range(20)]
        preferences = [{'preference_key': 'avoid', 'value': saved, 'source': 'explicit'}]
        request = RecommendationRequest(query='键盘')
        self.assertEqual(constraints(request, preferences)['excluded_terms'], saved)
        forwarded = request.model_dump(exclude_none=True, exclude_unset=True)
        self.assertEqual(constraints(forwarded, preferences)['excluded_terms'], saved)
        override = RecommendationRequest(query='键盘', excluded_terms=[])
        self.assertEqual(constraints(override, preferences)['excluded_terms'], [])
        self.assertEqual(RecommendationRequest(excluded_terms=saved).excluded_terms, saved)

    def test_strategy_validation_does_not_allow_disabling_hard_gates(self):
        self.assertEqual(strategy_config(DEFAULT_STRATEGIES['rules-v1'])['ranking'], 'rule')
        for invalid in ({**DEFAULT_STRATEGIES['rules-v1'], 'ignore_stock': True},
                        {**DEFAULT_STRATEGIES['rules-v1'], 'weights': {'content': float('nan')}},
                        {**DEFAULT_STRATEGIES['rules-v1'], 'quotas': {route: 20 for route in ('content', 'category', 'copurchase', 'popular', 'newest')}}):
            with self.assertRaises(StateError):
                strategy_config(invalid)
        with self.assertRaises(ValidationError):
            RecommendationRequest.model_validate({'query': '键盘', 'subject_key': 'other'})
        with self.assertRaises(ValidationError):
            RecommendationRequest.model_validate({'max_price_cents': True})

    def test_fixed_hash_and_duplicate_or_invented_rerank_ids(self):
        self.assertEqual(bucket_for('scope', 'experiment', 'user:one', 'salt'), bucket_for('scope', 'experiment', 'user:one', 'salt'))
        self.assertGreater(len({bucket_for('scope', 'experiment', str(i), 'salt') for i in range(100)}), 30)
        cards = [{'sku_key': 'a'}, {'sku_key': 'b'}]
        self.assertEqual(validate_rerank({'sku_keys': ['b', 'a']}, cards), ['b', 'a'])
        for keys in (['a', 'a'], ['a', 'outside'], ['a']):
            with self.assertRaises(ValueError):
                validate_rerank(keys, cards)
        merged = merge_candidates({'content': [{'productId': 'a'}, {'productId': 'a'}],
            'copurchase': ['b', 'a', 'outside']}, product_scope=scope_filter({'include': ['a', 'b'], 'exclude': ['outside']}))
        self.assertEqual(set(merged), {'a', 'b'})
        self.assertEqual(set(merged['a']), {'content', 'copurchase'})


if __name__ == '__main__':
    unittest.main()
