"""Shopping retrieve: catalog search only, hard-constraint empty set, no popular fill."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
import unittest

from smartlect.shopping_mission import empty_mission
from smartlect.shopping_retrieve import ALGORITHM_VERSION, STRATEGY_VERSION, ShoppingRetrieve


class FakeCommerce:
    def __init__(self):
        self.calls = []
        self.products = {
            'content': dict(productId='content', productName='轻便键盘', categoryId='desk', status=1),
            'popular': dict(productId='popular', productName='基础键盘', categoryId='desk', status=1),
            'new': dict(productId='new', productName='轻便鼠标', categoryId='desk', status=1),
        }
        self.prices = {key: Decimal('100.00') for key in self.products}
        self.stocks = {key: 10 for key in self.products}

    async def request(self, service, path, *, data=None, **kwargs):
        self.calls.append((service, path, deepcopy(data)))
        if path.endswith('/searchOnSale'):
            if data.get('keyword'):
                keys = ['content'] if '键盘' in data['keyword'] or '轻便' in data['keyword'] else []
            else:
                keys = list(self.products)
            return [deepcopy(self.products[key]) for key in keys[:data['limit']]]
        if path.endswith('/popularProducts') or path.endswith('/coPurchaseProductIds'):
            raise AssertionError('shopping retrieve must not call ' + path)
        if path.endswith('/snapshotBatch'):
            keys = data['productIds']
            return {'products': [deepcopy(self.products[key]) for key in keys],
                'skus': [dict(productId=key, propertyValueIdHash='hash-' + key, propertyValueIds='v' + key,
                              price=self.prices[key], sort=0) for key in keys],
                'propertyValues': [dict(productId=key, propertyValueId='v' + key, propertyName='颜色', propertyValue='黑色') for key in keys]}
        if path.endswith('/getBatch'):
            return [dict(productId=row['productId'], propertyValueIdHash=row['propertyValueIdHash'],
                         stock=self.stocks[row['productId']]) for row in data]
        raise AssertionError('Unexpected Java endpoint ' + path)


class ShoppingRetrieveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(subject_type='user', actor_id='alice', execution_scope_id='isolated',
                                     permissions=('shopping:read',))
        self.scope = {'include': ['content', 'popular', 'new'], 'exclude': []}
        self.commerce = FakeCommerce()

    async def test_hard_constraint_empty_set_does_not_call_popular(self):
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': '键盘', 'max_price_cents': 1}, mission=empty_mission(), product_scope=self.scope)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics']['empty_reason'], 'hard_constraint_unsatisfied')
        self.assertFalse(result['diagnostics']['popular_used'])
        self.assertEqual(result['strategy_version'], STRATEGY_VERSION)
        self.assertEqual(result['algorithm_version'], ALGORITHM_VERSION)
        self.assertTrue(any(path.endswith('/searchOnSale') for _, path, _ in self.commerce.calls))
        self.assertFalse(any('popularProducts' in path or 'coPurchase' in path for _, path, _ in self.commerce.calls))

    async def test_saved_avoid_preference_is_soft_and_browse_may_use_newest(self):
        preferences = [{'preference_key': 'avoid', 'value': ['黑色'], 'source': 'explicit'}]
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': '键盘'}, mission=empty_mission(), preferences=preferences, product_scope=self.scope)
        self.assertEqual([item['productId'] for item in result['items']], ['content'])
        browse = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': ''}, mission=empty_mission(), product_scope=self.scope)
        self.assertTrue(browse['diagnostics']['browse_newest'])
        self.assertGreaterEqual(len(browse['items']), 1)
        self.assertFalse(any('popularProducts' in path for _, path, _ in self.commerce.calls))

    async def test_keyword_miss_scans_on_sale_then_applies_required_terms(self):
        self.commerce.products['pro'] = dict(productId='pro', productName='金属机械键盘',
                                             categoryId='desk', status=1)
        self.commerce.prices['pro'] = Decimal('399.00')
        self.commerce.stocks['pro'] = 8
        self.scope['include'].append('pro')
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'required_terms': ['金属', '键盘']}, mission=empty_mission(),
            product_scope=self.scope)
        self.assertEqual([item['productId'] for item in result['items']], ['pro'])
        self.assertIsNone(result['diagnostics']['empty_reason'])
        self.assertFalse(result['diagnostics']['popular_used'])
        self.assertTrue(any((data or {}).get('keyword') == '' for _, path, data in self.commerce.calls
                            if path.endswith('/searchOnSale')))

    async def test_soft_query_miss_browses_on_sale(self):
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': '灰色飞船'}, mission=empty_mission(), product_scope=self.scope)
        self.assertGreaterEqual(len(result['items']), 1)
        self.assertTrue(result['diagnostics']['browse_newest'])
        self.assertIsNone(result['diagnostics']['empty_reason'])

    async def test_exclude_only_does_not_browse_fill(self):
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': '鼠标', 'excluded_terms': ['黑色']}, mission=empty_mission(),
            product_scope=self.scope)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics']['empty_reason'], 'hard_constraint_unsatisfied')
        self.assertFalse(any((data or {}).get('keyword') == '' for _, path, data in self.commerce.calls
                            if path.endswith('/searchOnSale')))


if __name__ == '__main__':
    unittest.main()
