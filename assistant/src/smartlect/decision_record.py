"""Append-only audit snapshots. Never changes answer_status, tickets, or grants."""
from smartlect.agents.shopping.policy import (CLOSE_REASONS, MODEL_CALL_LIMIT, TOOL_CALL_LIMIT,
                                              RETRIEVAL_CALL_LIMIT, ANSWER_REPAIR_LIMIT,
                                              TURN_TOKEN_BUDGET)

SHOPPING_MODEL_LIMIT = MODEL_CALL_LIMIT
SHOPPING_TOOL_LIMIT = TOOL_CALL_LIMIT
SHOPPING_RETRIEVAL_LIMIT = RETRIEVAL_CALL_LIMIT
SHOPPING_REPAIR_LIMIT = ANSWER_REPAIR_LIMIT

_BUDGET_CODES = frozenset({'context_limit', 'model_call_or_time_limit', 'rerank_context_limit',
                           'retrieval_rewrite_limit', 'tool_call_limit', 'turn_token_budget'})


def _close_reason(result, context):
    """轮次终止原因归一（组件 5）：所有收口路径映射到 policy.CLOSE_REASONS 枚举。

    顺序敏感：显式覆盖 > 恢复路径 > 安全覆写 > 降级 fallback_reason > closeout 模板 > completed。
    显式覆盖但不在枚举内时原样保留——check 会失败并暴露未登记的终止原因，
    静默重映射成已知值等于把新路径的可见性藏起来。
    """
    explicit = context.get('close_reason')
    if explicit:
        return explicit
    closeout = result.get('closeout')
    if closeout in {'recovered_proposal', 'recovered_ticket', 'handoff_tool'}:
        return closeout if closeout != 'handoff_tool' else 'handoff'
    if result.get('safety_override'):
        return 'guard_violation'
    fallback = context.get('fallback_reason')
    if fallback is not None:
        # asyncio.timeout 抛内置 TimeoutError（无 code，str 为空串）：那是轮级 deadline。
        if not fallback or 'TimeoutError' in fallback:
            return 'deadline'
        if fallback == 'answer_contract_failed':
            return 'repair_exhausted'
        if fallback in _BUDGET_CODES:
            return 'budget_exceeded'
        if fallback.startswith('model_') or fallback.startswith('explicit_'):
            return 'provider_fault'
        return 'degraded'
        if fallback.startswith('model_') or fallback.startswith('explicit_'):
            return 'provider_fault'
        return 'degraded'
    if closeout == 'empty_evidence':
        return 'retrieval_empty'
    if closeout == 'provider_fault':
        return 'provider_fault'
    return 'completed'


def _elapsed_ms(attempts):
    """从 model_attempts 的首末 started_at 推导 run 级耗时（无则 None）。"""
    if not attempts:
        return None
    from datetime import datetime
    try:
        first = datetime.fromisoformat(attempts[0]['started_at'])
        last = datetime.fromisoformat(attempts[-1]['started_at'])
        return int((last - first).total_seconds() * 1000)
    except (KeyError, ValueError, TypeError):
        return None


def _ids(items, key):
    values = []
    for item in items or []:
        if isinstance(item, dict) and item.get(key):
            values.append(item[key])
    return values


def _ref(value, key):
    return value.get(key) if isinstance(value, dict) else None


def _dispatch_summary(result, context):
    """派发审计（组件 6）：任务数/未核验数来自 run context 的 dispatch_summary，
    token 与成本从 model_attempts 中 prompt_version 以 sub- 开头的子智能体
    调用聚合——「派发是否值得」可用消融数据回答，而不是靠感觉。"""
    summary = context.get('dispatch_summary')
    if not isinstance(summary, dict):
        return None
    sub_attempts = [a for a in (context.get('model_attempts') or [])
                    if str(a.get('prompt_version') or '').startswith('sub-')]
    usage = [a.get('usage') or {} for a in sub_attempts]
    return {
        'task_count': summary.get('task_count'),
        'unverified_count': summary.get('unverified_count'),
        'model_attempts': len(sub_attempts),
        'total_tokens': sum(int(u.get('total_tokens') or 0) for u in usage),
        'cost_estimate_cny': round(sum(
            float(a.get('cost_estimate_cny') or 0) for a in sub_attempts), 6),
    }


def _check(name, passed, *, applicable=True):
    if not applicable:
        return {'id': name, 'status': 'not_applicable'}
    return {'id': name, 'status': 'passed' if passed else 'failed'}


