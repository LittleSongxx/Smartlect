"""Deterministic turn guards: intent heuristics, retrieval budget, label coercion.

Each guard is pure with respect to (text, context-shape): no DB, no model, no clock.
"""
import re

from smartlect.knowledge import misses_utterance_constraints
from .contract import FinalAnswer

def retrieval_budget_action(context, utterance):
    """Third search: uncovered leftovers get an empty observation; covering leftovers still fault."""
    if context.get('retrieval_calls', 0) < 2:
        return 'search'
    if misses_utterance_constraints(context.get('visible_citations'), utterance):
        return 'empty_observation'
    return 'raise_rewrite_limit'


def keep_uncovered_leftovers(data):
    return bool((data.get('retrieval') or {}).get('rewrite_exhausted_uncovered'))


def store_policy_allows_empty_citations(context, utterance):
    """A gap statement needs no leftover citation when retrieval missed the question."""
    if context.get('legal_empty_visible'):
        return True
    visible = context.get('visible_citations') or []
    return bool(context.get('retrieval_calls')) and misses_utterance_constraints(visible, utterance)


def rejected_search_data(model_query, *, exhausted=False):
    return {'answer_status': 'insufficient', 'citations': [],
            'empty_visible_evidence': True,
            'retrieval': {'empty_visible_evidence': True,
                          'submitted_query': None, 'model_query': model_query,
                          'rewrite_rejected': not exhausted,
                          'rewrite_exhausted_uncovered': exhausted}}


def allow_retrieval_rewrite(context, *, utterance, model_query):
    """Second rewrite is independent; coverage is not a veto. Legal empty is not searched again."""
    if context.get('retrieval_calls', 0) < 1:
        return True
    if context.get('legal_empty_visible') or not context.get('visible_citations'):
        return False
    return True


_PRODUCT_UNIQUE = re.compile(
    r'成分|配料|用法|怎么用|如何使用|包装|禁忌|注意事项|卖点|材质|产地|品牌|含量|保质期|'
    r'规格参数|规格怎么选|有哪些规格|什么规格|哪种规格|几种规格|多少规格|怎么选规格|'
    r'尺寸|克重|净含量|功效|配方|防腐|过敏|副作用|储存|保鲜|这件.*(是什么|有什么)|'
    r'本商品|这个商品'
)
_STORE_POLICY_CUE = re.compile(r'运费|包邮|退换|退货|退款|发票|保修|配送|怎么退|如何退|售后流程')


def looks_like_product_unique_fact(text):
    """Ingredient/spec/packaging questions need this-turn product evidence."""
    value = str(text or '')
    if _STORE_POLICY_CUE.search(value) and not _PRODUCT_UNIQUE.search(value):
        return False
    return bool(_PRODUCT_UNIQUE.search(value))


def looks_like_service_request(text):
    """Performative service act, not a question about whether a service exists."""
    value = str(text or '')
    if re.search(r'(?:规则|范围|条件|流程).{0,16}(?:是什么|如何|怎么)|(?:是什么|如何|怎么).{0,16}(?:规则|范围|条件)', value):
        return False
    if re.search(r'(?:怎么|如何|咋)[^，。！？]{0,12}(?:换|退|补寄|报修|取消)', value):
        return False
    if re.search(r'(?:能|能否|能不能|可以|可不可以)[^，。！？]{0,12}(?:退款|退货|换货|补寄|取消|报修)', value):
        return False
    return bool(re.search(r'(?:请|帮我|麻烦)(?:现在)?(?:帮我|给我)?'
                          r'(?:预约|办理|安排|申请|查一下|查查|查|换|退|补寄|报修)', value))


def looks_like_irreconcilable_sources(text):
    """User asserts published sources cannot be reconciled. Asking how two topics differ is not this."""
    value = str(text or '')
    if re.search(r'(?:有什么|有何|哪些).{0,8}(?:区别|不一样|不同)', value):
        return False
    return bool(re.search(
        r'(?:两份|两种|两版|两处).{0,16}(?:不一样|不一致|矛盾|冲突|对不上)|(?:互相矛盾|说法不一|资料冲突|政策冲突)',
        value))


_STORE_FACT_WORDS = r'(?:库存|售罄|可售|下架|买得到|买不到|有货|没货|在售|缺货|现货)'
_SEARCH_OFFER_CUE = r'(?:检索|查询|搜索|找找|找一找|看看|确认|核实|推荐|查到|查一下|筛选)'
_HUMAN_NECESSITY = re.compile(r'(?:需要|建议|应当|必须|须)[^，。；！？]{0,14}人工(?:客服)?[^，。；！？]{0,6}(?:核实|处理|判断|介入|跟进)')
_HUMAN_OFFER = re.compile(r'我[^，。；！？]{0,12}(?:转交人工|转人工|创建工单|帮您转)')
_HUMAN_DEFERRAL = re.compile(r'(?:可以|可|建议|不妨)[^，。；！？]{0,16}(?:提交|发起|联系|找)[^，。；！？]{0,10}(?:工单|人工|客服)')


