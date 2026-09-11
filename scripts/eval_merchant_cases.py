"""Five frozen Merchant workloads on isolated Java resources; one live run per case.

This driver never manages services or retries failed model plans. Bootstrap grants
and user confirmations are explicit simulated human actions. Final semantic review
is separate from deterministic receipt checks; --self-test performs no I/O to services.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import traceback
import uuid

from check_f3 import json_value
from check_f5 import ACTIONS, live_run_checks
from eval_comparison import business_change, manual_actions
from eval_rag import freeze_bindings
from runtime import ROOT
from scenario_client import ScenarioClient, now
from smartlect.agents.merchant import PROMPT_VERSION, SCHEMA_VERSION, _model_payload
from smartlect.business_skills import load_skill
from smartlect.events import canonical


MANIFEST = ROOT / 'evals/merchant-case-manifest.json'
FROZEN_MANIFEST = 'c951970f5ef80ad6280a8fad83ffc45225692d994a273b54344a27c295eaca01'
SOURCE_NAMES = ('agents/merchant.py', 'merchant/store.py', 'merchant/service.py',
                'ads/store.py', 'ads/service.py', 'ads/analytics.py', 'business_skills.py',
                'skills/campaign_plan.json', 'skills/performance_review.json', 'skills/creative_copy.json',
                'recommendation/store.py', 'provider.py', 'commerce.py', 'state.py', 'events.py')


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_value) + '\n')
    temporary.replace(path)


def contract():
    if digest(MANIFEST) != FROZEN_MANIFEST:
        raise ValueError('frozen_merchant_manifest_changed')
    value = json.loads(MANIFEST.read_text())
    if len(value['cases']) != 5 or [c['case_id'] for c in value['cases']] != value['case_order']:
        raise ValueError('five_distinct_ordered_cases_required')
    return value


def freeze_sources():
    source = {name: digest(ROOT / 'growth/src/smartlect' / name) for name in SOURCE_NAMES}
    installed = {name: sha256(files('smartlect').joinpath(name).read_bytes()).hexdigest() for name in SOURCE_NAMES}
    if source != installed:
        raise ValueError('installed_merchant_source_differs; install_before_evaluation')
    runtime = freeze_bindings('live')  # Source/installed/model metadata only; opens no case JSONL.
    return {'manifest_sha256': FROZEN_MANIFEST, 'merchant_sources': source,
            'runtime_bindings': runtime, 'merchant_model': merchant_model_settings(runtime),
            'drivers': {name: digest(ROOT / 'scripts' / name) for name in (
                'eval_merchant_cases.py', 'scenario_client.py', 'check_f5.py', 'eval_comparison.py')},
            'prompt_version': PROMPT_VERSION, 'schema_version': SCHEMA_VERSION,
            'skills': {name: load_skill(name, domain='merchant') for name in (
                'campaign_plan', 'performance_review', 'creative_copy')},
            'index_applicability': 'Merchant structured facts; no RAG index or question set is used.'}


def merchant_model_settings(runtime):
    model = {**runtime['model'], 'max_completion_tokens': 3000, 'max_attempts_per_run': 4,
             'response_format_type': 'json_object', 'function_tool_count': 0, 'dimensions': None}
    host = model.get('endpoint_host') or ''
    model['region'] = host.split('.')[1] if '.maas.aliyuncs.com' in host else {
        'dashscope.aliyuncs.com': 'cn-beijing', 'dashscope-intl.aliyuncs.com': 'ap-southeast-1',
        'dashscope-us.aliyuncs.com': 'us-east-1'}.get(host, 'unknown')
    return model


def actual_versions_match(context, spec, frozen):
    versions = context.get('skill_versions') or {}
    attempts = context.get('model_attempts') or []
    expected = frozen['merchant_model']
    skill_match = bool(versions) and spec.get('skill_versions') == versions and all(
        frozen['skills'].get(name, {}).get('version') == version for name, version in versions.items())
    model_match = bool(attempts) and type(context.get('model_calls')) is int and 1 <= context['model_calls'] <= expected['max_attempts_per_run']
    for attempt in attempts:
        skill_match = skill_match and attempt.get('skill_versions') == versions
        model_match = model_match and all(attempt.get(key) == expected[key] for key in (
            'model_id', 'region', 'enable_search', 'enable_thinking', 'stream')) and all(
            (attempt.get('request_parameters') or {}).get(key) == expected[key] for key in (
                'temperature', 'max_completion_tokens', 'response_format_type', 'function_tool_count', 'dimensions')) and (
            attempt.get('prompt_version') == frozen['prompt_version'] and attempt.get('schema_version') == frozen['schema_version']
            and type(attempt.get('attempt')) is int and 1 <= attempt['attempt'] <= expected['max_attempts_per_call'])
    return bool(skill_match), bool(model_match)


class MerchantCaseClient(ScenarioClient):
    def record(self, key, value):
        self.evidence.setdefault(key, []).append(value)
        self.save()
        return value

    def request(self, path, payload=None, **options):
        if payload is not None and (path.endswith('/confirm') or path.startswith('payments/') and path.endswith('/complete')):
            self.record('explicit_user_confirmations', {'path': path, 'request': payload,
                'actor_id': self.session['userId'], 'confirmed_at': now()})
        result = super().request(path, payload, **options)
        if path != 'scopes/select' and not path.endswith('/session'):
            self.record('http_receipts', {'path': path, 'request': payload, 'options': options,
                'response': result, 'observed_at': now()})
        return result

    def java_call(self, service, path, data, *, user=False):
        row = self.record('java_http_receipts', {'service': service, 'path': path,
            'request': data, 'actor_id': self.session['userId'] if user else None, 'started_at': now()})
        row['response'] = self.java.request(service, path, data=data, session=self.session if user else None)
        row['completed_at'] = now()
        self.save()
        return row['response']

    def stock(self, sku):
        return self.java_call('stock', '/internal/stock/getBatch', [{
            'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}])[0]['stock']

    def orders(self):
        return self.java_call('order', '/internal/order/commerce/listOrders', {'limit': 30}, user=True)

    def events(self, ids):
        rows = self.wait(lambda: self.rows('SELECT * FROM commerce_event WHERE event_id IN (' +
            ','.join(['%s'] * len(ids)) + ')', tuple(ids)),
            lambda values: len(values) == len(ids) and all(v['status'] == 'APPLIED' for v in values),
            'Wait for the declared Java event IDs to be APPLIED', timeout=45)
        self.record('consumed_java_events', {'requested_event_ids': ids, 'rows': rows, 'observed_at': now()})
        return rows


def bootstrap(client, protocol):
    settings = protocol['bootstrap']
    client.sku = next(s for s in client.catalog['skus'] if s['productId'] == client.manifest['products'][0])
    client.campaign_id, client.creative_id = uuid.uuid4().hex, uuid.uuid4().hex
    client.check(not client.request('ads', merchant=True)['campaigns'], 'Fresh case has independent advertising resources')
    campaign = client.request('ads/campaigns', {'campaign_id': client.campaign_id, 'name': client.evidence['case_id'],
        'product_id': client.sku['productId'], 'sku_key': client.sku['propertyValueIdHash'],
        'budget_cents': settings['campaign_budget_cents'], 'cpc_cents': settings['cpc_cents']}, merchant=True)
    creative = client.request('ads/creatives', {'creative_id': client.creative_id, 'campaign_id': client.campaign_id,
        'copy_text': '推广：查看实际商品规格，结合用途与预算选择。'}, merchant=True)
    request = {'grant_id': uuid.uuid4().hex, 'initial_plan_id': 'merchant-eval-bootstrap-' + uuid.uuid4().hex,
        'initial_plan_version': 1, 'expected_campaign_versions': {client.campaign_id: campaign['version']},
        'expected_creative_versions': {client.creative_id: creative['version']},
        'envelope': {'objective': protocol['objective'], 'product_scope': client.manifest['products'],
            'allowed_action_types': ACTIONS, 'budget_cap_cents': settings['scope_budget_cap_cents'],
            'max_budget_change_cents': settings['max_budget_change_cents'],
            'valid_until': (datetime.now(timezone.utc) + timedelta(hours=settings['grant_hours'])).isoformat(),
            'recommendation_policy_range': {'rankings': ['rule', 'content'], 'groups': ['all'], 'max_weight': 20, 'max_quota': 20}}}
    client.evidence['explicit_merchant_approval'] = {'request': request,
        'role': 'local evaluation driver explicitly approves the saved bootstrap resources and stable envelope'}
    client.save()
    client.grant = client.request('ads/grants', request, merchant=True)
    client.check(client.grant['envelope_hash'] == sha256(canonical(client.grant['envelope']).encode()).hexdigest(),
                 'Initial approval persists the exact stable envelope hash')
    activation = manual_actions(client, client.grant, [
        {'action_type': 'activate_campaign', 'campaign_id': client.campaign_id, 'expected_version': campaign['version']},
        {'action_type': 'activate_creative', 'campaign_id': client.campaign_id, 'creative_id': client.creative_id,
         'expected_version': creative['version']}], reason='merchant_eval_explicit_bootstrap')
    client.check(activation['status'] == 'APPLIED', 'Explicit bootstrap authorization enables the saved resources')
    client.evidence.update(bootstrap_receipt=activation, approved_grant=client.grant,
        advertised_sku=client.sku, initial_stock=client.stock(client.sku))
    client.save()


def traffic(client, impressions, clicks):
    row = client.record('traffic_rounds', {'impressions_requested': impressions, 'clicks_requested': clicks,
                                         'exposures': [], 'clicks': [], 'started_at': now()})
    for index in range(impressions):
        exposure = client.request('ads/exposures', {'exposure_id': uuid.uuid4().hex, 'creative_id': client.creative_id})
        row['exposures'].append(exposure)
        if index < clicks:
            charged = client.request('ads/clicks', {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']})
            client.check(charged['status'] == 'CHARGED' and charged['amount_cents'] == 1,
                         'A declared click incurs exactly one real local CPC cent')
            row['clicks'].append(charged)
        if (index + 1) % 25 == 0:
            print(f"{client.evidence['case_id']}: {index + 1}/{impressions} actual exposures", flush=True)
    row['completed_at'] = now()
    client.save()


def confirmed_order(client, quantity):
    conversation = client.conversation()
    proposal = client.propose(conversation, 'order', {'payMethod': 'mock', 'addressId': client.session['addressId'],
        'orderFrom': 0, 'orderList': [{'productId': client.sku['productId'],
            'propertyValueIds': client.sku['propertyValueIds'], 'buyCount': quantity}]})
    row = client.record('user_transactions', {'conversation_id': conversation, 'quantity': quantity,
        'order_proposal': proposal, 'state': 'AWAITING_EXPLICIT_CONFIRMATION'})
    row['order'] = client.confirm(proposal)
    row['payment'] = client.request('payments/' + row['order']['receipt']['payOrderId'])
    client.check(row['payment']['paymentStatus'] == 'PENDING', 'A confirmed order alone is unpaid, not a payment failure')
    row['state'] = 'CONFIRMED_UNPAID'
    client.save()
    return row


def cancel_watermark_matches(rows, *, user_id, order_id, pay_order_id, scope):
    if len(rows) != 1:
        return False
    event = rows[0]
    # Legacy Java CANCEL has no pay_order_id; its original order+owner still bind it.
    return (event.get('event_type') == 'CANCEL' and event.get('status') == 'APPLIED'
            and event.get('source') == 'ORDER' and event.get('amount_cents') is None
            and event.get('user_id') == user_id and event.get('order_id') == order_id
            and event.get('pay_order_id') in {None, pay_order_id} and event.get('frozen_scope') == scope)


def construct_case(client, case):
    traffic(client, case['fixture']['impressions'], case['fixture']['clicks'])
    operation = case['fixture']['operation']
    if operation == 'reserve_all_stock_unpaid':
        row = confirmed_order(client, client.evidence['initial_stock'])
        client.check(client.stock(client.sku) == 0, 'Java confirmed full-stock reservation leaves zero available stock')
        client.evidence['stockout_unpaid_reservation'] = row
    elif operation == 'java_decline_and_separate_cancel':
        row = confirmed_order(client, 1)
        request = {'attemptId': uuid.uuid4().hex, 'payOrderId': row['order']['receipt']['payOrderId']}
        decline = client.java_call('pay', '/internal/pay/mock/decline', request, user=True)
        recovered = client.java_call('pay', '/internal/pay/mock/attempt', request, user=True)
        client.check(decline == recovered and decline['attemptStatus'] == 'DECLINED'
                     and decline['reasonCode'] == 'MOCK_CHANNEL_DECLINED' and decline['paymentMode'] == 'mock'
                     and decline['currency'] == 'CNY' and decline['attemptedAmountCents'] == row['order']['receipt']['amountCents']
                     and decline['attemptId'] == request['attemptId'] and decline['payOrderId'] == request['payOrderId']
                     and decline['userId'] == client.session['userId'] and bool(decline['occurredAt']),
                     'Original Java attempt query recovers the exact owned DECLINED amount, time, reason and IDs')
        client.evidence['java_decline'] = decline
        client.events([decline['eventId']])
        cancelled = confirmed_order(client, 1)
        order = next(o for o in client.orders() if o['payOrderId'] == cancelled['order']['receipt']['payOrderId'])
        proposal = client.propose(cancelled['conversation_id'], 'cancel', {'orderId': order['orderId']})
        cancelled['cancel'] = client.confirm(proposal)
        client.check(cancelled['cancel']['receipt']['stockRestored'], 'Separate cancellation restores its own stock reservation')
        rows = client.wait(lambda: client.rows("SELECT e.*,m.execution_scope_id AS frozen_scope FROM commerce_event e "
            "LEFT JOIN commerce_attribution_meta m USING(event_id) WHERE e.user_id=%s AND e.order_id=%s AND e.event_type='CANCEL'",
            (client.session['userId'], order['orderId'])), lambda values: cancel_watermark_matches(values,
                user_id=client.session['userId'], order_id=order['orderId'], pay_order_id=order['payOrderId'], scope=client.scope),
            'Wait for the separate Java CANCEL watermark', timeout=45)
        ids = [event['event_id'] for event in rows]
        client.record('consumed_java_events', {'requested_event_ids': ids, 'rows': rows, 'observed_at': now()})
        client.evidence['cancel_negative_control'] = {'transaction': cancelled, 'event_ids': ids, 'events': rows,
            'expected': {'user_id': client.session['userId'], 'order_id': order['orderId'],
                         'pay_order_id': order['payOrderId'], 'execution_scope_id': client.scope}}
        row['payment_after_decline_and_separate_cancel'] = client.request('payments/' + request['payOrderId'])
        client.check(row['payment_after_decline_and_separate_cancel']['paymentStatus'] == 'PENDING',
                     'DECLINED does not convert its pending payment intent into paid or cancelled')
    elif operation == 'one_payment_and_full_refund':
        row = confirmed_order(client, 1)
        item = client.pay(row['order'])
        amount = row['order']['receipt']['amountCents']
        proposal = client.propose(row['conversation_id'], 'refund', {'orderItemId': item['orderItemId'],
            'refundAmountCents': amount, 'reason': '固定经营评测：单样本全额退款'})
        row['refund_proposal'], row['refund'] = proposal, client.confirm(proposal)
        client.check(row['refund']['receipt']['refundStatus'] == 'COMPLETED', 'Refund is Java COMPLETED, not merely accepted')
        row['ledger'] = client.wait(lambda: client.ledger.summary(row['order']['receipt']['payOrderId']),
            lambda r: r['paidCents'] == r['refundedCents'] == amount and r['paymentConversions'] == 1,
            'Wait for one actual payment and its full-refund ledger', timeout=45)
        row['attribution'] = client.wait(lambda: client.request('attribution', merchant=True,
            params={'payOrderId': row['order']['receipt']['payOrderId']}),
            lambda r: len(r['events']) == 2 and all(e['calculation_status'] == 'FINAL' for e in r['events']),
            'Wait for original payment/refund campaign attribution', timeout=45)
        events = row['attribution']['events']
        client.check({e['event_type'] for e in events} == {'PAYMENT', 'REFUND'} and all(
            e['campaign_id'] == client.campaign_id and e['execution_scope_id'] == client.scope
            and e['amount_cents'] == amount for e in events), 'Both financial facts retain the actual campaign and exact cents')
        client.events([e['event_id'] for e in events])
        client.wait(lambda: client.stock(client.sku), lambda stock: stock == client.evidence['initial_stock'],
                    'Wait for Java full-refund stock restoration', timeout=45)
        client.evidence['refund_sample'] = {'paid_orders': 1, 'refunded_orders': 1,
            'paid_cents': amount, 'refunded_cents': amount, 'net_cents': 0,
            'financial_population_or_causal_maturity': False}
    client.evidence['before_model'] = {'ads': client.request('ads', merchant=True),
        'java_stock': client.stock(client.sku), 'java_orders': client.orders(), 'observed_at': now()}
    client.save()


def run_once(client, protocol):
    record = client.record('model_runs', {'domain': 'merchant', 'started_at': now(), 'request': {
        'request_id': uuid.uuid4().hex, 'objective': protocol['objective'], 'mode': 'live',
        'product_scope': client.manifest['products'], 'planned_budget_cents': protocol['bootstrap']['scope_budget_cap_cents']}})
    record['created_run'] = client.request('merchant/runs', record['request'], merchant=True)
    identifier = record['created_run'].get('agent_run_id')
    if not identifier:
        record['completed_at'] = now()
        return record
    record['agent_run_id'] = identifier
    def read():
        record['run'] = client.request('merchant/runs/' + identifier, merchant=True)
        client.save()
        return record['run']
    client.wait(read, lambda run: run['state'] not in {'CREATED', 'RUNNING'}, 'One bounded live Merchant run', timeout=95)
    snapshot = client.request('merchant', merchant=True)
    record['plan'] = next((p for p in snapshot['plans'] if p['agent_run_id'] == identifier), None)
    context_rows = client.rows('SELECT context_json FROM merchant_run_context WHERE agent_run_id=%s AND execution_scope_id=%s',
                               (identifier, client.scope))
    record['persisted_input_context'] = json.loads(context_rows[0]['context_json']) if context_rows else None
    observation_id = (record['persisted_input_context'] or {}).get('observation_id')
    record['observation'] = next((o for o in snapshot['observations'] if o['observation_id'] == observation_id), None)
    record['completed_at'] = now()
    if record['observation'] and record['persisted_input_context']:
        source = {**record['persisted_input_context'], 'observation': record['observation'], 'previous_plan': None,
                  'approved_experiences': [], 'ads': client.evidence['before_model']['ads']}
        record['model_payload_reconstruction'] = _model_payload(source)
        record['input_capture_limit'] = ('Request, immutable observation, persisted plan metadata and pre-request ads/grant '
            'are captured. The payload is reconstructed with frozen source; exact provider message bytes are not retained by runtime. '
            'This fresh scope has no prior Merchant plan or approved experience.')
    client.save()
    return record


def observe_after(client):
    started_at = now()
    before = client.request('ads', merchant=True)
    probe = client.request('ads/exposures', {'exposure_id': uuid.uuid4().hex, 'creative_id': client.creative_id},
                           accepted=(200, 403, 409))
    after = client.request('ads', merchant=True)
    payments = [{'pay_order_id': row['order']['receipt']['payOrderId'],
        'receipt': client.request('payments/' + row['order']['receipt']['payOrderId'])}
        for row in client.evidence.get('user_transactions', [])]
    observation = {'type': 'post_action_http_observation', 'started_at': started_at, 'ads_before_probe': before,
        'actual_exposure_probe': probe, 'ads_after_probe': after, 'java_stock': client.stock(client.sku),
        'java_orders': client.orders(), 'java_payments': payments, 'completed_at': now(), 'merchant_replan_invoked': False,
        'interpretation': 'A real new exposure or inventory-protected rejection plus subsequent HTTP/Java reads; '
                          'not a fabricated persisted Merchant snapshot, model rerun, conversion or benefit.'}
    decline = client.evidence.get('java_decline')
    if decline:
        observation['original_decline_after_run'] = client.java_call('pay', '/internal/pay/mock/attempt',
            {key: decline[key] for key in ('attemptId', 'payOrderId')}, user=True)
    observation['completed_at'] = now()
    client.evidence['post_action_observation'] = observation
    client.save()
    return observation


def exact_fact_links(diagnosis, facts):
    """Projection integrity only; reference-only proposals bind values on the server.

    Matching compiled values is not a score for model arithmetic or prose understanding.
    Required metrics below still measure the model-selected IDs; no IDs are added.
    """
    linked = []
    for item in diagnosis.get('observed_facts', []):
        original = facts.get(item.get('evidence_id'))
        if (original is None or item['evidence_id'] not in diagnosis.get('evidence_ids', [])
                or original['metric'] != item.get('metric') or type(original['value']) is not type(item.get('value'))
                or original['value'] != item['value']):
            return None
        linked.append(original)
    return linked


def assess(case, data, protocol):
    record = data['model_runs'][0] if data.get('model_runs') else {}
    run, plan, obs = record.get('run') or {}, record.get('plan') or {}, record.get('observation') or {}
    spec, context = plan.get('spec') or {}, run.get('context') or {}
    actions, diagnoses = spec.get('actions', []), spec.get('diagnosis', [])
    facts = {f['evidence_id']: f for f in obs.get('facts', [])}
    links = [exact_fact_links(d, facts) for d in diagnoses]
    relevant = [f for d, items in zip(diagnoses, links) if items is not None and d['code'] in case['diagnosis_codes'] for f in items]
    metrics = {f['metric'] for f in relevant}
    summary, fixture = obs.get('summary') or {}, case['fixture']
    values = {f['metric']: f['value'] for f in facts.values()}
    post = data.get('post_action_observation') or {}
    after, before = post.get('ads_after_probe') or {}, data.get('before_model', {}).get('ads') or {}
    probe, probe_before = post.get('actual_exposure_probe') or {}, post.get('ads_before_probe') or {}
    checks = {'one_run': len(data.get('model_runs', [])) == 1 and bool(run),
        'one_plan': bool(plan) and run.get('state') != 'FAILED',
        'actual_mode_live': (run.get('result') or {}).get('model_mode') == spec.get('model_mode') == 'live',
        'exact_fact_links': bool(diagnoses) and all(items is not None for items in links)
            and all(set(d.get('evidence_ids', [])) <= set(facts) for d in diagnoses),
        'required_observed_metrics': set(case['required_metrics']) <= metrics,
        'finite_allowed_actions': len(actions) <= 8 and all(a['action_type'] in case['allowed_candidate_actions'] for a in actions),
        'original_traffic_counts': summary.get('impressions') == fixture['impressions'] and summary.get('clicks') == fixture['clicks'],
        'no_invented_financial_facts': summary.get('payment_failures') == int(case['case_id'] == 'm-payment-failure')
            and summary.get('cancelled_orders') == int(case['case_id'] == 'm-payment-failure'),
        'source_versions_bound': context.get('prompt_version') == data['freeze']['prompt_version']
            and context.get('schema_version') == data['freeze']['schema_version'],
        'post_action_http_observation': bool(post) and bool(after),
        'stable_grant_and_cumulative_spend': bool(after.get('account')) and
            after['account']['grant_id'] == data['approved_grant']['grant_id'] and
            after['account']['spent_cents'] == before.get('account', {}).get('spent_cents') == fixture['clicks']
            and after['account']['budget_cap_cents'] == protocol['bootstrap']['scope_budget_cap_cents']
            and after['account']['reservations_cents'] == 0 and len(after.get('grants', [])) == 1}
    if after.get('grants'):
        checks['unchanged_authorization_envelope'] = all(after['grants'][0].get(key) == data['approved_grant'].get(key)
            for key in ('grant_id', 'envelope_hash', 'envelope'))
    checks['actual_skill_versions_bound'], checks['actual_model_parameters_bound'] = actual_versions_match(context, spec, data['freeze'])
    if 'http_status' in probe:
        checks['new_traffic_receipt_matches'] = probe.get('body', {}).get('error') in {
            'ads_not_active', 'ads_budget_exhausted', 'fresh_positive_stock_required'} and (
            after.get('impressions') == probe_before.get('impressions'))
    else:
        creative = next((c for c in probe_before.get('creatives', []) if c['creative_id'] == probe.get('creative_id')), {})
        checks['new_traffic_receipt_matches'] = bool(probe.get('exposure_id')) and (
            after.get('impressions') == probe_before.get('impressions', 0) + 1
            and probe.get('creative_version') == creative.get('version')
            and probe.get('copy_text') == creative.get('copy_text'))
    try:
        live_run_checks(record)
        checks['bounded_live_provider_trace'] = True
    except (AssertionError, KeyError, TypeError):
        checks['bounded_live_provider_trace'] = False
    receipts = plan.get('action_receipts', [])
    changes = [change for r in receipts if r.get('receipt', {}).get('status') == 'APPLIED'
               for change in r['receipt'].get('changes', [])]
    checks['execution_receipts'] = plan.get('status') in {'WAIT_OBSERVATION', 'REVIEWED'} and (
        not actions and not receipts or bool(actions) and len(changes) == len(actions)
        and all(r.get('command_status') == 'business_completed' and r.get('receipt', {}).get('status') == 'APPLIED' for r in receipts))
    if actions:
        checks['action_authorization'] = plan.get('grant_id') == data['approved_grant']['grant_id']
    if case['case_id'] == 'm-stockout':
        checks['stockout_protected_unpaid'] = values.get('stock') == post.get('java_stock') == 0 and all(
            c['status'] != 'ACTIVE' for c in after.get('campaigns', [])) and 'http_status' in probe and (
            len(post.get('java_payments', [])) == 1 and post['java_payments'][0]['receipt']['paymentStatus'] == 'PENDING')
    elif case['case_id'] == 'm-creative-fatigue':
        checks['low_ctr_screen_only'] = values.get('impressions') == 250 and values.get('clicks') == 1
    elif case['case_id'] == 'm-payment-failure':
        decline = data.get('java_decline') or {}
        checks['authoritative_decline_link'] = decline.get('attemptStatus') == 'DECLINED' and decline.get('reasonCode') == 'MOCK_CHANNEL_DECLINED' and any(
            f['metric'] == 'payment_failures' and f['kind'] == 'payment_attempt' and f['value'] == 1
            and decline.get('eventId') in f.get('source_ids', []) for f in relevant)
        checks['decline_remains_separate_from_cancel'] = post.get('original_decline_after_run') == decline and any(
            row['pay_order_id'] == decline.get('payOrderId') and row['receipt']['paymentStatus'] == 'PENDING'
            for row in post.get('java_payments', []))
    elif case['case_id'] == 'm-refund-risk':
        sample = data.get('refund_sample') or {}
        checks['one_real_refund_sample'] = values.get('paid_cents') == values.get('refunded_cents') == sample.get('paid_cents') and (
            type(sample.get('paid_cents')) is int and sample['paid_cents'] > 0 and values.get('payment_conversions') == 1)
        checks['no_risk_budget_increase'] = all(a['budget_cents'] <= protocol['bootstrap']['campaign_budget_cents']
            for a in actions if a['action_type'] == 'set_budget')
    changed = [c for c in changes if business_change(c)]
    return {'deterministic_checks': checks, 'deterministic_checks_passed': all(checks.values()),
        'actual_mode': (run.get('result') or {}).get('model_mode', 'not_completed'),
        'action_outcome': 'NO_PLAN' if not plan else 'NO_ACTION_REQUIRES_SEMANTIC_REVIEW' if not actions else
            'APPLIED_CHANGED' if changed and checks['execution_receipts'] else
            'APPLIED_NO_CHANGE' if checks['execution_receipts'] else 'NOT_COMPLETED',
        'proposed_action_count': len(actions), 'applied_action_count': len(changes), 'changed_action_count': len(changed),
        'exact_fact_references': relevant, 'semantic_review': {'status': 'PENDING_INDEPENDENT_REVIEW',
            'rubric': case, 'instructions': protocol['semantic_review']},
        'semantic_pass': None, 'causal_or_uplift_claim_supported': False}


def main(args):
    protocol = contract()
    if args.seed not in protocol['seeds'] or args.repeat_id not in protocol['repeat_ids']:
        raise ValueError('seed_must_be_1_2_3_and_repeat_id_1_2')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    frozen = freeze_sources()
    write(args.output_dir / 'freeze.json', {'created_at': now(), 'protocol': protocol, 'bindings': frozen})
    run_id = 'merchant-eval-' + uuid.uuid4().hex
    result = {'phase': 'F6-merchant-cases', 'run_id': run_id, 'started_at': now(), 'status': 'RUNNING',
        'seed': args.seed, 'repeat_id': args.repeat_id, 'requested_mode': args.mode, 'case_files': [],
        'formal_f6_complete': False, 'semantic_review_complete': False}
    write(args.output_dir / 'summary.json', result)
    resources = set()
    for case in protocol['cases']:
        path = args.output_dir / (case['case_id'] + '.json')
        data = {'case_id': case['case_id'], 'run_id': run_id, 'scenario': case['case_id'], 'seed': args.seed,
            'repeat_id': args.repeat_id, 'status': 'RUNNING', 'created_at': now(), 'expected': case, 'freeze': frozen}
        # ponytail: five cases and at most 250 exposures; use an append-only journal if this workload grows.
        def save(): write(path, data)
        save()
        client = None
        try:
            if freeze_sources() != frozen: raise ValueError('frozen_source_changed_mid_suite')
            client = MerchantCaseClient(data, save, requested_mode=args.mode)
            client.setup()
            owned = {('scope', client.scope), *[('user', u['userId']) for u in client.manifest['users']],
                     *[('product', p) for p in client.manifest['products']]}
            client.check(not (owned & resources), 'This case shares no Java user, product, inventory owner or scope with an earlier case')
            resources.update(owned)
            bootstrap(client, protocol)
            construct_case(client, case)
            run_once(client, protocol)
            observe_after(client)
            data['scores'] = assess(case, data, protocol)
            data['scores']['deterministic_checks']['source_unchanged_after_case'] = freeze_sources() == frozen
            data['scores']['deterministic_checks_passed'] = all(data['scores']['deterministic_checks'].values())
            data['status'] = 'AWAITING_SEMANTIC_REVIEW' if data['scores']['deterministic_checks_passed'] else 'FAILED'
        except Exception as error:
            data.update(status='FAILED', error_type=type(error).__name__, failure_frames=[
                {'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                for frame in traceback.extract_tb(error.__traceback__)])
            if isinstance(error, AssertionError): data['assertion'] = str(error)
            data['recovery'] = 'Keep original request IDs, model attempts and business outcomes. Do not retry with another prompt or overwrite this directory.'
        finally:
            if client: client.close()
            data['finished_at'] = now()
            save()
        result['case_files'].append({'case_id': case['case_id'], 'path': str(path), 'sha256': digest(path),
            'status': data['status'], 'actual_mode': data.get('scores', {}).get('actual_mode', 'not_completed')})
        write(args.output_dir / 'summary.json', result)
    result.update(finished_at=now(), status='AWAITING_SEMANTIC_REVIEW' if all(
        c['status'] == 'AWAITING_SEMANTIC_REVIEW' for c in result['case_files']) else 'FAILED',
        counts=dict(Counter(c['status'] for c in result['case_files'])))
    write(args.output_dir / 'summary.json', result)
    print(json.dumps({'status': result['status'], 'counts': result['counts'], 'output': str(args.output_dir)}), flush=True)
    return int(result['status'] == 'FAILED')


def self_test():
    value = contract()
    assert len(set(value['case_order'])) == 5 and value['model_runs_per_case'] == 1
    assert value['repeat_ids'] == [1, 2]
    fact = {'evidence_id': 'java-attempt', 'kind': 'payment_attempt', 'metric': 'payment_failures', 'value': 1,
            'source_ids': ['event-1']}
    diagnosis = {'code': 'payment_failures', 'evidence_ids': ['java-attempt'],
                 'observed_facts': [{'evidence_id': 'java-attempt', 'metric': 'payment_failures', 'value': 1}]}
    assert exact_fact_links(diagnosis, {'java-attempt': fact}) == [fact]
    for changed in ({**fact, 'metric': 'cancelled_orders'}, {**fact, 'value': None}, {**fact, 'value': 2}, {**fact, 'value': True}):
        assert exact_fact_links(diagnosis, {'java-attempt': changed}) is None
    assert exact_fact_links({**diagnosis, 'evidence_ids': []}, {'java-attempt': fact}) is None
    assert not value['cases'][-1]['allowed_candidate_actions']
    original_cancel = {'event_type': 'CANCEL', 'status': 'APPLIED', 'source': 'ORDER', 'amount_cents': None,
        'user_id': 'user', 'order_id': 'cancelled-order', 'pay_order_id': None, 'frozen_scope': 'owned-scope'}
    original_ids = {'user_id': 'user', 'order_id': 'cancelled-order', 'pay_order_id': 'cancelled-pay', 'scope': 'owned-scope'}
    assert cancel_watermark_matches([original_cancel], **original_ids)
    assert not cancel_watermark_matches([], **original_ids)
    for field, wrong in (('order_id', 'declined-order'), ('pay_order_id', 'declined-pay'), ('frozen_scope', 'store'),
                         ('status', 'PENDING'), ('event_type', 'PAYMENT_ATTEMPT'), ('amount_cents', 1)):
        assert not cancel_watermark_matches([{**original_cancel, field: wrong}], **original_ids)

    def sample(case):
        # In-memory evaluator inputs only; these objects are never saved as business evidence.
        fixture = case['fixture']
        metrics = {'stock': 0 if case['case_id'] == 'm-stockout' else 5,
            'impressions': fixture['impressions'], 'clicks': fixture['clicks'],
            'paid_cents': 100 if case['case_id'] == 'm-refund-risk' else 0,
            'refunded_cents': 100 if case['case_id'] == 'm-refund-risk' else 0,
            'payment_conversions': int(case['case_id'] == 'm-refund-risk'),
            'payment_failures': int(case['case_id'] == 'm-payment-failure'),
            'cancelled_orders': int(case['case_id'] == 'm-payment-failure')}
        facts = [{'evidence_id': name, 'metric': name, 'value': number,
                  'kind': 'payment_attempt' if name == 'payment_failures' else 'ads',
                  'source_ids': ['java-decline'] if name == 'payment_failures' else ['source-' + name]}
                 for name, number in metrics.items()]
        spec = {'model_mode': 'live', 'actions': [], 'diagnosis': [{'code': case['diagnosis_codes'][0],
            'evidence_ids': case['required_metrics'], 'observed_facts': [
                {'evidence_id': name, 'metric': name, 'value': metrics[name]} for name in case['required_metrics']]}]}
        context = {'prompt_version': PROMPT_VERSION, 'schema_version': SCHEMA_VERSION,
            'model_calls': 1, 'plan_repairs': 0, 'context_bytes': 100, 'context_limit_bytes': 36000,
            'skill_versions': {'campaign_plan': '1', 'performance_review': '1'}, 'model_attempts': [
                {'status': 'succeeded', 'model_mode': 'live', 'model_id': 'qwen3.7-plus',
                 'usage': {'input_tokens': 10, 'output_tokens': 10}}]}
        frozen_model = merchant_model_settings({'model': {'model_id': 'qwen3.7-plus',
            'endpoint_host': 'dashscope.aliyuncs.com', 'temperature': 0, 'enable_search': False,
            'enable_thinking': False, 'stream': False, 'max_attempts_per_call': 2,
            'max_attempts_per_run': 6, 'max_completion_tokens': 1600}})
        spec['skill_versions'] = dict(context['skill_versions'])
        context['model_attempts'][0].update(region='cn-beijing', enable_search=False, enable_thinking=False,
            stream=False, attempt=1, prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
            skill_versions=dict(context['skill_versions']), request_parameters={key: frozen_model[key] for key in (
                'temperature', 'max_completion_tokens', 'response_format_type', 'function_tool_count', 'dimensions')})
        account = {'grant_id': 'grant', 'spent_cents': fixture['clicks'], 'budget_cap_cents': 400, 'reservations_cents': 0}
        grant = {'grant_id': 'grant', 'envelope_hash': 'fixed-hash', 'envelope': {'budget_cap_cents': 400}}
        ads = {'account': account, 'impressions': fixture['impressions'], 'grants': [deepcopy(grant)],
            'campaigns': [{'status': 'PAUSED' if metrics['stock'] == 0 else 'ACTIVE'}],
            'creatives': [{'creative_id': 'creative', 'version': 2, 'copy_text': '推广：核对规格。'}]}
        after = deepcopy(ads)
        if metrics['stock'] == 0:
            probe = {'http_status': 409, 'body': {'error': 'fresh_positive_stock_required'}}
        else:
            after['impressions'] += 1
            probe = {'exposure_id': 'next-exposure', 'creative_id': 'creative', 'creative_version': 2,
                     'copy_text': '推广：核对规格。'}
        decline = {'attemptStatus': 'DECLINED', 'reasonCode': 'MOCK_CHANNEL_DECLINED', 'eventId': 'java-decline', 'payOrderId': 'pay'}
        return {'freeze': {'prompt_version': PROMPT_VERSION, 'schema_version': SCHEMA_VERSION,
            'merchant_model': frozen_model, 'skills': {name: {'version': version} for name, version in context['skill_versions'].items()}},
            'approved_grant': grant, 'before_model': {'ads': ads}, 'java_decline': decline,
            'refund_sample': {'paid_cents': 100}, 'model_runs': [{'run': {'state': 'WAIT_OUTCOME', 'context': context,
                'result': {'model_mode': 'live'}}, 'plan': {'spec': spec, 'status': 'WAIT_OBSERVATION',
                'action_receipts': [], 'grant_id': 'grant'}, 'observation': {'facts': facts, 'summary': metrics}}],
            'post_action_observation': {'ads_before_probe': ads, 'ads_after_probe': after,
                'actual_exposure_probe': probe, 'java_stock': metrics['stock'], 'original_decline_after_run': decline,
                'java_payments': [{'pay_order_id': 'pay', 'receipt': {'paymentStatus': 'PENDING'}}]}}

    for case in value['cases']:
        scored = assess(case, sample(case), value)
        assert scored['deterministic_checks_passed'], scored['deterministic_checks']
        assert scored['action_outcome'] == 'NO_ACTION_REQUIRES_SEMANTIC_REVIEW'
        assert scored['applied_action_count'] == 0 and scored['semantic_pass'] is None
    bound = sample(value['cases'][1])
    assert bound['freeze']['merchant_model']['max_completion_tokens'] == 3000
    assert bound['freeze']['merchant_model']['max_attempts_per_run'] == 4
    changed = deepcopy(bound)
    changed['model_runs'][0]['run']['context']['skill_versions']['campaign_plan'] = 'different'
    assert not assess(value['cases'][1], changed, value)['deterministic_checks']['actual_skill_versions_bound']
    for field, altered in (('region', 'ap-southeast-1'), ('enable_thinking', True), ('model_id', 'unapproved-model')):
        changed = deepcopy(bound)
        changed['model_runs'][0]['run']['context']['model_attempts'][0][field] = altered
        assert not assess(value['cases'][1], changed, value)['deterministic_checks']['actual_model_parameters_bound']
    changed = deepcopy(bound)
    changed['model_runs'][0]['run']['context']['model_attempts'][0]['request_parameters']['max_completion_tokens'] = 1600
    assert not assess(value['cases'][1], changed, value)['deterministic_checks']['actual_model_parameters_bound']
    changed = deepcopy(bound)
    changed['model_runs'][0]['run']['context']['model_calls'] = 5
    assert not assess(value['cases'][1], changed, value)['deterministic_checks']['actual_model_parameters_bound']
    payment = sample(value['cases'][2])
    next(f for f in payment['model_runs'][0]['observation']['facts'] if f['metric'] == 'payment_failures')['kind'] = 'commerce'
    assert not assess(value['cases'][2], payment, value)['deterministic_checks']['authoritative_decline_link']
    trial = sample(value['cases'][1])
    plan = trial['model_runs'][0]['plan']
    plan['spec']['actions'] = [{'action_type': 'replace_creative'}]
    plan['status'], plan['action_receipts'] = 'EXECUTING', [{'command_status': 'unknown', 'action_id': 'original'}]
    failed = assess(value['cases'][1], trial, value)
    assert not failed['deterministic_checks_passed'] and failed['action_outcome'] == 'NOT_COMPLETED'
    unchanged = {'kind': 'creative', 'action_type': 'replace_creative',
                 'before': {'copy_text': 'same'}, 'after': {'copy_text': 'same'}}
    plan['status'], plan['action_receipts'] = 'WAIT_OBSERVATION', [{
        'command_status': 'business_completed', 'receipt': {'status': 'APPLIED', 'changes': [unchanged]}}]
    scored = assess(value['cases'][1], trial, value)
    assert scored['action_outcome'] == 'APPLIED_NO_CHANGE' and scored['changed_action_count'] == 0
    trial['model_runs'][0]['plan'] = None
    assert assess(value['cases'][1], trial, value)['action_outcome'] == 'NO_PLAN'
    changed_budget = sample(value['cases'][1])
    changed_budget['post_action_observation']['ads_after_probe']['account']['spent_cents'] = 0
    assert not assess(value['cases'][1], changed_budget, value)['deterministic_checks']['stable_grant_and_cumulative_spend']
    changed_budget['post_action_observation']['ads_after_probe']['grants'][0]['envelope_hash'] = 'expanded'
    assert not assess(value['cases'][1], changed_budget, value)['deterministic_checks']['unchanged_authorization_envelope']
    print('Merchant evaluation self-test passed: five cases, exact fact types, authoritative decline, safe no-action, UNKNOWN and no-op receipts. No services or model calls.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['live'], default='live')
    parser.add_argument('--seed', type=int, choices=[1, 2, 3], default=1)
    parser.add_argument('--repeat-id', type=int, choices=[1, 2], default=1)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--self-test', action='store_true')
    options = parser.parse_args()
    if options.self_test:
        self_test()
    else:
        if options.output_dir is None: parser.error('--output-dir is required and must not already exist')
        raise SystemExit(main(options))
