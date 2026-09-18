"""Retrieval-plane compilation: empty product_ids are store policy only."""
import unittest

from smartlect.knowledge_scope import (PRODUCT, PRODUCT_AND_STORE, STORE, citation_covers_product,
                                       compile_search_filter, search_document_clause)
from smartlect.session_focus import compile_focus


class SessionFocusTests(unittest.TestCase):
    def test_product_mode_requires_id_and_sets_corpus(self):
        focus = compile_focus(product_id="p1", sku_key="p1:h", focus_mode="PRODUCT")
        self.assertEqual(focus["focus_mode"], "PRODUCT")
        self.assertEqual(focus["focus_product_id"], "p1")
        self.assertEqual(focus["knowledge_corpus"], "PRODUCT_AND_STORE")
        self.assertEqual(compile_search_filter(focus)["corpus"], PRODUCT_AND_STORE)
        self.assertEqual(compile_search_filter(focus)["product_id"], "p1")

    def test_product_mode_ignores_model_product_id(self):
        focus = compile_focus(product_id="p1", focus_mode="PRODUCT")
        compiled = compile_search_filter(focus, requested_product_id="forged")
        self.assertEqual(compiled["product_id"], "p1")

    def test_global_honors_model_product_id(self):
        focus = compile_focus(focus_mode="GLOBAL", product_id="p9")
        self.assertEqual(focus["focus_mode"], "GLOBAL")
        self.assertIsNone(focus["focus_product_id"])
        compiled = compile_search_filter(focus, requested_product_id="forged")
        self.assertEqual(compiled["corpus"], PRODUCT_AND_STORE)
        self.assertEqual(compiled["product_id"], "forged")

    def test_product_without_id_falls_back_to_global(self):
        self.assertEqual(compile_focus(focus_mode="PRODUCT")["focus_mode"], "GLOBAL")


class KnowledgeScopeClauseTests(unittest.TestCase):
    def test_store_requires_empty_product_ids(self):
        clause, values = search_document_clause(corpus=STORE)
        self.assertIn("JSON_LENGTH(d.product_ids_json)=0", clause)
        self.assertNotIn("JSON_CONTAINS", clause)
        self.assertEqual(values, [])

    def test_product_requires_pinned_id(self):
        clause, values = search_document_clause(product_id="p1", corpus=PRODUCT)
        self.assertIn("JSON_LENGTH(d.product_ids_json)>0", clause)
        self.assertIn("JSON_CONTAINS", clause)
        self.assertEqual(len(values), 1)

    def test_product_and_store_is_explicit_union(self):
        clause, values = search_document_clause(product_id="p1", corpus=PRODUCT_AND_STORE)
        self.assertIn("JSON_LENGTH(d.product_ids_json)=0", clause)
        self.assertIn("JSON_CONTAINS", clause)
        self.assertEqual(len(values), 1)

    def test_default_without_product_is_store_only(self):
        clause, _ = search_document_clause()
        self.assertIn("JSON_LENGTH(d.product_ids_json)=0", clause)
        self.assertNotIn("OR JSON_CONTAINS", clause)

    def test_citation_covers_only_matching_product(self):
        self.assertTrue(citation_covers_product({"product_ids": ["p1"]}, "p1"))
        self.assertFalse(citation_covers_product({"product_ids": []}, "p1"))
        self.assertFalse(citation_covers_product({"product_ids": ["p2"]}, "p1"))


if __name__ == "__main__":
    unittest.main()