def answer_offers_human_transfer(answer):
    """The model itself volunteers to transfer/create a ticket (first person).
    Strong intent: no policy citation is required to compile it into action."""
    return bool(_HUMAN_OFFER.search(answer or ''))


def answer_defers_ticket_to_user(answer):
    """The answer tells the user to go file the ticket themselves — a deferral of an
    action store policy performs on the same condition (v14 sup-d-32: '可以描述情况
    并提交本地人工客服工单' closed as answered with no ticket). Weaker than a
    first-person offer, so compiling it additionally requires the cited policy to
    mention human handling, exactly like the necessity path."""
    return bool(_HUMAN_DEFERRAL.search(answer or ''))


def answer_states_human_necessity(answer):
    """The answer asserts human verification is needed. Weaker signal — a trailing
    hedge can produce it — so compiling it additionally requires the cited policy
    itself to mention human handling."""
    return bool(_HUMAN_NECESSITY.search(answer or ''))


def no_business_claim_has_store_conclusion(answer):
    """Availability or stock assertions are store facts, not chit-chat.

    A mention inside a search/verification offer ("我可以为您检索当前有货的商品")
    describes the offered action, not store state — v11 sup-d-50 died exactly
    there: a well-formed clarify was rejected twice, the repair hint pointed at
    "format" (nothing to fix), and the budget exhausted into a degraded turn.
    Only availability words without a nearby action cue assert facts."""
    text = answer or ''
    scrubbed = re.sub(_SEARCH_OFFER_CUE + r'[^，。；！？\s]{0,6}' + _STORE_FACT_WORDS, '', text)
    return bool(re.search(_STORE_FACT_WORDS, scrubbed))


def coerce_observed_fact_grounding(final, context):
    """Relabel a mis-tagged fact answer instead of rejecting the turn.

    Live shape: tools already returned the SKU, the model wrote the correct spec,
    then marked grounding=no_business_claim to dodge the citation requirement.
    That is a label error, not missing evidence. Policy wording without retrieval
    stays rejected — that claim is still ungrounded.
    """
    if getattr(final, 'grounding', None) != 'no_business_claim':
        return False
    if not context.get('fact_observed'):
        return False
    answer = getattr(final, 'answer', '') or ''
    has_sku = bool(getattr(final, 'selected_sku_keys', None))
    if not has_sku and not no_business_claim_has_store_conclusion(answer):
        return False
    if _STORE_POLICY_CUE.search(answer) and not context.get('retrieval_calls'):
        return False
    final.grounding = 'user_facts'
    context['grounding_compiled_from_observation'] = True
    return True


def salvage_unstructured_fact_answer(raw, context):
    """Accept a natural-language closeout after this turn already observed facts.

    The stream shows the `answer` field — or raw markdown when the model skips
    JSON. Without this, the first contract repair is spent on Invalid JSON, and
    the one remaining attempt often mis-tags grounding and tickets the user.
    """
    text = (raw or '').strip()
    if not text or text.lstrip().startswith('{'):
        return None
    if not context.get('fact_observed'):
        return None
    if _STORE_POLICY_CUE.search(text) and not context.get('retrieval_calls'):
        return None
    return FinalAnswer(
        answer=text[:4000],
        request_kind='inquire_fact',
        handoff_requested=False,
        grounding='user_facts',
        citation_chunk_ids=[],
        selected_sku_keys=[],
        requires_clarification=False,
    )


def bind_sole_observed_sku(final, products, context):
    """A single observed SKU is the spec the user asked about; attach it."""
    if getattr(final, 'selected_sku_keys', None):
        return False
    if getattr(final, 'grounding', None) != 'user_facts':
        return False
    keys = [key for key in (products or {}) if key]
    if len(keys) != 1:
        return False
    final.selected_sku_keys = keys
    context['sku_selected_from_sole_observation'] = True
    return True


_CATALOG_FACT = re.compile(r'价格|多少钱|库存|有货|售价|现价|规格')


def looks_like_catalog_fact_question(text):
    """Spec / price / stock questions can close from Java receipts without a second JSON."""
    value = str(text or '')
    if looks_like_service_request(value):
        return False
    if re.search(r'转人工|转交人工|找人工', value):
        return False
    if _STORE_POLICY_CUE.search(value) and not _PRODUCT_UNIQUE.search(value):
        return False
    return looks_like_product_unique_fact(value) or bool(_CATALOG_FACT.search(value))
