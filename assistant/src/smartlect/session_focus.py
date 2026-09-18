"""Server-compiled shopping focus. The model does not choose a knowledge corpus."""
import re

FOCUS_MODES = ("GLOBAL", "PRODUCT", "GUIDE")
_LEAVE_PRODUCT_FOCUS = re.compile(
    r'全店|别的商品|其他商品|另外选|换个品类|换一个品类|我的订单|查(?:一下)?订单|随便看看')
_SUBSTITUTE_AROUND_FOCUS = re.compile(r'替代|换一款|还有别的|其他款|更大瓶|同类')


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


def leaves_product_focus(utterance):
    """The user is leaving this product for store-wide or account work."""
    return bool(_LEAVE_PRODUCT_FOCUS.search(str(utterance or '')))


def allows_catalog_around_focus(utterance):
    """Ask for alternatives; keep knowledge pin, do not pin retrieve product_id."""
    return bool(_SUBSTITUTE_AROUND_FOCUS.search(str(utterance or '')))


def pin_focus_retrieve_params(params, focus, utterance=''):
    """PRODUCT focus retrieve stays on this product unless the user left or asked for alts."""
    focus = focus if isinstance(focus, dict) else {}
    result = dict(params or {})
    if focus.get('focus_mode') != 'PRODUCT' or not focus.get('focus_product_id'):
        return result
    if leaves_product_focus(utterance) or allows_catalog_around_focus(utterance):
        return result
    if result.get('comparison_targets') or result.get('sku_keys'):
        return result
    result['product_id'] = str(focus['focus_product_id'])
    return result


def pin_focus_offer_args(arguments, focus):
    """PRODUCT focus offer cannot switch to another productId."""
    result = dict(arguments) if isinstance(arguments, dict) else {}
    focus = focus if isinstance(focus, dict) else {}
    if focus.get('focus_mode') == 'PRODUCT' and focus.get('focus_product_id'):
        result['productId'] = str(focus['focus_product_id'])
    return result
