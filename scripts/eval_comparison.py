"""Four isolated policy branches on fixed opportunities and real Smartlect APIs.

The hidden response model is an explicit synthetic workload, never a prediction
of real buyers. --smoke identifies reduced runs; no services are managed here.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
import traceback
import uuid

import httpx

from check_f3 import json_value, proposal_from
from check_f4 import login_merchant
from demo import cents
from runtime import ROOT
from scenario_client import ScenarioClient, now
from smartlect.events import canonical
from smartlect.privacy import redact_text
from smartlect.recommendation.store import DEFAULT_STRATEGIES


PROTOCOL_PATH = ROOT / 'evals' / 'comparison-protocol.json'
PROTOCOL = json.loads(PROTOCOL_PATH.read_text())
BRANCHES = tuple(PROTOCOL['branches'])
SEEDS = tuple(PROTOCOL['seeds'])
AD_ACTIONS = ['pause_campaign', 'pause_creative', 'resume_campaign', 'resume_creative', 'set_budget', 'replace_creative']
CATEGORIES = ('数码', '家居', '运动', '阅读')


class PendingPlan(RuntimeError):
    """A branch must stop before generating traffic under an unresolved action."""


def draw(seed, round_number, user_index, visit_index, kind):
    key = canonical([seed, round_number, user_index, visit_index, kind])
    return int(hashlib.sha256(key.encode()).hexdigest()[:13], 16) / 2**52


def opportunity(seed, round_number, index, users):
    user, visit = index % users, index // users
    return {'round': round_number, 'user_logical_index': user, 'visit_index': visit,
            'draws': {kind: draw(seed, round_number, user, visit, kind) for kind in PROTOCOL['draw_kinds']}}


def profile(seed, user_index):
    return {'category_index': int(draw(seed, 0, user_index, 0, 'profile_category') * 4),
            'stated_budget_cents': 1500 + int(draw(seed, 0, user_index, 0, 'profile_budget') * 6000),
            'latent_price_sensitivity': .2 + .7 * draw(seed, 0, user_index, 0, 'profile_sensitivity'),
            'latent_prefers_short_copy': draw(seed, 0, user_index, 0, 'profile_copy') < .5}


def fit(person, product_index, price_cents):
    category = 1.0 if product_index % 4 == person['category_index'] else .30
    price = max(.10, 1 - person['latent_price_sensitivity'] * min(price_cents / person['stated_budget_cents'], 1.5) / 1.5)
    return category, price


def sku_terms(catalog):
    """Per-SKU vocabulary taken from Java's own product name and property values."""
    names = {row['productId']: str(row.get('productName') or '') for row in catalog.get('products', [])}
    properties = {(row['productId'], row['propertyValueId']): str(row.get('propertyValue') or '')
                  for row in catalog.get('propertyValues', [])}
    terms = {}
    for sku in catalog.get('skus', []):
        product = sku['productId']
        values = [properties.get((product, value_id), '')
                  for value_id in str(sku.get('propertyValueIds') or '').split('-')]
        terms[product, sku['propertyValueIdHash']] = tuple(sorted(
            {part for part in (names.get(product, ''), *values) if len(part) >= 2}))
    return terms


def copy_fit(text, person, terms):
    """Score copy against the advertised SKU's own attributes, never a fixed word list.

    A single hardcoded sentence therefore cannot score well across the catalog, so the
    simulated click model and the agents under test share no vocabulary. The ad label is
    rendered by the display layer and is deliberately not rewarded here.
    """
    mentioned = sum(term in text for term in terms) / len(terms) if terms else 0.0
    return .15 + .55 * mentioned + .30 * ((len(text) <= 25) == person['latent_prefers_short_copy'])


def choose(items, weights, value):
    total, cumulative = sum(weights), 0
    if not items or total <= 0:
        return None
    for item, weight in zip(items, weights, strict=True):
        cumulative += weight
        if value * total < cumulative:
            return item
    return items[-1]


def branch_objective(branch):
    allowed = {'fixed': '保持初始规则和投放，不做经营优化。',
               'recommendation': '仅允许按成熟观测调整全范围推荐策略，投放预算和素材保持原样。',
               'ads': '仅允许按成熟观测调整投放预算、素材及启停，推荐保持初始规则。',
               'joint': '允许按成熟观测调整投放及全范围推荐策略。'}[branch]
    return ('依据本轮实际库存、曝光点击、支付退款事实审慎经营；' + allowed +
            '累计授权预算不能重置或扩大。推荐只能group all同步修改两组。'
            '先保护无货，样本未成熟则等待，不推断支付失败原因，不保证收益。')


def branch_actions(branch):
    allowed = ['activate_campaign', 'activate_creative']
    if branch in {'ads', 'joint'}:
        allowed = list(dict.fromkeys(allowed + AD_ACTIONS))
    if branch in {'recommendation', 'joint'}:
        allowed.append('set_recommendation_policy')
    return allowed


