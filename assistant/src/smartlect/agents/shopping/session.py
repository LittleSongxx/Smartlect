"""One bounded Shopping ReAct run, grounded answers and proposals without execution."""
import asyncio
import json
import re
import time
import uuid
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import Literal
from pydantic import ValidationError

from smartlect.answer_guards import unsupported_state_claims
from smartlect.business_skills import USER_SKILLS, catalog, render_loaded_skills, suggest_skills
from smartlect.commerce import CommerceError
from smartlect.db import canonical
from smartlect.provider import ProviderError
from smartlect.privacy import redact_text
from smartlect.memory import estimate_text_tokens
from smartlect.state import StateError
from smartlect.knowledge import misses_utterance_constraints
from smartlect.knowledge_scope import citation_covers_product
from smartlect.decision_record import attach_shopping_audit
from smartlect.catalog_gate import _fold
from smartlect.shopping_mission import (MAX_REQUIRED, _unique, explicit_from_request, extract_mission,
                                        looks_like_product_request,
                                        ground_tool_params, merge_mission, mission_retrieve_params,
                                        normalize_mission, requirement_slots, retrieve_matches_mission,
                                        selects_products, shopping_request, shopping_turn_changed)
from smartlect.session_focus import pin_focus_offer_args, pin_focus_retrieve_params
from smartlect.shopping_retrieve import ShoppingRetrieve
from smartlect.tools import Arguments, REGISTRY, ToolReceipt, invoke, schemas
from smartlect import prompts
from .policy import (BOOTSTRAP_TOOLS, EMPTY_EVIDENCE_ANSWER, EXCEPTION_KINDS, MODEL_CALL_LIMIT,
                     PRODUCT_UNCOVERED_ANSWER, PROMPT_VERSION, PROPOSAL_CONFIRMATION,
                     PROVIDER_FAULT_ANSWER, REQUEST_KINDS, SCHEMA_VERSION, SEMANTIC_RERANK_PROMPT,
                     STATE_SELF_ANSWER_TOOLS, SYSTEM_POLICY_BODY, TOOL_CALL_LIMIT)
from .profiles import SHOPPING_MAIN, render_profile
from .clarify_gate import clarify_hint, needs_clarification
from .contract import (BudgetExceeded, FinalAnswer, GuardViolation, extract_streamed_answer,
                       final_answer_response_format)
from .compile import (attach_proposal_confirmation, classify_evidence,
                      close_degraded_turn, compile_decision, controller_fallback_result,
                      empty_evidence_result, proposal_intent_note, render_observed_catalog_answer,
                      salvage_observed_fact_closeout, store_side_denials,
                      template_observed_catalog_result)
from .guardrails import (allow_retrieval_rewrite, answer_defers_ticket_to_user,
                         answer_offers_human_transfer, answer_states_human_necessity,
                         bind_named_observed_skus, bind_sole_observed_sku,
                         coerce_observed_fact_grounding,
                         keep_uncovered_leftovers, looks_like_catalog_fact_question,
                         looks_like_irreconcilable_sources, looks_like_product_unique_fact,
                         looks_like_service_request, no_business_claim_has_store_conclusion,
                         rejected_search_data, retrieval_budget_action,
                         salvage_unstructured_fact_answer,
                         store_policy_allows_empty_citations)
from .observations import (constraint_echo, knowledge_observation, order_observation, product_observation,
                           sku_items, sku_observation, sku_obeys_request)


