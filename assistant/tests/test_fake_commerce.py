"""Deterministic fake Java catalog used by agent/shopping contract tests (no DB, no model)."""
from copy import deepcopy
from decimal import Decimal

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


