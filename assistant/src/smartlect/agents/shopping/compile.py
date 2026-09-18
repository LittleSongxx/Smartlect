"""Deterministic closeouts: decision compilation, fallback text, template answers."""
import json

from smartlect.knowledge import misses_utterance_constraints
from smartlect.shopping_mission import normalize_mission
from .policy import (EMPTY_EVIDENCE_ANSWER, EXCEPTION_KINDS, PRODUCT_UNCOVERED_ANSWER,
                     PROVIDER_FAULT_ANSWER, PROPOSAL_CONFIRMATION, REQUEST_KINDS)
from .guardrails import (_STORE_POLICY_CUE, looks_like_catalog_fact_question,
                         looks_like_product_unique_fact)

def store_side_denials(denied):
    """Ticket-grade ACL denials only: store-side material a human can legitimately
    verify. Another user's personal data (ACTOR) or login-gated USER docs are privacy
    or self-service refusals — a human must not proxy-read them either, so they do
    not compile a ticket (v14 sup-d-55: the retrieval gate surfaced user_b's note and
    the acl_denied auto-ticket broke an otherwise honest refusal)."""
    return [row for row in denied or [] if row.get('acl') == 'MERCHANT']


def classify_evidence(context):
    """Map this-turn retrieval to supported | none | conflicting | quarantined | acl_denied | unobserved."""
    quarantined = bool(context.get('quarantined'))
    status = context.get('knowledge_status')
    citations = context.get('citations') or []
    if isinstance(citations, dict):
        citations = list(citations.values())
    visible = [item for item in citations if not (isinstance(item, dict) and item.get('carries_untrusted_instructions'))]
    retrieved = bool(context.get('retrieval_calls')) or status is not None
    if quarantined:
        return 'quarantined'
    if status == 'conflicting':
        return 'conflicting'
    if context.get('acl_denied'):
        return 'acl_denied'
    if visible:
        return 'supported'
    if retrieved:
        return 'none'
    return 'unobserved'


def compile_decision(request_kind, evidence, *, proposal=None, quarantined=False, handoff_requested=False,
                     product_unique_fact=False, product_grounded=False):
    """Compile answer_status and whether to open a ticket. Shared by finish and fallback.

    Unique product facts cannot be compiled as answered from unobserved or store-only leftovers.
    A product-unique question that this turn already grounded on the offer is answered
    even without a knowledge search — unobserved here means no policy retrieval, not
    “no product fact”.
    """
    if request_kind not in REQUEST_KINDS:
        raise ValueError('invalid_request_kind')
    if proposal:
        return {'answer_status': 'answered', 'open_ticket': False}
    if quarantined or evidence in {'conflicting', 'quarantined', 'acl_denied'}:
        return {'answer_status': 'needs_human', 'open_ticket': True}
    if request_kind in EXCEPTION_KINDS or handoff_requested:
        return {'answer_status': 'needs_human', 'open_ticket': True}
    if product_unique_fact and not product_grounded:
        return {'answer_status': 'insufficient', 'open_ticket': False}
    if (product_unique_fact and product_grounded and request_kind == 'inquire_fact'
            and evidence == 'unobserved'):
        return {'answer_status': 'answered', 'open_ticket': False}
    if request_kind == 'request_service':
        if evidence == 'supported':
            return {'answer_status': 'answered', 'open_ticket': False}
        return {'answer_status': 'needs_human', 'open_ticket': True}
    if request_kind == 'inquire_fact' and evidence == 'unobserved':
        return {'answer_status': 'insufficient', 'open_ticket': False}
    if evidence == 'supported' or (request_kind == 'clarify' and evidence == 'unobserved'):
        return {'answer_status': 'answered', 'open_ticket': False}
    return {'answer_status': 'insufficient', 'open_ticket': False}


def empty_evidence_result(reason='empty_visible_evidence'):
    decision = compile_decision('inquire_fact', 'none')
    return {'answer': EMPTY_EVIDENCE_ANSWER, 'answer_status': decision['answer_status'],
            'proposal': None, 'citations': [], 'products': [], 'orders': [],
            'empty_visible_evidence': True, 'fallback_empty_reason': reason,
            'request_kind': 'inquire_fact', 'evidence_kind': 'none', 'compiled': decision,
            'closeout': 'empty_evidence'}


