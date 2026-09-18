"""Tool-result projections: what the model is allowed to observe from each receipt."""
from smartlect.catalog_gate import _fold
from smartlect.events import canonical

def knowledge_observation(data):
    observation = {'evidence_status': {'answered':'retrieved','insufficient':'none',
                   'conflicting':'conflicting','needs_human':'unsafe'}[data['answer_status']],
                   'evidence_only': True, 'source_trust': 'untrusted_data', 'citations': [],
                   'quarantined': []}
    for citation in data['citations']:
        if citation.get('carries_untrusted_instructions'):
            # Named but not quoted. Reproducing the passage is how an injection payload reaches
            # the answer even when the model refuses to obey it, and a caller cannot tell an
            # echoed payload from an executed one. The model still learns the document exists.
            observation['quarantined'].append({key: citation[key] for key in ('chunk_id', 'title')})
            continue
        item = {key: citation[key] for key in ('chunk_id', 'title', 'content')}
        candidate = {**observation, 'citations': [*observation['citations'], item]}
        if len(canonical(candidate).encode()) > 6500:
            break  # Keep complete source chunks under the existing tool-result limit.
        observation = candidate
    if not observation['citations'] and observation['evidence_status'] == 'retrieved':
        observation['evidence_status'] = 'none'
    if (data.get('retrieval') or {}).get('empty_visible_evidence') or data.get('empty_visible_evidence'):
        observation['empty_visible_evidence'] = True
    denied = [{'doc_id': item.get('doc_id'), 'title': item.get('title') or ''}
              for item in data.get('acl_denied') or [] if item.get('doc_id')]
    if denied:
        observation['acl_denied'] = denied
    return observation


def product_observation(data):
    # Identity and parameters are visible; product-level totals and SKU stock do not
    # establish sellable quantities. Price/stock stay off the knowledge index.
    properties = []
    for item in data.get('propertyValues') or []:
        if not isinstance(item, dict):
            continue
        name = item.get('propertyName') or item.get('name')
        value = item.get('propertyValue') or item.get('value')
        if name and value:
            properties.append({'propertyName': str(name), 'propertyValue': str(value)})
    identities = []
    for sku in data.get('skus') or []:
        if not isinstance(sku, dict):
            continue
        product_id = sku.get('productId') or data.get('productId')
        sku_hash = sku.get('propertyValueIdHash')
        value_ids = sku.get('propertyValueIds')
        if not product_id or not (sku_hash or value_ids):
            continue
        identities.append({
            'sku_key': f"{product_id}:{sku_hash}" if sku_hash else None,
            'productId': product_id,
            'propertyValueIdHash': sku_hash,
            'propertyValueIds': value_ids,
        })
    return {**{key: data.get(key) for key in ('productId', 'productName', 'categoryId',
            'description', 'status', 'minPrice', 'maxPrice', 'brand')},
            'propertyValues': properties,
            'sku_identities': identities,
            'sku_stock': 'not_observed; use recommend_skus for current sellable specifications'}


def sku_items(data):
    items = data.get('items') if isinstance(data, dict) else data
    return [item for item in (items or []) if isinstance(item, dict) and item.get('sku_key')]


def sku_observation(data):
    cards = [{key: item[key] for key in ('sku_key', 'productId', 'propertyValueIds', 'productName',
              'price_cents', 'stock', 'specification', 'reasons') if key in item} for item in sku_items(data)]
    if not isinstance(data, dict):
        return cards
    extra = {key: data[key] for key in ('empty_reason', 'comparison', 'comparison_complete', 'missing_targets',
                                        'filter_report')
             if key in data and data.get(key) not in ([], {})}
    return {**extra, 'items': cards}


def constraint_echo(request):
    """The gate the retrieve actually applied, echoed next to the filter report so
    a gap between the user's qualifiers and the declared gate is visible in situ."""
    request = request or {}
    echo = {}
    for key in ('required_terms', 'excluded_terms'):
        if request.get(key):
            echo[key] = list(request[key])
    if request.get('max_price_cents') is not None:
        echo['max_price_cents'] = request['max_price_cents']
    if (request.get('min_price_cents') or 0) > 0:
        echo['min_price_cents'] = request['min_price_cents']
    if (request.get('quantity') or 1) > 1:
        echo['quantity'] = request['quantity']
    if request.get('category_id'):
        echo['category_id'] = request['category_id']
    return echo


def sku_obeys_request(item, request):
    text = _fold(str(item.get('productName') or '') + ' ' + str(item.get('specification') or ''))
    maximum = request.get('max_price_cents')
    if maximum is not None and item.get('price_cents') is not None and item['price_cents'] > maximum:
        return False
    minimum = request.get('min_price_cents') or 0
    if minimum and item.get('price_cents') is not None and item['price_cents'] < minimum:
        return False
    if any(_fold(term) not in text for term in request.get('required_terms') or []):
        return False
    if any(_fold(term) in text for term in request.get('excluded_terms') or []):
        return False
    if request.get('category_id') and item.get('categoryId') != request['category_id']:
        return False
    return True
