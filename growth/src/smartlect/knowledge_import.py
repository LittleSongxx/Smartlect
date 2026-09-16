"""Product knowledge auto-import: Java product facts become DRAFT knowledge documents.

Java stays the authority: every import pulls live product detail through the internal
batchDetail endpoint (sanitized on the Java side) and only ever writes DRAFT documents —
a human still reviews and publishes through the normal checksum/ACL lifecycle. Re-import
is overlay-style: the previous auto DRAFT for the same product is discarded first, MANUAL
documents are never touched, and published versions are never silently withdrawn (the
summary flags them instead).

Import does not pre-embed: vectors are produced by the async index pipeline when the
draft is published, so rejected drafts never spend embedding budget.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone

from smartlect.commerce import CommerceError

def _reason(error):
    return getattr(error, "code", None) or str(error)[:120] or type(error).__name__


BATCH = 50
IMPORT_CAP = 200  # per call; a full catalog is imported in successive calls
DOC_PREFIX = "product-"


def product_doc_id(product_id):
    return DOC_PREFIX + re.sub(r"[^0-9A-Za-z_-]", "", str(product_id))[:100]


def build_document(detail):
    """Assemble one knowledge body from a sanitized product detail map; None if nothing citable."""
    if not isinstance(detail, dict) or not detail.get("productId"):
        return None
    name = str(detail.get("productName") or detail["productId"]).strip()
    sections = []

    description = str(detail.get("description") or detail.get("productDesc") or "").strip()
    if description:
        sections.append("## 商品描述\n" + description)

    lines = []
    brand = detail.get("brand")
    if brand:
        lines.append(f"- 品牌：{brand}")
    for property_ in detail.get("propertyValues") or []:
        key = str(property_.get("propertyName") or "").strip()
        value = str(property_.get("propertyValue") or "").strip()
        if key and value:
            lines.append(f"- {key}：{value}")
    if lines:
        sections.append("## 规格参数\n" + "\n".join(lines))

    facts = []
    min_price, max_price = detail.get("minPrice"), detail.get("maxPrice")
    if min_price is not None and max_price is not None:
        facts.append(f"价格区间 {min_price} 至 {max_price} 元")
    if detail.get("totalStock") is not None:
        facts.append("当前有货，总库存 " + str(detail["totalStock"]) if detail.get("inStock")
                     else "当前总库存 " + str(detail["totalStock"]))
    if facts:
        sections.append("## 价格与库存\n" + "；".join(facts) + "。以商品页实时数据为准。")

    if not sections:
        return None
    now = datetime.now(timezone.utc)
    return {
        "valid_from": now.isoformat(),
        "valid_until": (now + timedelta(days=730)).isoformat(),  # refreshed by re-import
        "doc_id": product_doc_id(detail["productId"]),
        "title": f"商品知识：{name}",
        "source_uri": f"product:{detail['productId']}",
        "source_type": "PRODUCT_AUTO",
        "body": f"# {name}\n\n" + "\n\n".join(sections),
        "language": "zh-CN",
        "acl": "PUBLIC",
        "product_ids": [str(detail["productId"])],
    }


async def import_products(actor, commerce, knowledge, *, product_ids=None):
    """Import the given (or all on-sale) products as DRAFT knowledge. Returns a summary."""
    if product_ids is None:
        ids = await commerce.request("product", "/internal/product/listOnSaleProductIds", actor=actor)
        if not isinstance(ids, list):
            raise CommerceError("commerce_outcome_unknown")
        product_ids = [str(item) for item in ids if item]
    product_ids = list(dict.fromkeys(str(item) for item in product_ids))[:IMPORT_CAP]

    imported, skipped, failed, published_pending = [], [], [], []
    for start in range(0, len(product_ids), BATCH):
        batch_ids = product_ids[start:start + BATCH]
        try:
            details = await commerce.request("product", "/internal/product/commerce/batchDetail",
                                             actor=actor, data={"productIds": batch_ids})
        except Exception as error:  # one unreachable batch must not void the whole import
            failed.extend({"product_id": item, "error": _reason(error)}
                          for item in batch_ids)
            continue
        if not isinstance(details, list):
            failed.extend({"product_id": item, "error": "commerce_outcome_unknown"} for item in batch_ids)
            continue
        by_id = {str(item.get("productId")): item for item in details if isinstance(item, dict)}
        for product_id in batch_ids:
            document = build_document(by_id.get(product_id))
            if document is None:
                skipped.append(product_id)
                continue
            try:
                existing = await asyncio.to_thread(
                    knowledge.document_versions, actor, document["doc_id"])
                if any(version["status"] == "PUBLISHED" for version in existing):
                    published_pending.append(product_id)
                await asyncio.to_thread(knowledge.discard_auto_drafts, actor, [document["doc_id"]])
                await asyncio.to_thread(knowledge.create_draft, actor, document)
                imported.append(product_id)
            except Exception as error:
                failed.append({"product_id": product_id, "error": _reason(error)})
    return {"imported": imported, "skipped": skipped, "failed": failed,
            "published_pending_review": published_pending,
            "requested": len(product_ids), "truncated": len(product_ids) == IMPORT_CAP,
            "note": "已生成/覆盖自动草稿；请到知识库页核对正文后发布，向量索引将在发布时自动执行。"}
