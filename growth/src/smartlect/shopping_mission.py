"""Conversation-scoped shopping slots. Closed extractor; not a taxonomy or preference profile."""
import re
import unicodedata

from smartlect.state import StateError, _integer, _text

MISSION_VERSION = 1
MAX_TERMS = 20
MAX_REQUIRED = 16
MAX_TARGETS = 4
COUNT_MEASURE = '个只条台把张件套份支块'
_CN_DIGITS = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def _cn_price(raw):
    """Like _cn_count but for prices: no 999 cap (预算1000元 is legal money)."""
    value = unicodedata.normalize('NFKC', str(raw or '').strip())
    if value.isdigit():
        return int(value)
    return _cn_count(raw)


def _cn_count(raw):
    """Arabic or simple Chinese numerals (through 百) to an int in [1, 999]."""
    value = unicodedata.normalize('NFKC', str(raw or '').strip())
    if not value:
        return None
    if value.isdigit():
        number = int(value)
        return number if 1 <= number <= 999 else None
    total, number = 0, None
    for char in value:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char == '十':
            total += (number or 1) * 10
            number = None
        elif char == '百':
            total += (number or 1) * 100
            number = None
        else:
            return None
    total += number or 0
    return total if 1 <= total <= 999 else None


def empty_mission():
    return {
        'version': MISSION_VERSION,
        'budget_max_cents': None,
        'min_price_cents': None,
        'category_id': None,
        'excluded_terms': [],
        'required_terms': [],
        'comparison_targets': [],
        'comparison_required': False,
        'query': '',
        'quantity': None,
        'rollback_authorized': False,
    }


def _fold(text):
    return unicodedata.normalize('NFKC', str(text or '')).casefold()


