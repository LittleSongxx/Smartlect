"""Product knowledge assembly. Projection publishes; this module only builds bodies.

Java stays the authority. Price and stock never enter the projected document — those
facts stay on get_product_offer / recommend_skus. MANUAL store policy is never written here.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re

CONTENT_SECTIONS = (
    ("selling_points", "卖点"),
    ("usage", "用法"),
    ("ingredients", "成分"),
    ("packaging", "包装"),
    ("contraindications", "禁忌"),
    ("after_sale_note", "售后备注"),
)
DOC_PREFIX = "product-"


def product_doc_id(product_id):
    return DOC_PREFIX + re.sub(r"[^0-9A-Za-z_-]", "", str(product_id))[:100]


def _text_block(value):
    if value is None:
        return ""
    return str(value).strip()


def content_map(detail):
    raw = detail.get("content") if isinstance(detail.get("content"), dict) else {}
    extra = _text_block(raw.get("extra_markdown") or detail.get("description") or detail.get("productDesc"))
    return {key: _text_block(raw.get(key)) for key, _ in CONTENT_SECTIONS} | {"extra_markdown": extra}


def build_document(detail):
    """Assemble one PRODUCT_AUTO body; None if nothing citable. No price or stock."""
    if not isinstance(detail, dict) or not detail.get("productId"):
        return None
    name = str(detail.get("productName") or detail["productId"]).strip()
    sections = []
    content = content_map(detail)

    brand = _text_block(detail.get("brand"))
    lines = []
    if brand:
        lines.append(f"- 品牌：{brand}")
    for property_ in detail.get("propertyValues") or []:
        if not isinstance(property_, dict):
            continue
        key = _text_block(property_.get("propertyName"))
        value = _text_block(property_.get("propertyValue"))
        if key and value:
            lines.append(f"- {key}：{value}")
    if lines:
        sections.append("## 规格参数\n" + "\n".join(lines))

    for key, heading in CONTENT_SECTIONS:
        block = content.get(key)
        if block:
            sections.append(f"## {heading}\n{block}")
    extra = content.get("extra_markdown")
    if extra:
        sections.append("## 商品描述\n" + extra)

    if not sections:
        return None
    now = datetime.now(timezone.utc)
    body = f"# {name}\n\n" + "\n\n".join(sections)
    return {
        "valid_from": now.isoformat(),
        "valid_until": (now + timedelta(days=730)).isoformat(),
        "doc_id": product_doc_id(detail["productId"]),
        "title": f"商品知识：{name}",
        "source_uri": f"product:{detail['productId']}",
        "source_type": "PRODUCT_AUTO",
        "body": body,
        "checksum": sha256(body.encode()).hexdigest(),
        "language": "zh-CN",
        "acl": "PUBLIC",
        "product_ids": [str(detail["productId"])],
    }