def setup(client, args, branch):
    """Parameterized Java setup; intentionally does not alter ScenarioClient.setup."""
    client.stage('Create independent comparison resources: ' + branch)
    request = {'scenarioRunId': client.evidence['run_id'], 'branchId': branch,
               'userCount': args.users, 'productCount': args.products, 'initialStock': 10}
    client.evidence['seed_request'] = request
    client.save()
    client.manifest = client.java.request('admin', '/internal/demo/scenario/seed', data=request)
    client.scope = client.manifest['executionScopeId']
    client.evidence.update(java_manifest=client.manifest, execution_scope_id=client.scope)
    client.save()
    client.store.register_scope(client.scope, scenario_run_id=request['scenarioRunId'], branch_id=branch,
        users=[u['userId'] for u in client.manifest['users']], products=client.manifest['products'])
    client.catalog = client.java.request('product', '/internal/product/snapshotBatch', data={'productIds': client.manifest['products']})
    client.product_indexes = {p: i for i, p in enumerate(client.manifest['products'])}
    client.skus = {(s['productId'], s['propertyValueIdHash']): s for s in client.catalog['skus']}
    client.sku_terms = sku_terms(client.catalog)
    stock_rows = client.java.request('stock', '/internal/stock/getBatch', data=[{
        'productId': s['productId'], 'propertyValueIdHash': s['propertyValueIdHash']} for s in client.manifest['skus']])
    stocks = {(s['productId'], s['propertyValueIdHash']): s['stock'] for s in stock_rows}
    logical = [{'product_index': s['productIndex'], 'spec_index': s['specIndex'],
                'price_cents': cents(client.skus[s['productId'], s['propertyValueIdHash']]['price']),
                'stock': stocks[s['productId'], s['propertyValueIdHash']]} for s in client.manifest['skus']]
    assert all(row['stock'] == 10 for row in logical)
    client.evidence['logical_initial_resources'] = logical
    client.evidence['logical_initial_sha256'] = hashlib.sha256(canonical(logical).encode()).hexdigest()
    client.mheaders = login_merchant(client.merchant, client.config)
    actor = client.merchant.get('/admin-api/assistant/session').json()['actor']
    client.store.grant_scope_access(actor['actor_id'], client.scope, client.evidence['run_id'])
    selected = client.request('scopes/select', {'execution_scope_id': client.scope}, merchant=True)
    client.mheaders = {'Origin': client.base, 'X-CSRF-Token': selected['csrf_token']}
    client.sessions = {}
    client.browser_sessions = {}
    client.objective = branch_objective(branch)
    client.cap = args.campaigns * 200
    client.campaign_ids, client.creative_ids = [], []
    for index in range(args.campaigns):
        sku = client.manifest['skus'][2 * index]
        campaign_id = uuid.uuid4().hex
        client.request('ads/campaigns', {'campaign_id': campaign_id, 'name': f'comparison campaign {index}',
            'product_id': sku['productId'], 'sku_key': sku['propertyValueIdHash'], 'budget_cents': 200, 'cpc_cents': 1}, merchant=True)
        client.campaign_ids.append(campaign_id)
        creatives = []
        for variant in range(args.creatives):
            identifier = uuid.uuid4().hex
            text = ('推广：核对商品规格与用途后再选择。' if variant == 0 else
                    '推广：欢迎查看本店当前提供的商品详情，结合自己的实际预算和日常需要仔细选择适合的款式。')
            client.request('ads/creatives', {'creative_id': identifier, 'campaign_id': campaign_id, 'copy_text': text}, merchant=True)
            creatives.append(identifier)
        client.creative_ids.append(creatives)

    def approve(actions, previous=None):
        snapshot = client.request('ads', merchant=True)
        request = {'grant_id': uuid.uuid4().hex, 'initial_plan_id': 'comparison-approval-' + uuid.uuid4().hex,
            'initial_plan_version': 1,
            'expected_campaign_versions': {c['campaign_id']: c['version'] for c in snapshot['campaigns']},
            'expected_creative_versions': {c['creative_id']: c['version'] for c in snapshot['creatives']},
            'envelope': {'objective': client.objective, 'product_scope': client.manifest['products'],
                'allowed_action_types': actions, 'budget_cap_cents': client.cap, 'max_budget_change_cents': 100,
                'valid_until': (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
                'recommendation_policy_range': {'rankings': ['rule', 'content'], 'groups': ['all'], 'max_weight': 20, 'max_quota': 20}}}
        if previous:
            request['replaces_grant_id'] = previous['grant_id']
        return client.request('ads/grants', request, merchant=True)

    # DRAFT resources remain DRAFT while the policy-only bootstrap grant is replaced.
    bootstrap = approve(['set_recommendation_policy'])
    manual_actions(client, bootstrap, [{'action_type': 'set_recommendation_policy', 'expected_version': 1,
        'policy': {'group': 'all', 'strategy_version': 'rules-v1', 'config': deepcopy(DEFAULT_STRATEGIES['rules-v1'])}}],
        reason='comparison_initial_pure_policy')
    client.grant = approve(branch_actions(branch), bootstrap)
    client.evidence['bootstrap_grant'] = bootstrap
    client.evidence['final_grant'] = client.grant
    state = client.request('ads', merchant=True)
    actions = [{'action_type': 'activate_campaign', 'campaign_id': c['campaign_id'], 'expected_version': c['version']}
               for c in state['campaigns']]
    actions += [{'action_type': 'activate_creative', 'campaign_id': c['campaign_id'], 'creative_id': c['creative_id'],
                 'expected_version': c['version']} for c in state['creatives']]
    for start in range(0, len(actions), 8):
        manual_actions(client, client.grant, actions[start:start + 8], reason='comparison_initial_delivery')
    state = client.request('ads', merchant=True)
    assert state['recommendation']['control_strategy_version'] == state['recommendation']['treatment_strategy_version'] == 'rules-v1'
    assert state['account']['spent_cents'] == 0 and state['account']['budget_cap_cents'] == client.cap
    client.evidence['initial_state'] = state
    client.evidence.update(transactions=[], rounds=[], opportunities=[], optimization_attempts=[])
    client.save()


def manual_actions(client, grant, actions, *, reason, evidence_ids=()):
    identifier = uuid.uuid4().hex
    return client.request('ads/actions', {'action_id': identifier, 'idempotency_key': 'comparison:' + identifier,
        'grant_id': grant['grant_id'], 'plan_id': 'comparison-rule-' + identifier, 'plan_version': 1,
        'reason_code': reason, 'evidence_ids': list(evidence_ids), 'actions': actions}, merchant=True)


def select_user(client, index):
    if index not in client.sessions:
        session = client.java.request('admin', '/internal/demo/scenario/session', data={
            'executionScopeId': client.scope, 'userIndex': index, 'password': client.config['SMARTLECT_DEMO_PASSWORD']})
        browser = client.clients.enter_context(httpx.Client(base_url=client.base, timeout=40, trust_env=False,
                                                            cookies={'token': session['token']}))
        auth = browser.get('/api/assistant/session')
        auth.raise_for_status()
        auth = auth.json()
        assert auth['actor']['execution_scope_id'] == client.scope and auth['actor']['actor_id'] == session['userId']
        client.sessions[index] = session
        client.browser_sessions[index] = (browser, {'Origin': client.base, 'X-CSRF-Token': auth['csrf_token']})
    client.session = client.sessions[index]
    client.user, client.uheaders = client.browser_sessions[index]


def purchase(client, chosen, op, person):
    conversation = client.conversation()
    parameters = {'payMethod': 'mock', 'addressId': client.session['addressId'], 'orderFrom': 0,
        'orderList': [{'productId': chosen['productId'], 'propertyValueIds': chosen['propertyValueIds'], 'buyCount': 1}]}
    proposal = client.propose(conversation, 'order', parameters)
    assert proposal['quote_total_cents'] == chosen['price_cents']
    transaction = {'user_logical_index': op['user_logical_index'], 'opportunity': {k: op[k] for k in ('round', 'visit_index')},
        'conversation_id': conversation, 'sku': chosen, 'order_proposal': proposal,
        'initial_stock': client.stock(chosen), 'status': 'AWAITING_USER_CONFIRMATION'}
    client.evidence['transactions'].append(transaction)
    client.save()
    order = client.confirm(proposal)
    assert order['receipt']['amountCents'] == chosen['price_cents']
    assert client.stock(chosen) == transaction['initial_stock'] - 1
    category, price = fit(person, client.product_indexes[chosen['productId']], chosen['price_cents'])
    transaction.update(order=order, pay_order_id=order['receipt']['payOrderId'], status='PAYMENT_SCHEDULED',
        payment_due_round=op['round'] + int(op['draws']['delay_payment'] < PROTOCOL['delayed_payment_probability']),
        refund_selected=op['draws']['refund'] < .10 + .20 * (1 - category * price),
        explicit_user_confirmations=['order'], registered_at=now())
    client.save()
    return transaction


def payment_watermark(ledger, paid, refunded):
    # exceptionMessages counts the whole database, including retained fault tests.
    return (ledger['paidCents'] == paid and ledger['refundedCents'] == refunded
            and ledger['paymentConversions'] == 1 and bool(ledger['events'])
            and all(e['status'] == 'APPLIED' for e in ledger['events']))


def settle(client, boundary):
    """Wait only for due business events. Future payment intentions stay explicitly pending."""
    for transaction in client.evidence['transactions']:
        if transaction['status'] != 'PAYMENT_SCHEDULED' or transaction['payment_due_round'] > boundary:
            continue
        select_user(client, transaction['user_logical_index'])
        pay_id = transaction['pay_order_id']
        amount = transaction['order']['receipt']['amountCents']
        client.request('payments/' + pay_id + '/complete', {'expected_amount_cents': amount})
        paid = client.wait(lambda: client.request('payments/' + pay_id),
            lambda r: r['commandStatus'] == 'business_completed', 'Wait for due Java payment', timeout=45)
        assert paid['paymentStatus'] == 'PAID' and paid['orderSynchronized']
        transaction.update(payment_receipt=paid, status='PAID', settled_at=now())
        transaction['explicit_user_confirmations'].append('payment')
        client.save()
        if transaction['refund_selected']:
            orders = client.java.request('order', '/internal/order/commerce/listOrders', data={'limit': 100}, session=client.session)
            item = next(i for o in orders if o['payOrderId'] == pay_id for i in o['items'])
            proposal = client.propose(transaction['conversation_id'], 'refund', {'orderItemId': item['orderItemId'],
                'refundAmountCents': amount, 'reason': '固定模拟用户决策：验收退款'})
            transaction['refund_proposal'] = proposal
            client.save()
            refund = client.confirm(proposal)
            assert refund['receipt']['refundStatus'] == 'COMPLETED'
            transaction.update(refund_receipt=refund, status='REFUNDED')
            transaction['explicit_user_confirmations'].append('refund')
        ledger = client.wait(lambda: client.ledger.summary(pay_id), lambda r:
            payment_watermark(r, amount, amount if transaction['refund_selected'] else 0),
            'Wait for due payment/refund message watermarks', timeout=45)
        attribution = client.wait(lambda: client.request('attribution', merchant=True, params={'payOrderId': pay_id}),
            lambda r: len(r['events']) == (2 if transaction['refund_selected'] else 1)
            and all(e['calculation_status'] == 'FINAL' for e in r['events']), 'Wait for due frozen attribution', timeout=45)
        assert all(e['execution_scope_id'] == client.scope and e['recommendation_id'] == transaction['sku']['recommendation_id']
                   and e['amount_cents'] == amount for e in attribution['events'])
        if transaction['refund_selected']:
            by_type = {e['event_type']: e for e in attribution['events']}
            assert all(by_type['PAYMENT'][key] == by_type['REFUND'][key] for key in (
                'context_id', 'ad_click_id', 'campaign_id', 'recommendation_click_id', 'recommendation_id', 'category'))
        transaction.update(ledger=ledger, attribution=attribution)
        client.save()


def perform_opportunity(client, args, op, seed):
    person = profile(seed, op['user_logical_index'])
    select_user(client, op['user_logical_index'])
    record = {'input': op, 'status': 'STARTED'}
    client.evidence['opportunities'].append(record)
    client.save()
    draws = op['draws']
    intent = draws['shopping_intent'] < PROTOCOL['natural_shopping_intent']
    if draws['channel'] < PROTOCOL['ad_share']:
        # The same exogenous slot is attempted even if this branch has paused it.
        slot = min(args.campaigns - 1, int(draws['campaign'] ** 2 * args.campaigns))
        variant = min(args.creatives - 1, int(draws['creative'] * args.creatives))
        exposure = client.request('ads/exposures', {'exposure_id': uuid.uuid4().hex,
            'creative_id': client.creative_ids[slot][variant]}, accepted=(200, 409, 403))
        record['exposure'] = exposure
        if 'http_status' in exposure:
            assert exposure['body'].get('error') in {'ads_not_active', 'ads_budget_exhausted', 'fresh_positive_stock_required'}
            record['status'] = 'AD_OPPORTUNITY_REJECTED'
            client.save()
            return
        product_index = client.product_indexes[exposure['product_id']]
        original = client.skus[exposure['product_id'], exposure['sku_key']]
        category, price = fit(person, product_index, cents(original['price']))
        terms = client.sku_terms.get((exposure['product_id'], exposure['sku_key']), ())
        chance = min(.12, max(.002, .003 + .08 * copy_fit(exposure['copy_text'], person, terms) * category * price))
        record['simulator_click_probability'] = chance
        if draws['click'] >= chance:
            record['status'] = 'AD_EXPOSURE_ONLY'
            client.save()
            return
        record['click'] = client.request('ads/clicks', {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']})
        intent = True
    else:
        record['landing'] = client.request('traffic/landing', {'entry_id': uuid.uuid4().hex})
    if not intent:
        record['status'] = 'NATURAL_LANDING_ONLY'
        client.save()
        return
    recommendation = client.request('recommendations', params={'query': CATEGORIES[person['category_index']],
        'max_price_cents': person['stated_budget_cents'], 'limit': 8})
    record['recommendation'] = recommendation
    assert all(p['productId'] in client.product_indexes and p['stock'] > 0 and p['price_cents'] <= person['stated_budget_cents']
               and (p['productId'], p['propertyValueIdHash']) in client.skus for p in recommendation['items'])
    # Independent salt cannot mix treatments: both groups must reference this version.
    policy = client.request('ads', merchant=True)['recommendation']
    assert recommendation['strategy_version'] == policy['control_strategy_version'] == policy['treatment_strategy_version']
    record['actual_policy'] = {k: policy[k] for k in ('control_strategy_version', 'treatment_strategy_version', 'revision')}
    items = recommendation['items']
    if not items:
        record['status'] = 'NO_ELIGIBLE_SKU'
        client.save()
        return
    weights = [math.prod(fit(person, client.product_indexes[p['productId']], p['price_cents'])) / (p['position'] + .5) for p in items]
    selected = choose(items, weights, draws['selection'])
    record['recommendation_exposures'] = client.request(f"recommendations/{recommendation['recommendation_id']}/exposures",
                                                        {'positions': [p['position'] for p in items]})
    record['recommendation_click'] = client.request(f"recommendations/{recommendation['recommendation_id']}/clicks",
                                                    {'position': selected['position']})
    chance = .045 * math.prod(fit(person, client.product_indexes[selected['productId']], selected['price_cents']))
    record.update(selected_sku=selected, simulator_purchase_probability=chance, status='RECOMMENDATION_CLICK_ONLY')
    if draws['purchase'] < chance:
        transaction = purchase(client, selected, op, person)
        record.update(pay_order_id=transaction['pay_order_id'], status='ORDER_CONFIRMED')
    client.save()


def plan_pending(plan):
    if not plan or plan.get('status') not in {'WAIT_OBSERVATION', 'REVIEWED', 'WAIT_APPROVAL', 'PARTIALLY_APPLIED', 'FAILED'}:
        return True
    receipts = plan.get('action_receipts', [])
    if any(r.get('command_status') not in {'business_completed', 'rejected'} for r in receipts):
        return True
    if any(r.get('command_status') == 'business_completed' and r.get('receipt', {}).get('status') != 'APPLIED' for r in receipts):
        return True
    if plan['status'] in {'WAIT_OBSERVATION', 'REVIEWED'}:
        changes = [c for r in receipts for c in r.get('receipt', {}).get('changes', [])]
        return len(changes) != len(plan.get('spec', {}).get('actions', []))
    return plan['status'] in {'PARTIALLY_APPLIED', 'FAILED'} and bool(plan.get('spec', {}).get('actions')) and not receipts


def recover_plan(client, record, plan, *, timeout=45):
    """Recover only the original plan/version; two bounded attempts, no new Agent run."""
    recovery = {'started_at': now(), 'original_plan': deepcopy(plan), 'requests': [], 'observations': [],
                'timeout_seconds': timeout, 'max_execute_requests': 2}
    record['recovery'] = recovery

    def pending(reason):
        recovery.update(status='PENDING_RECOVERY', reason=reason, completed_at=now())
        record['status'] = 'PENDING_RECOVERY'
        client.evidence['pending_plan'] = recovery
        client.save()
        raise PendingPlan(reason)

    if not plan or not plan.get('plan_id') or type(plan.get('version')) is not int:
        pending('original_plan_identity_missing')
    identifier, version = plan['plan_id'], plan['version']
    request = {'expected_version': version}
    recovery.update(plan_id=identifier, expected_version=version)
    next_attempt = 0.0
    deadline = time.monotonic() + timeout

    def bounded_request(*args, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pending('original_plan_recovery_deadline')
        previous_timeout = client.merchant.timeout
        client.merchant.timeout = httpx.Timeout(min(10, remaining))
        try:
            return client.request(*args, **kwargs)
        finally:
            client.merchant.timeout = previous_timeout

    def read():
        nonlocal next_attempt
        snapshot = bounded_request('merchant', merchant=True)
        current = next((p for p in snapshot['plans'] if p['plan_id'] == identifier), None)
        if current is None or current.get('version') != version:
            pending('original_plan_missing_or_version_changed')
        if not recovery['observations'] or current != recovery['observations'][-1]:
            recovery['observations'].append(deepcopy(current))
            client.save()
        if not plan_pending(current):
            return current
        if len(recovery['requests']) < 2 and time.monotonic() >= next_attempt:
            attempt = {'plan_id': identifier, 'request': dict(request), 'started_at': now()}
            recovery['requests'].append(attempt)
            client.save()
            response = bounded_request('merchant/plans/' + identifier + '/execute', request,
                                       merchant=True, accepted=(200, 409))
            attempt.update(response=response, completed_at=now())
            client.save()
            # A live worker lease is 30 seconds. Poll reads while it expires rather
            # than issuing fresh plans or hammering the original execute endpoint.
            next_attempt = time.monotonic() + 30
            if 'http_status' in response:
                if response.get('body', {}).get('error') != 'plan_busy':
                    pending('original_plan_recovery_rejected')
            else:
                if response.get('plan_id') != identifier or response.get('version') != version:
                    pending('recovery_changed_original_plan_identity')
                current = response
        return current

    try:
        settled = client.wait(read, lambda p: not plan_pending(p), 'Recover original Merchant action outcomes', timeout=timeout)
    except (AssertionError, httpx.HTTPError) as error:
        recovery['error_type'] = type(error).__name__
        pending('original_plan_outcome_not_confirmed')
    recovery.update(status='RESOLVED', final_plan=deepcopy(settled), completed_at=now())
    record['plan'] = settled
    client.save()
    return settled


def optimize(client, args, branch, round_number):
    if branch == 'fixed' or round_number == args.rounds:
        return
    record = {'after_round': round_number, 'mode': args.mode, 'started_at': now()}
    client.evidence['optimization_attempts'].append(record)
    client.save()
    request = {'request_id': uuid.uuid4().hex, 'objective': client.objective, 'mode': args.mode,
               'product_scope': client.manifest['products'], 'planned_budget_cents': client.cap}
    record['request'] = request
    created = client.request('merchant/runs', request, merchant=True)
    record['created_run'] = created
    if 'agent_run_id' not in created:
        if created.get('plan_recovery_required'):
            recover_plan(client, record, created.get('latest_plan'))
            record['status'] = 'ORIGINAL_PLAN_RECOVERED_NO_NEW_MODEL'
        elif created.get('unchanged_observation'):
            latest_plan = created.get('latest_plan')
            if plan_pending(latest_plan):
                recover_plan(client, record, latest_plan)
                record['status'] = 'ORIGINAL_PLAN_RECOVERED_NO_NEW_MODEL'
            else:
                record['status'] = 'WAIT_NEW_OBSERVATION'
        else:
            recover_plan(client, record, None)
        record['completed_at'] = now()
        client.save()
        return
    def read():
        record['run'] = client.request('merchant/runs/' + created['agent_run_id'], merchant=True)
        client.save()
        return record['run']
    run = client.wait(read, lambda r: r['state'] not in {'CREATED', 'RUNNING'}, 'Bounded comparison Merchant planning', timeout=95)
    snapshot = client.request('merchant', merchant=True)
    plan = next((p for p in snapshot['plans'] if p['agent_run_id'] == run['agent_run_id']), None)
    record.update(plan=plan, status=run['state'], completed_at=now())
    if ((plan and plan_pending(plan))
            or (not plan and (run.get('result') or {}).get('execution_status') == 'UNKNOWN')):
        record['plan_before_recovery'] = deepcopy(plan)
        plan = recover_plan(client, record, plan)
    if plan:
        record['observation'] = next(o for o in snapshot['observations'] if o['observation_id'] == plan['observation_id'])
        assert len(plan['spec']['actions']) <= 8
        if plan['action_receipts']:
            assert plan['grant_id'] == client.grant['grant_id']
        if args.mode == 'rule' and branch in {'recommendation', 'joint'}:
            state = client.request('ads', merchant=True)
            policy = state['recommendation']
            recommendation_clicks = record['observation']['summary'].get('recommendation_clicks', 0)
            if recommendation_clicks >= 10 and policy['control_strategy_version'] == policy['treatment_strategy_version'] == 'rules-v1':
                evidence = [f['evidence_id'] for f in record['observation']['facts']
                            if f['kind'] == 'recommendation' and f['metric'] == 'recommendation_clicks'
                            and f['value'] == recommendation_clicks]
                assert evidence, 'A rule strategy change needs the original scoped recommendation-click fact'
                record['rule_recommendation_receipt'] = manual_actions(client, client.grant, [{
                    'action_type': 'set_recommendation_policy', 'expected_version': policy['revision'],
                    'policy': {'group': 'all', 'strategy_version': 'content-v1', 'config': deepcopy(DEFAULT_STRATEGIES['content-v1'])}}],
                    reason='comparison_predeclared_mature_recommendation_rule', evidence_ids=evidence)
    client.save()


def summarize(client):
    state = client.request('ads', merchant=True)
    transactions = client.evidence['transactions']
    paid = sum(t.get('ledger', {}).get('paidCents', 0) for t in transactions)
    refunded = sum(t.get('ledger', {}).get('refundedCents', 0) for t in transactions)
    spend = state['account']['spent_cents']
    assert state['account']['grant_id'] == client.grant['grant_id'] and state['account']['budget_cap_cents'] == client.cap
    assert spend == state['spend_cents'] and 0 <= spend <= client.cap
    assert state['recommendation']['control_strategy_version'] == state['recommendation']['treatment_strategy_version']
    attempts = client.evidence['optimization_attempts']
    model_attempts = [a for r in attempts for a in r.get('run', {}).get('context', {}).get('model_attempts', [])]
    receipts = [receipt.get('receipt', {}) for r in attempts for receipt in (r.get('plan') or {}).get('action_receipts', [])]
    receipts += [r['rule_recommendation_receipt'] for r in attempts if r.get('rule_recommendation_receipt')]
    # A recovered plan may appear in two observations; one action ID is one outcome.
    applied_receipts = {r['action_id']: r for r in receipts if r.get('status') == 'APPLIED'}
    applied = [c for receipt in applied_receipts.values() for c in receipt.get('changes', [])]
    realized = [c for c in applied if business_change(c)]
    return {'paid_cents': paid, 'refunded_cents': refunded, 'net_cents': paid - refunded, 'ad_spend_cents': spend,
        'net_less_ads_cents': paid - refunded - spend, 'orders': len(transactions),
        'pending_payments': sum(t['status'] == 'PAYMENT_SCHEDULED' for t in transactions),
        'impressions': state['impressions'], 'clicks': state['clicks'], 'final_policy': state['recommendation'],
        'applied_action_count': len(applied),
        'realized_intervention_count': len(realized), 'realized_action_types': [c['action_type'] for c in realized],
        'provider_attempt_count': len(model_attempts),
        'live_successful_attempts': sum(a.get('model_mode') == 'live' and a.get('status') == 'succeeded' for a in model_attempts),
        'fallback_runs': sum((r.get('run', {}).get('result') or {}).get('model_mode') == 'rule-fallback' for r in attempts),
        'failed_optimization_runs': sum(r.get('run', {}).get('state') == 'FAILED' for r in attempts),
        'unapproved_plans': sum((r.get('plan') or {}).get('status') == 'WAIT_APPROVAL' for r in attempts),
        'estimated_known_model_cost_cny': sum(a['cost_estimate_cny'] for a in model_attempts if a.get('cost_estimate_cny') is not None),
        'unknown_model_cost_attempts': sum(a.get('cost_estimate_cny') is None for a in model_attempts),
        'known_input_tokens': sum(a.get('usage', {}).get('input_tokens') or 0 for a in model_attempts),
        'known_output_tokens': sum(a.get('usage', {}).get('output_tokens') or 0 for a in model_attempts),
        'unknown_usage_attempts': sum(a.get('usage', {}).get('input_tokens') is None or
                                      a.get('usage', {}).get('output_tokens') is None for a in model_attempts),
        'grant_id': client.grant['grant_id'], 'final_account': state['account']}


def business_change(change):
    if change['kind'] != 'recommendation':
        return any(change['before'].get(k) != change['after'].get(k) for k in ('status', 'budget_cents', 'copy_text'))
    before, after = change['before'], change['after']
    configs = {s['strategy_version']: s['config'] for s in before['strategies']}
    groups = ('control', 'treatment') if after['group'] == 'all' else (after['group'],)
    return any(configs[before[group + '_strategy_version']] != after['config'] for group in groups)


def paired_report(branches):
    metrics = ('paid_cents', 'refunded_cents', 'net_cents', 'ad_spend_cents', 'net_less_ads_cents')
    completed = {(b['seed'], b['branch']): b['summary'] for b in branches if b.get('status') == 'COMPLETED'}
    result = {}
    for branch in BRANCHES[1:]:
        rows = [{'seed': seed, **{metric: completed[seed, branch][metric] - completed[seed, 'fixed'][metric] for metric in metrics}}
                for seed in SEEDS if (seed, branch) in completed and (seed, 'fixed') in completed]
        result[branch] = {'paired_differences': rows, 'seed_count': len(rows), 'descriptive_uncertainty': {
            metric: {'mean': statistics.fmean([r[metric] for r in rows]), 'min': min(r[metric] for r in rows),
                     'max': max(r[metric] for r in rows), 'sample_std': statistics.stdev([r[metric] for r in rows]) if len(rows) > 1 else None}
            for metric in metrics} if rows else {}, 'claim': 'Synthetic paired differences only; no real-world significance or uplift claim.'}
    return result


def journal_changes(data, latest):
    components = [('stage', None, data.get('stage'))]
    for kind in ('writes', 'transactions', 'optimization_attempts', 'opportunities'):
        rows = data.get(kind, [])
        # Settlement updates earlier delayed transactions, not necessarily the tail.
        indexes = range(len(rows)) if kind == 'transactions' else [len(rows) - 1] if rows else []
        components.extend((kind, index, {'index': index, 'value': rows[index]}) for index in indexes)
    for kind, index, value in components:
        encoded = json.dumps(value, ensure_ascii=False, default=json_value)
        key = kind, index
        if encoded != latest.get(key):
            latest[key] = encoded
            yield {'component': kind, 'record': value}


def main(args):
    from eval_rag import freeze_bindings  # Reads checksums/manifest only, never a case JSONL.

    def current_bindings():
        return {'runtime': freeze_bindings('live' if args.mode == 'live' else 'mock'),
                'protocol_sha256': hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
                'comparison_driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    defaults = PROTOCOL['defaults']
    actual = {'rounds': args.rounds, 'opportunities_per_round': args.opportunities, 'users': args.users,
              'products': args.products, 'campaigns': args.campaigns, 'creatives_per_campaign': args.creatives}
    reduced = any(actual[k] != defaults[k] for k in actual) or tuple(args.seeds) != SEEDS
    if len(set(args.seeds)) != len(args.seeds) or not set(args.seeds) <= set(SEEDS) or args.repeat_id < 1:
        raise ValueError('seeds_must_be_distinct_predeclared_values_and_repeat_id_positive')
    if reduced and not args.smoke:
        raise ValueError('reduced_dimensions_or_seed_subset_require_explicit_smoke')
    if not (1 <= args.rounds <= 4 and 1 <= args.opportunities <= 300 and 1 <= args.users <= 100
            and 2 <= args.products <= 20 and 1 <= args.campaigns <= min(6, args.products) and 1 <= args.creatives <= 2):
        raise ValueError('comparison_dimensions_outside_bounded_protocol')
    binding = current_bindings()
    run_id = 'comparison-' + uuid.uuid4().hex
    output = args.output or ROOT / 'artifacts' / (run_id + '.json')
    progress = args.progress or ROOT / 'artifacts' / 'local' / (run_id + '-progress.json')
    journal_dir = output.with_suffix('')
    if output.exists() or progress.exists() or journal_dir.exists() or output.resolve() == progress.resolve():
        raise ValueError('choose_unused_output_progress_and_journal_paths')
    journal_dir.mkdir(parents=True)
    result = {'phase': 'F6-comparison', 'run_id': run_id, 'status': 'RUNNING', 'started_at': now(), 'mode': args.mode,
        'repeat_id': args.repeat_id, 'smoke': reduced or args.smoke, 'dimensions': actual, 'seeds': args.seeds,
        'protocol': PROTOCOL, 'protocol_sha256': hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        'comparison_driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'frozen_bindings': binding,
        'strategy_configs': deepcopy(DEFAULT_STRATEGIES), 'branches': [], 'opportunity_inputs': {},
        'interpretation': 'Real local Java/API execution of a declared synthetic workload; no real users, real funds or real advertising.'}
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_value) + '\n')
        tmp.replace(path)
    # Freeze all exogenous opportunities before any branch performs a business action.
    inputs = {seed: [opportunity(seed, r, i, args.users) for r in range(1, args.rounds + 1)
                    for i in range(args.opportunities)] for seed in args.seeds}
    for seed, opportunities in inputs.items():
        destination = journal_dir / f'opportunities-{seed}.json'
        frozen = {'seed': seed, 'profiles_simulator_only': [profile(seed, u) for u in range(args.users)], 'opportunities': opportunities}
        write(destination, frozen)
        result['opportunity_inputs'][str(seed)] = {'path': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}
    write(progress, result)
    resources, initial_hash = set(), None
    for seed in args.seeds:
        for branch in BRANCHES:
            data = {'run_id': f'{run_id}-{seed}', 'scenario': 'comparison', 'seed': seed, 'branch': branch,
                    'status': 'RUNNING', 'requested_mode': args.mode, 'repeat_id': args.repeat_id, 'checks': []}
            # scenarioRunId stays within Java's 64-character limit; branches have independent registry resources.
            result['branches'].append(data)
            journal = journal_dir / f'{seed}-{branch}.jsonl'
            latest = {}
            def save():
                for change in journal_changes(data, latest):
                    with journal.open('a') as stream:
                        stream.write(json.dumps(change, ensure_ascii=False, default=json_value) + '\n')
            client = None
            try:
                data['runtime_binding_before_matches'] = current_bindings() == binding
                assert data['runtime_binding_before_matches'], 'Runtime/driver/protocol changed before this branch'
                client = ScenarioClient(data, save, requested_mode='live' if args.mode == 'live' else 'configured')
                setup(client, args, branch)
                if initial_hash is None:
                    initial_hash = data['logical_initial_sha256']
                assert data['logical_initial_sha256'] == initial_hash, 'Logical Java price/stock fixtures must match across all branches'
                owned = {('user', u['userId']) for u in client.manifest['users']} | {('product', p) for p in client.manifest['products']}
                assert not owned & resources, 'Java resources must not overlap between branches or seeds'
                resources.update(owned)
                for round_number in range(1, args.rounds + 1):
                    settle(client, round_number)
                    round_inputs = [op for op in inputs[seed] if op['round'] == round_number]
                    round_record = {'round': round_number, 'input_sha256': hashlib.sha256(canonical(round_inputs).encode()).hexdigest(), 'started_at': now()}
                    data['rounds'].append(round_record)
                    for index, op in enumerate(round_inputs):
                        perform_opportunity(client, args, op, seed)
                        if (index + 1) % 50 == 0:
                            print(f'{seed}/{branch}/round {round_number}: {index + 1}/{args.opportunities}', flush=True)
                    settle(client, round_number)
                    round_record['business_watermark'] = summarize(client)
                    round_record['future_payments'] = [{'pay_order_id': t['pay_order_id'], 'due_round': t['payment_due_round']}
                        for t in data['transactions'] if t['status'] == 'PAYMENT_SCHEDULED']
                    optimize(client, args, branch, round_number)
                    round_record['completed_at'] = now()
                    write(progress, result)
                settle(client, args.rounds + 1)
                data['summary'] = summarize(client)
                assert data['summary']['pending_payments'] == 0
                targets = [{'productId': s['productId'], 'propertyValueIdHash': s['propertyValueIdHash']} for s in client.manifest['skus']]
                data['final_stock'] = client.java.request('stock', '/internal/stock/getBatch', data=targets)
                expected = {(s['productId'], s['propertyValueIdHash']): s['initialStock'] for s in client.manifest['skus']}
                for transaction in data['transactions']:
                    if transaction['status'] == 'PAID':
                        expected[transaction['sku']['productId'], transaction['sku']['propertyValueIdHash']] -= 1
                assert len(data['final_stock']) == len(expected)
                assert all(row['stock'] == expected[row['productId'], row['propertyValueIdHash']] >= 0 for row in data['final_stock'])
                data['stock_reconciled_to_individual_orders'] = True
                if branch == 'fixed':
                    assert data['summary']['provider_attempt_count'] == data['summary']['realized_intervention_count'] == 0
                data.update(status='COMPLETED', completed_at=now())
            except Exception as error:
                data.update(status='PENDING_RECOVERY' if isinstance(error, PendingPlan) else 'FAILED', error_type=type(error).__name__,
                    error=redact_text(str(error), client.config.values() if client else ()),
                    failure_frames=[{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                                    for f in traceback.extract_tb(error.__traceback__)])
                # A failed branch keeps its resources and facts; other predeclared branches are still attempted.
            finally:
                if client:
                    client.close()
                try:
                    data['runtime_binding_after_matches'] = current_bindings() == binding
                except Exception as error:
                    data['runtime_binding_after_matches'] = False
                    data['binding_error_type'] = type(error).__name__
                if not data['runtime_binding_after_matches']:
                    data.update(status='FAILED', binding_error='Runtime/driver/protocol changed during this branch')
                data['request_journal'] = str(journal)
                archive = journal_dir / f'{seed}-{branch}.json'
                write(archive, data)
                data['raw_evidence'] = {'path': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
                for kind in ('writes', 'opportunities'):
                    data[kind + '_count'] = len(data.pop(kind, []))
                write(progress, result)
    result.update(paired_report=paired_report(result['branches']), completed_at=now(),
                  status='COMPLETED' if all(b['status'] == 'COMPLETED' for b in result['branches']) else 'FAILED')
    result['realized_interventions_by_branch'] = {f"{b['seed']}:{b['branch']}": b.get('summary', {}).get('realized_action_types', []) for b in result['branches']}
    write(output, result)
    write(progress, result)
    print('Comparison evidence: ' + str(output), flush=True)
    return 0 if result['status'] == 'COMPLETED' else 1


def self_test():
    a = [opportunity(42, 1, index, 100) for index in range(300)]
    for _branch in BRANCHES:
        # Arbitrary extra model/tool work has no mutable PRNG state to advance.
        draw(42, 1, 50, 2, 'unrelated_extra_model_call')
        assert a == [opportunity(42, 1, index, 100) for index in range(300)]
    assert opportunity(17, 1, 0, 100) != opportunity(42, 1, 0, 100)
    assert len({canonical(o) for o in a}) == 300
    person = profile(42, 0)
    catalog = {'products': [{'productId': 'p1', 'productName': '静音键盘'}, {'productId': 'p2', 'productName': '陶瓷杯'}],
               'propertyValues': [{'productId': 'p1', 'propertyValueId': 'v1', 'propertyValue': '青轴'},
                                  {'productId': 'p2', 'propertyValueId': 'v2', 'propertyValue': '白色'}],
               'skus': [{'productId': 'p1', 'propertyValueIdHash': 'h1', 'propertyValueIds': 'v1'},
                        {'productId': 'p2', 'propertyValueIdHash': 'h2', 'propertyValueIds': 'v2'}]}
    terms = sku_terms(catalog)
    assert terms['p1', 'h1'] == ('青轴', '静音键盘') and terms['p2', 'h2'] == ('白色', '陶瓷杯')
    assert all(0 <= copy_fit(text, person, terms['p1', 'h1']) <= 1
               for text in ('静音键盘青轴手感', '推广：查看商品信息', ''))
    # No fixed sentence may score well on every SKU: the scorer and the agents share no vocabulary.
    generic = '推广：查看商品信息，按用途与预算选择适合的规格。'
    assert max(copy_fit(generic, person, terms[key]) for key in terms) < copy_fit('静音键盘青轴', person, terms['p1', 'h1'])
    assert choose(['a', 'b'], [1, 3], 0) == 'a' and choose(['a', 'b'], [1, 3], .5) == 'b'
    assert choose([], [], .2) is None
    assert 0 < math.prod(fit(person, 0, 1000)) <= 1
    summaries = [{'seed': 17, 'branch': branch, 'status': 'COMPLETED', 'summary': dict.fromkeys(
        ('paid_cents', 'refunded_cents', 'net_cents', 'ad_spend_cents', 'net_less_ads_cents'), 10 if branch == 'fixed' else 5)} for branch in BRANCHES]
    assert paired_report(summaries)['joint']['paired_differences'][0]['net_less_ads_cents'] == -5
    activation = {'activate_campaign', 'activate_creative'}
    assert set(branch_actions('fixed')) == activation
    assert set(branch_actions('recommendation')) == activation | {'set_recommendation_policy'}
    assert not set(AD_ACTIONS) & set(branch_actions('recommendation'))
    assert set(branch_actions('ads')) == activation | set(AD_ACTIONS)
    assert set(branch_actions('joint')) == activation | set(AD_ACTIONS) | {'set_recommendation_policy'}
    ledger = {'paidCents': 100, 'refundedCents': 0, 'paymentConversions': 1,
              'events': [{'status': 'APPLIED'}], 'exceptionMessages': 23}
    assert payment_watermark(ledger, 100, 0)
    assert not payment_watermark({**ledger, 'events': [{'status': 'RETRY'}]}, 100, 0)
    assert not payment_watermark(ledger, 99, 0)

    pending = {'plan_id': 'original-plan', 'version': 7, 'agent_run_id': 'original-run', 'observation_id': 'obs',
        'grant_id': 'grant', 'status': 'EXECUTING', 'spec': {'actions': [{'action_type': 'replace_creative'}]},
        'action_receipts': [{'command_status': 'unknown', 'action_id': 'original-action'}]}
    settled = {**pending, 'status': 'WAIT_OBSERVATION', 'action_receipts': [{'command_status': 'business_completed',
        'receipt': {'action_id': 'original-action', 'status': 'APPLIED', 'changes': [{'kind': 'creative',
            'action_type': 'replace_creative', 'before': {'copy_text': 'before'}, 'after': {'copy_text': 'after'}}]}}]}
    assert plan_pending(pending) and not plan_pending(settled)
    assert plan_pending({**settled, 'action_receipts': pending['action_receipts']})

    class Client:
        def __init__(self, response_kind):
            self.response_kind, self.current, self.calls = response_kind, deepcopy(pending), []
            self.evidence = {'optimization_attempts': []}
            self.objective, self.manifest, self.cap, self.grant = 'fixed objective', {'products': ['product']}, 400, {'grant_id': 'grant'}
            self.merchant = argparse.Namespace(timeout=httpx.Timeout(60))

        def save(self):
            pass

        def request(self, path, payload=None, **_options):
            self.calls.append((path, deepcopy(payload)))
            if path == 'merchant/runs':
                if self.response_kind == 'unchanged':
                    return {'unchanged_observation': True, 'latest_plan': deepcopy(settled)}
                if self.response_kind == 'new_run_unknown':
                    return {'agent_run_id': 'original-run'}
                return {'plan_recovery_required': True, 'latest_plan': deepcopy(pending)}
            if path == 'merchant/runs/original-run':
                return {'agent_run_id': 'original-run', 'state': 'WAIT_OUTCOME', 'result': {'execution_status': 'UNKNOWN'}}
            if path == 'merchant':
                current = deepcopy(self.current)
                if self.response_kind == 'version_changed': current['version'] = 8
                return {'plans': [current], 'observations': [{'observation_id': 'obs'}]}
            assert path == 'merchant/plans/original-plan/execute' and payload == {'expected_version': 7}
            if self.response_kind != 'still_unknown': self.current = deepcopy(settled)
            return deepcopy(self.current)

        def wait(self, read, predicate, _label, **_options):
            current = read()
            if not predicate(current): raise AssertionError('bounded fake wait expired')
            return current

    args = argparse.Namespace(rounds=2, mode='live')
    unchanged = Client('unchanged')
    optimize(unchanged, args, 'joint', 1)
    assert unchanged.evidence['optimization_attempts'][0]['status'] == 'WAIT_NEW_OBSERVATION'
    assert [p for p, _ in unchanged.calls] == ['merchant/runs']
    for kind in ('recover_existing', 'new_run_unknown'):
        client = Client(kind)
        optimize(client, args, 'joint', 1)
        record = client.evidence['optimization_attempts'][0]
        assert record['recovery']['status'] == 'RESOLVED' and record['plan']['version'] == 7
        assert [payload for path, payload in client.calls if path.endswith('/execute')] == [{'expected_version': 7}]
        assert sum(path == 'merchant/runs' for path, _ in client.calls) == 1  # Recovery never starts another model.
    for kind in ('still_unknown', 'version_changed'):
        client, traffic_after = Client(kind), []
        try:
            optimize(client, args, 'joint', 1)
            traffic_after.append('must_not_run')
        except PendingPlan:
            pass
        assert not traffic_after and client.evidence['pending_plan']['status'] == 'PENDING_RECOVERY'
        assert all(payload == {'expected_version': 7} for path, payload in client.calls if path.endswith('/execute'))
    incomplete = deepcopy(summaries)
    next(b for b in incomplete if b['branch'] == 'joint')['status'] = 'PENDING_RECOVERY'
    assert paired_report(incomplete)['joint']['seed_count'] == 0

    data, latest = {'transactions': [{'pay_order_id': 'old', 'status': 'PAYMENT_SCHEDULED'},
                                    {'pay_order_id': 'new', 'status': 'PAID'}]}, {}
    list(journal_changes(data, latest))
    data['transactions'][0].update(status='PAID', ledger={'paidCents': 100})
    changes = list(journal_changes(data, latest))
    assert len(changes) == 1 and changes[0]['component'] == 'transactions' and changes[0]['record']['index'] == 0
    assert changes[0]['record']['value']['ledger'] == {'paidCents': 100} and not list(journal_changes(data, latest))
    state = {'account': {'grant_id': 'grant', 'spent_cents': 0, 'budget_cap_cents': 400}, 'spend_cents': 0,
        'recommendation': {'control_strategy_version': 'rules-v1', 'treatment_strategy_version': 'rules-v1'},
        'impressions': 0, 'clicks': 0}
    client = argparse.Namespace(request=lambda *a, **k: state, cap=400, grant={'grant_id': 'grant'},
        evidence={'transactions': [], 'optimization_attempts': [{'plan': settled}, {'plan': settled}]})
    assert summarize(client)['realized_intervention_count'] == 1
    print('Comparison self-check passed: fixed draws, factor grants, scoped payment watermarks, original-plan recovery/UNKNOWN block, historical transaction journal, unique interventions and negative pairs.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('live', 'rule'), default='rule')
    parser.add_argument('--seeds', nargs='+', type=int, choices=SEEDS, default=list(SEEDS))
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--opportunities', type=int, default=300)
    parser.add_argument('--users', type=int, default=100)
    parser.add_argument('--products', type=int, default=20)
    parser.add_argument('--campaigns', type=int, default=6)
    parser.add_argument('--creatives', type=int, default=2)
    parser.add_argument('--repeat-id', type=int, default=1)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--progress', type=Path)
    options = parser.parse_args()
    if options.self_test:
        self_test()
    else:
        raise SystemExit(main(options))