def bounded_messages(messages, tool_schemas, question):
    """上下文裁剪：langchain-core trim_messages 按预算保留近期消息，系统提示永不被裁。

    框架原生策略 token_counter 之前 2026-09 由 ADR 0004 实测校准（12000→14400），
    迁移到 trim_messages 后沿用同一上限做 strategy=last 的硬界。"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.messages.utils import trim_messages as lc_trim_messages

    def to_lc(entry):
        role = entry.get('role')
        if role == 'system':
            return SystemMessage(content=entry.get('content') or '')
        if role == 'user':
            return HumanMessage(content=entry.get('content') or '')
        if role == 'tool':
            return ToolMessage(content=entry.get('content') or '', tool_call_id=entry.get('tool_call_id') or '')
        calls = []
        for c in entry.get('tool_calls') or []:
            function = c.get('function') or {}
            args = function.get('arguments', {})
            if isinstance(args, str):
                try:
                    import json
                    args = json.loads(args)
                except Exception:
                    args = {}
            calls.append({'id': c.get('id') or '', 'name': function.get('name') or '', 'args': args})
        return AIMessage(content=entry.get('content') or '', tool_calls=calls)

    def counter(entries):
        payload = [dict(m) for m in entries]
        return estimate_text_tokens(canonical({'messages': payload, 'tools': tool_schemas})) + 16 * len(payload)

    # 框架 trim 决定保留集合；返回值仍是原始 wire dict（逐字节不变，模型协议无需转换）。
    originals = list(messages)
    lc_pairs = [(to_lc(m), m) for m in originals]
    original_by_lc_id = {id(lc): original for lc, original in lc_pairs}

    def kept_counter(kept):
        return counter([original_by_lc_id[id(k)] for k in kept if id(k) in original_by_lc_id])

    trimmed = lc_trim_messages(
        [pair[0] for pair in lc_pairs],
        max_tokens=14400, token_counter=kept_counter,
        strategy='last', allow_partial=False, include_system=True, start_on='human')
    kept_ids = {id(original_by_lc_id[id(message)]) for message in trimmed if id(message) in original_by_lc_id}
    result = [original for lc, original in lc_pairs if id(original) in kept_ids]
    if not any(m['role'] == 'user' for m in result):
        raise BudgetExceeded('context_limit')
    # fail-closed：本轮窗口（最后一个用户消息到结尾）必须完整保留——
    # 框架 trim 会把超限消息静默丢弃，这里把「本轮自身放不下」翻译回原契约的 BudgetExceeded。
    matches = [i for i, m in enumerate(originals)
               if m['role'] == 'user' and (m.get('content') == question
                                           or str(m.get('content') or '').startswith(question))]
    if not matches:
        matches = [i for i, m in enumerate(originals) if m['role'] == 'user']
    if matches:
        turn_start = max(matches)
        if len(result) < len(originals) - turn_start:
            raise BudgetExceeded('context_limit')
    # ADR 0004 的双上限之一：字节硬界（token 估算之外的真实负载防线）。
    if len(canonical({'messages': result, 'tools': tool_schemas}).encode()) > 43200:
        raise BudgetExceeded('context_limit')
    return result, counter(trimmed)


async def run_shopping(*, actor, run, lease, store, commerce, knowledge, memory, provider, mode, config,
                       recommendations=None, attribution=None):
    conversation_id = run['conversation_id']
    context = dict(run.get('context') or {})
    context.setdefault('model_calls', 0)
    context.setdefault('tool_calls', 0)
    context.setdefault('model_attempts', [])
    context.setdefault('answer_repairs', min(1,len(context.get('answer_rejections',[]))))
    # Prompt/skill text resolves from the DB template store (hot-editable, versioned)
    # with the packaged code as the frozen fallback; the run records which version it used.
    policy_body, prompt_label = await asyncio.to_thread(
        prompts.resolve_system, getattr(store, 'connect', None), 'shopping', SYSTEM_POLICY_BODY, PROMPT_VERSION)
    context.update(prompt_version=prompt_label, schema_version=SCHEMA_VERSION, skill_versions={})
    skills = {name: await asyncio.to_thread(prompts.resolve_skill, getattr(store, 'connect', None), 'shopping', name)
              for name in USER_SKILLS}
    context['skill_versions'] = {name: skill['version'] for name, skill in skills.items()}
    skill_catalog = catalog(domain='shopping')
    evidence, citations, products, orders = [], {}, {}, []
    proposal = None
    handoff_result = None
    context.setdefault('retrieval_calls', 0)
    context.setdefault('acl_denied', [])
    context.setdefault('accepted_tools', [])
    started = time.monotonic()
    remaining = 90
    if run.get('deadline'):
        remaining = (datetime.fromisoformat(run['deadline'].replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds()
    timeout_at = started + max(0, min(85, remaining - 5))

    async def persist():
        await asyncio.to_thread(store.save_context, lease, context)

    async def emit(kind, data):
        await asyncio.to_thread(store.append_event, lease, kind, data)

    async def before_attempt():
        if await asyncio.to_thread(memory.handoff_state, actor, conversation_id):
            raise StateError('human_control_active')
        # The turn deadline still bounds the run; the call count is a configurable
        # backstop (default 6). Evaluation stacks raise it so bounded-ReAct burnout
        # reflects model behaviour, not the cap.
        if context['model_calls'] >= MODEL_CALL_LIMIT or time.monotonic() >= timeout_at:
            raise BudgetExceeded('model_call_or_time_limit')
        context['model_calls'] += 1
        await persist()  # A crash before the response cannot give this attempt back.

    async def trace(record):
        context['model_attempts'].append(record)
        await persist()

    async def embed_query(query):
        if not config.get('SMARTLECT_EMBEDDING_API_KEY') or mode != 'live':
            return {}
        result = await provider.embed([query], before_attempt=before_attempt, on_trace=trace,
                                      skill_versions=context['skill_versions'], cacheable=True)
        meta = result['metadata']
        return {'query_vector': result['embeddings'][0], 'embedding_model': meta['model_id'],
                'index_version': f"{meta['model_id']}:d{meta['dimensions']}:v1"}

    async def semantic_rerank(data):
        if len(canonical(data).encode()) > 10000:
            raise BudgetExceeded('rerank_context_limit')
        response = await provider.chat([{'role': 'system', 'content': SEMANTIC_RERANK_PROMPT},
                                       {'role': 'user', 'content': canonical(data)}],
            response_format={'type': 'json_object'}, before_attempt=before_attempt, on_trace=trace, max_attempts=1,
            prompt_version='recommendation-rerank-v1', schema_version='sku-permutation-v1',
            skill_versions=context['skill_versions'], max_tokens=800)
        return json.loads(response['message']['content'])

    retriever = ShoppingRetrieve(commerce)

    async def persist_mission(params, extra_explicit=None):
        previous = await asyncio.to_thread(memory.mission, actor, conversation_id)
        explicit = {**explicit_from_request(params), **(extra_explicit or {})}
        explicit.pop('required_terms', None)
        slots = requirement_slots(question)
        # 回退已按用户授权落地后，不再从问句把必含词重新加硬（见 answer_node 的
        # rollback_authorized 降级：任务状态携带 sticky 的 rollback_applied）。
        if slots and not previous.get('rollback_applied'):
            explicit['required_terms'] = slots
        mission = merge_mission(previous, extract_mission(question), explicit)
        return await asyncio.to_thread(memory.put_mission, actor, conversation_id, mission, lease=lease)

    def saved_payload(saved):
        diagnostics = saved.get('diagnostics') or {}
        payload = {
            'items': saved.get('items') or [],
            'diagnostics': {
                'empty_reason': diagnostics.get('empty_reason'),
                'popular_used': bool(diagnostics.get('popular_used')),
                'copurchase_used': bool(diagnostics.get('copurchase_used')),
            },
        }
        if diagnostics.get('empty_reason'):
            payload['empty_reason'] = diagnostics['empty_reason']
        # Which constraint eliminated what: an unexplained empty set forces the model
        # into blind parameter sweeps. Counts go to the model only on an empty result;
        # the applied-gate echo goes along every constrained retrieve so under-declared
        # qualifiers are visible where the selection decision is made.
        report = {}
        if not (saved.get('items') or []):
            report = {key: diagnostics[key] for key in ('eligible_skus', 'initial_filtered', 'final_filtered',
                                                        'recall_relaxed')
                      if diagnostics.get(key)}
        applied = constraint_echo(context.get('shopping_request'))
        if applied:
            report['applied_constraints'] = applied
        if report:
            payload['filter_report'] = report
        for key in ('comparison', 'comparison_complete', 'missing_targets'):
            if key in saved:
                payload[key] = saved[key]
        return payload

    def remember_retrieve(params, mission, saved):
        context['shopping_request'] = shopping_request(params, mission)
        if saved.get('empty_reason') or (saved.get('diagnostics') or {}).get('empty_reason'):
            context['empty_reason'] = saved.get('empty_reason') or saved['diagnostics']['empty_reason']
        context.setdefault('recommendations', []).append({k: saved[k] for k in (
            'recommendation_id', 'assignment_id', 'strategy_version', 'ranking_mode', 'algorithm_version') if k in saved})

    async def recommend(params):
        if attribution is None:
            raise ValueError('recommendation_service_unavailable')
        preferences = await asyncio.to_thread(memory.preferences, actor) if actor.subject_type == 'user' else []
        previous = await asyncio.to_thread(memory.mission, actor, conversation_id)
        params, ungrounded = ground_tool_params(params, question, previous)
        if ungrounded:
            context.setdefault('ungrounded_hard_slots_dropped', []).append(ungrounded)
        params = pin_focus_retrieve_params(params, context, question)
        mission = await persist_mission(params)
        if mission.get('comparison_required') and (mission.get('comparison_targets') or params.get('comparison_targets')
                                                    or params.get('sku_keys')):
            compare_params = dict(params)
            if not compare_params.get('comparison_targets') and not compare_params.get('sku_keys'):
                compare_params['comparison_targets'] = list(mission.get('comparison_targets') or [])
            return await compare(compare_params)
        # Tool-arg required_terms are a documented gate source (skill instruction + tool
        # schema); persist_mission keeps the stored mission extractor-owned regardless.
        result = await retriever.recommend(actor, params, mission=mission, preferences=preferences,
            product_scope=await asyncio.to_thread(attribution.product_scope, actor),
            semantic_rerank=semantic_rerank if mode == 'live' else None)
        saved = await asyncio.to_thread(attribution.save_recommendation, actor, result, conversation_id)
        remember_retrieve(params, mission, saved)
        return saved_payload(saved)

    async def search(params):
        if attribution is None:
            raise ValueError('recommendation_service_unavailable')
        previous = await asyncio.to_thread(memory.mission, actor, conversation_id)
        params, ungrounded = ground_tool_params(params, question, previous)
        if ungrounded:
            context.setdefault('ungrounded_hard_slots_dropped', []).append(ungrounded)
        params = pin_focus_retrieve_params(params, context, question)
        mission = await persist_mission(params)
        result = await retriever.search(
            actor, params,
            product_scope=await asyncio.to_thread(attribution.product_scope, actor))
        saved = await asyncio.to_thread(attribution.save_recommendation, actor, result, conversation_id)
        remember_retrieve(params, mission, saved)
        return saved_payload(saved)

    async def compare(params):
        if attribution is None:
            raise ValueError('comparison_service_unavailable')
        preferences = await asyncio.to_thread(memory.preferences, actor) if actor.subject_type == 'user' else []
        extra = {}
        if params.get('sku_keys') or params.get('comparison_targets'):
            extra['comparison_required'] = True
        if params.get('comparison_targets') is not None:
            extra['comparison_targets'] = list(params.get('comparison_targets') or [])
        previous = await asyncio.to_thread(memory.mission, actor, conversation_id)
        params, ungrounded = ground_tool_params(params, question, previous)
        if ungrounded:
            context.setdefault('ungrounded_hard_slots_dropped', []).append(ungrounded)
        params = pin_focus_retrieve_params(params, context, question)
        mission = await persist_mission(params, extra)
        result = await retriever.compare(actor, params, mission=mission, preferences=preferences,
            product_scope=await asyncio.to_thread(attribution.product_scope, actor),
            semantic_rerank=semantic_rerank if mode == 'live' else None)
        saved = await asyncio.to_thread(attribution.save_recommendation, actor, result, conversation_id)
        remember_retrieve(params, mission, saved)
        return saved_payload(saved)

    def allowed_tools():
        loaded = {name for skill in skills.values() for name in skill.get('tools') or ()}
        return set(BOOTSTRAP_TOOLS) | loaded

    async def call_tool(name, arguments, call_id=None):
        nonlocal proposal, orders, handoff_result
        if name == 'get_product_offer':
            arguments = pin_focus_offer_args(arguments, context)
        if await asyncio.to_thread(memory.handoff_state, actor, conversation_id):
            raise StateError('human_control_active')
        if context['tool_calls'] >= TOOL_CALL_LIMIT:
            raise BudgetExceeded('tool_call_limit')
        if name == 'search_knowledge':
            model_query = arguments.get('query', '') if isinstance(arguments, dict) else ''
            budget = retrieval_budget_action(context, question)
            reject = None
            if budget == 'raise_rewrite_limit':
                raise BudgetExceeded('retrieval_rewrite_limit')
            if budget == 'empty_observation':
                reject = 'exhausted'
            elif context['retrieval_calls'] >= 1 and not allow_retrieval_rewrite(
                    context, utterance=question, model_query=model_query):
                reject = 'rewrite'
            if reject:
                context['tool_calls'] += 1
                context.setdefault('accepted_tools', []).append(name)
                await persist()
                await emit('tool_started', {'name': name})
                data = rejected_search_data(model_query, exhausted=reject == 'exhausted')
                receipt = ToolReceipt(data=data, tool_succeeded=True,
                                      observed_at=datetime.now(timezone.utc).isoformat(),
                                      evidence_id=call_id or (
                                          ('rewrite-exhausted:' if reject == 'exhausted' else 'rewrite-rejected:')
                                          + run['agent_run_id']),
                                      command_status='command_accepted').model_dump()
                evidence.append(receipt['evidence_id'])
                context['knowledge_status'] = 'insufficient'
                await emit('tool_result', {'name': name, 'evidence_id': receipt['evidence_id'],
                                           'command_status': receipt['command_status']})
                return receipt
            context['retrieval_calls'] += 1
        context['tool_calls'] += 1
        context.setdefault('accepted_tools', []).append(name)
        await persist()
        await emit('tool_started', {'name': name})
        receipt = await invoke(name, arguments, actor=actor, commerce=commerce, store=store, lease=lease,
                               knowledge=knowledge, embed_query=embed_query if mode == 'live' else None,
                               memory=memory, allowed=allowed_tools(), call_id=call_id, recommend=recommend,
                               search=search, compare=compare,
                               product_scope=await asyncio.to_thread(attribution.product_scope, actor) if attribution is not None else None,
                               observed_citations=citations, user_utterance=question, focus=context,
                               provider=provider if mode == 'live' else None)
        evidence.append(receipt['evidence_id'])
        data = receipt['data']
        if name != 'load_skill':
            context['fact_observed'] = True
        if name == 'load_skill':
            skills[data['skill_id']] = data
            context['skill_versions'][data['skill_id']] = data['version']
        elif name == 'search_knowledge':
            citations.update({c['chunk_id']: c for c in data['citations']
                              if not c.get('carries_untrusted_instructions')})
            context['retrieval'] = data['retrieval']
            context['knowledge_status'] = data['answer_status']
            context['visible_citations'] = list(citations.values())
            context['quarantined'] = [c for c in data['citations'] if c.get('carries_untrusted_instructions')]
            if 'acl_denied' in data:
                context['acl_denied'] = store_side_denials(data.get('acl_denied'))
            context['legal_empty_visible'] = (
                not citations and data['answer_status'] != 'conflicting'
                and not context['quarantined'] and not context['acl_denied'])
        elif name in {'search_skus', 'recommend_skus', 'compare_skus'}:
            products.update({item['sku_key']: item for item in sku_items(data)})
            if isinstance(data, dict):
                route_errors = (data.get('diagnostics') or {}).get('route_errors') or {}
                relaxed_term = route_errors.get('required_term_relaxed')
                if relaxed_term:
                    # 检索层已判定该必含词不是商品属性词并放宽（诊断留痕）；会话级
                    # 发布门（sku_obeys_request）必须用同一口径，否则放宽的商品
                    # 会在终答发布时被旧词二次筛掉——选品面在最后一米丢失。
                    context['required_term_relaxed'] = relaxed_term
                    current = context.get('shopping_request') or {}
                    if relaxed_term in (current.get('required_terms') or []):
                        updated = dict(current)
                        updated['required_terms'] = [t for t in current['required_terms'] if t != relaxed_term]
                        context['shopping_request'] = updated
                if data.get('comparison'):
                    context['comparison'] = data['comparison']
                if 'comparison_complete' in data:
                    context['comparison_complete'] = data.get('comparison_complete')
                if data.get('missing_targets'):
                    context['comparison_missing_targets'] = data['missing_targets']
                if data.get('empty_reason'):
                    context['empty_reason'] = data['empty_reason']
        elif name == 'get_product_offer':
            context['product_offer_observed'] = True
            if isinstance(data, dict) and data.get('productId'):
                context['product_offer_product_id'] = str(data['productId'])
                context['product_offer'] = {
                    'productId': data.get('productId'),
                    'productName': data.get('productName'),
                }
        elif name == 'get_my_orders':
            orders = data
        elif name == 'get_order_status' and data:
            orders = [data]
        elif name.startswith('propose_'):
            proposal = data
            mission_state = await asyncio.to_thread(memory.mission, actor, conversation_id)
            context['proposal_intent_note'] = proposal_intent_note(proposal, mission_state)
        elif name == 'task_dispatch':
            # 子智能体分型路由结果透出：每个任务路由到了哪个 profile、执行状态如何。
            await emit('decision', {
                'fork': 'task_dispatch', 'reason': 'sub_agent_routing',
                'task_count': len(data.get('results') or []),
                'routing': [{'task': row.get('task'), 'profile': row.get('profile'),
                             'routing_reason': row.get('routing_reason'),
                             'status': row.get('status')}
                            for row in data.get('results') or []]})
        elif name == 'request_handoff':
            handoff_result = {'answer': data['answer'] + '\n已建立本地客服工单，等待人工接管。',
                'answer_status': 'needs_human', 'ticket': data['ticket'], 'handoff_origin': 'model_tool',
                'citations': [{**item, 'text': item['content']} for item in data['citations']],
                'products': [], 'orders': [], 'proposal': None,
                'request_kind': 'request_handoff', 'handoff_requested': True,
                'compiled': {'answer_status': 'needs_human', 'open_ticket': True},
                'closeout': 'handoff_tool'}
        await emit('tool_result', {'name': name, 'evidence_id': receipt['evidence_id'],
                                   'command_status': receipt['command_status']})
        return receipt

    async def finish(result, effective_mode):
        result.update(model_mode=effective_mode, skill_versions=context['skill_versions'],
                      tool_evidence_ids=evidence, model_calls=context['model_calls'], tool_calls=context['tool_calls'])
        if result.get('citations') and not await asyncio.to_thread(knowledge.validate_citations, actor, result['citations']):
            result.update(answer='引用的知识已撤回、失效或不可访问，请等待人工核实。',
                          answer_status='needs_human', citations=[])
            result['safety_override'] = 'citation_no_longer_visible'
        active = await asyncio.to_thread(memory.handoff_state, actor, conversation_id)
        if active and not (handoff_result and active['status'] == 'OPEN'
                and active['ticket_id'] == handoff_result['ticket']['ticket_id']
                and result.get('ticket', {}).get('ticket_id') == active['ticket_id']):
            raise StateError('human_control_active')
        if not result.get('ticket') and result['answer_status'] == 'needs_human':
            ticket = await asyncio.to_thread(memory.handoff, actor, conversation_id, 'knowledge_or_model_unresolved',
                                              evidence=result.get('citations', []), cancel_running=False, lease=lease)
            result['ticket'] = ticket
            result.setdefault('handoff_origin',
                              'controller_safety' if effective_mode == 'live' else 'controller_fallback')
        context['model_mode'] = effective_mode
        context['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        attach_shopping_audit(result, context)
        try:
            return await asyncio.to_thread(memory.finish_answer, lease, actor, result, context)
        except StateError as error:
            if error.code != 'citation_no_longer_visible':
                raise
            result.update(answer='引用资料已变更，已转人工核实。', answer_status='needs_human', citations=[], proposal=None)
            result['safety_override'] = 'citation_no_longer_visible'
            result['ticket'] = await asyncio.to_thread(memory.handoff, actor, conversation_id, 'citation_changed',
                                                       evidence=[], cancel_running=False, lease=lease)
            attach_shopping_audit(result, context)
            return await asyncio.to_thread(memory.finish_answer, lease, actor, result, context)

    memory_context = await asyncio.to_thread(memory.context, actor, conversation_id)
    if memory_context['handoff']:
        recovered = {'answer_status': 'needs_human', 'ticket': memory_context['handoff'],
                     'handoff_origin': 'recovered_existing_ticket', 'closeout': 'recovered_ticket'}
        attach_shopping_audit(recovered, context)
        return await asyncio.to_thread(store.finish_run, lease, state='CANCELLED', result=recovered)
    saved = await asyncio.to_thread(store.get_conversation, actor, conversation_id)
    recovered = next((p for p in saved['proposals'] if p['agent_run_id'] == run['agent_run_id'] and p['status'] == 'PROPOSED'), None)
    if recovered:
        return await finish({'answer': '已恢复保存的交易提案，请核对后确认。', 'answer_status': 'answered',
                             'citations': [], 'products': [], 'orders': [], 'proposal': recovered,
                             'closeout': 'recovered_proposal'}, mode)
    original = next((m for m in memory_context['messages'] if m['message_id'] == run['message_id']), None)
    if original is None:
        raise StateError('message_forgotten_or_expired')
    recent = [{'role': m['role'], 'content': m['content']} for m in memory_context['messages']
              if m['role'] in {'user', 'assistant'} and m['sequence'] <= original['sequence']]
    question = next((m['content'] for m in reversed(recent) if m['role'] == 'user'), '')
    # 系统提示 = 声明式角色契约块 + 冻结的策略叙事文本：契约是数据（可测试、可审计），
    # 叙事保留 v27 以来的全部语义，版本随契约块引入升到 v28。
    suggestions = suggest_skills(question, entries=skill_catalog)
    suggestion_line = (('\n本轮Skill预告（按意图关键词匹配，优先按其流程处理）：' + '、'.join(suggestions))
                       if suggestions else '')
    # 低置信度澄清闸（确定性判据，见 clarify_gate.py）：命中只注入引导 + 记 decision 事件，
    # 不强制改判、不新增往返；终答编译仍由 answer_node 守卫链决定。
    clarify, clarify_reason, clarify_missing = needs_clarification(question, memory_context.get('mission'))
    clarify_line = ('\n' + clarify_hint(clarify_reason, clarify_missing)) if clarify else ''
    # 可解释路由事件：本轮的 Skill 预告与澄清闸判定先落一条 decision（SSE 透出，
    # 管理端事件流可回放）——「为什么这轮这么走」在事件表里可查，不只在审计快照里。
    setup_decision = {'fork': 'turn_setup', 'reason': 'intent_keywords',
                      'skill_suggestions': suggestions}
    if clarify:
        setup_decision['clarify_gate'] = clarify_reason
        setup_decision['fork'] = 'clarify_gate'
    await emit('decision', setup_decision)
    system = (render_profile(SHOPPING_MAIN) + '\n' + policy_body +
              '\n可加载Skills目录：' + canonical(skill_catalog) + suggestion_line + clarify_line +
              '\n已加载业务流程：' + render_loaded_skills(skills) +
              '\n只读上下文：' + canonical({'preferences': memory_context['preferences'], 'summary': memory_context['summary'],
                                         'mission': memory_context.get('mission')}) +
              '\n主体类别：' + actor.subject_type)
    focus_parts = []
    if context.get('focus_product_id'):
        focus_parts.append('商品编号 ' + str(context['focus_product_id']))
    if context.get('focus_sku_key'):
        focus_parts.append('规格编号 ' + str(context['focus_sku_key']))
    focus_mode = context.get('focus_mode') or ('PRODUCT' if focus_parts else 'GLOBAL')
    if focus_parts:
        focus_fact = ('本轮焦点=' + focus_mode + '：' + '，'.join(focus_parts)
                      + '。当前是「问这件」：search_knowledge 已由服务端限定本商品知识+店规；'
                      + '独特事实须引用本商品切片或先 get_product_offer。'
                      + '用户未明确离开这件时，不要主动查全店选品或无关订单；'
                      + 'recommend_skus / search_skus 由服务端钉死本商品。'
                      + '规格、价格、库存以工具回执为准，系统可直接据此收口。'
                      + '这件怎么退、运费等店规仍须 search_knowledge。'
                      + '若用户问的是其他商品、全店选品或无关订单，用一句礼貌说明：'
                      + '当前只能回答这件商品和适用店规；想问其他请点输入框上的「改问全店」。'
                      + '不要说总机，不要责备用户。')
        system += '\n' + focus_fact
    elif focus_mode in {'GLOBAL', 'GUIDE'}:
        system += '\n本轮焦点=' + focus_mode + '：知识检索仅店规；选品走 recommend_skus / compare_skus。'

    # 真 token 流式：模型终答 JSON 一边生成一边抽取 answer 字段，节流后以
    # message_delta 增量事件落库（SSE 透出）。权威全文仍由 finish_answer 的
    # replace 事件收口；断线重连按 sequence 重放已持久化增量，天然幂等。
    streamed = {'buffer': '', 'emitted_chars': 0, 'last_emit': 0.0}

    async def on_token(text):
        if not text:
            return
        streamed['buffer'] += text
        buffer = streamed['buffer']
        # 只预览契约 JSON 的 answer 字段：普通文本轮（含被拒格式）不流式，
        # 避免把后来会被守卫丢弃的内容推给用户。
        if not buffer.lstrip().startswith('{'):
            return
        partial = extract_streamed_answer(buffer)
        if not partial:
            return
        new_chars = len(partial) - streamed['emitted_chars']
        if new_chars <= 0:
            return
        now = time.monotonic()
        # 双闸节流：新内容 ≥120 字符立即发；否则距上次 ≥0.4s 发——
        # 控制事件表写入频率（≤~2.5 次/秒），首 token 后 ~0.4s 用户即可见进度。
        if new_chars >= 120 or now - streamed['last_emit'] >= 0.4:
            await emit('message_delta', {'text': partial[streamed['emitted_chars']:]})
            streamed['emitted_chars'] = len(partial)
            streamed['last_emit'] = now

    async def model_node(state):
        streamed.update(buffer='', emitted_chars=0, last_emit=0.0)
        # 每轮模型调用开始先发一条 replace 空事件：重置前端的增量游标，
        # 上一轮被丢弃的预览（如修复轮前的无效输出）不会拼接进本轮。
        await emit('message_delta', {'text': '', 'replace': True})
        repairing = bool(state.get('repair'))
        if repairing and state.get('repair_no_tools'):
            # 修复阶段 2：只暴露 finish_answer 并定向强制调用。函数调用参数 schema 由
            # provider 原生强制（实验确认 json_schema 在带 tools 时被静默忽略），
            # 结构化终答因此有确定性出口；解析走既有 finish_answer 分支。
            from .contract import final_answer_schema
            finish = final_answer_schema()
            messages, context['context_upper_bound_tokens'] = bounded_messages(state['messages'], [finish], question)
            response = await provider.chat(messages, before_attempt=before_attempt, on_trace=trace, max_tokens=1600,
                                           prompt_version=context['prompt_version'], skill_versions=context['skill_versions'],
                                           schema_version=SCHEMA_VERSION, stream=True, on_delta=on_token,
                                           tools=[finish],
                                           tool_choice={'type': 'function', 'function': {'name': 'finish_answer'}})
            return {'messages': messages + [response['message']], 'response': response['message']}
        elif repairing:
            # 修复阶段 1：放开只读检索工具。修复提示词写着「可用只读工具补充本题事实」，
            # 此前却把工具剥光，模型只能把「没检索的追问」格式化。通用机制：先给一次
            # 补检索的机会；一旦检索过（或再次失败）由 tool_node/answer_node 置
            # repair_no_tools 进入阶段 2 的 schema 强制收口。
            available = [schema for schema in schemas(actor, allowed_tools())
                         if schema['function']['name'] in
                         {'search_knowledge', 'recommend_skus', 'search_skus', 'compare_skus', 'get_product_offer'}]
        else:
            available = schemas(actor, allowed_tools())
        messages, context['context_upper_bound_tokens'] = bounded_messages(state['messages'], available, question)
        kwargs = {'tools': available or None, 'tool_choice': 'auto' if available else None}
        response = await provider.chat(messages, before_attempt=before_attempt, on_trace=trace, max_tokens=1600,
                                       prompt_version=context['prompt_version'], skill_versions=context['skill_versions'],
                                       schema_version=SCHEMA_VERSION, stream=True, on_delta=on_token, **kwargs)
        return {'messages': messages + [response['message']], 'response': response['message']}

    rejected_calls = {}

    async def tool_node(state):
        messages = list(state['messages'])
        for call in state['response'].get('tool_calls') or []:
            try:
                arguments = json.loads(call['function']['arguments'])
                # A model that cannot decode a rejection re-sends identical arguments
                # until the call budget dies (v11 sup-d-50: remember_preference x4).
                # The second identical attempt is intercepted instead of executed.
                key = (call['function']['name'], canonical(arguments))
                if key in rejected_calls:
                    failure = {'error': 'identical_rejected_call', 'previous': rejected_calls[key],
                               'instruction': '同样的参数已被拒绝；请修改参数，或放弃该动作直接继续回答。'}
                    await emit('tool_result', {'name': call['function']['name'],
                                               'rejected_before_result': True, **failure})
                    messages.append({'role': 'tool', 'tool_call_id': call['id'],
                                     'content': canonical(failure)})
                    continue
                receipt = await call_tool(call['function']['name'], arguments, uuid.uuid4().hex)
                data = receipt['data']
                if call['function']['name'] == 'load_skill':
                    observation = {k: data[k] for k in ('skill_id', 'instructions', 'output_contract', 'stop_conditions')}
                elif call['function']['name'] == 'search_knowledge':
                    observation = knowledge_observation(data)
                    context['model_citation_chunk_ids'] = list(citations)
                    context['knowledge_status'] = data['answer_status']
                    if observation['evidence_status'] == 'none':
                        context['knowledge_status'] = 'insufficient'
                    context['visible_citations'] = list(citations.values())
                    context['quarantined'] = observation.get('quarantined') or []
                    if 'acl_denied' in data:
                        context['acl_denied'] = store_side_denials(data.get('acl_denied'))
                    context['legal_empty_visible'] = (
                        observation['evidence_status'] == 'none' and not context['quarantined']
                        and not context.get('acl_denied')
                        and data.get('answer_status') != 'conflicting'
                        and not keep_uncovered_leftovers(data) and not citations)
                elif call['function']['name'] == 'get_product_offer':
                    observation = product_observation(data)
                elif call['function']['name'] == 'task_dispatch':
                    # 台账里的 receipt 保留全量 results；模型观察只投影组装层产物，
                    # 避免多任务结论把 6500 字节观察上限撑爆变成 result_too_large。
                    observation = {key: data[key] for key in (
                        'summary', 'all_succeeded', 'succeeded_count', 'merge_instruction')
                        if key in data}
                    if data.get('incomplete_tasks'):
                        observation['incomplete_tasks'] = data['incomplete_tasks']
                elif call['function']['name'] in {'get_refund_status', 'get_payment_status', 'get_order_status'}:
                    observation = order_observation(call['function']['name'], receipt)
                elif call['function']['name'] in {'search_skus', 'recommend_skus', 'compare_skus'}:
                    observation = sku_observation(data)
                else:
                    observation = receipt
                encoded = canonical(observation)
                if len(encoded.encode()) > 6500:
                    # Keep a valid error object, never half JSON or a misleading truncated quote.
                    encoded = canonical({'error': 'result_too_large', 'instruction': '缩小查询条件或limit再查询'})
            except (BudgetExceeded, StateError):
                raise
            except Exception as error:
                failure = {'error': type(error).__name__, 'code': getattr(error, 'code', 'tool_rejected')}
                if isinstance(error, ValidationError):
                    failure['fields'] = error.errors(include_input=False, include_context=False)
                    failure['input_types'] = {str(item['loc'][0]): type(arguments.get(item['loc'][0])).__name__
                                              for item in failure['fields'] if item['loc'] and isinstance(arguments, dict)}
                else:
                    failure['reason'] = str(error)[:160]
                rejected_calls[(call['function']['name'], canonical(arguments))] = failure
                encoded = canonical(failure)
                await emit('tool_result', {'name': call['function']['name'], 'rejected_before_result': True, **failure})
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': encoded})
        if not proposal and not handoff_result:
            batch = {call['function']['name'] for call in (state['response'].get('tool_calls') or [])}
            if batch & {'search_skus', 'recommend_skus', 'compare_skus'}:
                templated = template_observed_catalog_result(context, products, utterance=question)
                if templated:
                    context['final_output_channel'] = 'observed_catalog_template'
                    await emit('decision', {'fork': 'catalog_template_closeout',
                                            'reason': 'catalog_facts_observed',
                                            'detail': '检索类工具已有结果，控制器按目录模板直接收口'})
                    return {'messages': messages, 'result': templated,
                            **({'repair_no_tools': True} if state.get('repair') else {})}
        # 修复阶段 1 检索过一次就进入阶段 2：下一轮模型调用无工具 + json_schema 强制。
        return {'messages': messages,
                **({'repair_no_tools': True} if state.get('repair') else {})}

    def repair_round_messages(state, reason):
        feedback = [{'role':'tool','tool_call_id':call['id'],
            'content':canonical({'error':reason[:500],'batch_executed':False})}
            for call in state['response'].get('tool_calls') or []]
        hint = (
                 '请仅修复输出格式或引用。校验失败：' + reason[:500] +
                 '。用结构化 JSON 提交 answer/request_kind/handoff_requested/grounding/citation_chunk_ids/selected_sku_keys/requires_clarification，不要填写answer_status；若系统只给出 finish_answer 工具则通过它提交同构参数。允许引用chunk_id：' +
                 canonical(list(citations)) + '；允许sku_key：' + canonical(list(products)) +
                 '。按request_kind声明诉求，系统编译是否建单。也可单独request_handoff。'
                 '可用只读工具补充本题事实，也可说明未知并继续可完成的部分；历史对话不代替本轮交易事实。'
                 '合同修复仍只有这一次，总模型/工具预算不增加，不新增任何批准或执行交易。')
        if context.get('fact_observed') and not citations:
            hint += ('本轮已有商品或订单工具回执：陈述规格、价格、库存或本人交易事实时 grounding 必须是 user_facts，'
                     '不要用 no_business_claim 躲避引用。')
        return state['messages'] + feedback + [{'role': 'system', 'content': hint}]

    def guard_repair_fits(state, reason):
        # A repair round is one more model call through bounded_messages. When the
        # window cannot host it (r-049: seven observation rounds had already filled
        # the ceiling), model_node would raise context_limit and downgrade a run
        # that already holds a complete answer, so the guard releases instead.
        try:
            bounded_messages(repair_round_messages(state, reason),
                             schemas(actor, allowed_tools()), question)
        except BudgetExceeded:
            return False
        return True

    async def answer_node(state):
        calls=state['response'].get('tool_calls') or []
        raw=state['response'].get('content') or ''
        names = [call['function']['name'] for call in calls]
        if 'request_handoff' not in names and not proposal:
            templated = template_observed_catalog_result(context, products, utterance=question)
            if templated:
                context['final_output_channel'] = 'observed_catalog_template'
                await emit('decision', {'fork': 'catalog_template_closeout',
                                        'reason': 'catalog_facts_observed',
                                        'detail': '答前已有目录事实，控制器按目录模板收口'})
                return {'result': templated}
        if not calls and not state.get('repair') and raw.strip() and not raw.lstrip().startswith('{'):
            # 确定性结构重述（通用机制，v15 的 finish_answer 工具等价物）：provider 在带
            # tools 时忽略 json_schema，散文通道因此敞开。散文不作为终答进入校验链，
            # 而是丢弃该散文轮、按「本轮是否已有证据」分流重做——无检索证据先给一轮
            # 只读工具（阶段1），已有证据直接 schema 强制收口（阶段2）。不消耗 answer_repairs。
            phase2 = bool(products or citations or context.get('retrieval_calls'))
            await emit('decision', {'fork': 'structure_restate',
                                    'reason': 'freeform_text_without_schema',
                                    'detail': ('已有本轮证据，schema 强制收口' if phase2
                                               else '尚无本轮证据，先开放只读检索再收口')})
            kept = list(state['messages'])
            if kept and kept[-1].get('role') == 'assistant' and not kept[-1].get('tool_calls'):
                kept = kept[:-1]  # 重做而非续写：散文轮不进入重述上下文，避免模型延续散文立场
            restate = [{'role': 'system',
                        'content': '上一次输出是不合契约的自由文本，已丢弃。请重新完成本轮任务：'
                                   '如仍缺事实先用工具检索；已有本轮工具回执时，终答必须基于回执收口'
                                   '（选品回执按推荐序填 selected_sku_keys，政策回执填 chunk_id 引用），'
                                   '不得以追问替代。准备好后按 FinalAnswer 契约提交结构化终答。'}]
            return {'repair': 1, 'repair_no_tools': phase2,
                    'messages': kept + restate}
        try:
            if calls:
                if len(calls)!=1 or calls[0]['function']['name'] not in {'finish_answer', 'request_handoff'}:
                    raise ValueError('terminal_tool_must_be_called_alone_after_observations')
                if calls[0]['function']['name'] == 'request_handoff':
                    await call_tool('request_handoff', json.loads(calls[0]['function']['arguments']), calls[0]['id'])
                    return {'result': handoff_result}
                raw=calls[0]['function']['arguments']
                context.setdefault('final_decision_call_ids',[]).append(calls[0]['id'])
                final = FinalAnswer.model_validate_json(raw)
                context['final_output_channel'] = (
                    'legacy_finish_answer_tool' if calls[0]['function']['name'] == 'finish_answer'
                    else 'structured_outputs')
            else:
                salvaged = salvage_unstructured_fact_answer(raw, context)
                if salvaged is not None:
                    final = salvaged
                    context['final_output_channel'] = 'salvaged_unstructured'
                    context['grounding_compiled_from_observation'] = True
                else:
                    final = FinalAnswer.model_validate_json(raw)
                    context['final_output_channel'] = 'structured_outputs'
            coerce_observed_fact_grounding(final, context)
            bind_sole_observed_sku(final, products, context)
            bind_named_observed_skus(final, products, context)
            if any(key not in citations for key in final.citation_chunk_ids) or any(key not in products for key in final.selected_sku_keys):
                raise ValueError('unsupported_reference')
            # The declared basis has to match what this turn actually observed. This replaces the
            # old evidence guard, which needed a greeting whitelist because it inferred intent
            # from the question text; the model now states its basis and the check is exact.
            context['declared_grounding'] = final.grounding
            if final.grounding == 'store_policy' and not final.citation_chunk_ids:
                visible_context = {**context, 'visible_citations': list(citations.values())}
                if not store_policy_allows_empty_citations(visible_context, question):
                    raise ValueError('store_policy_grounding_requires_this_turn_citation')
            if final.grounding == 'user_facts' and not context.get('fact_observed'):
                raise ValueError('user_facts_grounding_requires_this_turn_tool_observation')
            if (final.grounding == 'user_facts' and not context.get('retrieval_calls')
                    and STATE_SELF_ANSWER_TOOLS & set(context.get('accepted_tools') or [])):
                # The skill already forbids concluding store matters without retrieval;
                # this makes it mechanical for the state-self-answer shape.
                raise ValueError('state_answer_requires_policy_evidence: '
                                 '本轮以本人状态收口但全程未取政策证据；请先 search_knowledge 检索相关政策，'
                                 '再把本人状态与政策依据合并作答；政策确实无相关内容时按资料不足收口')
            if (not final.selected_sku_keys and context.get('empty_reason') == 'hard_constraint_unsatisfied'
                    and not context.get('rollback_repair_done')):
                mission_now = await asyncio.to_thread(memory.mission, actor, conversation_id)
                if mission_now.get('rollback_authorized'):
                    # The user already granted availability-over-qualifiers ("按可售来");
                    # bouncing the substitution question back defers a decision they made.
                    # Demoted to a deterministic controller fix (no model repair round):
                    # move the unsatisfied required terms out of the hard gate into the
                    # query and re-retrieve once. Sellable results close via the catalog
                    # template; a genuinely unbuyable category still closes as an honest
                    # empty set on the original insufficient path.
                    context['rollback_repair_done'] = True
                    request = dict(context.get('shopping_request') or {})
                    blockers = [str(term) for term in (request.get('required_terms') or []) if term]
                    if blockers:
                        # 必含词由任务抽取持有并在每次检索前重建，因此放宽必须落在任务状态上：
                        # 按用户授权清空硬约束词（标记 rollback_applied 留审计），词并入 query 软匹配。
                        softened_mission = {**mission_now, 'required_terms': [], 'rollback_applied': True}
                        await asyncio.to_thread(memory.put_mission, actor, conversation_id,
                                                 normalize_mission(softened_mission), lease=lease)
                        softened = {**request,
                                    'query': ' '.join([str(request.get('query') or ''), *blockers]).strip(),
                                    'required_terms': []}
                        try:
                            await call_tool('recommend_skus', pin_focus_retrieve_params(softened, context, question))
                            templated = template_observed_catalog_result(context, products, utterance=question)
                            if templated:
                                context['final_output_channel'] = 'observed_catalog_template'
                                return {'result': templated}
                            cards = [item for item in products.values()
                                     if isinstance(item, dict) and item.get('sku_key')]
                            if cards:
                                # 放宽后有可售件但问句不是目录事实形态：仍由控制器按授权
                                # 直接出替代收口（披露"按可售来"），不把决定推回给用户。
                                shown = cards[:3]
                                decision_now = compile_decision('inquire_fact', 'unobserved',
                                                                product_unique_fact=bool(
                                                                    context.get('focus_mode') == 'PRODUCT'
                                                                    and looks_like_product_unique_fact(question)),
                                                                product_grounded=True)
                                context['final_output_channel'] = 'rollback_substitution_template'
                                return {'result': {
                                    'answer': ('已按您的「按可售来」授权放宽规格要求。当前可售：' + '\n'
                                              + render_observed_catalog_answer(shown, context.get('product_offer'))),
                                    'answer_status': decision_now['answer_status'], 'proposal': None,
                                    'citations': [], 'products': shown, 'orders': orders or [],
                                    'request_kind': 'inquire_fact', 'handoff_requested': False,
                                    'grounding': 'user_facts', 'evidence_kind': 'unobserved',
                                    'compiled': decision_now, 'closeout': 'rollback_substitution_template'}}
                        except (StateError, ValueError, CommerceError, TimeoutError) as error:
                            context['selection_refresh_error'] = getattr(error, 'code', None) or str(error)[:120]
            state_claims = unsupported_state_claims(final.answer, context.get('accepted_tools'))
            if state_claims:
                guard_reason = ('state_claim_without_receipt: '
                                '答案声明了用户订单/优惠券/账户的当前状态（' + '、'.join(state_claims[:3]) +
                                '），但本轮没有任何订单查询工具回执——这是编造的观测。'
                                '请删除这些状态声明，改为请用户提供订单号或转人工核实，只保留有证据支撑的政策内容')
                if context.get('state_claim_repair_done') or not guard_repair_fits(state, guard_reason):
                    # 修复后仍声明状态，或窗口已放不下修复轮：放行但留残余旗标，
                    # 不把坏答案升级成通道失败
                    context['state_claim_residual'] = state_claims
                else:
                    context['state_claim_repair_done'] = True
                    raise GuardViolation(guard_reason)
            if final.grounding == 'no_business_claim' and (final.citation_chunk_ids or final.selected_sku_keys):
                raise ValueError('no_business_claim_cannot_carry_evidence')
            if final.grounding == 'no_business_claim' and no_business_claim_has_store_conclusion(final.answer):
                raise ValueError('no_business_claim_cannot_state_store_facts')
            request_kind = final.request_kind
            # Option A (user decision 2026-09-13): a service-request turn whose own
            # answer concedes human verification compiles into an actual ticket —
            # asking "需要我帮您转人工吗?" defers an action store policy performs
            # on the condition itself. A first-person transfer offer compiles
            # directly; a bare necessity statement additionally requires the cited
            # policy to mention human handling (visitor-scope answers hedge too).
            cited_human_policy = any('人工' in (row.get('content') or '')
                                     for row in citations.values())
            if (request_kind == 'request_service' and not final.handoff_requested
                    and (answer_offers_human_transfer(final.answer)
                         or ((answer_states_human_necessity(final.answer)
                              or answer_defers_ticket_to_user(final.answer)) and cited_human_policy))):
                final.handoff_requested = True
                context['handoff_compiled_from_answer'] = True
            if looks_like_irreconcilable_sources(question) and request_kind not in EXCEPTION_KINDS:
                request_kind = 'request_handoff'
            evidence_kind = classify_evidence({
                'citations': list(citations.values()),
                'knowledge_status': context.get('knowledge_status'),
                'quarantined': context.get('quarantined'),
                'acl_denied': context.get('acl_denied'),
                'retrieval_calls': context.get('retrieval_calls', 0),
            })
            focus_pid = context.get('focus_product_id')
            product_unique = (context.get('focus_mode') == 'PRODUCT'
                              and request_kind == 'inquire_fact'
                              and looks_like_product_unique_fact(question))
            product_grounded = bool(
                context.get('product_offer_observed')
                or any(citation_covers_product(item, focus_pid) for item in citations.values())
            )
            decision = compile_decision(request_kind, evidence_kind, proposal=proposal,
                                        quarantined=bool(context.get('quarantined')),
                                        handoff_requested=final.handoff_requested,
                                        product_unique_fact=product_unique,
                                        product_grounded=product_grounded)
            if (decision['answer_status'] == 'insufficient'
                    and not context.get('selection_repair_done')
                    and looks_like_product_request(question)
                    and not ({'recommend_skus', 'search_skus', 'compare_skus'}
                             & set(context.get('accepted_tools') or []))):
                # Selection closeout gate (shop-d-56 shape): a product request that
                # ends insufficient without any selection attempt skipped the
                # selection plane entirely — the user is owed at least the honest
                # state of the catalog (real prices, or an honest empty set), not a
                # bare "no policy found". Demoted to a cheap controller fallback
                # (no model repair round, no extra model budget): retrieve once with
                # the merged mission slots; sellable cards close via the catalog
                # template, an honest empty set keeps the original insufficient path.
                # Hybrid demotion: when the controller itself holds usable selection
                # params (mission slots from this turn), retrieve server-side — no
                # model repair round. When extraction yields nothing (the utterance
                # needs the model to phrase the query), keep the original bounded
                # GuardViolation repair round rather than retrieving with junk.
                mission_now = await asyncio.to_thread(memory.mission, actor, conversation_id)
                extracted = extract_mission(question)
                slots = requirement_slots(question)
                merged = merge_mission(mission_now, extracted,
                                       {'required_terms': slots} if slots else {})
                params = mission_retrieve_params(merged)
                if any(params.get(key) for key in ('query', 'max_price_cents', 'min_price_cents',
                                                   'required_terms', 'category_id')):
                    context['selection_repair_done'] = True
                    try:
                        await call_tool('recommend_skus', pin_focus_retrieve_params(params, context, question))
                        templated = template_observed_catalog_result(context, products, utterance=question)
                        if templated:
                            context['final_output_channel'] = 'observed_catalog_template'
                            return {'result': templated}
                    except (StateError, ValueError, CommerceError, TimeoutError) as error:
                        context['selection_refresh_error'] = getattr(error, 'code', None) or str(error)[:120]
                else:
                    gate_reason = ('selection_request_requires_selection: '
                                   '本轮以资料不足收口，但用户请求带选品信号（价格/数量/排除/购买词）且未做任何选品。'
                                   '若这是购物请求：请先用 recommend_skus 按用户约束（必含词/价格/排除）选品，'
                                   '有货按可售商品推荐；约束无法满足时如实说明哪条约束买不到（诚实空集）。'
                                   '若确非购物请求（纯政策咨询）：按资料不足原样收口。')
                    if not guard_repair_fits(state, gate_reason):
                        context['selection_gate_skipped'] = 'window'
                    else:
                        context['selection_repair_done'] = True
                        raise GuardViolation(gate_reason)
            extracted = extract_mission(question)
            slots = requirement_slots(question)
            if shopping_turn_changed(extracted, slots) and selects_products(extracted, slots):
                # The mission records whatever this turn contributed, but only a turn that
                # names what to select (price/budget/category/comparison/quantity or a
                # closed buy frame) may materialise a selection. Policy text routinely
                # carries 要/不要 shapes ("退款需要确认吗", "不要转人工"), and running the
                # catalog on those mints a junk constraint for the whole conversation.
                previous = await asyncio.to_thread(memory.mission, actor, conversation_id)
                explicit = {'required_terms': slots} if slots else {}
                mission = await asyncio.to_thread(
                    memory.put_mission, actor, conversation_id,
                    merge_mission(previous, extracted, explicit), lease=lease)
                last = context.get('shopping_request') or {}
                try:
                    if extracted.get('comparison_required') and (
                            mission.get('comparison_targets') or last.get('comparison_targets') or last.get('sku_keys')):
                        if context.get('comparison_complete') is None:
                            await call_tool('compare_skus', pin_focus_retrieve_params(
                                mission_retrieve_params(mission), context, question))
                    elif last and not retrieve_matches_mission(last, mission):
                        # Re-sync an existing selection with the merged mission. With no
                        # earlier retrieval there is nothing to keep consistent: the model
                        # selects on its own, and the closeout gate still catches a product
                        # request that tries to close without one.
                        await call_tool('recommend_skus', pin_focus_retrieve_params(
                            mission_retrieve_params(mission), context, question))
                except (StateError, ValueError, CommerceError, TimeoutError) as error:
                    # This refresh is optional: the turn already holds its own observations,
                    # and the selection closeout gate below still decides whether a product
                    # request may close without one. An unavailable selection plane must not
                    # discard a complete answer (same doctrine as guard_repair_fits).
                    context['selection_refresh_error'] = getattr(error, 'code', None) or str(error)[:120]
            request = context.get('shopping_request') or {}
            selected = [key for key in final.selected_sku_keys
                        if key in products and sku_obeys_request(products[key], request)]
            result = {'answer': final.answer, 'answer_status': decision['answer_status'],
                      'request_kind': request_kind, 'handoff_requested': final.handoff_requested,
                      'requires_clarification': final.requires_clarification, 'grounding': final.grounding,
                      'evidence_kind': evidence_kind, 'compiled': decision,
                      'focus_mode': context.get('focus_mode'),
                      'citations': [{**citations[key], 'text': citations[key]['content']} for key in final.citation_chunk_ids],
                      'products': [products[key] for key in selected], 'orders': orders, 'proposal': proposal}
            if (product_unique and not product_grounded
                    and decision['answer_status'] == 'insufficient' and not proposal):
                result['answer'] = PRODUCT_UNCOVERED_ANSWER
                result['refuse_reason'] = 'product_uncovered'
            if context.get('empty_reason') and not selected:
                result['empty_reason'] = context['empty_reason']
            if context.get('comparison'):
                result['comparison'] = context['comparison']
                result['comparison_complete'] = context.get('comparison_complete')
                if context.get('comparison_missing_targets'):
                    result['missing_targets'] = context['comparison_missing_targets']
            elif context.get('comparison_complete') is not None:
                result['comparison_complete'] = context.get('comparison_complete')
                if context.get('comparison_missing_targets'):
                    result['missing_targets'] = context['comparison_missing_targets']
            if proposal:
                note = context.get('proposal_intent_note')
                result.update(answer=attach_proposal_confirmation(final.answer, intent_note=note),
                              answer_status='answered')
                if note:
                    result['proposal_intent_note'] = note
            elif decision['open_ticket']:
                result['handoff_origin'] = 'compiled_decision'
            return {'result': result}
        except (ValidationError, ValueError) as error:
            reason = (canonical(error.errors(include_input=False, include_context=False))
                      if isinstance(error, ValidationError) else str(error))
            rejected_output = redact_text(raw or canonical(calls))
            context.setdefault('answer_rejections', []).append({
                'error': type(error).__name__, 'reason': reason[:1000],
                'candidate_output': rejected_output[:12000], 'candidate_output_truncated': len(rejected_output) > 12000,
                'allowed_chunk_ids': list(citations), 'allowed_sku_keys': list(products)})
            if not isinstance(error, GuardViolation):
                if context['answer_repairs'] >= 1:
                    if state.get('repair') and not state.get('repair_no_tools'):
                        # 修复阶段 1 再失败：不给第二次自由轮，直接进阶段 2 的
                        # schema 强制收口（无工具）。这是同一次修复轮内的相位推进，
                        # 不增加 answer_repairs 计数，预算由 model_attempts 兜底。
                        await persist()
                        await emit('decision', {'fork': 'answer_repair_phase2', 'reason': str(reason)[:200],
                                                'detail': '修复轮检索阶段未收口，切 schema 强制终答'})
                        return {'repair': 1, 'repair_no_tools': True,
                                'messages': repair_round_messages(state, reason)}
                    await persist()
                    raise BudgetExceeded('answer_contract_failed')
                context['answer_repairs'] += 1
            await persist()
            await emit('decision', {'fork': 'answer_repair', 'reason': str(reason)[:200],
                                    'detail': '终答契约校验失败，进入唯一一次修复轮'})
            return {'repair': 1, 'messages': repair_round_messages(state, reason)}

    session = SimpleNamespace(model_node=model_node, tool_node=tool_node, answer_node=answer_node)
    from smartlect.graph_runtime import invoke_config, shopping_graph, shopping_session, ensure_postgres_tables
    token = shopping_session.set(session)
    async def heartbeat():
        while True:
            await asyncio.sleep(20)
            await asyncio.to_thread(store.renew_lease, lease, ttl_seconds=90)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        if mode != 'live':
            raise ProviderError('explicit_' + mode)
        ensure_postgres_tables()
        async with asyncio.timeout(max(1, timeout_at - time.monotonic())):
            result = await shopping_graph().ainvoke(
                {'messages': [{'role': 'system', 'content': system}] + recent,
                 'response': {}, 'result': {}, 'repair': context['answer_repairs']},
                invoke_config(conversation_id, run['agent_run_id']))
        return await finish(result['result'], 'live')
    except (ProviderError, BudgetExceeded, TimeoutError) as error:
        context['fallback_reason'] = getattr(error, 'code', str(error))
        if context['fallback_reason'] == 'answer_contract_failed':
            templated = template_observed_catalog_result(context, products, utterance=question)
            if templated:
                return await finish(templated, 'live')
            salvaged = salvage_observed_fact_closeout(
                context, utterance=question, orders=orders, products=products)
            if salvaged:
                return await finish(salvaged, 'live')
        # Legal empty or leftover citations stay a business closeout. A bare provider/budget
        # timeout with no such closeout opens a ticket so the fault is visible to the merchant.
        try:
            await emit('error', {'degraded': True, 'reason': context['fallback_reason'],
                                 'error_type': type(error).__name__, 'model_calls': context['model_calls'],
                                 'tool_calls': context['tool_calls'], 'answered_by': 'controller_fallback'})
        except StateError:
            pass  # A handoff or clear already fenced this run; the fallback answer still stands.
        reason = context['fallback_reason']
        legal_empty = context.get('legal_empty_visible') or (
            context.get('retrieval_calls', 0) > 0 and not citations
            and not context.get('quarantined') and not context.get('acl_denied')
            and context.get('knowledge_status') not in {'conflicting', 'needs_human'})
        result = close_degraded_turn(
            reason, citations=citations, legal_empty=legal_empty, utterance=question,
            orders=orders, proposal=proposal, handoff_result=handoff_result,
            acl_denied=bool(context.get('acl_denied')), proposal_note=context.get('proposal_intent_note'))
        return await finish(result, 'mock' if mode == 'mock' else 'rule-fallback')
    finally:
        shopping_session.reset(token)
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
