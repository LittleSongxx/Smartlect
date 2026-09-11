"""F4 API advertising gate: real persisted CPC, Java transactions, simulated money only.

The driver explicitly acts as the approving local merchant and confirming user.
It reads only its newly requested CAPTCHA from Smartlect Redis, then uses normal
Java login and the same cookie/CSRF advertising APIs as the frontend. It never
creates synthetic advertising touchpoints or writes Java transaction tables.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback
import uuid

import httpx

from check_f3 import json_value, proposal_from
from demo import cents, wait_for
from runtime import ROOT, ENV_FILE, parse_env
from smartlect.commerce import CommerceClient
from smartlect.events import Ledger, canonical, connect_from_env


def login_merchant(client, config):
    challenge = client.post('/admin-api/account/checkCode')
    challenge.raise_for_status()
    challenge = challenge.json()
    assert challenge['code'] == 200, 'Java CAPTCHA request failed'
    key = challenge['data']['checkCodeKey']
    # Only the one newly requested local CAPTCHA is read; no credential appears in argv or evidence.
    env = {**os.environ, 'REDISCLI_AUTH': config['SMARTLECT_REDIS_PASSWORD']}
    response = subprocess.run(['docker', 'exec', '-e', 'REDISCLI_AUTH', 'smartlect-redis-1',
        'redis-cli', '--raw', 'GET', 'smartlect:checkcode:' + key],
        env=env, capture_output=True, text=True, timeout=10)
    assert response.returncode == 0, 'Local CAPTCHA lookup failed'
    captcha = json.loads(response.stdout)
    assert isinstance(captcha, str) and captcha.isdigit(), 'Local CAPTCHA value unavailable'
    result = client.post('/admin-api/account/login', data={
        'account': config.get('SMARTLECT_ADMIN_ACCOUNT', 'admin'),
        'password': config['SMARTLECT_ADMIN_PASSWORD'], 'checkCode': captcha, 'checkCodeKey': key})
    assert result.status_code == 200 and result.json()['code'] == 200, 'Java merchant login failed'
    auth = client.get('/admin-api/assistant/session')
    assert auth.status_code == 200, 'Merchant session bridge failed'
    auth = auth.json()
    assert auth['actor']['subject_type'] == 'merchant' and 'admin:legacy' in auth['actor']['permissions']
    return {'Origin': str(client.base_url).rstrip('/'), 'X-CSRF-Token': auth['csrf_token']}


def check_restart(evidence, output):
    """Restart only our API, then recover a previously charged (now paused) click."""
    config = parse_env(ENV_FILE)
    java = CommerceClient(config)
    session = java.request('admin', '/internal/demo/session', form={
        'userIndex': 78, 'password': config['SMARTLECT_DEMO_PASSWORD']})
    assert session['userId'] == evidence['user_id']
    base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
    click = evidence['rounds'][-1]['click']
    request = {k: click[k] for k in ('click_id','exposure_id')}
    with httpx.Client(base_url=base,timeout=25,trust_env=False) as user, httpx.Client(base_url=base,timeout=25,trust_env=False) as merchant:
        user.cookies.set('token',session['token'])
        auth = user.get('/api/assistant/session').json()
        headers = {'Origin':base,'X-CSRF-Token':auth['csrf_token']}
        login_merchant(merchant,config)
        before = merchant.get('/admin-api/assistant/ads').json()
        first = user.post('/api/assistant/ads/clicks',json=request,headers=headers)
        assert first.status_code == 200 and first.json() == click
        runtime_code = "from runtime import *; env=parse_env(ENV_FILE); records=load_processes(); stop_process(records['growth']); start_app('growth',env,records); wait_apps(['growth'],records)"
        subprocess.run(['/usr/bin/python3','-c',runtime_code],cwd=ROOT/'scripts',check=True,timeout=120)
        replay = user.post('/api/assistant/ads/clicks',json=request,headers=headers)
        assert replay.status_code == 200 and replay.json() == click
        after = merchant.get('/admin-api/assistant/ads').json()
        for field in ('account','campaigns','creatives','impressions','clicks','spend_cents'):
            assert before[field] == after[field], 'Restart/replay changed ' + field
    result = {'api_restarted':True,'paused_revoked_grant_click_replayed_exactly':True,
              'account_before':before['account'],'account_after':after['account'],
              'impressions':after['impressions'],'clicks':after['clicks'],'spend_cents':after['spend_cents'],
              'no_new_fee_or_touch':True,'click_id':click['click_id']}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def main(output, progress):
    scenario = 'f4-' + uuid.uuid4().hex
    evidence = {'phase': 'F4', 'scenario_run_id': scenario, 'status': 'RUNNING',
        'java_http': True, 'payment_mode': 'mock', 'ad_mode': 'persisted_simulated_cpc',
        'model_mode': 'not_called', 'live_model_called': False,
        'merchant_confirmation': 'local driver explicitly approves the displayed immutable envelope',
        'captcha_mode': 'normal Java login; only this locally requested CAPTCHA read from Smartlect Redis',
        'rounds': [], 'actions': [], 'checks': [],
        'evidence_scope': 'F4 deterministic API execution and accounting; no Merchant model or growth-effect claim'}

    def save():
        progress.parent.mkdir(parents=True, exist_ok=True)
        temporary = progress.with_suffix('.tmp')
        temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=json_value) + '\n')
        temporary.replace(progress)

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
        assert config.get('SMARTLECT_PAYMENT_MODE') == 'mock', 'mock payment required'
        for key, value in config.items():
            if key.startswith(('SMARTLECT_GROWTH_MYSQL_', 'SMARTLECT_MYSQL_')):
                os.environ[key] = value
        preserved = {path: hashlib.sha256(path.read_bytes()).hexdigest()
            for pattern in ('f1-*.json', 'f2-*.json', 'f3-*.json') for path in (ROOT / 'artifacts').glob(pattern)}
        assert output.resolve() not in {path.resolve() for path in preserved}, 'Preserve earlier evidence'
        java, ledger = CommerceClient(config), Ledger()
        java.request('admin', '/internal/demo/seed')
        user = java.request('admin', '/internal/demo/session', form={
            'userIndex': 78, 'password': config['SMARTLECT_DEMO_PASSWORD']})
        ids = sorted(p for p in java.request('product', '/internal/product/listOnSaleProductIds')
                     if p.startswith('910000000000'))
        catalogue = java.request('product', '/internal/product/snapshotBatch', data={'productIds': ids})['skus']
        base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']

        def stock(sku):
            return java.request('stock', '/internal/stock/getBatch', data=[{
                'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}])[0]['stock']

        with httpx.Client(base_url=base, timeout=25, trust_env=False) as merchant, \
                httpx.Client(base_url=base, timeout=25, trust_env=False) as browser:
            stage('Normal Java merchant login and user session')
            merchant_headers = login_merchant(merchant, config)
            merchant_id = http(merchant, 'GET', '/admin-api/assistant/session')['actor']['actor_id']
            browser.cookies.set('token', user['token'])
            session = http(browser, 'GET', '/api/assistant/session')
            headers = {'Origin': base, 'X-CSRF-Token': session['csrf_token']}
            evidence['execution_scope_id'] = session['actor']['execution_scope_id']
            evidence['user_id'] = user['userId']

            def post(path, payload):
                return http(browser, 'POST', path, json=payload, headers=headers)

            def mpost(path, payload):
                return http(merchant, 'POST', '/admin-api/assistant/ads/' + path,
                            json=payload, headers=merchant_headers)

            def snapshot():
                return http(merchant, 'GET', '/admin-api/assistant/ads')

            conversation = post('/api/assistant/conversations', {})['conversation_id']
            evidence['conversation_id'] = conversation
            recommendation = http(browser, 'GET', '/api/assistant/recommendations', params={'max_price_cents': 2000, 'limit': 8})
            sku = next(item for item in recommendation['items']
                       if any((item['productId'], item['propertyValueIdHash']) == (s['productId'], s['propertyValueIdHash']) for s in catalogue))
            ad_sku = next(s for s in catalogue if s['productId'] != sku['productId'] and stock(s) > 0)
            campaign_id, creative_id = uuid.uuid4().hex, uuid.uuid4().hex
            evidence.update(campaign_id=campaign_id, creative_id=creative_id, advertised_product_id=ad_sku['productId'],
                            purchased_product_id=sku['productId'], recommendation=recommendation)
            before = snapshot()
            evidence['account_before'] = before['account']
            stage('Save DRAFT campaign and creative, then explicitly approve stable grant')
            campaign = mpost('campaigns', {'campaign_id': campaign_id, 'name': scenario,
                'product_id': ad_sku['productId'], 'sku_key': ad_sku['propertyValueIdHash'],
                'budget_cents': 0 if before['account'] else 100, 'cpc_cents': 10})
            creative = mpost('creatives', {'creative_id': creative_id, 'campaign_id': campaign_id,
                                         'copy_text': '推广：Smartlect 本地模拟活动，点击费用 10 分'})
            assert (campaign['status'], creative['status']) == ('DRAFT', 'DRAFT')
            denied = browser.post('/api/assistant/ads/exposures', json={'exposure_id': uuid.uuid4().hex,
                                  'creative_id': creative_id}, headers=headers)
            assert denied.status_code in (403, 409, 422), 'Draft exposure must be rejected'
            cap = max((before.get('account') or {}).get('budget_cap_cents', 0),
                      sum(c['budget_cents'] for c in before['campaigns']) + 100)
            review = snapshot()
            reviewed_campaigns = {c['campaign_id']: c['version'] for c in review['campaigns']
                                  if c['owner_id'] == merchant_id and c['product_id'] == ad_sku['productId']}
            reviewed_creatives = {c['creative_id']: c['version'] for c in review['creatives']
                                  if c['owner_id'] == merchant_id and c['campaign_id'] in reviewed_campaigns}
            grant_request = {'grant_id': uuid.uuid4().hex, 'initial_plan_id': uuid.uuid4().hex,
                'initial_plan_version': 1, 'expected_campaign_versions': reviewed_campaigns,
                'expected_creative_versions': reviewed_creatives,
                'envelope': {'objective': 'F4 local simulated CPC and attribution acceptance',
                'product_scope': [ad_sku['productId']], 'allowed_action_types': ['activate_campaign', 'activate_creative',
                    'pause_campaign', 'pause_creative', 'resume_campaign', 'resume_creative', 'set_budget', 'replace_creative'],
                'budget_cap_cents': cap, 'max_budget_change_cents': 100,
                'valid_until': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}}
            if before['account']:
                grant_request['replaces_grant_id'] = before['account']['grant_id']
            grant = mpost('grants', grant_request)
            assert grant['envelope_hash'] == hashlib.sha256(canonical(grant['envelope']).encode()).hexdigest()
            assert grant['plan_snapshot_hash'] == hashlib.sha256(canonical(grant['plan_snapshot']).encode()).hexdigest()
            assert {c['campaign_id']: c['version'] for c in grant['plan_snapshot']['campaigns']} == reviewed_campaigns
            assert {c['creative_id']: c['version'] for c in grant['plan_snapshot']['creatives']} == reviewed_creatives
            evidence['approved_grant'] = grant

            def action(kind, round_id, **extra):
                state = snapshot()
                is_creative = kind.endswith('creative')
                target = next(c for c in state['creatives' if is_creative else 'campaigns']
                              if c['creative_id' if is_creative else 'campaign_id'] == (creative_id if is_creative else campaign_id))
                item = {'action_type': kind, 'campaign_id': campaign_id, 'expected_version': target['version'], **extra}
                if is_creative:
                    item['creative_id'] = creative_id
                request = {'action_id': uuid.uuid4().hex, 'idempotency_key': uuid.uuid4().hex,
                    'grant_id': grant['grant_id'], 'plan_id': scenario + '-plan-' + str(round_id),
                    'plan_version': round_id, 'agent_run_id': scenario + '-invocation-' + str(round_id),
                    'round_id': scenario + '-round-' + str(round_id), 'reason_code': 'explicit_f4_acceptance',
                    'evidence_ids': [], 'actions': [item]}
                result = mpost('actions', request)
                assert result['status'] == 'APPLIED', f'Round {round_id}: {kind} must be applied'
                assert mpost('actions', request) == result, f'Round {round_id}: {kind} replay receipt differs'
                evidence['actions'].append(result)
                return result

            def flow(round_id):
                stage(f'Round {round_id}: new exposure, paid click and exact receipt replay')
                exposure_request = {'exposure_id': uuid.uuid4().hex, 'creative_id': creative_id}
                request = {'click_id': uuid.uuid4().hex, 'exposure_id': exposure_request['exposure_id']}
                result = {'round_id': scenario + '-round-' + str(round_id),
                          'exposure_request': exposure_request, 'click_request': request}
                evidence['rounds'].append(result)
                save()
                exposed = post('/api/assistant/ads/exposures', exposure_request)
                result['exposure'] = exposed
                save()
                assert exposed['amount_cents'] == 0 and exposed['ad_label'], 'Exposure is free and labeled as advertising'
                clicked = post('/api/assistant/ads/clicks', request)
                result['click'] = clicked
                save()
                assert clicked['status'] == 'CHARGED' and clicked['amount_cents'] == 10, f'Round {round_id}: click must charge exactly 10 cents'
                assert post('/api/assistant/ads/clicks', request) == clicked, f'Round {round_id}: original click and persisted replay receipts differ'
                result['click_replay_matches'] = True
                save()
                return request, clicked

            if campaign['budget_cents'] == 0:
                action('set_budget', 1, budget_cents=100)
            action('activate_campaign', 1)
            action('activate_creative', 1)
            stage('Round 1 produces a new exposure, paid click and trusted AD_CLICK')
            click_request, first_click = flow(1)
            position, rec_id = sku['position'], recommendation['recommendation_id']
            exposed_rec = post(f'/api/assistant/recommendations/{rec_id}/exposures', {'positions': [position]})['touches'][0]
            clicked_rec = post(f'/api/assistant/recommendations/{rec_id}/clicks', {'position': position})['touches'][0]
            landing = post('/api/assistant/traffic/landing', {'entry_id': scenario + '-natural-return'})
            assert landing['traffic_channel'] == 'NATURAL'
            action('pause_campaign', 1)
            assert post('/api/assistant/ads/clicks', click_request) == first_click
            rejected = browser.post('/api/assistant/ads/exposures', json={'exposure_id': uuid.uuid4().hex,
                'creative_id': creative_id}, headers=headers)
            assert rejected.status_code in (403, 409, 422), 'Paused campaign must stop new flow'
            action('resume_campaign', 2)
            action('replace_creative', 2, copy_text='推广：Smartlect 第二轮已批准素材')
            _, second_click = flow(2)
            assert first_click != second_click
            landing = post('/api/assistant/traffic/landing', {'entry_id': scenario + '-round2-natural-return'})
            assert landing['traffic_channel'] == 'NATURAL'

            stage('User explicitly confirms Java order and independent mock payment')
            initial_stock = stock(sku)
            proposed = proposal_from(post(f'/api/assistant/conversations/{conversation}/proposals', {
                'message_id': scenario + '-order', 'action_type': 'order', 'parameters': {
                'payMethod': 'mock', 'addressId': user['addressId'], 'orderFrom': 0, 'orderList': [{
                    'productId': sku['productId'], 'propertyValueIds': sku['propertyValueIds'], 'buyCount': 1}]}}))
            assert proposed['status'] == 'PROPOSED' and stock(sku) == initial_stock

            def confirm(proposal):
                return proposal_from(post('/api/assistant/proposals/' + proposal['proposal_id'] + '/confirm', {
                    'proposal_version': proposal.get('decision_version') or proposal['version'], 'approved': True}))

            ordered = wait_for(lambda: confirm(proposed), lambda value: value['status'] in ('SUCCEEDED', 'FAILED'), 'confirmed Java order')
            assert ordered['status'] == 'SUCCEEDED'
            receipt = ordered['receipt']
            pay_id, amount = receipt['payOrderId'], receipt['amountCents']
            evidence.update(pay_order_id=pay_id, order_proposal_id=proposed['proposal_id'], order_receipt=receipt,
                            initial_stock=initial_stock, amount_cents=amount)
            save()
            assert amount == sku['price_cents'] and stock(sku) == initial_stock - 1
            assert confirm(proposed)['receipt'] == receipt
            post(f'/api/assistant/payments/{pay_id}/complete', {'expected_amount_cents': amount})
            paid = wait_for(lambda: http(browser, 'GET', f'/api/assistant/payments/{pay_id}'),
                lambda value: value['commandStatus'] == 'business_completed', 'Java payment synchronization')
            assert paid['paymentStatus'] == 'PAID' and paid['orderSynchronized']
            evidence['payment_receipt'] = paid
            _, later_click = flow(3)
            # This post-order click pays normally, but cannot enter the frozen order context.
            orders = java.request('order', '/internal/order/commerce/listOrders', session=user, data={'limit': 100})
            item = next(item for order in orders if order['payOrderId'] == pay_id for item in order['items'])
            assert cents(item['paidAmount']) == amount
            refund = proposal_from(post(f'/api/assistant/conversations/{conversation}/proposals', {
                'message_id': scenario + '-refund', 'action_type': 'refund', 'parameters': {
                    'orderItemId': item['orderItemId'], 'refundAmountCents': amount, 'reason': '合成 F4 CPC 归因验收退款'}}))
            final = wait_for(lambda: confirm(refund), lambda value: value['status'] in ('SUCCEEDED', 'FAILED'), 'Java refund')
            assert final['status'] == 'SUCCEEDED' and final['receipt']['refundStatus'] == 'COMPLETED'
            evidence['refund_receipt'] = final['receipt']
            evidence['final_stock'] = wait_for(lambda: stock(sku), lambda value: value == initial_stock, 'refund inventory restoration')
            financial = wait_for(lambda: ledger.summary(pay_id), lambda value:
                value['paidCents'] == value['refundedCents'] == amount, 'worker financial watermark')
            assert financial['netCents'] == 0 and financial['paymentConversions'] == 1

            stage('Confirm temporary purchase of all advertised A inventory and observe real stockout protection')
            unclicked = post('/api/assistant/ads/exposures', {'exposure_id': uuid.uuid4().hex, 'creative_id': creative_id})
            ad_initial_stock = stock(ad_sku)
            assert 1 <= ad_initial_stock <= 999, 'Owned advertised SKU stock must fit the confirmed quantity contract'
            temporary = proposal_from(post(f'/api/assistant/conversations/{conversation}/proposals', {
                'message_id': scenario + '-stockout-order', 'action_type': 'order', 'parameters': {
                    'payMethod': 'mock', 'addressId': user['addressId'], 'orderFrom': 0, 'orderList': [{
                        'productId': ad_sku['productId'], 'propertyValueIds': ad_sku['propertyValueIds'],
                        'buyCount': ad_initial_stock}]}}))
            assert temporary['status'] == 'PROPOSED' and stock(ad_sku) == ad_initial_stock
            depleted = wait_for(lambda: confirm(temporary), lambda value: value['status'] in ('SUCCEEDED', 'FAILED'),
                               'user-confirmed advertised SKU stockout order')
            assert depleted['status'] == 'SUCCEEDED'
            temporary_receipt = depleted['receipt']
            temporary_pay_id = temporary_receipt['payOrderId']
            protection = {'initial_stock': ad_initial_stock, 'order_proposal_id': temporary['proposal_id'],
                'temporary_pay_order_id': temporary_pay_id, 'temporary_order_receipt': temporary_receipt,
                'outcome': 'unpaid_order_to_be_cancelled_not_payment_failure'}
            evidence['stockout_protection'] = protection
            save()
            assert confirm(temporary)['receipt'] == temporary_receipt
            protection['sold_out_stock'] = wait_for(lambda: stock(ad_sku), lambda value: value == 0, 'Java advertised SKU zero-stock watermark')
            pending = http(browser, 'GET', f'/api/assistant/payments/{temporary_pay_id}')
            assert pending['paymentStatus'] == 'PENDING', 'The temporary order has no payment confirmation'
            before_protection = snapshot()
            denied_exposure = browser.post('/api/assistant/ads/exposures',
                json={'exposure_id': uuid.uuid4().hex, 'creative_id': creative_id}, headers=headers)
            denied_click = browser.post('/api/assistant/ads/clicks',
                json={'click_id': uuid.uuid4().hex, 'exposure_id': unclicked['exposure_id']}, headers=headers)
            for rejected in (denied_exposure, denied_click):
                assert rejected.status_code in (403, 409, 422), 'Observed stockout must refuse new traffic'
            protected = snapshot()
            protected_campaign = next(c for c in protected['campaigns'] if c['campaign_id'] == campaign_id)
            protected_creative = next(c for c in protected['creatives'] if c['creative_id'] == creative_id)
            assert protected_campaign['status'] == protected_creative['status'] == 'PAUSED'
            assert protected_campaign['pause_reason'] == protected_creative['pause_reason'] == 'stockout'
            assert protected['account']['spent_cents'] == before_protection['account']['spent_cents']
            assert (protected['impressions'], protected['clicks']) == (before_protection['impressions'], before_protection['clicks'])
            assert post('/api/assistant/ads/clicks', click_request) == first_click
            protection.update(exposure_rejection=denied_exposure.json(), click_rejection=denied_click.json(),
                campaign=protected_campaign, creative=protected_creative,
                observations=[o for o in protected['observations']
                              if o['product_id'] == ad_sku['productId'] and o['sku_key'] == ad_sku['propertyValueIdHash']],
                original_click_recovered=True, spending_unchanged=True)
            save()

            stage('User confirms cancellation, inventory restores, then merchant explicitly resumes both levels')
            temporary_orders = java.request('order', '/internal/order/commerce/listOrders', session=user, data={'limit': 100})
            temporary_order = next(order for order in temporary_orders if order['payOrderId'] == temporary_pay_id)
            cancellation = proposal_from(post(f'/api/assistant/conversations/{conversation}/proposals', {
                'message_id': scenario + '-stockout-cancel', 'action_type': 'cancel',
                'parameters': {'orderId': temporary_order['orderId']}}))
            protection.update(temporary_order_id=temporary_order['orderId'], cancel_proposal_id=cancellation['proposal_id'])
            save()
            cancelled = wait_for(lambda: confirm(cancellation), lambda value: value['status'] in ('SUCCEEDED', 'FAILED'),
                                 'user-confirmed cancellation and inventory restoration')
            assert cancelled['status'] == 'SUCCEEDED' and cancelled['receipt']['stockRestored']
            assert confirm(cancellation)['receipt'] == cancelled['receipt']
            protection.update(cancel_proposal_id=cancellation['proposal_id'], cancellation_receipt=cancelled['receipt'],
                final_stock=wait_for(lambda: stock(ad_sku), lambda value: value == ad_initial_stock, 'Java advertised stock restoration'),
                outcome='cancelled_unpaid_order_not_payment_failure')
            still_paused = browser.post('/api/assistant/ads/exposures',
                json={'exposure_id': uuid.uuid4().hex, 'creative_id': creative_id}, headers=headers)
            assert still_paused.status_code in (403, 409, 422), 'Positive inventory cannot automatically resume advertising'
            action('resume_campaign', 4)
            action('resume_creative', 4)
            flow(4)
            temporary_money = ledger.summary(temporary_pay_id)
            assert temporary_money['paidCents'] == temporary_money['refundedCents'] == temporary_money['netCents'] == 0
            protection['temporary_order_ledger'] = temporary_money
            protection['explicit_resume_produced_new_paid_click'] = True
            save()

            stage('Reconcile spend, independent recommendation/ad attribution and refund inheritance')
            projected = wait_for(lambda: rows('''SELECT e.event_id,e.event_type,e.order_item_id,e.amount_cents,
                p.* FROM commerce_event e JOIN commerce_attribution p USING(event_id)
                WHERE e.pay_order_id=%s AND e.event_type IN ('PAYMENT','REFUND') ORDER BY e.event_id''', (pay_id,)),
                lambda values: len(values) == 2 and all(v['calculation_status'] == 'FINAL' for v in values), 'attribution watermark')
            ad_touches = rows("SELECT touch_id,origin,campaign_id,creative_id,product_id,metadata_json FROM traffic_touch WHERE campaign_id=%s AND kind='AD_CLICK' ORDER BY occurred_at,touch_id", (campaign_id,))
            assert len(ad_touches) == 4 and all(t['origin'] == 'ads_executor' for t in ad_touches)
            assert all(t['product_id'] == ad_sku['productId'] for t in ad_touches)
            for fact in projected:
                assert fact['category'] == 'AD_ATTRIBUTED' and fact['campaign_id'] == campaign_id
                assert fact['recommendation_click_id'] == clicked_rec['touch_id'] and fact['recommendation_id'] == rec_id
                assert fact['ad_click_id'] == ad_touches[1]['touch_id']
                assert fact['ad_click_id'] not in {t['touch_id'] for t in ad_touches[2:]}
                assert fact['traffic_channel'] == 'NATURAL'
            payment, refunded = ({p['event_type']: p for p in projected}[kind] for kind in ('PAYMENT', 'REFUND'))
            inherited = ('context_id', 'order_created_at', 'category', 'campaign_id', 'creative_id', 'ad_click_id',
                         'recommendation_click_id', 'recommendation_id', 'traffic_channel')
            assert all(payment[key] == refunded[key] for key in inherited)
            assert refunded['reason'] == 'refund_inherits_payment'
            spend = rows('SELECT click_id,exposure_id,amount_cents,touch_id,account_id,grant_id FROM ad_spend WHERE campaign_id=%s ORDER BY occurred_at,click_id', (campaign_id,))
            assert len(spend) == 4 and sum(s['amount_cents'] for s in spend) == 40
            assert {s['touch_id'] for s in spend} == {t['touch_id'] for t in ad_touches}
            action('pause_campaign', 4)
            state = snapshot()
            persisted_grant = next(g for g in state['grants'] if g['grant_id'] == grant['grant_id'])
            assert (persisted_grant['plan_snapshot'], persisted_grant['plan_snapshot_hash']) == (grant['plan_snapshot'], grant['plan_snapshot_hash'])
            campaign = next(c for c in state['campaigns'] if c['campaign_id'] == campaign_id)
            assert campaign['spent_cents'] == 40 and campaign['status'] == 'PAUSED'
            before_spent = (before.get('account') or {}).get('spent_cents', 0)
            assert state['account']['spent_cents'] == before_spent + 40
            assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in preserved.items())
            evidence.update(status='PASSED', ledger=financial, attribution=projected, ad_touches=ad_touches, spend=spend,
                campaign_final=campaign, account_after=state['account'], prior_evidence_preserved=True,
                recommendation_exposure_id=exposed_rec['touch_id'], natural_return_id=landing['touch_id'],
                checks=['DRAFT forbidden; explicit stable grant and two-level activation',
                    'free exposure and four new paid clicks, repeat click without repeat spend',
                    'pause stops new flow, original click recovers, explicit resume and changed creative produce next round',
                    'Java confirmed purchase of B after paid advertising A; independent recommendation source',
                    'post-order paid click cannot hijack frozen attribution; confirmed refund inherits payment',
                    'Java-confirmed sold-out advertising SKU protects both levels and rejects new flow without charges',
                    'user-confirmed unpaid cancellation restores inventory; explicit two-level resume produces fourth paid click',
                    'four clicks cost 40 cents; paid/refunded reconcile to net zero; both initial inventories restored'])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=json_value) + '\n')
            save()
            print('F4 API gate passed: ' + str(output), flush=True)
            return 0
    except Exception as error:
        evidence.update(status='FAILED', error_type=type(error).__name__)
        evidence['failure_frames'] = [{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                                     for frame in traceback.extract_tb(error.__traceback__)]
        if isinstance(error, AssertionError):
            evidence['assertion'] = str(error)
        save()
        location = evidence['failure_frames'][-1] if evidence['failure_frames'] else None
        print('F4 gate failed at ' + evidence.get('stage', 'initialization') + ': ' + type(error).__name__
              + (f" ({location['file']}:{location['line']})" if location else ''), flush=True)
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/f4-live-execution.json')
    parser.add_argument('--progress', type=Path, default=ROOT / 'artifacts/local/f4-progress.json')
    args = parser.parse_args()
    raise SystemExit(main(args.output, args.progress))
