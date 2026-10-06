"""Deterministic turn guards: intent heuristics, retrieval budget, label coercion.

Each guard is pure with respect to (text, context-shape): no DB, no model, no clock.

分层（ADR-0013）：本模块的守卫分两层，治理路线不同——

A. 证据契约校验（bind_* / coerce_* / 检索预算 / no_business_claim_*）
   校验「终答声明 × 本轮回执」的一致性，是纯确定性不变量：引用必须来自本轮
   chunk_id、SKU 必须来自本轮回执、标签与观测相符。无意图推断，永久保留。

B. 意图帧启发式（looks_like_* / answer_*_human_*）
   中文关键词正则推断用户/答案的意图，在 session.answer_node 拥有覆盖模型
   request_kind 声明的改判权（破例帧强制 exception、矛盾资料强制 handoff、
   目录事实形态触发模板收口等）。它们锚定 v11–v28 评测合同的具体失败样本，
   但天然易误报（中文表达多样），按 ADR-0013 路线评测驱动逐条降级为
   提示/审计标记；降级判据是模型 request_kind 声明在评测中的可靠率达标。
   每个意图帧的改判点见各函数 docstring。
"""
import re

from smartlect.knowledge import misses_utterance_constraints
from .contract import FinalAnswer

# ── A. 证据契约校验与检索预算（确定性不变量，永久保留）─────────────────────

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


# ── B. 意图帧启发式（改判权见 ADR-0013，评测驱动逐条降级）───────────────────

def looks_like_product_unique_fact(text):
    """Ingredient/spec/packaging questions need this-turn product evidence.

    改判点：compile.py 的 product_unique_fact 编译（不足→PRODUCT_UNCOVERED_ANSWER
    替换答案、已接地→无检索也判 answered）。
    """
    value = str(text or '')
    if _STORE_POLICY_CUE.search(value) and not _PRODUCT_UNIQUE.search(value):
        return False
    return bool(_PRODUCT_UNIQUE.search(value))


def looks_like_service_request(text):
    """Performative service act, not a question about whether a service exists.

    改判点：looks_like_catalog_fact_question 的排除项（服务请求不走目录模板
    收口）；终答 request_kind=request_service 的编译语义与其同源。
    """
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
    """User asserts published sources cannot be reconciled. Asking how two topics differ is not this.

    改判点：session.answer_node——命中且 request_kind 非 exception 族时强制
    重编为 request_handoff（开人工单），覆盖模型的 inquire_fact 声明。
    """
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
    Strong intent: no policy citation is required to compile it into action.

    改判点：session.answer_node——request_service 轮命中即强制置位
    handoff_requested 并开单（覆盖模型声明）。
    """
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


# ── A（续）. 标签矫正与选品绑定：声明 × 回执的确定性编译，永久保留 ──────────

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
    if context.get('shopping_request') is not None or context.get('recommendations'):
        # 本轮已有选品检索回执：散文终答按零选品 salvage 会把 Pass@1 打分面清空
        # （终答文本列了 SKU 而结构化 selected_sku_keys 为空）。放行给修复轮——
        # 修复轮带 json_schema strict 绑定，能拿到带选品的合法终答。
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
    """A single observed SKU is the spec the user asked about; attach it.

    内容寻址版（2026-10-05）：模型声明 grounding 不可靠时（强制收口轮常标错），
    只要答案正文实际点名了唯一观察 SKU 的商品名，就按确定性证据绑定——
    陈述了该商品的价格/库存却交空选品，是把打分面丢掉而不是诚实留空。
    """
    if getattr(final, 'selected_sku_keys', None):
        return False
    keys = [key for key in (products or {}) if key]
    if len(keys) != 1:
        return False
    if getattr(final, 'grounding', None) != 'user_facts':
        card = (products or {}).get(keys[0]) or {}
        name = str(card.get('productName') or '').strip()
        answer = str(getattr(final, 'answer', '') or '')
        if not name or name.casefold() not in answer.casefold():
            return False
        final.grounding = 'user_facts'
        context['grounding_compiled_from_observation'] = True
    final.selected_sku_keys = keys
    context['sku_selected_from_sole_observation'] = True
    return True


def bind_named_observed_skus(final, products, context):
    """内容寻址选品绑定（sole-bind 的多选泛化，2026-10-05）。

    终答正文点名了哪些本轮观察到的商品（商品名折叠子串命中），就把哪些
    绑进 selected_sku_keys——「列了就要选」是打分面完整性不变量：强制收口
    轮的模型常叙述商品却漏填结构化选品（holdout-4 范畴词形状根因）。
    只绑定本轮回执内商品、按回执推荐序、上限 8；诚实空集答案不点名商品
    则不触发。与 answer_guards 同哲学：声明（正文）×证据（回执）确定性编译。
    """
    if getattr(final, 'selected_sku_keys', None):
        return False
    answer = str(getattr(final, 'answer', '') or '')
    if not answer:
        return False
    from smartlect.catalog_gate import _fold
    folded = _fold(answer)
    hits = []
    for key, card in (products or {}).items():
        if not isinstance(card, dict) or not key:
            continue
        name = str(card.get('productName') or '').strip()
        if name and _fold(name) in folded:
            hits.append(key)
    if not hits:
        return False
    hits.sort(key=lambda k: ((products[k].get('rank') or products[k].get('position') or 9999), k))
    final.selected_sku_keys = hits[:8]
    context['sku_selected_from_named_observation'] = True
    if getattr(final, 'grounding', None) != 'user_facts':
        final.grounding = 'user_facts'
        context['grounding_compiled_from_observation'] = True
    return True


_CATALOG_FACT = re.compile(r'价格|多少钱|库存|有货|售价|现价|规格')


def looks_like_catalog_fact_question(text):
    """Spec / price / stock questions can close from Java receipts without a second JSON.

    改判点：compile.template_observed_catalog_result——命中即由控制器按目录
    模板直接收口（跳过模型终答），session 的 tool_node/answer_node 两处消费。
    """
    value = str(text or '')
    if looks_like_service_request(value):
        return False
    if re.search(r'转人工|转交人工|找人工', value):
        return False
    if _STORE_POLICY_CUE.search(value) and not _PRODUCT_UNIQUE.search(value):
        return False
    return looks_like_product_unique_fact(value) or bool(_CATALOG_FACT.search(value))