def _unique(values, limit):
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = ' '.join(value.split())
        if not item or len(item) > 128:
            continue
        key = _fold(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def normalize_mission(value):
    data = value if isinstance(value, dict) else {}
    budget = data.get('budget_max_cents')
    if budget is not None:
        _integer(budget, 'budget_max_cents', 0, 100000000)
    minimum = data.get('min_price_cents')
    if minimum is not None:
        _integer(minimum, 'min_price_cents', 0, 100000000)
    quantity = data.get('quantity')
    if quantity is not None:
        _integer(quantity, 'quantity', 1, 999)
    category = data.get('category_id')
    if category is not None:
        category = _text(category, 'category_id', 64)
    query = ' '.join(str(data.get('query') or '').split())[:200]
    return {
        'version': MISSION_VERSION,
        'budget_max_cents': budget,
        'min_price_cents': minimum,
        'category_id': category,
        'excluded_terms': _unique(data.get('excluded_terms') or [], MAX_TERMS),
        'required_terms': _unique(data.get('required_terms') or [], MAX_REQUIRED),
        'comparison_targets': _unique(data.get('comparison_targets') or [], MAX_TARGETS),
        'comparison_required': bool(data.get('comparison_required')),
        'query': query,
        'quantity': quantity,
        # Authorization persists for the conversation once given ("按可售来").
        'rollback_authorized': bool(data.get('rollback_authorized')),
    }


def extract_mission(utterance):
    """Deterministic slots from the current user turn. No scene-word tables."""
    text = str(utterance or '').strip()
    extracted = empty_mission()
    reversed_terms = []
    if not text:
        extracted['reversed_terms'] = reversed_terms
        return extracted
    for match in re.finditer(r'预算\s*([0-9０-９一二两三四五六七八九十百千]+)\s*(?:元|块)?', text):
        price = _cn_price(match.group(1))
        if price:
            extracted['budget_max_cents'] = price * 100
    # Buy-count intent: purchase verb + count + measure word. Interrogatives without
    # a count ("能买吗") and result-count asks ("推荐3个") stay outside.
    for match in re.finditer(r'(?:买|购买|要|来)\s*([0-9０-９一二两三四五六七八九十百千]+)\s*[' + COUNT_MEASURE + ']', text):
        count = _cn_count(match.group(1))
        if count:
            extracted['quantity'] = count
    # Price windows ("50元到150元之间") carry both bounds; the first number must
    # carry a currency so quantity ranges ("2到3个") never parse as prices.
    for match in re.finditer(r'([0-9０-９一二两三四五六七八九十百千]+)\s*(?:元|块)\s*(?:到|至|-|—|~)'
                             r'\s*([0-9０-９一二两三四五六七八九十百千]+)\s*(?:元|块)?(?:之间|以内|以下)?', text):
        low, high = _cn_price(match.group(1)), _cn_price(match.group(2))
        if low and high:
            extracted['min_price_cents'] = min(low, high) * 100
            extracted['budget_max_cents'] = max(low, high) * 100
    # Bare numbers bind prices only when not followed by a measure word, so
    # "两百以内" is a budget but "三个以内" stays a count phrase.
    for match in re.finditer(r'([0-9０-９一二两三四五六七八九十百千]+)\s*(?![个只条台把张件套支])'
                             r'(?:元|块)?\s*(?:以内|以下)', text):
        price = _cn_price(match.group(1))
        if price:
            extracted['budget_max_cents'] = price * 100
    for match in re.finditer(r'([0-9０-９一二两三四五六七八九十百千]+)\s*(?![个只条台把张件套支])'
                             r'(?:元|块)?\s*以上', text):
        price = _cn_price(match.group(1))
        if price:
            extracted['min_price_cents'] = price * 100
    for match in re.finditer(r'其实\s*([^，。！？\s]{1,12})\s*可以', text):
        reversed_terms.append(match.group(1))
    for match in re.finditer(r'([^，。！？\s]{1,12})\s*(?:也行|没关系)', text):
        term = match.group(1)
        reversed_terms.append(term[2:] if term.startswith('其实') else term)
    for match in re.finditer(r'可以要\s*([^，。！？\s]{1,12})', text):
        reversed_terms.append(match.group(1))
    extracted['reversed_terms'] = _unique(reversed_terms, MAX_TERMS)
    for match in re.finditer(r'(?:不要买|不要|别要|排除)\s*([^，。！？\s]{1,16})', text):
        term = match.group(1)
        if not any(_fold(term) == _fold(item) for item in extracted['reversed_terms']):
            extracted['excluded_terms'].append(term)
    extracted['excluded_terms'] = _unique(extracted['excluded_terms'], MAX_TERMS)
    if re.search(r'比较|对比', text):
        extracted['comparison_required'] = True
    for match in re.finditer(
            r'(?:比较|对比)\s*(?:一下|下)?\s*([^，。！？\s]{1,16})\s*(?:和|与|跟)\s*([^，。！？\s]{1,16})',
            text):
        extracted['comparison_targets'].extend([match.group(1), match.group(2)])
        extracted['comparison_required'] = True
    for match in re.finditer(
            r'([^，。！？\s]{1,16})\s*(?:和|与|跟)\s*([^，。！？\s]{1,16})\s*(?:比一比|比较|对比|比一下|比)',
            text):
        extracted['comparison_targets'].extend([match.group(1), match.group(2)])
        extracted['comparison_required'] = True
    for match in re.finditer(r'([^，。！？\s]{1,16})\s*(?:和|与|跟)\s*([^，。！？\s]{1,16})', text):
        left, right = match.group(1), match.group(2)
        if left in {'其实', '不要', '别要', '排除'} or right in {'可以', '也行', '没关系'}:
            continue
        if re.search(r'不要|别要|排除', text[max(0, match.start() - 4):match.start()]):
            continue
        extracted['comparison_targets'].extend([left, right])
        extracted['comparison_required'] = True
    cleaned = []
    for target in extracted['comparison_targets']:
        item = re.sub(r'^(?:比较一下|对比一下|比一比|比较|对比)', '', target)
        cleaned.append(re.sub(r'(?:比较一下|对比一下|比一比|比较|对比)$', '', item))
    extracted['comparison_targets'] = _unique(cleaned, MAX_TARGETS)
    expanded = []
    for target in extracted['comparison_targets']:
        expanded.extend(part for part in re.split(r'[、/]', target) if part)
    extracted['comparison_targets'] = _unique(expanded, MAX_TARGETS)
    match = re.search(r'([A-Za-z][A-Za-z0-9]{0,7})类目', text)
    if match:
        extracted['category_id'] = match.group(1)
    # Users say the category in Chinese while the catalog ids are Latin; a closed
    # word map bridges them so a declared category can ground (v11 shop-d-52/54:
    # "桌面这个类目" could never trace a model-declared 'desk', the guard dropped
    # it, and the categoryless browse came back with every category's goods).
    match = re.search(r'(桌面|音频|配件|家具)[^，。！？\s]{0,4}(?:类目|分类|类别|类)', text)
    if match:
        extracted['category_id'] = {'桌面': 'desk', '音频': 'audio',
                                    '配件': 'acc', '家具': 'furn'}[match.group(1)]
    # Explicit rollback authorization ("按可售来", "买不到就放宽"): availability
    # trumps the strict qualifier set, so an empty set under authorization must
    # be substituted, not bounced back to the user (v11-v14 shop-d-19 kept
    # asking for permission the user had already granted).
    if re.search(r'按可售来|买不到就|买不起就算了|实在没有就|没有的话|有什么买什么|有啥买啥|随便挑|随便选', text):
        extracted['rollback_authorized'] = True
    return extracted


def requirement_slots(utterance):
    """Closed frames only: 要/只要 X, explicit buy frames, and price-attributive 的 X.
    Not a free-noun harvest."""
    text = str(utterance or '').strip()
    raw = []
    for match in re.finditer(r'(?<![不别需求主])(?:只要|要)([^，。！？、\s]{1,16})', text):
        if text[max(0, match.start() - 2):match.start()] == '可以':
            continue
        term = match.group(1)
        if term.startswith('预算'):
            continue
        # "要买三个呢" captures 买三个呢 — strip the buy intent and the count+measure
        # phrase so only a real product noun survives; a bare quantity is not a term.
        term = re.sub(r'^(?:买|购买)?(?:[0-9０-９一二两三四五六七八九十百千]+\s*'
                      r'[个只条台把张件套份支块]?)+', '', term)
        if not term:
            continue
        raw.append(term)
    # Explicit purchase intent names the product: 买/购买 + optional count+measure + term.
    # Negations and interrogatives (买不到/能买吗) stay outside via lookarounds.
    # The capture may not start with a numeral: with a trailing count+measure and no
    # noun ("买一把"), the greedy prefix group would otherwise backtrack and hand the
    # quantity phrase itself to the capture — poisoning every later retrieval.
    for match in re.finditer(r'(?<![不别没])(?:买|购买)(?![吗吧呢到不没来])'
                             r'(?:[0-9０-９一二两三四五六七八九十百千]+\s*[个只条台把张件套份支块]?)*'
                             r'([^，。！？、\s0-9０-９一二两三四五六七八九十百千]{2,16})', text):
        raw.append(match.group(1))
    for match in re.finditer(
            r'(?:预算\s*\d+\s*(?:元|块)?|\d+\s*(?:元|块)\s*(?:以内|以上)|以内|以上)\s*的\s*([^，。！？、\s]{1,16})',
            text):
        raw.append(match.group(1))
    # Bare attributive noun phrase ("白色的入门耳机"): the whole utterance is the
    # product ask. Harvest the HEAD noun phrase only — the model reliably names
    # colour qualifiers but under-reports the head (v14 shop-d-34 passed only
    # 白色 and let a white wireless headset through), and the tool-arg union
    # then tops the gate up structurally. Interrogatives, negations, reversals
    # and multi-clause turns stay out: this frame is a noun phrase, not a
    # sentence.
    stripped = re.sub(r'[?？。!！]+$', '', text)
    if (2 <= len(stripped) <= 16 and stripped.count('的') == 1
            and not re.search(r'[，,、;；]|吗|呢|能不能|可不可以|有没有|是不是|多少|是什么|哪个|哪些|什么|'
                              r'怎么|你们|客服|政策|订单|退款|优惠|发票|地址|也|的话|就行|有哪些|不要|别|只要', stripped)):
        head = stripped.partition('的')[2]
        if head and 2 <= len(head) <= 10 and not re.search(r'[0-9０-９]', head):
            raw.append(head)
    terms = []
    for item in raw:
        item = re.sub(r'(?:这款|看看|给我看|来一[个台份])$', '', item)
        item = re.sub(r'(?:有哪些|什么|哪个|哪些|几款|几样|什么样)$', '', item)
        item = re.sub(r'[呢吧吗啊嘛呀哦]+$', '', item).strip('的')
        if not item:
            continue
        latin = ''.join(re.findall(r'[A-Za-z0-9]+', item))
        cjk = ''.join(re.findall(r'[\u3400-\u9fff]+', item))
        if len(latin) >= 2:
            terms.append(latin)
        if len(cjk) == 2:
            terms.append(cjk)
        elif len(cjk) > 2:
            import jieba
            words = [word.strip() for word in jieba.lcut(cjk) if len(word.strip()) >= 2]
            terms.extend(words or [cjk])
    return _unique(terms, MAX_REQUIRED)


def _remove_reversed(terms, reversed_terms):
    dropped = [_fold(item) for item in reversed_terms]
    return [term for term in terms if not any(key == _fold(term) or key in _fold(term) for key in dropped)]


def merge_mission(previous, extracted, explicit=None):
    """Tool args beat this-turn extract, which beats the stored conversation slots."""
    previous = normalize_mission(previous)
    extracted = extracted if isinstance(extracted, dict) else empty_mission()
    explicit = explicit if isinstance(explicit, dict) else {}
    reversed_terms = list(extracted.get('reversed_terms') or [])
    if explicit.get('budget_max_cents') is not None:
        budget = explicit['budget_max_cents']
    elif extracted.get('budget_max_cents') is not None:
        budget = extracted['budget_max_cents']
    else:
        budget = previous['budget_max_cents']
    if explicit.get('min_price_cents') is not None:
        minimum = explicit['min_price_cents']
    elif extracted.get('min_price_cents') is not None:
        minimum = extracted['min_price_cents']
    else:
        minimum = previous['min_price_cents']
    if explicit.get('quantity'):
        quantity = explicit['quantity']
    elif extracted.get('quantity'):
        quantity = extracted['quantity']
    else:
        quantity = previous['quantity']
    if explicit.get('category_id') is not None:
        category = explicit['category_id']
    elif extracted.get('category_id') is not None:
        category = extracted['category_id']
    else:
        category = previous['category_id']
    if explicit.get('excluded_terms') is not None:
        excluded = list(explicit['excluded_terms'])
        excluded.extend(extracted.get('excluded_terms') or [])
    else:
        excluded = list(previous['excluded_terms'])
        excluded.extend(extracted.get('excluded_terms') or [])
    excluded = _remove_reversed(_unique(excluded, MAX_TERMS), reversed_terms)
    if explicit.get('required_terms') is not None:
        required = list(explicit['required_terms'])
    else:
        required = list(previous['required_terms'])
        required.extend(extracted.get('required_terms') or [])
    if explicit.get('comparison_targets') is not None:
        targets = list(explicit['comparison_targets'])
    else:
        targets = list(previous['comparison_targets'])
        targets.extend(extracted.get('comparison_targets') or [])
    if explicit.get('comparison_required') is not None:
        comparison_required = bool(explicit['comparison_required'])
    elif extracted.get('comparison_required'):
        comparison_required = True
    else:
        comparison_required = bool(previous['comparison_required']) and bool(_unique(targets, MAX_TARGETS))
    if explicit.get('query'):
        query = explicit['query']
    else:
        query = previous.get('query') or ''
    return normalize_mission({
        'budget_max_cents': budget,
        'min_price_cents': minimum,
        'category_id': category,
        'excluded_terms': excluded,
        # Rollback authorization is sticky: once granted it covers later turns
        # of the same purchase conversation too.
        'rollback_authorized': bool(previous.get('rollback_authorized')
                                    or extracted.get('rollback_authorized')),
        'required_terms': required,
        'comparison_targets': targets,
        'comparison_required': comparison_required,
        'query': query,
        'quantity': quantity,
    })


def explicit_from_request(params):
    explicit = {}
    if params.get('max_price_cents') is not None:
        explicit['budget_max_cents'] = params['max_price_cents']
    if (params.get('min_price_cents') or 0) > 0:
        explicit['min_price_cents'] = params['min_price_cents']
    if params.get('quantity'):
        explicit['quantity'] = params['quantity']
    if params.get('category_id') is not None:
        explicit['category_id'] = params['category_id']
    if 'excluded_terms' in params:
        explicit['excluded_terms'] = list(params.get('excluded_terms') or [])
    if 'required_terms' in params:
        explicit['required_terms'] = list(params.get('required_terms') or [])
    if params.get('comparison_targets') is not None:
        explicit['comparison_targets'] = list(params['comparison_targets'])
    if params.get('query'):
        explicit['query'] = params['query']
    return explicit


def has_hard_constraints(request, mission=None):
    mission = mission or empty_mission()
    return bool(
        request.get('max_price_cents') is not None
        or (request.get('min_price_cents') or 0) > 0
        or (request.get('quantity') or 1) > 1
        or request.get('required_terms')
        or request.get('excluded_terms')
        or request.get('excluded_product_ids')
        or request.get('excluded_sku_keys')
        or request.get('product_id')
        or request.get('category_id')
        or mission.get('budget_max_cents') is not None
        or (mission.get('min_price_cents') or 0) > 0
        or (mission.get('quantity') or 1) > 1
        or mission.get('category_id')
        or mission.get('excluded_terms')
        or mission.get('required_terms')
        or mission.get('comparison_required')
    )


def apply_mission_to_request(request, mission):
    result = dict(request)
    if result.get('max_price_cents') is None and mission.get('budget_max_cents') is not None:
        result['max_price_cents'] = mission['budget_max_cents']
    if (result.get('min_price_cents') or 0) <= 0 and (mission.get('min_price_cents') or 0) > 0:
        result['min_price_cents'] = mission['min_price_cents']
    if (result.get('quantity') or 1) <= 1 and (mission.get('quantity') or 0) > 1:
        result['quantity'] = mission['quantity']
    if result.get('category_id') is None and mission.get('category_id'):
        result['category_id'] = mission['category_id']
    if not str(result.get('query') or '').strip() and mission.get('query'):
        result['query'] = mission['query']
    result['excluded_terms'] = _unique([*(result.get('excluded_terms') or []), *(mission.get('excluded_terms') or [])], MAX_TERMS)
    result['required_terms'] = _unique([*(result.get('required_terms') or []), *(mission.get('required_terms') or [])], MAX_REQUIRED)
    for key in ('required_terms', 'excluded_terms', 'excluded_product_ids', 'excluded_sku_keys'):
        if any(not str(value).strip() or len(str(value)) > 128 for value in result.get(key) or []):
            raise StateError('invalid_recommendation_constraint', 422)
    if result.get('max_price_cents') is not None and result.get('min_price_cents', 0) > result['max_price_cents']:
        raise StateError('invalid_price_interval', 422)
    return result


def shopping_request(params, mission):
    """Hard slots come from this-turn args and mission, never long-term user_preference."""
    from smartlect.catalog_gate import RecommendationRequest
    allowed = set(RecommendationRequest.model_fields)
    request = RecommendationRequest.model_validate({key: value for key, value in (params or {}).items() if key in allowed})
    return apply_mission_to_request(request.model_dump(), normalize_mission(mission))


def retrieval_variants(request, mission):
    variants = []

    def add(text):
        item = ' '.join(str(text or '').split())
        if item and item not in variants:
            variants.append(item)

    add(request.get('query'))
    if request.get('required_terms'):
        add(' '.join(request['required_terms']))
    targets = mission.get('comparison_targets') or []
    if len(targets) == 1:
        add(targets[0])
    return variants[:3]


def looks_like_product_request(utterance):
    """Narrow shopping-intent probe for the selection closeout gate: a price
    phrase, an exclusion in either word order, a buy/order verb, or count+
    measure. Support questions that merely reference a past purchase ("我买的
    键盘能退吗") carry none of these shapes and stay untouched — the gate only
    matters when a turn ends insufficient without any selection attempt."""
    text = str(utterance or '')
    return bool(
        re.search(r'[0-9０-９一二两三四五六七八九十百千]+\s*(?:元|块)', text)
        # "不要转人工/不要退款" negates a service action, not a product attribute.
        or re.search(r'(?:的\s*)?(?:不要|别要|不买|排除|不含|除了)(?!转人工|人工|客服|退款|退货|售后)', text)
        or re.search(r'(?:卖我|想买|要买|购买|下单|建单|来一[个只条台把张件套支]|推荐几|看看有什么)', text)
        or re.search(r'[0-9０-９一二两三四五六七八九十]+\s*[个只条台把张件套支根]', text)
    )


def shopping_turn_changed(extracted, slots=()):
    """This turn wrote or replaced a conversation shopping slot."""
    extracted = extracted if isinstance(extracted, dict) else {}
    return bool(
        extracted.get('budget_max_cents') is not None
        or (extracted.get('min_price_cents') or 0) > 0
        or extracted.get('category_id')
        or extracted.get('excluded_terms')
        or extracted.get('reversed_terms')
        or extracted.get('comparison_required')
        or extracted.get('comparison_targets')
        or extracted.get('quantity')
        or slots
    )


def selects_products(extracted, slots=()):
    """This turn names something to select, so the catalog is worth querying.

    Stricter than ``shopping_turn_changed``: a bare exclusion or a reversed term
    ("不要塑料") says what to drop, not what to look for, and on its own never
    justifies a selection query. Policy text contains 要/不要 shapes that the lexical
    frames cannot tell apart from shopping ("退款需要确认吗"), so the plane that runs
    a retrieval keys on the positive slots only.
    """
    extracted = extracted if isinstance(extracted, dict) else {}
    return bool(
        extracted.get('budget_max_cents') is not None
        or (extracted.get('min_price_cents') or 0) > 0
        or extracted.get('category_id')
        or extracted.get('comparison_required')
        or extracted.get('comparison_targets')
        or extracted.get('quantity')
        or slots
    )


def retrieve_matches_mission(request, mission):
    """Last retrieve already carries the conversation hard slots."""
    if not request:
        return False
    mission = normalize_mission(mission)
    if mission['budget_max_cents'] is not None and request.get('max_price_cents') != mission['budget_max_cents']:
        return False
    if (mission['min_price_cents'] or 0) > 0 and request.get('min_price_cents') != mission['min_price_cents']:
        return False
    if (mission['quantity'] or 1) > 1 and (request.get('quantity') or 1) != mission['quantity']:
        return False
    if mission['category_id'] and request.get('category_id') != mission['category_id']:
        return False
    have_excluded = {_fold(item) for item in request.get('excluded_terms') or []}
    have_required = {_fold(item) for item in request.get('required_terms') or []}
    if any(_fold(item) not in have_excluded for item in mission['excluded_terms']):
        return False
    if any(_fold(item) not in have_required for item in mission['required_terms']):
        return False
    return True


def mission_retrieve_params(mission):
    """Tool args for a retrieve that shopping_request can merge with mission."""
    mission = normalize_mission(mission)
    params = {}
    if mission['query']:
        params['query'] = mission['query']
    if mission['budget_max_cents'] is not None:
        params['max_price_cents'] = mission['budget_max_cents']
    if (mission['min_price_cents'] or 0) > 0:
        params['min_price_cents'] = mission['min_price_cents']
    if (mission['quantity'] or 0) > 1:
        params['quantity'] = mission['quantity']
    if mission['category_id']:
        params['category_id'] = mission['category_id']
    if mission['excluded_terms']:
        params['excluded_terms'] = list(mission['excluded_terms'])
    if mission['comparison_targets']:
        params['comparison_targets'] = list(mission['comparison_targets'])
    return params


def validate_sku_key(value):
    key = _text(value, 'sku_key', 160)
    if ':' not in key:
        raise StateError('invalid_sku_key', 422)
    product_id, digest = key.split(':', 1)
    if not product_id or not digest or len(product_id) > 64:
        raise StateError('invalid_sku_key', 422)
    return key


def _squash(text):
    return re.sub(r'[\W_]+', '', _fold(text))


def _mentions_amount(utterance, yuan):
    """The user named this exact amount this turn without a marker word
    ("300 买不到就 600 吧") - Arabic digit run not followed by a measure word,
    or the simple CJK round-hundred/thousand form. A count frame ("买2个")
    never mentions an amount."""
    text = str(utterance or '')
    if re.search(r'(?:^|[^0-9])' + str(int(yuan)) + r'(?!\s*[0-9个只条台把张件套支块])', text):
        return True
    hundreds = {'1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六', '7': '七', '8': '八', '9': '九'}
    digits = str(int(yuan))
    if len(digits) == 3 and digits.endswith('00'):
        cjk = hundreds[digits[0]] + '百'
        return cjk in text and not re.search(cjk + r'[一二两三四五六七八九]?[十百千万个只条台把张件套支]', text)
    if len(digits) == 4 and digits[1:] == '000':
        cjk = hundreds[digits[0]] + '千'
        return cjk in text and not re.search(cjk + r'[一二两三四五六七八九]?[十百千万个只条台把张件套支]', text)
    return False


def ground_tool_params(params, utterance, mission):
    """Model-declared hard slots must trace back to user words — this turn's utterance
    or the stored conversation mission. Untraceable slots are demoted (dropped from the
    gate) instead of silently filtering the catalog; product/sku id exclusions are
    catalog-grounded and exempt. Mirrors ADR-0002: the model declares, the system
    compiles against what the user actually said."""
    params = params or {}
    mission = normalize_mission(mission)
    text = _squash(utterance)
    dropped = {}
    filtered = dict(params)
    for key in ('required_terms', 'excluded_terms'):
        values = params.get(key)
        if values is None:
            continue
        mission_pool = {_squash(value) for value in mission.get(key) or []}
        kept, lost = [], []
        for value in values:
            needle = _squash(value)
            (kept if needle and (needle in text or needle in mission_pool) else lost).append(value)
        if lost:
            dropped[key] = lost
            filtered[key] = kept
    category = params.get('category_id')
    if category is not None and _squash(category) not in text and category != mission.get('category_id'):
        dropped['category_id'] = category
        filtered.pop('category_id', None)
    extracted = extract_mission(utterance)
    for param_key, slot_key in (('max_price_cents', 'budget_max_cents'), ('min_price_cents', 'min_price_cents')):
        value = params.get(param_key)
        if value is None or (param_key == 'min_price_cents' and not value):
            continue
        if extracted.get(slot_key) != value and mission.get(slot_key) != value:
            # A marker-less amount the user actually named this turn ("就600吧")
            # grounds the model's declaration; without this the stale mission
            # budget overwrites the user's latest instruction (v12 shop-d-50).
            if value % 100 == 0 and _mentions_amount(utterance, value // 100):
                continue
            dropped[param_key] = value
            filtered.pop(param_key)
    # A model-supplied buy count must equal the count the user actually said (this
    # turn or the stored mission); anything else is dropped and the mission count
    # refills the request, so quietly shrinking quantity to dodge an empty set
    # cannot pass the gate.
    quantity = params.get('quantity')
    if quantity is not None and quantity != extracted.get('quantity') and quantity != mission.get('quantity'):
        dropped['quantity'] = quantity
        filtered.pop('quantity', None)
    return filtered, dropped
