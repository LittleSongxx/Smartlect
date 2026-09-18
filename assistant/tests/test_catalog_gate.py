"""Catalog gate is a move, not a new eligibility policy."""
from decimal import Decimal
import unittest

from smartlect import catalog_gate
from smartlect.catalog_gate import (
    RecommendationRequest, constraints, eligible_skus, in_scope, is_isolated_product_id, scope_filter)
from smartlect.recommendation import service


class CatalogGateTests(unittest.TestCase):
    def test_homepage_reexports_the_same_gate(self):
        self.assertIs(service.RecommendationRequest, catalog_gate.RecommendationRequest)
        self.assertIs(service.constraints, catalog_gate.constraints)
        self.assertIs(service.eligible_skus, catalog_gate.eligible_skus)
        self.assertIs(service.scope_filter, catalog_gate.scope_filter)
        self.assertIs(service.in_scope, catalog_gate.in_scope)

    def test_eligible_skus_still_rejects_term_and_stock_without_product_totals(self):
        snapshot = {
            'products': [dict(productId='p', productName='红键盘', categoryId='desk', status=1)],
            'skus': [dict(productId='p', propertyValueIdHash='h', propertyValueIds='v', price=Decimal('10.00'))],
            'propertyValues': [dict(productId='p', propertyValueId='v', propertyValue='红')],
            'totalStocks': {'p': 999},
        }
        stocks = [dict(productId='p', propertyValueIdHash='h', stock=3)]
        scope = scope_filter({'include': ['p'], 'exclude': []})
        request = RecommendationRequest(query='键盘').model_dump()
        cards, removed = eligible_skus(snapshot, stocks, request, product_scope=scope)
        self.assertEqual([card['sku_key'] for card in cards], ['p:h'])
        blocked = RecommendationRequest(query='键盘', excluded_terms=['红']).model_dump()
        empty, filtered = eligible_skus(snapshot, stocks, blocked, product_scope=scope)
        self.assertEqual(empty, [])
        self.assertEqual(filtered['term_constraint'], 1)
        stocks[0]['stock'] = 0
        sold, stock_filtered = eligible_skus(snapshot, stocks, request, product_scope=scope)
        self.assertEqual(sold, [])
        self.assertEqual(stock_filtered['stock_unavailable'], 1)

    def test_open_store_scope_rejects_isolated_prefixes(self):
        scope = scope_filter({'include': None, 'exclude': []})
        self.assertTrue(is_isolated_product_id('910000000000001'))
        self.assertTrue(is_isolated_product_id('930000000081301'))
        self.assertFalse(is_isolated_product_id('917186661226040'))
        self.assertFalse(in_scope('910000000000001', scope))
        self.assertFalse(in_scope('930000000081301', scope))
        self.assertTrue(in_scope('917186661226040', scope))
        scoped = scope_filter({'include': ['930000000081301'], 'exclude': []})
        self.assertTrue(in_scope('930000000081301', scoped))
        self.assertFalse(in_scope('unprefixed-eval', scope, 'eval'))
        self.assertTrue(in_scope('910000000000001', scope, 'store'))

    def test_explicit_saved_avoid_still_becomes_homepage_hard_gate(self):
        request = RecommendationRequest(query='键盘')
        preferences = [{'preference_key': 'avoid', 'value': ['红'], 'source': 'explicit'}]
        self.assertEqual(constraints(request, preferences)['excluded_terms'], ['红'])


if __name__ == '__main__':
    unittest.main()