def shopping_decision(result, context):
    compiled = result.get('compiled') if isinstance(result.get('compiled'), dict) else {}
    proposal = result.get('proposal') if isinstance(result.get('proposal'), dict) else None
    ticket = result.get('ticket') if isinstance(result.get('ticket'), dict) else None
    return {
        'plane': 'shopping',
        'prompt_version': context.get('prompt_version'),
        'schema_version': context.get('schema_version'),
        'skill_versions': dict(context.get('skill_versions') or result.get('skill_versions') or {}),
        'model_mode': result.get('model_mode'),
        'request_kind': result.get('request_kind'),
        'handoff_requested': bool(result.get('handoff_requested')),
        'grounding': result.get('grounding'),
        'evidence_kind': result.get('evidence_kind'),
        'compiled_answer_status': compiled.get('answer_status'),
        'compiled_open_ticket': compiled.get('open_ticket'),
        'answer_status': result.get('answer_status'),
        'handoff_origin': result.get('handoff_origin'),
        'safety_override': result.get('safety_override'),
        'closeout': result.get('closeout'),
        'close_reason': _close_reason(result, context),
        'dispatch': _dispatch_summary(result, context),
        'cache_read_ratio': _cache_read_ratio(context),
        'final_output_channel': context.get('final_output_channel'),
        'accepted_tools': list(context.get('accepted_tools') or []),
        'dispatch_enabled': bool(context.get('dispatch_enabled')),
        'elapsed_ms': _elapsed_ms(context.get('model_attempts')),
        'citation_chunk_ids': _ids(result.get('citations'), 'chunk_id'),
        'proposal_id': _ref(proposal, 'proposal_id'),
        'ticket_id': _ref(ticket, 'ticket_id'),
        'budget': {
            'model_attempts_used': int(context.get('model_calls') or 0),
            'model_attempts_limit': SHOPPING_MODEL_LIMIT,
            'tool_calls_used': int(context.get('tool_calls') or 0),
            'tool_calls_limit': SHOPPING_TOOL_LIMIT,
            'retrieval_calls_used': int(context.get('retrieval_calls') or 0),
            'retrieval_calls_limit': SHOPPING_RETRIEVAL_LIMIT,
            'answer_repairs_used': int(context.get('answer_repairs') or 0),
            'answer_repairs_limit': SHOPPING_REPAIR_LIMIT,
            'input_tokens': _token_sum(context, 'input_tokens'),
            'cached_input_tokens': _token_sum(context, 'cached_input_tokens'),
            'turn_tokens_used': _token_sum(context, 'total_tokens'),
            'turn_token_budget': TURN_TOKEN_BUDGET,
            'turn_budget_tier': context.get('turn_budget_tier'),
        },
        'cost_estimate_cny': round(sum(
            float(a.get('cost_estimate_cny') or 0)
            for a in (context.get('model_attempts') or [])
        ), 6),
    }


def _token_sum(context, key):
    """按 attempt 聚合 usage 字段；上游不报的 attempt 不计入（未知不当 0）。"""
    return sum(int(((a.get('usage') or {}).get(key)) or 0)
               for a in (context.get('model_attempts') or []))


def _cache_read_ratio(context):
    cached = _token_sum(context, 'cached_input_tokens')
    total = _token_sum(context, 'input_tokens')
    # 无输入时返回 None 而不是 0——未知不当 0（上游不报 cached 时同样为 None 语义）。
    if total and cached:
        return round(cached / total, 4)
    return None


def shopping_checks(result, context, decision=None):
    decision = decision or shopping_decision(result, context)
    budget = decision['budget']
    grounding = result.get('grounding')
    status = result.get('answer_status')
    compiled = bool(result.get('request_kind') or result.get('compiled') or result.get('handoff_origin'))
    return [
        _check('compiled_decision_present', compiled, applicable=result.get('closeout') not in {
            'recovered_proposal', 'recovered_ticket'}),
        _check('close_reason_known', decision['close_reason'] in CLOSE_REASONS),
        _check('policy_grounding_has_this_turn_citation',
               bool(decision['citation_chunk_ids']) or bool(context.get('legal_empty_visible')),
               applicable=grounding == 'store_policy' and status == 'answered'),
        _check('no_business_claim_has_no_citations',
               not decision['citation_chunk_ids'], applicable=grounding == 'no_business_claim'),
        _check('proposal_is_not_execution',
               status == 'answered' and not decision['ticket_id'],
               applicable=bool(decision['proposal_id'])),
        _check('needs_human_has_ticket', bool(decision['ticket_id']), applicable=status == 'needs_human'),
        _check('budget_within_limits',
               budget['model_attempts_used'] <= budget['model_attempts_limit']
               and budget['tool_calls_used'] <= budget['tool_calls_limit']
               and budget['retrieval_calls_used'] <= budget['retrieval_calls_limit']
               and budget['answer_repairs_used'] <= budget['answer_repairs_limit']),
    ]


def attach_shopping_audit(result, context):
    """Add audit/audit_checks. Leaves answer_status, ticket, proposal, and citations untouched."""
    audit = shopping_decision(result, context)
    result['audit'] = audit
    result['audit_checks'] = shopping_checks(result, context, audit)
    result['decision'] = audit
    result['checks'] = result['audit_checks']
    return result
