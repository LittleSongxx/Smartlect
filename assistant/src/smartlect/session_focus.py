"""Server-compiled shopping focus. The model does not choose a knowledge corpus."""

FOCUS_MODES = ("GLOBAL", "PRODUCT", "GUIDE")


def compile_focus(*, product_id=None, sku_key=None, focus_mode=None):
    """Write the turn's retrieval plane from the entry payload.

    PRODUCT requires a product_id. GLOBAL/GUIDE never inherit a leftover product
    filter: each run starts empty and this dict is the only focus the tools see.
    """
    pid = str(product_id or "").strip()
    sku = str(sku_key or "").strip()
    mode = str(focus_mode or "").strip().upper()
    if mode not in FOCUS_MODES:
        mode = "PRODUCT" if pid else "GLOBAL"
    if mode == "PRODUCT" and not pid:
        mode = "GLOBAL"
    if mode != "PRODUCT":
        pid, sku = "", ""
    return {
        "focus_mode": mode,
        "focus_product_id": pid or None,
        "focus_sku_key": sku or None,
        "knowledge_corpus": "PRODUCT_AND_STORE" if mode == "PRODUCT" else "STORE",
    }
