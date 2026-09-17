"""Product knowledge body assembly: columns in, price/stock out."""
import unittest

from smartlect.knowledge_import import build_document, product_doc_id


def detail(product_id="p1", **extra):
    return {"productId": product_id, "productName": "保温杯 500ml", "status": 1,
            "minPrice": "39.00", "maxPrice": "59.00", "totalStock": 12, "inStock": True,
            "description": "316 不锈钢内胆，保温 12 小时。",
            "brand": "Smartlect",
            "propertyValues": [{"propertyName": "品牌", "propertyValue": "Smartlect"},
                               {"propertyName": "容量", "propertyValue": "500ml"}],
            **extra}


class BuildDocumentTests(unittest.TestCase):
    def test_assembles_sections_and_stable_doc_id(self):
        document = build_document(detail())
        self.assertEqual(document["doc_id"], "product-p1")
        self.assertEqual(product_doc_id("p1"), "product-p1")
        self.assertEqual(document["source_type"], "PRODUCT_AUTO")
        self.assertEqual(document["acl"], "PUBLIC")
        self.assertEqual(document["product_ids"], ["p1"])
        self.assertEqual(document["checksum"], document["checksum"])
        for fragment in ("# 保温杯 500ml", "## 商品描述", "## 规格参数", "- 品牌：Smartlect",
                         "- 容量：500ml"):
            self.assertIn(fragment, document["body"])
        self.assertNotIn("价格与库存", document["body"])
        self.assertNotIn("39.00", document["body"])
        self.assertNotIn("总库存", document["body"])

    def test_columns_and_extra_markdown(self):
        document = build_document(detail(content={
            "ingredients": "不锈钢、硅胶圈",
            "usage": "开水预热后注入",
            "extra_markdown": "",
        }, description="旧版整篇"))
        self.assertIn("## 成分", document["body"])
        self.assertIn("不锈钢、硅胶圈", document["body"])
        self.assertIn("## 用法", document["body"])
        self.assertIn("旧版整篇", document["body"])

    def test_skips_products_with_nothing_citable(self):
        self.assertIsNone(build_document({"productId": "p2", "productName": "空商品"}))
        self.assertIsNone(build_document(None))


if __name__ == "__main__":
    unittest.main()
