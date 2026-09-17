"""Knowledge retrieval planes. Empty product_ids can only be store policy."""

from smartlect.events import canonical
from smartlect.state import _text

STORE = "STORE"
PRODUCT = "PRODUCT"
PRODUCT_AND_STORE = "PRODUCT_AND_STORE"
CORPORA = (STORE, PRODUCT, PRODUCT_AND_STORE)


def compile_search_filter(focus, requested_product_id=None):
    """PRODUCT focus is pinned. GLOBAL may honor a model-requested product_id."""
    focus = focus if isinstance(focus, dict) else {}
    mode = focus.get("focus_mode") or "GLOBAL"
    focus_pid = focus.get("focus_product_id")
    requested = str(requested_product_id).strip() if requested_product_id else ""
    if mode == "PRODUCT" and focus_pid:
        return {"product_id": str(focus_pid), "corpus": PRODUCT_AND_STORE}
    if requested:
        return {"product_id": requested, "corpus": PRODUCT_AND_STORE}
    return {"product_id": None, "corpus": STORE}


def search_document_clause(*, product_id=None, category_id=None, corpus=None):
    """SQL fragment and bind values for the published-document scan.

    Invariant: JSON_LENGTH(product_ids_json)=0 is STORE only. A product document
    must JSON_CONTAIN its product_id and must not be empty.
    """
    filters, values = [], []
    resolved = corpus if corpus in CORPORA else (PRODUCT_AND_STORE if product_id else STORE)
    if resolved == STORE:
        filters.append("AND JSON_LENGTH(d.product_ids_json)=0")
    elif resolved == PRODUCT:
        pid = _text(product_id, "product_id", 128)
        filters.append("AND JSON_LENGTH(d.product_ids_json)>0 AND JSON_CONTAINS(d.product_ids_json,%s)")
        values.append(canonical(pid))
    else:
        pid = _text(product_id, "product_id", 128)
        filters.append("AND (JSON_LENGTH(d.product_ids_json)=0 OR JSON_CONTAINS(d.product_ids_json,%s))")
        values.append(canonical(pid))
    if category_id is not None:
        filters.append("AND (JSON_LENGTH(d.category_ids_json)=0 OR JSON_CONTAINS(d.category_ids_json,%s))")
        values.append(canonical(_text(category_id, "category_id", 128)))
    return " ".join(filters), values


def parse_product_ids(value):
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        import json
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item)]


def citation_covers_product(item, product_id):
    if not product_id or not isinstance(item, dict):
        return False
    return str(product_id) in parse_product_ids(item.get("product_ids"))
