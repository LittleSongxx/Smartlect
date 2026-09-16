"""Product knowledge import contracts: body assembly, overlay semantics, failure isolation."""
import asyncio
import unittest
from unittest.mock import Mock

import httpx

from smartlect.auth import ActorContext
from smartlect.commerce import AsyncCommerceClient, CommerceError
from smartlect.knowledge_import import build_document, import_products

ACTOR = ActorContext(subject_type="merchant", actor_id="boss", session_id="s",
                     permissions=("admin:legacy",), execution_scope_id="scope")


def detail(product_id="p1", **extra):
    return {"productId": product_id, "productName": "保温杯 500ml", "status": 1,
            "minPrice": "39.00", "maxPrice": "59.00", "totalStock": 12, "inStock": True,
            "description": "316 不锈钢内胆，保温 12 小时。",
            "propertyValues": [{"propertyName": "品牌", "propertyValue": "Smartlect"},
                               {"propertyName": "容量", "propertyValue": "500ml"}],
            **extra}


class BuildDocumentTests(unittest.TestCase):
    def test_assembles_sections_and_stable_doc_id(self):
        document = build_document(detail())
        self.assertEqual(document["doc_id"], "product-p1")
        self.assertEqual(document["source_type"], "PRODUCT_AUTO")
        self.assertEqual(document["acl"], "PUBLIC")
        self.assertEqual(document["product_ids"], ["p1"])
        for fragment in ("# 保温杯 500ml", "## 商品描述", "## 规格参数", "- 品牌：Smartlect",
                         "- 容量：500ml", "## 价格与库存", "以商品页实时数据为准"):
            self.assertIn(fragment, document["body"])

    def test_skips_products_with_nothing_citable(self):
        self.assertIsNone(build_document({"productId": "p2", "productName": "空商品"}))
        self.assertIsNone(build_document(None))


class ImportProductsTests(unittest.TestCase):
    def test_import_writes_drafts_with_overlay_and_isolates_batch_failures(self):
        calls = []

        def java(request):
            calls.append(request.url.path)
            if request.url.path == "/internal/product/commerce/batchDetail":
                import json
                ids = json.loads(request.content)["productIds"]
                return httpx.Response(200, json={"status": "success", "data": [
                    detail(item) for item in ids if item != "p-empty"]})
            if request.url.path == "/internal/product/listOnSaleProductIds":
                return httpx.Response(200, json={"status": "success", "data": ["p1", "p-empty"]})
            raise AssertionError(request.url.path)

        commerce = AsyncCommerceClient({"SMARTLECT_PRODUCT_PORT": "18102", "SMARTLECT_INTERNAL_TOKEN": "t"},
                                       transport=httpx.MockTransport(java))
        knowledge = Mock()
        knowledge.document_versions.return_value = []
        summary = asyncio.run(import_products(ACTOR, commerce, knowledge))

        self.assertEqual(summary["imported"], ["p1"])
        self.assertEqual(summary["skipped"], ["p-empty"])
        self.assertEqual(summary["failed"], [])
        self.assertEqual(knowledge.discard_auto_drafts.call_count, 1)
        draft_payload = knowledge.create_draft.call_args[0][1]
        self.assertEqual(draft_payload["doc_id"], "product-p1")
        self.assertEqual(draft_payload["source_type"], "PRODUCT_AUTO")

    def test_published_versions_flagged_and_batch_failure_does_not_void_import(self):
        def java(request):
            if request.url.path == "/internal/product/commerce/batchDetail":
                return httpx.Response(500, text="boom")
            raise AssertionError(request.url.path)

        commerce = AsyncCommerceClient({"SMARTLECT_PRODUCT_PORT": "18102", "SMARTLECT_INTERNAL_TOKEN": "t"},
                                       transport=httpx.MockTransport(java))
        knowledge = Mock()
        knowledge.document_versions.return_value = [{"status": "PUBLISHED"}]
        summary = asyncio.run(import_products(ACTOR, commerce, knowledge, product_ids=["p9"]))
        self.assertEqual(summary["imported"], [])
        self.assertEqual(summary["published_pending_review"], [])  # the flag only lands when a draft gets created
        self.assertEqual(summary["failed"], [{"product_id": "p9", "error": "commerce_outcome_unknown"}])
        knowledge.create_draft.assert_not_called()

    def test_flag_is_reported_when_published_version_exists_and_draft_reimports(self):
        def java(request):
            if request.url.path == "/internal/product/commerce/batchDetail":
                return httpx.Response(200, json={"status": "success", "data": [detail("p1")]})
            raise AssertionError(request.url.path)

        commerce = AsyncCommerceClient({"SMARTLECT_PRODUCT_PORT": "18102", "SMARTLECT_INTERNAL_TOKEN": "t"},
                                       transport=httpx.MockTransport(java))
        knowledge = Mock()
        knowledge.document_versions.return_value = [{"status": "PUBLISHED"}, {"status": "DRAFT"}]
        summary = asyncio.run(import_products(ACTOR, commerce, knowledge, product_ids=["p1"]))
        self.assertEqual(summary["imported"], ["p1"])
        self.assertEqual(summary["published_pending_review"], ["p1"])


if __name__ == "__main__":
    unittest.main()