def controller_fallback_result(reason, *, citations, legal_empty=False, utterance=''):
    """Fault closeout: leftovers that miss the question are an empty set, not a paste."""
    visible = list(citations.values()) if isinstance(citations, dict) else list(citations or [])
    uncovered = bool(visible) and misses_utterance_constraints(visible, utterance)
    if legal_empty or not visible or uncovered:
        if reason == 'retrieval_rewrite_limit':
            empty_reason = reason
        elif uncovered:
            empty_reason = 'uncovered_visible_leftovers'
        elif legal_empty:
            empty_reason = 'legal_empty_visible'
        else:
            empty_reason = reason
        return empty_evidence_result(empty_reason)
    return {'answer': '本轮暂未完成回答，可重试或选择人工客服。',
            'answer_status': 'insufficient', 'proposal': None,
            'citations': [{**item, 'text': item['content']} for item in visible[:2]],
            'products': [], 'orders': []}


def close_degraded_turn(reason, *, citations, legal_empty=False, utterance='', orders=None,
                        proposal=None, handoff_result=None, acl_denied=False, proposal_note=None):
    """Provider/budget/timeout closeout. A completed business decision stays; a bare fault escalates.
    A saved proposal with a compiled intent note keeps the note — degradation never
    hides that the proposal departs from what the user asked for."""
    if handoff_result:
        return handoff_result
    if proposal:
        answer = '交易提案已保存，请核对后确认。模型当前未能继续回复。'
        if proposal_note:
            answer += '\n' + proposal_note
        return {'answer': answer, 'answer_status': 'answered', 'proposal': proposal,
                'citations': [], 'products': [], 'orders': orders or []}
    if acl_denied:
        decision = compile_decision('inquire_fact', 'acl_denied')
        return {'answer': '当前身份无权查看匹配本题的已发布资料，已转人工核实。',
                'answer_status': decision['answer_status'], 'proposal': None,
                'citations': [], 'products': [], 'orders': orders or [],
                'handoff_origin': 'compiled_decision',
                'request_kind': 'inquire_fact', 'evidence_kind': 'acl_denied', 'compiled': decision}
    visible = list(citations.values()) if isinstance(citations, dict) else list(citations or [])
    if reason == 'model_output_truncated':
        return controller_fallback_result(
            reason, citations=citations, legal_empty=legal_empty or not visible, utterance=utterance)
    if legal_empty or visible:
        return controller_fallback_result(
            reason, citations=citations, legal_empty=legal_empty, utterance=utterance)
    return {'answer': PROVIDER_FAULT_ANSWER, 'answer_status': 'needs_human',
            'proposal': None, 'citations': [], 'products': [], 'orders': orders or [],
            'handoff_origin': 'provider_fault', 'closeout': 'provider_fault'}


def attach_proposal_confirmation(answer, *, intent_note=None):
    """Keep this-turn explanation; append the confirmation the card still requires.
    A compiled intent note (quantity departed from what the user asked) is appended
    by the controller and cannot be omitted by the model."""
    text = (answer or '').strip()
    parts = [text] if text else []
    if intent_note and intent_note not in text:
        parts.append(intent_note)
    if PROPOSAL_CONFIRMATION not in text:
        parts.append(PROPOSAL_CONFIRMATION)
    return '\n'.join(parts) if parts else PROPOSAL_CONFIRMATION


