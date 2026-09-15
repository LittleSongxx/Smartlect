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
        self.specs = {key: '黑色' for key in self.products}

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
                'propertyValues': [dict(productId=key, propertyValueId='v' + key, propertyName='颜色',
                                        propertyValue=self.specs.get(key, '黑色')) for key in keys]}
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

    async def test_soft_query_miss_returns_honest_empty_set(self):
        # shop-d-65 lesson: a keyword that matches nothing on sale must not be
        # relaxed into whole-scope enumeration — the user asked for that product,
        # and unrelated bestsellers are not an answer. Relaxation stays for
        # keyword-less browse (budget-only requests) below.
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': '灰色飞船'}, mission=empty_mission(), product_scope=self.scope)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics']['empty_reason'], 'no_eligible_sku')
        self.assertFalse(result['diagnostics']['browse_newest'])
        self.assertFalse(result['diagnostics']['recall_relaxed'])
        self.assertFalse(result['diagnostics']['popular_used'])
        # A hard-slot variant of the same miss (excluded terms present) stays an
        # honest hard-constraint empty set instead of filtered bestsellers.
        hard = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': 'USB 线', 'excluded_terms': ['黑色']}, mission=empty_mission(),
            product_scope=self.scope)
        self.assertEqual(hard['items'], [])
        self.assertEqual(hard['diagnostics']['empty_reason'], 'hard_constraint_unsatisfied')
        self.assertFalse(hard['diagnostics']['recall_relaxed'])
        self.assertFalse(any('popularProducts' in path or 'coPurchase' in path for _, path, _ in self.commerce.calls))

    async def test_keyword_miss_with_required_terms_keeps_rescue_path(self):
        # Paraphrased requests carry required_terms; the keyword-miss honest-empty
        # branch must not cut off the post-gate rescue that resolves them.
        self.commerce.products['pro'] = dict(productId='pro', productName='金属机械键盘',
                                             categoryId='desk', status=1)
        self.commerce.prices['pro'] = Decimal('399.00')
        self.commerce.stocks['pro'] = 8
        self.scope['include'].append('pro')
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': '金属机械', 'required_terms': ['金属', '键盘']}, mission=empty_mission(),
            product_scope=self.scope)
        self.assertEqual([item['productId'] for item in result['items']], ['pro'])
        self.assertIsNone(result['diagnostics']['empty_reason'])

    async def test_hard_slot_keyword_miss_is_honest_empty_not_filtered_bestsellers(self):
        # The pre-narrowing behavior relaxed a keyword miss into whole-scope
        # enumeration and let the eligibility gate pick survivors — on the toy
        # catalog that happened to look right, on the real one it returned mice
        # for "USB 线" (v15 shop-d-65). A keyword miss now closes honestly even
        # with hard slots present.
        self.commerce.specs['new'] = '粉色'
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': '鼠标', 'excluded_terms': ['黑色']}, mission=empty_mission(),
            product_scope=self.scope)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics']['empty_reason'], 'hard_constraint_unsatisfied')
        self.assertFalse(result['diagnostics']['recall_relaxed'])
        self.assertFalse(result['diagnostics']['popular_used'])
        self.assertFalse(any((data or {}).get('keyword') == '' for _, path, data in self.commerce.calls
                            if path.endswith('/searchOnSale')))

    async def test_relaxed_recall_stays_empty_when_gate_removes_everything(self):
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'query': '鼠标', 'excluded_terms': ['黑色']}, mission=empty_mission(),
            product_scope=self.scope)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics']['empty_reason'], 'hard_constraint_unsatisfied')
        self.assertFalse(result['diagnostics']['popular_used'])
        self.assertFalse(any('popularProducts' in path or 'coPurchase' in path for _, path, _ in self.commerce.calls))

    async def test_budget_only_hard_request_recalls_and_filters_by_price(self):
        # "100元以内有什么": budget is hard, but recall must not be blocked by it.
        self.commerce.prices['popular'] = Decimal('500.00')
        result = await ShoppingRetrieve(self.commerce).recommend(
            self.actor, {'max_price_cents': 20000}, mission=empty_mission(), product_scope=self.scope)
        self.assertEqual(sorted(item['productId'] for item in result['items']), ['content', 'new'])
        self.assertTrue(result['diagnostics']['recall_relaxed'])
        self.assertIsNone(result['diagnostics']['empty_reason'])
        self.assertFalse(result['diagnostics']['popular_used'])


if __name__ == '__main__':
    unittest.main()
