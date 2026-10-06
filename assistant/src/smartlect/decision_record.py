import time
"""Append-only audit snapshots. Never changes answer_status, tickets, or grants."""
from smartlect.agents.shopping.policy import (MODEL_CALL_LIMIT, TOOL_CALL_LIMIT,
                                              RETRIEVAL_CALL_LIMIT, ANSWER_REPAIR_LIMIT)

SHOPPING_MODEL_LIMIT = MODEL_CALL_LIMIT
SHOPPING_TOOL_LIMIT = TOOL_CALL_LIMIT
SHOPPING_RETRIEVAL_LIMIT = RETRIEVAL_CALL_LIMIT
SHOPPING_REPAIR_LIMIT = ANSWER_REPAIR_LIMIT


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
        },
        'cost_estimate_cny': round(sum(
            float(a.get('cost_estimate_cny') or 0)
            for a in (context.get('model_attempts') or [])
        ), 6),
    }


def shopping_checks(result, context, decision=None):
    decision = decision or shopping_decision(result, context)
    budget = decision['budget']
    grounding = result.get('grounding')
    status = result.get('answer_status')
    compiled = bool(result.get('request_kind') or result.get('compiled') or result.get('handoff_origin'))
    return [
        _check('compiled_decision_present', compiled, applicable=result.get('closeout') not in {
            'recovered_proposal', 'recovered_ticket'}),
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

    return result
