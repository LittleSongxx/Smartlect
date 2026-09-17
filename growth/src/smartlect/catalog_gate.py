"""SKU eligibility and request constraints. Shared by homepage rec and ads; ranking stays elsewhere."""
from collections import Counter
from decimal import Decimal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from smartlect.ads.analytics import to_cents
from smartlect.state import StateError


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    query: str = Field(default='', max_length=200, description='名称/规格软匹配排序；资格门请用required_terms/excluded_terms/category_id/价格')
    product_id: str | None = Field(default=None, min_length=1, max_length=64, description='用户指定的真实商品ID；仅缩小授权范围')
    category_id: str | None = Field(default=None, min_length=1, max_length=64, description='用户点名的真实类目ID，如desk类目填desk；未知省略，不能猜')
    max_price_cents: int | None = Field(default=None, ge=0, le=100000000, description='单价预算上限（分）')
    min_price_cents: int = Field(default=0, ge=0, le=100000000)
    quantity: int = Field(default=1, ge=1, le=999,
        description='要买的数量；检索按它校验库存，勿为绕开空结果调小')
    limit: int = Field(default=4, ge=1, le=8)
    required_terms: list[str] = Field(default_factory=list, max_length=16,
        description='名称/规格须逐项包含的文字；限定词（颜色/档位/型号/材质/品名）全部列入，少报会放行不合规商品')
    excluded_terms: list[str] = Field(default_factory=list, max_length=20, description='名称/规格不得包含的文字')
    excluded_product_ids: list[str] = Field(default_factory=list, max_length=64)
    excluded_sku_keys: list[str] = Field(default_factory=list, max_length=64)


def _fold(text):
    return unicodedata.normalize('NFKC', text).casefold()


def constraints(request, preferences=()):
    request = request if isinstance(request, RecommendationRequest) else RecommendationRequest.model_validate(request)
    result = request.model_dump()
    for key in ('required_terms', 'excluded_terms', 'excluded_product_ids', 'excluded_sku_keys'):
        if any(not value.strip() or len(value) > 128 for value in result[key]):
            raise StateError('invalid_recommendation_constraint', 422)
    # Only explicit saved restrictions become default hard constraints. Inferred
    # preferences remain ranking signals; current request restrictions take priority.
    for preference in preferences:
        if preference.get('source') != 'explicit':
            continue
        if preference.get('preference_key') == 'budget_max_cents' and result['max_price_cents'] is None:
            value = preference.get('value')
            if type(value) is int and 0 <= value <= 100000000:
                result['max_price_cents'] = value
        if preference.get('preference_key') == 'avoid' and 'excluded_terms' not in request.model_fields_set:
            value = preference.get('value')
            if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
                result['excluded_terms'] = list(value)
    if result['max_price_cents'] is not None and result['min_price_cents'] > result['max_price_cents']:
        raise StateError('invalid_price_interval', 422)
    return result


ISOLATED_PRODUCT_PREFIXES = ('9100', '9300')


def is_isolated_product_id(product_id):
    text = '' if product_id is None else str(product_id)
    return text.startswith(ISOLATED_PRODUCT_PREFIXES)


def scope_filter(product_scope):
    if not isinstance(product_scope, dict) or set(product_scope) != {'include', 'exclude'}:
        raise StateError('product_scope_required', 403)
    included, excluded = product_scope['include'], product_scope['exclude']
    if included is not None and (not isinstance(included, list) or len(included) > 5000):
        raise StateError('invalid_product_scope', 403)
    if not isinstance(excluded, list) or len(excluded) > 5000:
        raise StateError('invalid_product_scope', 403)
    if any(not isinstance(value, str) or not value or len(value) > 64 for value in [*(included or []), *excluded]):
        raise StateError('invalid_product_scope', 403)
    return None if included is None else frozenset(included), frozenset(excluded)


def is_eval_catalog(catalog_scope=None):
    return str(catalog_scope or '').strip().lower() == 'eval'


def in_scope(product_id, product_scope, catalog_scope=None):
    included, excluded = product_scope
    if product_id in excluded:
        return False
    if included is None:
        if is_eval_catalog(catalog_scope):
            return False
        if str(catalog_scope or '').strip().lower() == 'store':
            return True
        return not is_isolated_product_id(product_id)
    return product_id in included


def eligible_skus(snapshot, stocks, request, *, product_scope, allowed_sku_keys=None):
    """Exact per-SKU stock, never totalStocks."""
    catalog = {row['productId']: row for row in snapshot.get('products', [])}
    stock_rows = {}
    duplicate_stock = set()
    for row in stocks:
        key = (row.get('productId'), row.get('propertyValueIdHash'))
        if key in stock_rows:
            duplicate_stock.add(key)
        stock_rows[key] = row.get('stock')
    properties = {(row['productId'], row['propertyValueId']): row for row in snapshot.get('propertyValues', [])}
    cards, removed, seen = [], Counter(), set()
    for sku in snapshot.get('skus', []):
        product_id, digest, value_ids = sku.get('productId'), sku.get('propertyValueIdHash'), sku.get('propertyValueIds')
        if any(not isinstance(value, str) or not value for value in (product_id, digest, value_ids)):
            removed['invalid_sku'] += 1
            continue
        key = product_id + ':' + digest
        if key in seen:
            removed['duplicate_sku'] += 1
            continue
        seen.add(key)
        product = catalog.get(product_id)
        catalog_scope = None if not product else product.get('catalogScope') or product.get('catalog_scope')
        if not in_scope(product_id, product_scope, catalog_scope) or allowed_sku_keys is not None and key not in allowed_sku_keys:
            removed['scope_or_candidate_denied'] += 1
            continue
        if not product or type(product.get('status')) is not int or product['status'] != 1:
            removed['not_on_sale'] += 1
            continue
        stock = stock_rows.get((product_id, digest))
        if (product_id, digest) in duplicate_stock or type(stock) is not int or stock < request['quantity']:
            removed['stock_unavailable'] += 1
            continue
        try:
            if type(sku.get('price')) not in {int, str, Decimal}:
                raise ValueError()
            price = to_cents(str(sku['price']))
        except ValueError:
            removed['invalid_price'] += 1
            continue
        if (price < request['min_price_cents'] or request['max_price_cents'] is not None
                and price > request['max_price_cents']):
            removed['price_constraint'] += 1
            continue
        if product_id in request['excluded_product_ids'] or key in request['excluded_sku_keys']:
            removed['explicit_exclusion'] += 1
            continue
        if request['category_id'] is not None and product.get('categoryId') != request['category_id']:
            removed['category_constraint'] += 1
            continue
        property_rows = [properties.get((product_id, value_id)) for value_id in value_ids.split('-')]
        if any(row is None or not isinstance(row.get('propertyValue'), str) for row in property_rows):
            removed['unknown_specification'] += 1
            continue
        specification = '/'.join(row['propertyValue'] for row in property_rows)
        text = _fold(str(product.get('productName') or '') + ' ' + specification)
        if (any(_fold(term) not in text for term in request['required_terms']) or
                any(_fold(term) in text for term in request['excluded_terms'])):
            removed['term_constraint'] += 1
            continue
        cards.append({**sku, 'price': str(sku['price']), 'price_cents': price, 'stock': stock,
            'productName': product.get('productName') or '', 'categoryId': product.get('categoryId'),
            'cover': product.get('cover'), 'specification': specification, 'sku_key': key})
    return cards, dict(removed)