def proposal_intent_note(proposal, mission):
    """ADR-0002 for the trade path: proposing fewer/more units than the user asked
    for is a legal partial fulfilment, but the departure is compiled into the
    visible answer — the model can never silently change what the user asked to
    buy. Only order proposals with an explicit multi-unit mission intent qualify."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get('parameters'), dict):
        return None
    wanted = (normalize_mission(mission) or {}).get('quantity') or 0
    if wanted <= 1:
        return None
    total = 0
    for item in proposal['parameters'].get('orderList') or []:
        try:
            total += int(item.get('buyCount') or 0)
        except (TypeError, ValueError):
            return None
    if not total or total == wanted:
        return None
    return (f'注意：用户要求 {wanted} 件，本提案共 {total} 件，差额未满足；'
            '请核对数量差异后再决定是否确认。')


def salvage_observed_fact_closeout(context, *, utterance='', orders=None, products=None):
    """Last-resort closeout after answer_contract_failed: keep the observed-fact draft.

    Do not open a ticket for a label/format miss when this turn already has tool
    facts. Policy-only drafts without retrieval are not salvaged.
    """
    if not context.get('fact_observed'):
        return None
    rejections = context.get('answer_rejections') or []
    if not rejections:
        return None
    candidate = (rejections[-1] or {}).get('candidate_output') or ''
    answer = None
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict) and str(payload.get('answer') or '').strip():
            answer = str(payload['answer']).strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        text = str(candidate).strip()
        if text and not text.lstrip().startswith('{'):
            answer = text
    if not answer:
        return None
    if _STORE_POLICY_CUE.search(answer) and not context.get('retrieval_calls'):
        return None
    product_unique = bool(
        context.get('focus_mode') == 'PRODUCT' and looks_like_product_unique_fact(utterance))
    product_grounded = bool(context.get('product_offer_observed') or context.get('fact_observed'))
    decision = compile_decision(
        'inquire_fact', 'unobserved',
        product_unique_fact=product_unique, product_grounded=product_grounded)
    cards = []
    if isinstance(products, dict) and len(products) == 1:
        cards = list(products.values())
    elif isinstance(products, list) and len(products) == 1:
        cards = list(products)
    return {
        'answer': answer[:4000],
        'answer_status': decision['answer_status'],
        'proposal': None,
        'citations': [],
        'products': cards,
        'orders': orders or [],
        'request_kind': 'inquire_fact',
        'handoff_requested': False,
        'grounding': 'user_facts',
        'evidence_kind': 'unobserved',
        'compiled': decision,
        'closeout': 'salvaged_observed_facts',
    }


def _money_cents(cents):
    if cents is None:
        return None
    yuan = cents / 100
    if yuan == int(yuan):
        return f'¥{int(yuan)}'
    return f'¥{yuan:.2f}'


def render_observed_catalog_answer(cards, offer=None):
    offer = offer or {}
    name = ((cards[0].get('productName') if cards else None)
            or offer.get('productName') or '这件商品')
    if not cards:
        return None
    if len(cards) == 1:
        item = cards[0]
        spec = item.get('specification') or '默认规格'
        price = _money_cents(item.get('price_cents'))
        stock = item.get('stock')
        price_text = f'现价 {price}' if price else '价格以结算为准'
        stock_text = f'库存 {stock}' if stock is not None else '库存已查询'
        return f'「{name}」当前可售规格是：{spec}。{price_text}，{stock_text}。'
    lines = [f'「{name}」当前可售规格如下：']
    for item in cards[:3]:
        spec = item.get('specification') or item.get('sku_key')
        price = _money_cents(item.get('price_cents')) or '价格以结算为准'
        stock = item.get('stock')
        stock_bit = f'，库存 {stock}' if stock is not None else ''
        lines.append(f'- {spec}，{price}{stock_bit}')
    if len(cards) > 3:
        lines.append(f'其余 {len(cards) - 3} 个规格可在详情页查看。')
    return '\n'.join(lines)


def template_observed_catalog_result(context, products, *, utterance=''):
    """Close spec/price/stock from this-turn SKU receipts. Policy and handoff stay on the table."""
    if not looks_like_catalog_fact_question(utterance):
        return None
    cards = [item for item in (products or {}).values() if isinstance(item, dict) and item.get('sku_key')]
    if not cards:
        return None
    if not context.get('fact_observed'):
        return None
    answer = render_observed_catalog_answer(cards, context.get('product_offer'))
    if not answer:
        return None
    product_unique = bool(
        context.get('focus_mode') == 'PRODUCT' and looks_like_product_unique_fact(utterance))
    decision = compile_decision(
        'inquire_fact', 'unobserved',
        product_unique_fact=product_unique, product_grounded=True)
    shown = cards[:3]
    return {
        'answer': answer[:4000],
        'answer_status': decision['answer_status'],
        'proposal': None,
        'citations': [],
        'products': shown,
        'orders': [],
        'request_kind': 'inquire_fact',
        'handoff_requested': False,
        'grounding': 'user_facts',
        'evidence_kind': 'unobserved',
        'compiled': decision,
        'closeout': 'observed_catalog_template',
    }
