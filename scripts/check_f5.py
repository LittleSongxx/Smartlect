"""F5 persisted Merchant gate: real qwen plans, local CPC and Java mock decline.

Run serially after the application and worker are ready. This driver starts no
services and changes no Java tables. Java creates a fresh owned scenario; only
Growth's resource registry is populated locally from its returned manifest.
Every business change then uses the existing authenticated HTTP APIs. The local
driver explicitly represents merchant grant approval and user confirmations.
No outcome is rewritten or retried with another prompt to make live gates pass.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import traceback
import uuid

import httpx

from check_f3 import json_value, proposal_from
from check_f4 import login_merchant
from demo import wait_for
from runtime import ROOT, ENV_FILE, parse_env
from smartlect.commerce import CommerceClient
from smartlect.events import Ledger, canonical, connect_from_env
from smartlect.merchant.store import MerchantStore


OBJECTIVE = ('在所选商品范围和累计模拟预算内启动草稿活动与素材，依据实际新观测审慎经营；'
             '库存不足先保护；当达到素材曝光门槛且点击占比低时，安排一次授权内的素材试验。'
             '素材试验按曝光门槛判断，不因点击量低于预算调整门槛而跳过；预算和推荐策略仍按各自门槛。'
             '支付失败或退款先核对权威事实，'
             '禁止臆测原因、扩大授权或保证增收。')
ACTIONS = ['activate_campaign', 'activate_creative', 'resume_campaign', 'resume_creative',
           'pause_campaign', 'pause_creative', 'set_budget', 'replace_creative', 'set_recommendation_policy']


def live_run_checks(record):
    run = record['run']
    context = run.get('context') or {}
    attempts = context.get('model_attempts', [])
    completed = [a for a in attempts if a.get('status') != 'started']
    succeeded = [a for a in completed if a.get('status') == 'succeeded' and a.get('model_mode') == 'live']
    assert record['plan']['spec']['model_mode'] == run['result']['model_mode'] == 'live', 'Fallback is not live evidence'
    assert succeeded and all(a['model_id'] == 'qwen3.7-plus' for a in succeeded), 'Actual configured qwen trace required'
    assert 1 <= context['model_calls'] <= 4 and context.get('plan_repairs', 0) <= 1, 'Bounded model calls and repair required'
    assert len(completed) == context['model_calls'], 'Every actual provider attempt must leave a final trace'
    assert all(type(a['usage']['input_tokens']) is int and type(a['usage']['output_tokens']) is int
               for a in succeeded), 'Successful live calls must report actual token usage'
    assert context['context_bytes'] <= context['context_limit_bytes'] <= 36000, 'Context limit must be recorded and enforced'
    assert context['skill_versions'].get('campaign_plan') and context['skill_versions'].get('performance_review')
    assert len(record['plan']['spec']['actions']) <= 8, 'Plan action bound exceeded'

def payment_diagnosis_supported(record, event_id):
    facts = [f for f in record['observation']['facts'] if f['kind'] == 'payment_attempt'
             and f['metric'] == 'payment_failures' and type(f['value']) is int and f['value'] == 1
             and event_id in f['source_ids']]
    return len(facts) == 1 and any(
        d['code'] in {'payment_failures', 'other'} and facts[0]['evidence_id'] in d['evidence_ids']
        and any(f['evidence_id'] == facts[0]['evidence_id'] and f['metric'] == 'payment_failures'
                and type(f['value']) is int and f['value'] == 1 for f in d['observed_facts'])
        for d in record['plan']['spec']['diagnosis'])


def main(output, progress):
    if output.resolve() == progress.resolve() or output.exists() or progress.exists():
        print('Choose distinct, unused --output and --progress paths; previous evidence is preserved.', flush=True)
        return 1
    scenario = 'f5-' + uuid.uuid4().hex
    evidence = {'phase': 'F5', 'fixture_version': 'merchant-controlled-creative-trial-v2', 'scenario_run_id': scenario, 'branch_id': 'merchant-live',
        'status': 'RUNNING', 'java_http': True, 'payment_mode': 'mock',
        'ad_mode': 'persisted_simulated_cpc', 'requested_model_mode': 'live',
        'merchant_confirmation': 'local driver explicitly approves the saved plan and immutable grant envelope',
        'user_confirmation': 'local driver explicitly confirms its own Java order and later cancellation',
        'model_runs': [], 'traffic_rounds': [], 'checks': [],
        'scope': 'F5 live plan/execute/replan and Java decline evidence; no conversion-uplift claim'}

    def write(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=json_value) + '\n')
        temporary.replace(path)

    def save():
        write(progress)

    def stage(label):
        evidence['stage'] = label
        save()
        print(label, flush=True)

    def rows(sql, params=()):
        with connect_from_env() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def http(client, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == 200, f'{method} {path}: HTTP {response.status_code}'
        return response.json()


    try:
        config = parse_env(ENV_FILE)
        assert config.get('SMARTLECT_PAYMENT_MODE') == 'mock', 'Only mock payment is authorized'
        for key, value in config.items():
            if key.startswith(('SMARTLECT_GROWTH_MYSQL_', 'SMARTLECT_MYSQL_')):
                os.environ[key] = value
        preserved = {path: hashlib.sha256(path.read_bytes()).hexdigest()
            for pattern in ('f1-*.json', 'f2-*.json', 'f3-*.json', 'f4-*.json')
            for path in (ROOT / 'artifacts').glob(pattern)}
        java, store, ledger = CommerceClient(config), MerchantStore(), Ledger()
        stage('Java creates isolated scenario resources; register only Growth-owned scope mappings')
        seed = {'scenarioRunId': scenario, 'branchId': evidence['branch_id'], 'userCount': 3,
                'productCount': 2, 'initialStock': 5}
        evidence['seed_request'] = seed
        save()
        manifest = java.request('admin', '/internal/demo/scenario/seed', data=seed)
        evidence['java_manifest'] = manifest
        scope = manifest['executionScopeId']
        evidence['execution_scope_id'] = scope
        save()
        assert java.request('admin', '/internal/demo/scenario/read', data={'executionScopeId': scope}) == manifest
        assert manifest['scenarioRunId'] == scenario and manifest['branchId'] == evidence['branch_id']
        assert (len(manifest['users']), len(manifest['products']), len(manifest['skus'])) == (3, 2, 4)
        store.register_scope(scope, scenario_run_id=scenario, branch_id=evidence['branch_id'],
            users=[u['userId'] for u in manifest['users']], products=manifest['products'])
        user = java.request('admin', '/internal/demo/scenario/session', data={
            'executionScopeId': scope, 'userIndex': 0, 'password': config['SMARTLECT_DEMO_PASSWORD']})
        evidence['user_id'] = user['userId']  # Cookie and password deliberately never enter evidence.
        catalogue = java.request('product', '/internal/product/snapshotBatch', data={'productIds': manifest['products']})['skus']
        sku = next(s for s in catalogue if s['productId'] == manifest['products'][0]
                   and s['propertyValueIdHash'] == manifest['skus'][0]['propertyValueIdHash'])

        def stock():
            return java.request('stock', '/internal/stock/getBatch', data=[{
                'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}])[0]['stock']

        base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
        with httpx.Client(base_url=base, timeout=25, trust_env=False) as merchant, \
                httpx.Client(base_url=base, timeout=25, trust_env=False) as browser:
            merchant_headers = login_merchant(merchant, config)
            original_actor = http(merchant, 'GET', '/admin-api/assistant/session')['actor']
            store.grant_scope_access(original_actor['actor_id'], scope, scenario)
            selected = http(merchant, 'POST', '/admin-api/assistant/scopes/select',
                json={'execution_scope_id': scope}, headers=merchant_headers)
            assert selected['actor']['execution_scope_id'] == scope
            merchant_headers = {'Origin': base, 'X-CSRF-Token': selected['csrf_token']}
            browser.cookies.set('token', user['token'])
            session = http(browser, 'GET', '/api/assistant/session')
            assert session['actor']['execution_scope_id'] == scope and session['actor']['actor_id'] == user['userId']
            assert session['model_mode'] == 'live', 'Configure the existing Growth provider for live before running this gate'
            headers = {'Origin': base, 'X-CSRF-Token': session['csrf_token']}

            def post(path, payload):
                return http(browser, 'POST', '/api/assistant/' + path, json=payload, headers=headers)

            def mpost(path, payload):
                return http(merchant, 'POST', '/admin-api/assistant/' + path, json=payload, headers=merchant_headers)

            def ads():
                return http(merchant, 'GET', '/admin-api/assistant/ads')

            def merchant_state():
                return http(merchant, 'GET', '/admin-api/assistant/merchant')

            def run_model(label, *, require_plan=True):
                stage(label)
                request = {'request_id': uuid.uuid4().hex, 'objective': OBJECTIVE, 'mode': 'live',
                           'product_scope': manifest['products'], 'planned_budget_cents': 400}
                record = {'label': label, 'request': request}
                evidence['model_runs'].append(record)
                save()
                created = mpost('merchant/runs', request)
                record['created_run'] = created
                save()
                assert created.get('agent_run_id'), 'New external observation must produce a new bounded run'

                def observe_run():
                    run = http(merchant, 'GET', '/admin-api/assistant/merchant/runs/' + created['agent_run_id'])
                    record['run'] = run
                    save()
                    return run

                final = wait_for(observe_run, lambda value: value['state'] not in {'CREATED', 'RUNNING'},
                                 label, timeout=95)
                state = merchant_state()
                record['plan'] = next((p for p in state['plans'] if p['agent_run_id'] == created['agent_run_id']), None)
                if record['plan']:
                    record['observation'] = next(o for o in state['observations']
                                               if o['observation_id'] == record['plan']['observation_id'])
                save()
                if require_plan:
                    assert final['state'] != 'FAILED' and record['plan'], 'Merchant run must save a usable plan'
                return record

            def flow(label, impressions):
                stage(label)
                record = {'label': label, 'exposures': [], 'pending_exposure_request': None}
                evidence['traffic_rounds'].append(record)
                for index in range(impressions):
                    request = {'exposure_id': uuid.uuid4().hex, 'creative_id': creative_id}
                    record['pending_exposure_request'] = request
                    save()
                    exposure = post('ads/exposures', request)
                    assert exposure['amount_cents'] == 0 and exposure['ad_label']
                    record['exposures'].append({k: exposure[k] for k in (
                        'exposure_id', 'creative_version', 'campaign_version', 'last_action_id', 'created_at')})
                    if index == 0:
                        record['first_exposure'] = exposure
                        record['click_request'] = {'click_id': uuid.uuid4().hex, 'exposure_id': request['exposure_id']}
                        save()
                        click = post('ads/clicks', record['click_request'])
                        record['click'] = click
                        save()
                        assert click['status'] == 'CHARGED' and click['amount_cents'] == 1
                        assert post('ads/clicks', record['click_request']) == click, 'Click replay must recover the original receipt'
                    record['pending_exposure_request'] = None
                    if (index + 1) % 25 == 0:
                        print(f'{label}: {index + 1}/{impressions} persisted exposures', flush=True)
                    save()
                record['account_after'] = ads()['account']
                save()
                return record

            stage('Save exactly one DRAFT campaign and creative through the merchant API')
            initial = ads()
            assert initial['account'] is None and not initial['campaigns'], 'Fresh Java scenario must have independent advertising state'
            campaign_id, creative_id = uuid.uuid4().hex, uuid.uuid4().hex
            evidence.update(campaign_id=campaign_id, creative_id=creative_id)
            save()
            campaign = mpost('ads/campaigns', {'campaign_id': campaign_id, 'name': scenario,
                'product_id': sku['productId'], 'sku_key': sku['propertyValueIdHash'], 'budget_cents': 300, 'cpc_cents': 1})
            creative = mpost('ads/creatives', {'creative_id': creative_id, 'campaign_id': campaign_id,
                'copy_text': '推广：查看商品规格，选择适合自己用途的款式。'})
            evidence['draft'] = {'campaign': campaign, 'creative': creative}
            assert campaign['status'] == creative['status'] == 'DRAFT'
            first = run_model('Live initial plan reads Java stock and requests merchant approval')
            live_run_checks(first)
            plan = first['plan']
            assert plan['status'] == 'WAIT_APPROVAL' and first['run']['state'] == 'WAIT_USER'
            assert {'activate_campaign', 'activate_creative'} <= {a['action_type'] for a in plan['spec']['actions']}
            assert first['observation']['summary']['payment_failures'] == 0
            assert ads()['account'] is None and ads()['campaigns'][0]['status'] == 'DRAFT'

            stage('Merchant explicitly approves this immutable live plan and a stable cumulative grant')
            review = ads()
            request = {'grant_id': uuid.uuid4().hex, 'initial_plan_id': plan['plan_id'],
                'initial_plan_version': plan['version'], 'merchant_plan_id': plan['plan_id'],
                'expected_campaign_versions': {c['campaign_id']: c['version'] for c in review['campaigns']},
                'expected_creative_versions': {c['creative_id']: c['version'] for c in review['creatives']},
                'envelope': {'objective': OBJECTIVE, 'product_scope': manifest['products'],
                    'allowed_action_types': ACTIONS, 'budget_cap_cents': 400, 'max_budget_change_cents': 100,
                    'valid_until': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    'recommendation_policy_range': {'rankings': ['rule', 'content'], 'groups': ['control', 'treatment'],
                                                    'max_weight': 5, 'max_quota': 8}}}
            evidence['grant_request'] = request
            save()
            grant = mpost('ads/grants', request)
            evidence['approved_grant'] = grant
            save()
            assert grant['plan_snapshot']['merchant_plan_spec'] == plan['spec']
            assert grant['envelope_hash'] == hashlib.sha256(canonical(grant['envelope']).encode()).hexdigest()
            assert grant['plan_snapshot_hash'] == hashlib.sha256(canonical(grant['plan_snapshot']).encode()).hexdigest()
            assert mpost('ads/grants', request) == grant, 'Repeated approval must return original grant'
            executed = mpost('merchant/plans/' + plan['plan_id'] + '/execute', {'expected_version': plan['version']})
            evidence['initial_execution'] = executed
            save()
            assert executed['status'] == 'WAIT_OBSERVATION' and executed['grant_id'] == grant['grant_id']
            assert executed['action_receipts'] and all(r['receipt']['status'] == 'APPLIED' for r in executed['action_receipts'])
            assert mpost('merchant/plans/' + plan['plan_id'] + '/execute', {'expected_version': plan['version']}) == executed
            assert ads()['account']['spent_cents'] == 0
            first_flow = flow('Actual first traffic: mature exposure sample and a single paid click', 250)
            assert first_flow['account_after']['spent_cents'] == 1

            second = run_model('Live replan consumes new traffic and changes creative within the original grant')
            live_run_checks(second)
            second_plan = second['plan']
            assert second_plan['parent_plan_id'] == plan['plan_id'] and second_plan['parent_plan_version'] == plan['version']
            assert second['run']['parent_run_id'] == first['run']['agent_run_id']
            assert second_plan['observation_id'] != plan['observation_id']
            assert second['observation']['watermark'] != first['observation']['watermark']
            summary = second['observation']['summary']
            assert summary['impressions'] == 250 and summary['clicks'] == 1 and summary['spend_cents'] == 1
            assert summary['clicks'] * 200 < summary['impressions'], 'Observed CTR must be below half a percent'
            assert second_plan['status'] == 'WAIT_OBSERVATION' and second_plan['grant_id'] == grant['grant_id']
            assert second_plan['authorization']['within_grant'] and second_plan['envelope_hash'] == grant['envelope_hash']
            replacements = [r['receipt'] for r in second_plan['action_receipts'] if r.get('receipt')
                            and any(c['action_type'] == 'replace_creative' for c in r['receipt'].get('changes', []))]
            assert replacements and all(r['status'] == 'APPLIED' for r in replacements), 'Live new observation must cause a real creative change'
            assert second['run']['context']['skill_versions'].get('creative_copy'), 'Creative Skill must be loaded on demand'

            stage('Unchanged external observation must not start another model call or reset spend')
            before_wait = merchant_state()
            waiting = mpost('merchant/runs', {'request_id': uuid.uuid4().hex, 'objective': OBJECTIVE, 'mode': 'live',
                'product_scope': manifest['products'], 'planned_budget_cents': 400})
            after_wait = merchant_state()
            evidence['unchanged_observation'] = {'response': waiting, 'runs_before': before_wait['runs'],
                'runs_after': after_wait['runs'], 'account_before': before_wait['account'], 'account_after': after_wait['account']}
            save()
            assert waiting['unchanged_observation'] and waiting['state'] == 'WAIT_OUTCOME' and not waiting.get('agent_run_id')
            assert before_wait['runs'] == after_wait['runs'], 'No new observation must leave every persisted model-call trace unchanged'
            assert before_wait['account'] == after_wait['account'] and after_wait['account']['spent_cents'] == 1
            next_flow = flow('Next actual traffic uses the applied creative version and new receipts', 1)
            assert next_flow['first_exposure']['creative_version'] > first_flow['first_exposure']['creative_version']
            assert next_flow['first_exposure']['copy_text'] != first_flow['first_exposure']['copy_text']
            assert next_flow['first_exposure']['creative_last_action_id'] in {r['action_id'] for r in replacements}
            assert next_flow['click']['click_id'] != first_flow['click']['click_id']
            assert next_flow['click']['creative_version'] == next_flow['first_exposure']['creative_version']
            assert next_flow['account_after']['spent_cents'] == 2 and next_flow['account_after']['grant_id'] == grant['grant_id']

            stage('User explicitly confirms a new Java order; unpaid is not payment failure')
            conversation = post('conversations', {})['conversation_id']
            evidence['conversation_id'] = conversation
            initial_stock = stock()
            proposed = proposal_from(post('conversations/' + conversation + '/proposals', {
                'message_id': scenario + '-order', 'action_type': 'order', 'parameters': {
                    'payMethod': 'mock', 'addressId': user['addressId'], 'orderFrom': 0,
                    'orderList': [{'productId': sku['productId'], 'propertyValueIds': sku['propertyValueIds'], 'buyCount': 1}]}}))
            evidence['order_proposal'] = proposed
            evidence['initial_stock'] = initial_stock
            save()
            assert proposed['status'] == 'PROPOSED' and stock() == initial_stock

            def confirm(proposal):
                return proposal_from(post('proposals/' + proposal['proposal_id'] + '/confirm', {
                    'proposal_version': proposal.get('decision_version') or proposal['version'], 'approved': True}))

            ordered = wait_for(lambda: confirm(proposed), lambda value: value['status'] in {'SUCCEEDED', 'FAILED'}, 'confirmed Java order')
            evidence['order_result'] = ordered
            save()
            assert ordered['status'] == 'SUCCEEDED'
            receipt = ordered['receipt']
            pay_id = receipt['payOrderId']
            evidence['pay_order_id'] = pay_id
            save()
            assert confirm(proposed)['receipt'] == receipt
            wait_for(stock, lambda value: value == initial_stock - 1, 'order inventory deduction')
            pending = http(browser, 'GET', '/api/assistant/payments/' + pay_id)
            evidence['pending_payment_before_attempt'] = pending
            assert pending['paymentStatus'] == 'PENDING'
            assert not rows("SELECT event_id FROM commerce_event WHERE user_id=%s AND event_type='PAYMENT_ATTEMPT'", (user['userId'],))

            stage('Java mock provider commits a DECLINED attempt; replay and v2 consumer preserve one fact')
            decline_request = {'attemptId': uuid.uuid4().hex, 'payOrderId': pay_id}
            evidence['decline_request'] = decline_request
            save()
            decline = java.request('pay', '/internal/pay/mock/decline', session=user, data=decline_request)
            evidence['java_decline'] = decline
            save()
            assert decline['attemptStatus'] == 'DECLINED' and decline['paymentMode'] == 'mock'
            assert decline['reasonCode'] == 'MOCK_CHANNEL_DECLINED' and decline['attemptedAmountCents'] == receipt['amountCents']
            assert java.request('pay', '/internal/pay/mock/decline', session=user, data=decline_request) == decline
            assert java.request('pay', '/internal/pay/mock/attempt', session=user, data=decline_request) == decline
            attempt_events = wait_for(lambda: rows('SELECT * FROM commerce_event WHERE event_id=%s', (decline['eventId'],)),
                lambda values: len(values) == 1 and values[0]['status'] == 'APPLIED', 'PAYMENT_ATTEMPT worker watermark')
            evidence['payment_attempt_events'] = attempt_events
            fact = attempt_events[0]
            assert fact['schema_version'] == 2 and fact['source'] == 'PAYMENT_PROVIDER'
            assert fact['event_type'] == 'PAYMENT_ATTEMPT' and fact['amount_cents'] is None
            assert json.loads(fact['raw_json'])['payload']['attemptId'] == decline_request['attemptId']
            assert http(browser, 'GET', '/api/assistant/payments/' + pay_id)['paymentStatus'] == 'PENDING'
            assert stock() == initial_stock - 1, 'Decline itself must not change payment or stock authority'
            third = run_model('Live diagnosis reads the committed Java payment attempt', require_plan=False)

            stage('User explicitly confirms cancellation; inventory restores and original decline remains queryable')
            orders = java.request('order', '/internal/order/commerce/listOrders', session=user, data={'limit': 100})
            order = next(o for o in orders if o['payOrderId'] == pay_id)
            cancellation = proposal_from(post('conversations/' + conversation + '/proposals', {
                'message_id': scenario + '-cancel', 'action_type': 'cancel', 'parameters': {'orderId': order['orderId']}}))
            evidence['cancel_proposal'] = cancellation
            save()
            cancelled = wait_for(lambda: confirm(cancellation), lambda value: value['status'] in {'SUCCEEDED', 'FAILED'}, 'confirmed Java cancellation')
            evidence['cancel_result'] = cancelled
            save()
            assert cancelled['status'] == 'SUCCEEDED' and cancelled['receipt']['stockRestored']
            assert confirm(cancellation)['receipt'] == cancelled['receipt']
            evidence['final_stock'] = wait_for(stock, lambda value: value == initial_stock, 'cancel inventory restoration')
            evidence['decline_after_cancellation'] = java.request('pay', '/internal/pay/mock/attempt', session=user, data=decline_request)
            assert evidence['decline_after_cancellation'] == decline
            assert java.request('pay', '/internal/pay/mock/decline', session=user, data=decline_request) == decline
            evidence['cancel_events'] = wait_for(lambda: rows(
                "SELECT * FROM commerce_event WHERE user_id=%s AND order_id=%s AND event_type='CANCEL'",
                (user['userId'], order['orderId'])), lambda values: len(values) == 1 and values[0]['status'] == 'APPLIED',
                'separate Java cancellation worker watermark')
            final_attempts = rows("SELECT * FROM commerce_event WHERE user_id=%s AND event_type='PAYMENT_ATTEMPT'", (user['userId'],))
            assert len(final_attempts) == 1 and final_attempts[0] == fact, 'Replay and cancellation must not add or mutate a failure fact'
            evidence['ledger'] = ledger.summary(pay_id)
            assert evidence['ledger']['paidCents'] == evidence['ledger']['refundedCents'] == evidence['ledger']['netCents'] == 0
            assert third['plan'] and third['run']['state'] != 'FAILED', 'Payment diagnosis must save a usable live plan'
            live_run_checks(third)
            assert third['plan']['parent_plan_id'] == second_plan['plan_id']
            failures = [f for f in third['observation']['facts'] if f['kind'] == 'payment_attempt' and f['metric'] == 'payment_failures']
            assert len(failures) == 1 and failures[0]['value'] == 1 and decline['eventId'] in failures[0]['source_ids']
            diagnoses = third['plan']['spec']['diagnosis']
            assert payment_diagnosis_supported(third, decline['eventId']), 'Live diagnosis must cite the Java decline fact and its observed failure count'
            assert third['observation']['summary']['cancelled_orders'] == 0, 'Diagnosis precedes the later user cancellation'
            final = ads()
            evidence['ads_final'] = final
            assert final['account']['grant_id'] == grant['grant_id'] and final['account']['spent_cents'] == 2
            assert final['account']['budget_cap_cents'] == 400 and len(final['grants']) == 1
            assert final['account']['reservations_cents'] == 0 and final['spend_cents'] == 2
            evidence['model_usage'] = [attempt for record in evidence['model_runs']
                for attempt in record['run'].get('context', {}).get('model_attempts', []) if attempt.get('status') != 'started']
            evidence['model_cost_estimate_cny'] = sum(a['cost_estimate_cny'] for a in evidence['model_usage']
                                                    if a.get('cost_estimate_cny') is not None)
            evidence['unpriced_model_attempts'] = sum(a.get('cost_estimate_cny') is None for a in evidence['model_usage'])
            assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in preserved.items())
            evidence.update(status='PASSED', prior_evidence_preserved=True, checks=[
                'isolated Java-owned scenario and authenticated merchant scope selection',
                'actual qwen bounded initial plan waits for explicit merchant approval',
                'immutable saved plan/grant then idempotent deterministic activation',
                'real mature low-CTR traffic changes next live plan and applies under the same grant',
                'unchanged external observation invokes no model and preserves cumulative spend',
                'new exposure/click use changed creative and receipts; cumulative CPC grows from one to two cents',
                'Java DECLINED attempt is idempotent, consumed as v2 behavior, and cited by the live diagnosis',
                'unpaid and later cancellation are separate facts; cancellation restores inventory and retains decline',
                'actual provider usage and modes retained; no revenue or causal improvement claimed'])
            write(output)
            save()
            print('F5 API gate passed: ' + str(output), flush=True)
            return 0
    except Exception as error:
        evidence.update(status='FAILED', error_type=type(error).__name__)
        evidence['failure_frames'] = [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                                     for frame in traceback.extract_tb(error.__traceback__)]
        if isinstance(error, AssertionError):
            # Our assertion strings and wait payloads contain only these owned, credential-free receipts.
            evidence['assertion'] = str(error)
        evidence['recovery'] = 'Retain saved request IDs, Java outcomes, model traces and already charged CPC; inspect before retrying.'
        write(output)
        save()
        location = evidence['failure_frames'][-1] if evidence['failure_frames'] else None
        print('F5 gate failed at ' + evidence.get('stage', 'initialization') + ': ' + type(error).__name__
              + (f" ({location['file']}:{location['line']})" if location else ''), flush=True)
        return 1


def audit_recorded(source, output):
    """Reconcile a recorded execution after correcting an over-specific category assertion.

    Both successful and unsuccessful semantic results are retained. No new model,
    commerce operation, exposure, click or grant is issued by this audit.
    """
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError('Use a new audit output; recorded evidence cannot be overwritten')
    raw = source.read_bytes()
    evidence = json.loads(raw)
    result = {'source': str(source), 'source_sha256': hashlib.sha256(raw).hexdigest(),
              'original_status': evidence['status'], 'status': 'FAILED', 'new_business_writes': 0,
              'criterion': 'authoritative event reference and exact failure count; payment_failures or other classification'}
    try:
        assert evidence['status'] == 'FAILED' and evidence.get('assertion', '').startswith('Live diagnosis must cite the Java decline fact')
        assert len(evidence['model_runs']) == 3
        for record in evidence['model_runs']:
            live_run_checks(record)
        supported = payment_diagnosis_supported(evidence['model_runs'][-1], evidence['java_decline']['eventId'])
        result['payment_diagnosis_supported'] = supported
        assert supported, 'The recorded live response omitted the required Java decline fact'
        config = parse_env(ENV_FILE)
        assert config['SMARTLECT_PAYMENT_MODE'] == 'mock'
        java = CommerceClient(config)
        # Session establishment and scope selection change authentication state only.
        user = java.request('admin', '/internal/demo/scenario/session', data={
            'executionScopeId': evidence['execution_scope_id'], 'userIndex': 0,
            'password': config['SMARTLECT_DEMO_PASSWORD']})
        assert user['userId'] == evidence['user_id']
        attempt = java.request('pay', '/internal/pay/mock/attempt', session=user, data=evidence['decline_request'])
        assert attempt == evidence['java_decline'] == evidence['decline_after_cancellation']
        campaign = evidence['draft']['campaign']
        stock = java.request('stock', '/internal/stock/getBatch', data=[{
            'productId': campaign['product_id'], 'propertyValueIdHash': campaign['sku_key']}])[0]['stock']
        assert stock == evidence['initial_stock'] == evidence['final_stock']
        assert evidence['cancel_result']['status'] == 'SUCCEEDED' and evidence['cancel_result']['receipt']['stockRestored']
        base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
        with httpx.Client(base_url=base, timeout=25, trust_env=False) as merchant:
            headers = login_merchant(merchant, config)
            selected = merchant.post('/admin-api/assistant/scopes/select',
                json={'execution_scope_id': evidence['execution_scope_id']}, headers=headers)
            assert selected.status_code == 200
            response = merchant.get('/admin-api/assistant/ads')
            assert response.status_code == 200
            final = response.json()
        grant = evidence['approved_grant']
        assert final['account']['grant_id'] == grant['grant_id'] and final['account']['spent_cents'] == 2
        assert final['account']['budget_cap_cents'] == 400 and len(final['grants']) == 1
        assert final['account']['reservations_cents'] == 0 and final['spend_cents'] == 2
        assert final['clicks'] == 2
        for key, value in config.items():
            if key.startswith(('SMARTLECT_GROWTH_MYSQL_', 'SMARTLECT_MYSQL_')):
                os.environ[key] = value
        ledger = Ledger().summary(evidence['pay_order_id'])
        assert ledger['paidCents'] == ledger['refundedCents'] == ledger['netCents'] == 0
        assert ledger['events'] == evidence['ledger']['events']
        result.update(status='RECORDED_PATH_VALIDATED', ads_final=final, ledger=ledger, stock=stock,
                      java_attempt=attempt, confirmed_source_unchanged=source.read_bytes() == raw)
    except AssertionError as error:
        result['assertion'] = str(error)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=json_value) + '\n')
    print(result['status'] + ': ' + str(output), flush=True)
    return 0 if result['status'] == 'RECORDED_PATH_VALIDATED' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/f5-live-merchant.json')
    parser.add_argument('--progress', type=Path, default=ROOT / 'artifacts/local/f5-progress.json')
    parser.add_argument('--audit-recorded', type=Path, help='Reconcile a recorded category-assertion failure without new business writes')
    args = parser.parse_args()
    raise SystemExit(audit_recorded(args.audit_recorded, args.output) if args.audit_recorded else main(args.output, args.progress))
