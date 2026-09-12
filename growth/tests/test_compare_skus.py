"""compare_skus: two to four cards, missing targets stay incomplete."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from smartlect.state import StateError
from smartlect.shopping_mission import empty_mission
from smartlect.shopping_retrieve import ShoppingRetrieve
from smartlect.tools import CompareArgs, REGISTRY


class FakeCommerce:
    def __init__(self):
        self.calls = []
        self.products = {
            'content': dict(productId='content', productName='轻便键盘', categoryId='desk', status=1),
            'popular': dict(productId='popular', productName='基础键盘', categoryId='desk', status=1),
            'new': dict(productId='new', productName='轻便鼠标', categoryId='desk', status=1),
        }
        self.prices = {'content': Decimal('80.00'), 'popular': Decimal('100.00'), 'new': Decimal('60.00')}
        self.stocks = {key: 10 for key in self.products}

    async def request(self, service, path, *, data=None, **kwargs):
        self.calls.append((service, path, deepcopy(data)))
        if path.endswith('/searchOnSale'):
            keyword = data.get('keyword') or ''
            if '鼠标' in keyword:
                keys = ['new']
            elif '键盘' in keyword:
                keys = ['content', 'popular']
            else:
                keys = []
            return [deepcopy(self.products[key]) for key in keys[:data['limit']]]
        if path.endswith('/popularProducts') or path.endswith('/coPurchaseProductIds'):
            raise AssertionError('compare must not call ' + path)
        if path.endswith('/snapshotBatch'):
            keys = data['productIds']
            return {'products': [deepcopy(self.products[key]) for key in keys if key in self.products],
                'skus': [dict(productId=key, propertyValueIdHash='hash-' + key, propertyValueIds='v' + key,
                              price=self.prices[key], sort=0) for key in keys if key in self.products],
                'propertyValues': [dict(productId=key, propertyValueId='v' + key, propertyName='颜色', propertyValue='黑色')
                                   for key in keys if key in self.products]}
        if path.endswith('/getBatch'):
            return [dict(productId=row['productId'], propertyValueIdHash=row['propertyValueIdHash'],
                         stock=self.stocks.get(row['productId'], 0)) for row in data]
        raise AssertionError('Unexpected Java endpoint ' + path)


class CompareSkuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(subject_type='user', actor_id='alice', execution_scope_id='isolated',
                                     permissions=('shopping:read',))
        self.scope = {'include': ['content', 'popular', 'new'], 'exclude': []}
        self.commerce = FakeCommerce()

    def test_registry_and_arity(self):
        self.assertEqual(REGISTRY['compare_skus'].permission, 'shopping:read')
        CompareArgs.model_validate({'sku_keys': ['a:b', 'c:d']})
        with self.assertRaises(ValidationError):
            CompareArgs.model_validate({'sku_keys': ['a:b'] * 5})

    async def test_two_to_four_keys_and_missing_target_is_incomplete(self):
        retriever = ShoppingRetrieve(self.commerce)
        complete = await retriever.compare(self.actor, {
            'sku_keys': ['content:hash-content', 'popular:hash-popular']}, mission=empty_mission(),
            product_scope=self.scope)
        self.assertEqual(len(complete['items']), 2)
        self.assertTrue(complete['comparison_complete'])
        self.assertEqual(complete['missing_targets'], [])
        self.assertTrue(any(row['field'] == 'price_cents' and row['differ'] for row in complete['comparison']['rows']))
        incomplete = await retriever.compare(self.actor, {
            'comparison_targets': ['键盘', '火星飞船']}, mission=empty_mission(), product_scope=self.scope)
        self.assertFalse(incomplete['comparison_complete'])
        self.assertIn('火星飞船', incomplete['missing_targets'])
        self.assertGreaterEqual(len(incomplete['items']), 1)
        self.assertFalse(any('popularProducts' in path for _, path, _ in self.commerce.calls))

    async def test_single_sku_key_is_rejected(self):
        with self.assertRaisesRegex(StateError, 'invalid_compare_sku_keys'):
            await ShoppingRetrieve(self.commerce).compare(
                self.actor, {'sku_keys': ['content:hash-content']}, mission=empty_mission(),
                product_scope=self.scope)


if __name__ == '__main__':
    unittest.main()
