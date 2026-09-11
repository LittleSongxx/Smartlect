"""Final Integration demos against the running, isolated Smartlect applications.

Every execution allocates fresh Java demo resources. --mode checks the running
mode; it never switches services or substitutes mock results for a failed live
run. Mock demonstrates the real handoff and deterministic transaction contracts,
and explicitly does not validate multi-turn model capability.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import traceback
import uuid

from check_f3 import json_value
from check_f5 import ACTIONS, OBJECTIVE
from runtime import ROOT
from scenario_client import ScenarioClient, now
from smartlect.events import canonical
from smartlect.privacy import redact_text


SCENARIOS = ('natural_assisted_purchase', 'campaign_assisted_purchase', 'support_refund_recovery')


def prepare_shopping(client, *, advertised=False):
    conversation = client.conversation()
    if not advertised:
        landing = client.request('traffic/landing', {'entry_id': uuid.uuid4().hex})
        client.evidence['natural_landing'] = landing
        client.check(landing['traffic_channel'] == 'NATURAL', 'Natural entry is recorded before the recommendation')
    if client.mode == 'live':
        clarified = client.message(conversation,
            '我想买些日常用的东西，预算和具体商品还没有决定。先问清缺少的需求，暂时不要下单。',
            label='Shopping asks for missing purchase constraints')
        client.check(clarified.get('requires_clarification') is True and not clarified.get('proposal'),
                     'First actual Shopping turn asks for clarification and creates no transaction proposal')
    policy = client.message(conversation, 'Smartlect的支付会扣真实的钱吗？请依据本店已发布政策回答并给出引用。',
                            label='Shopping answers the local payment policy with citations')
    client.verify_citations(policy)
    client.evidence['policy_answer'] = policy
    if client.mode == 'mock':
        client.check(policy.get('ticket') is not None and policy['answer_status'] == 'needs_human',
                     'Mock Shopping honestly transfers unsupported model work to a persisted human ticket')
        client.evidence['mock_limit'] = ('Actual mock Shopping has no generative clarification or SKU planning; '
            'the following transaction uses normal deterministic UI recommendation/proposal APIs, not simulated model answers.')
        close_ticket(client, policy['ticket'], '已核对本项目发布的模拟支付政策；后续交易仍须用户逐笔明确确认。')
        conversation = client.conversation()
    else:
        client.check(policy['answer_status'] == 'answered', 'Live policy question is answered without handoff')
    product_id = client.manifest['products'][1 if advertised else client.evidence['seed'] % 2]
    if client.mode == 'live':
        offer = client.message(conversation,
            f'我的用途是日常使用，预算20元，只考虑本次场景商品。请从真实有货SKU中查找商品{product_id}，'
            '展示规格及价格；只根据已提供商品事实，不要推断功能，先不下单。',
            label='Shopping uses clarified constraints to recommend authoritative SKUs')
        products = offer.get('products', [])
        client.check(bool(products) and all(p['price_cents'] <= 2000 for p in products),
                     'Live Shopping returns budget-constrained real recommendation cards')
    else:
        recommendation = client.request('recommendations', params={'max_price_cents': 2000, 'limit': 8})
        client.evidence['deterministic_recommendation'] = recommendation
        products = recommendation['items']
    sku = client.select_sku(products, product_id)
    client.click_recommendation(sku)
    return conversation, sku


def buy_and_refund(client, conversation, sku, *, interrupt=False, ad_click=None):
    client.stage('User selects one displayed SKU and requests a concrete confirmation proposal')
    before = client.stock(sku)
    client.evidence['initial_stock'] = before
    if client.mode == 'live':
        result = client.message(conversation,
            f"请购买商品{sku['productId']}，规格ID {sku['propertyValueIds']}，数量1，使用我的默认收货地址。"
            '请生成具体下单确认卡，等我确认，不要直接付款。', label='Shopping proposes the user-selected Java order')
        proposal = result.get('proposal')
        client.check(bool(proposal), 'Live Shopping produces a real persisted order proposal')
    else:
        proposal = client.propose(conversation, 'order', {'payMethod': 'mock', 'addressId': client.session['addressId'],
            'orderFrom': 0, 'orderList': [{'productId': sku['productId'], 'propertyValueIds': sku['propertyValueIds'], 'buyCount': 1}]})
    client.evidence['order_proposal'] = proposal
    client.save()
    parameters = proposal['parameters']
    client.check(proposal['action_type'] == 'order' and proposal['status'] == 'PROPOSED'
                 and proposal['quote_total_cents'] == sku['price_cents'] and len(parameters['orderList']) == 1
                 and parameters['orderList'][0]['productId'] == sku['productId']
                 and parameters['orderList'][0]['propertyValueIds'] == sku['propertyValueIds']
                 and parameters['orderList'][0]['buyCount'] == 1 and client.stock(sku) == before,
                 'Exact SKU/quantity/Java quote is reviewable and no inventory changes before confirmation')
    order = client.confirm(proposal)
    client.check(client.stock(sku) == before - 1, 'Confirmed Java order reserves inventory exactly once')
    item = client.pay(order)
    if client.mode == 'live':
        queried = client.message(conversation,
            f"请查询我刚才订单{item['orderId']}的实际状态和已购明细，先不要变更订单或退款。",
            label='Shopping customer service reads the user-owned paid order')
        client.check(any(o['orderId'] == item['orderId'] for o in queried.get('orders', []))
                     and not queried.get('proposal'), 'Customer-service query returns the actual owned order without writing')
        result = client.message(conversation,
            f"请为订单明细{item['orderItemId']}申请剩余全额退款，金额{sku['price_cents']}分。"
            '原因是本地演示验收，生成确认卡等我确认。', label='Shopping proposes the exact owned-item refund')
        refund = result.get('proposal')
        client.check(bool(refund), 'Live Shopping produces the requested persisted refund proposal')
    else:
        refund = client.propose(conversation, 'refund', {'orderItemId': item['orderItemId'],
            'refundAmountCents': sku['price_cents'], 'reason': '本地演示验收全额退款'})
    client.evidence['refund_proposal'] = refund
    client.save()
    client.check(refund['status'] == 'PROPOSED' and refund['action_type'] == 'refund'
                 and refund['parameters']['orderItemId'] == item['orderItemId']
                 and refund['parameters']['refundAmountCents'] == sku['price_cents'],
                 'Refund confirmation names the actual owned item and exact remaining amount')
    final = client.confirm(refund, discard_response=interrupt)
    client.check(final['receipt']['refundStatus'] == 'COMPLETED', 'Java refund reaches COMPLETED, not merely accepted')
    client.reconcile(sku, final, ad_click=ad_click)
    return final


def close_ticket(client, ticket, reply):
    identifier = ticket['ticket_id']
    current = next(t for t in client.request('support', merchant=True) if t['ticket_id'] == identifier)
    if current['status'] == 'OPEN':
        current = client.request('support/' + identifier, {'action': 'take_over', 'version': current['version']},
                                 merchant=True, method='PATCH')
    client.check(current['status'] == 'TAKEN_OVER', 'Merchant explicitly takes over the persisted customer-service ticket')
    detail = client.request('support/' + identifier, merchant=True)
    client.check(detail['conversation']['conversation_id'] == ticket['conversation_id'] and bool(detail['messages']),
                 'Assigned human reads the original persisted conversation through ticket authorization')
    client.evidence.setdefault('human_contexts', []).append(detail)
    current = client.request('support/' + identifier, {'action': 'reply', 'version': current['version'], 'reply': reply},
                             merchant=True, method='PATCH')
    closed = client.request('support/' + identifier, {'action': 'close', 'version': current['version']},
                            merchant=True, method='PATCH')
    client.check(closed['status'] == 'CLOSED', 'Local human reply and ticket closure persist')
    client.evidence.setdefault('human_tickets', []).append(closed)
    client.save()


def natural_assisted_purchase(client):
    conversation, sku = prepare_shopping(client)
    buy_and_refund(client, conversation, sku)
    client.evidence['support_end'] = {'mode': 'independent_answer_and_completed_refund', 'conversation_id': conversation}


def support_refund_recovery(client):
    conversation, sku = prepare_shopping(client)
    final = buy_and_refund(client, conversation, sku, interrupt=True)
    ticket = client.request(f'conversations/{conversation}/handoff', {})
    client.check(ticket['conversation_id'] == conversation, 'Refund conversation can independently enter local human support')
    probe = {'message_id': uuid.uuid4().hex, 'text': '接管期间不要自动执行任何操作。'}
    client.evidence['handoff_boundary_probe'] = {'conversation_id': conversation, 'request': probe}
    client.save()
    blocked = client.user.post(f'/api/assistant/conversations/{conversation}/messages', headers=client.uheaders, json=probe)
    client.evidence['handoff_boundary_probe']['http_status'] = blocked.status_code
    client.check(blocked.status_code == 409, 'Human handoff blocks new automatic Shopping runs')
    close_ticket(client, ticket, '已核对原退款操作到达 COMPLETED；重复查询和确认未增加退款或库存恢复。')
    client.evidence['support_end'] = {'mode': 'persisted_human_ticket_closed', 'conversation_id': conversation,
        'refund_proposal_id': final['proposal_id'], 'automatic_message_after_takeover_http': blocked.status_code}
    client.save()


def campaign_assisted_purchase(client):
    client.stage('Merchant proposes an owned DRAFT activity and creative before first approval')
    sku_a = next(s for s in client.catalog['skus'] if s['productId'] == client.manifest['products'][0])
    campaign_id, creative_id = uuid.uuid4().hex, uuid.uuid4().hex
    campaign = client.request('ads/campaigns', {'campaign_id': campaign_id, 'name': client.evidence['run_id'],
        'product_id': sku_a['productId'], 'sku_key': sku_a['propertyValueIdHash'], 'budget_cents': 300, 'cpc_cents': 1}, merchant=True)
    creative = client.request('ads/creatives', {'creative_id': creative_id, 'campaign_id': campaign_id,
        'copy_text': '推广：查看实际商品规格，选择适合日常用途的款式。'}, merchant=True)
    client.evidence['draft'] = {'campaign': campaign, 'creative': creative}
    client.check(campaign['status'] == creative['status'] == 'DRAFT', 'DRAFT activity and creative cannot spend before approval')
    initial = client.merchant_run(OBJECTIVE)
    plan = initial['plan']
    client.check(plan['status'] == 'WAIT_APPROVAL' and not plan['action_receipts']
                 and {'activate_campaign', 'activate_creative'} <= {a['action_type'] for a in plan['spec']['actions']},
                 'Merchant initial finite plan waits for explicit first approval')
    review = client.request('ads', merchant=True)
    request = {'grant_id': uuid.uuid4().hex, 'initial_plan_id': plan['plan_id'], 'initial_plan_version': plan['version'],
        'merchant_plan_id': plan['plan_id'],
        'expected_campaign_versions': {c['campaign_id']: c['version'] for c in review['campaigns']},
        'expected_creative_versions': {c['creative_id']: c['version'] for c in review['creatives']},
        'envelope': {'objective': OBJECTIVE, 'product_scope': client.manifest['products'], 'allowed_action_types': ACTIONS,
            'budget_cap_cents': 400, 'max_budget_change_cents': 100,
            'valid_until': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            'recommendation_policy_range': {'rankings': ['rule', 'content'], 'groups': ['control', 'treatment'],
                                            'max_weight': 8, 'max_quota': 16}}}
    grant = client.request('ads/grants', request, merchant=True)
    client.evidence['approved_grant'] = grant
    client.check(grant['plan_snapshot']['merchant_plan_spec'] == plan['spec']
                 and grant['envelope_hash'] == hashlib.sha256(canonical(grant['envelope']).encode()).hexdigest(),
                 'Explicit merchant grant freezes the reviewed plan and exact authorization envelope')
    executed = client.request(f"merchant/plans/{plan['plan_id']}/execute", {'expected_version': plan['version']}, merchant=True)
    client.check(executed['status'] == 'WAIT_OBSERVATION' and bool(executed['action_receipts']), 'Approved initial plan actually enables delivery')
    client.evidence['initial_execution'] = executed

    def flow(label, count):
        client.stage(label)
        record = {'label': label, 'exposures': []}
        client.evidence.setdefault('traffic_rounds', []).append(record)
        for index in range(count):
            exposure = client.request('ads/exposures', {'exposure_id': uuid.uuid4().hex, 'creative_id': creative_id})
            record['exposures'].append(exposure)
            if index == 0:
                click_request = {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}
                record['click'] = client.request('ads/clicks', click_request)
                client.check(client.request('ads/clicks', click_request) == record['click'], 'One ad click replays with no second charge')
            if (index + 1) % 50 == 0:
                print(f'{label}: {index + 1}/{count}', flush=True)
        record['account_after'] = client.request('ads', merchant=True)['account']
        client.save()
        return record

    first_flow = flow('Actual ad A traffic: 250 exposures and one CPC click', 250)
    client.check(first_flow['account_after']['spent_cents'] == 1, 'First actual CPC touch debits one cent in the stable account')
    storefront_ads = client.request('ads/recommendations', params={'limit': 2})
    client.check(storefront_ads.get('ranking_mode') == 'rule' and storefront_ads.get('items')
                 and all(item.get('ad_label') == '推广' and item.get('creative_id') == creative_id
                         for item in storefront_ads['items']),
                 'Storefront ad endpoint returns the currently active authorized creative without charging a view')
    client.check(client.request('ads', merchant=True)['account']['spent_cents'] == 1,
                 'Reading storefront ad candidates does not create an impression or CPC charge')
    conversation, sku_b = prepare_shopping(client, advertised=True)
    client.check(sku_b['productId'] != sku_a['productId'], 'Shopping selects real product B after actual advertisement for A')
    buy_and_refund(client, conversation, sku_b, ad_click=first_flow['click'])
    second = client.merchant_run(OBJECTIVE)
    next_plan = second['plan']
    client.check(next_plan['parent_plan_id'] == plan['plan_id'] and next_plan['observation_id'] != plan['observation_id'],
                 'Merchant replans from a genuinely new observation and preserves plan ancestry')
    client.check(second['observation']['summary']['paid_cents'] == second['observation']['summary']['refunded_cents']
                 == sku_b['price_cents'], 'Merchant observes confirmed payment and refund, not an invented gain')
    client.check(next_plan['status'] == 'WAIT_OBSERVATION', 'Replanning yields known execution results or an explicit safe wait')
    changes = [c for r in next_plan['action_receipts'] for c in r.get('receipt', {}).get('changes', [])]
    if next_plan['spec']['actions']:
        client.check(next_plan['grant_id'] == grant['grant_id'] and next_plan['authorization']['within_grant']
                     and bool(changes) and all(r.get('receipt', {}).get('status') == 'APPLIED'
                                              for r in next_plan['action_receipts']),
                     'Nonempty Merchant adjustment executes only within the original grant')
    else:
        client.check(not next_plan['action_receipts'] and next_plan['authorization'].get('required') is False,
                     'Conservative no-action diagnosis creates no invented execution receipt')
    adjusted = any(c['kind'] == 'recommendation' or any(c['before'].get(k) != c['after'].get(k)
                   for k in ('status', 'budget_cents', 'copy_text')) for c in changes)
    client.evidence['adjustment_demonstrated'] = adjusted
    if not adjusted:
        client.evidence['remaining_scenario_gate'] = 'Model retained a safe wait; this run does not demonstrate a post-refund business adjustment.'
    unchanged = client.request('merchant/runs', {'request_id': uuid.uuid4().hex, 'objective': OBJECTIVE, 'mode': client.mode,
        'product_scope': client.manifest['products'], 'planned_budget_cents': 400}, merchant=True)
    client.check(unchanged.get('unchanged_observation') is True and not unchanged.get('agent_run_id'),
                 'No new business observation means no additional model run')
    state = client.request('ads', merchant=True)
    current_campaign = next(c for c in state['campaigns'] if c['campaign_id'] == campaign_id)
    current_creative = next(c for c in state['creatives'] if c['creative_id'] == creative_id)
    if current_campaign['status'] == current_creative['status'] == 'ACTIVE':
        next_flow = flow('Next actual traffic uses the currently applied campaign and creative', 1)
        exposure = next_flow['exposures'][0]
        final_account = next_flow['account_after']
        client.check(exposure['creative_version'] == current_creative['version']
                     and exposure['campaign_version'] == current_campaign['version']
                     and exposure['copy_text'] == current_creative['copy_text']
                     and final_account['spent_cents'] == 2,
                     'A genuinely new exposure/click uses current state and increments cumulative spend once')
    else:
        denied = client.request('ads/exposures', {'exposure_id': uuid.uuid4().hex, 'creative_id': creative_id}, accepted=(409,))
        final_account = client.request('ads', merchant=True)['account']
        client.check(denied['body'].get('error') in {'ads_not_active', 'ads_budget_exhausted'}
                     and final_account['spent_cents'] == 1,
                     'A new traffic opportunity respects the applied pause/exhaustion without charging')
        client.evidence['next_traffic_rejection'] = denied
    client.check(final_account['grant_id'] == grant['grant_id'] and final_account['budget_cap_cents'] == 400,
                 'A later round keeps the original grant and cumulative budget cap')
    client.evidence['final_account'] = final_account
    client.evidence['next_recommendation'] = client.request('recommendations', params={'max_price_cents': 2000, 'limit': 8})
    client.evidence['outcome_claim'] = 'Functional controlled trial only; report actual refund/net/spend and waiting or adjustment. No uplift claim.'
    client.save()


def main(args):
    run_id = 'final-' + uuid.uuid4().hex
    output = args.output or ROOT / 'artifacts' / (run_id + '.json')
    progress = args.progress or ROOT / 'artifacts' / 'local' / (run_id + '-progress.json')
    if output.resolve() == progress.resolve() or output.exists() or progress.exists():
        print('Use distinct unused evidence paths; previous results are preserved.', flush=True)
        return 2
    evidence = {'phase': 'F6-demo', 'scenario': args.scenario, 'seed': args.seed, 'run_id': run_id,
        'started_at': now(), 'status': 'RUNNING', 'requested_mode': args.mode,
        'confirmation_policy': 'local driver explicitly acts as the scoped user and merchant; every transaction and first grant is confirmed',
        'scope': 'functional demo; not four-branch causal evaluation or RAG/tool benchmark', 'checks': []}
    def write(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=json_value) + '\n')
        temporary.replace(path)
    def save():
        write(progress)
    client = None
    save()
    try:
        client = ScenarioClient(evidence, save, requested_mode=args.mode)
        client.setup()
        client.seed_knowledge()
        globals()[args.scenario](client)
        complete = evidence.get('adjustment_demonstrated', True)
        evidence['ai_capability_verified'] = client.mode == 'live' and complete
        evidence['status'] = ('PASSED' if complete else 'SAFE_WAIT_NO_ADJUSTMENT') if client.mode == 'live' else 'PASSED_MOCK_CONTRACT'
        evidence['completed_at'] = now()
        client.collect_index_usage()
        write(output)
        save()
        print('Evidence: ' + str(output), flush=True)
        return 0 if client.mode == 'mock' or complete else 3
    except Exception as error:
        evidence.update(status='FAILED', error_type=type(error).__name__, completed_at=now(),
            error=redact_text(str(error), client.config.values() if client else ()),
            failure_frames=[{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                            for f in traceback.extract_tb(error.__traceback__)],
            recovery='Preserve all original request/proposal/grant IDs and charged CPC; inspect saved receipts before any retry.')
        if client and hasattr(client, 'scope'):
            try:
                client.collect_index_usage()
            except Exception as collection_error:
                evidence['usage_collection_error_type'] = type(collection_error).__name__
        write(output)
        save()
        print('FAILED: ' + type(error).__name__ + '; evidence: ' + str(output), flush=True)
        return 1
    finally:
        if client:
            client.close()


def self_test():
    """No config, network, models or database: protect evidence and recovery behavior."""
    from copy import deepcopy
    import httpx

    calls, snapshots = [], []
    proposal = {'proposal_id': 'original-proposal', 'action_id': 'original-action',
                'idempotency_key': 'original-key', 'status': 'PROPOSED', 'version': 1}
    final = {**proposal, 'status': 'SUCCEEDED', 'receipt': {'refundStatus': 'COMPLETED'}}
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith('/scopes/select'):
            return httpx.Response(200, json={'actor': {'actor_id': 'owner', 'execution_scope_id': 'scope'},
                                            'csrf_token': 'never-retain-this-capability'})
        if request.url.path.endswith('/confirm'):
            return httpx.Response(200, json={'proposal': final})
        return httpx.Response(200, json=final)
    client = ScenarioClient.__new__(ScenarioClient)
    client.evidence = {'writes': [], 'checks': []}
    client.save = lambda: snapshots.append(deepcopy(client.evidence))
    client.uheaders = client.mheaders = {'Origin': 'http://127.0.0.1'}
    with httpx.Client(base_url='http://127.0.0.1', transport=httpx.MockTransport(handler)) as http:
        client.user = client.merchant = http
        selected = client.request('scopes/select', {'execution_scope_id': 'scope'}, merchant=True)
        assert selected['csrf_token'] == 'never-retain-this-capability'
        assert 'never-retain-this-capability' not in json.dumps(snapshots)
        result = client.confirm(proposal, discard_response=True)
        assert result == final
        assert calls[-2:] == [('POST', '/api/assistant/proposals/original-proposal/confirm'),
                              ('GET', '/api/assistant/proposals/original-proposal')]
        assert client.evidence['confirmation_interruption']['response_body_read'] is False
        assert client.evidence['confirmation_interruption']['server_unknown_state_asserted'] is False
    assert all(callable(globals()[scenario]) for scenario in SCENARIOS)
    print('Final demo self-check passed: capability-free evidence and original-action recovery; no external calls.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=SCENARIOS)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--mode', choices=('configured', 'live', 'mock'), default='configured')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--progress', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.scenario:
            parser.error('--scenario is required unless --self-test is used')
        raise SystemExit(main(args))
