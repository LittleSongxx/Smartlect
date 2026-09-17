"""Storefront slugs and ads 200xx stay separate; only the explicit map joins them."""
import unittest

from smartlect.ads.inference import CATEGORY_WORDS
from smartlect.catalog_taxonomy import (ADS_INFERENCE_CATEGORIES, ADS_TO_STORE, STORE_CATEGORIES,
                                        STORE_TO_ADS, ads_ids_for_store_category, compatible_category,
                                        store_category_for_ads_id)


class CatalogTaxonomyTests(unittest.TestCase):
    def test_live_systems_are_not_collapsed(self):
        self.assertEqual(STORE_CATEGORIES, frozenset({'desk', 'audio', 'acc', 'furn'}))
        self.assertTrue(ADS_INFERENCE_CATEGORIES.isdisjoint(STORE_CATEGORIES))
        self.assertEqual(set(CATEGORY_WORDS), ADS_INFERENCE_CATEGORIES)

    def test_explicit_map_is_bidirectional_for_declared_pairs(self):
        self.assertEqual(store_category_for_ads_id('20003'), 'audio')
        self.assertEqual(ads_ids_for_store_category('audio'), ('20003',))
        self.assertTrue(compatible_category('acc', '20001'))
        self.assertFalse(compatible_category('desk', '20003'))
        self.assertIsNone(store_category_for_ads_id('desk'))
        self.assertEqual(ads_ids_for_store_category('desk'), ())

    def test_map_only_contains_declared_ads_ids(self):
        self.assertTrue(set(ADS_TO_STORE).issubset(ADS_INFERENCE_CATEGORIES))
        self.assertTrue(set(STORE_TO_ADS).issubset(STORE_CATEGORIES))


if __name__ == '__main__':
    unittest.main()
