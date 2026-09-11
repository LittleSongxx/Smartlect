"""F3 Gateway/Java attribution gate; synthetic ad fixtures, mock money, no model calls.

Run only after the v2 consumer and Java producers are deployed. This script never
starts services, changes Java tables, or exercises F4 advertising spend.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import httpx

from demo import cents
from runtime import ROOT, ENV_FILE, parse_env
from smartlect.attribution import AttributionStore
from smartlect.auth import ActorContext
from smartlect.commerce import CommerceClient
from smartlect.events import Ledger, canonical, connect_from_env


def json_value(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError('unsupported evidence value')


def proposal_from(result):
    return result.get('proposal') or result['result']['proposal']


def main(output, progress):
    evidence = {'phase': 'F3', 'run_id': 'f3-' + uuid.uuid4().hex, 'status': 'RUNNING',
        'model_mode': 'not_called', 'live_model_called': False, 'java_http': True,
        'payment_mode': 'mock', 'ad_mode': 'synthetic_fixture_no_spend', 'cases': [], 'checks': [],
        'evidence_scope': 'Gateway attribution and real Java v2 facts; no F4 spending or growth-effect claim'}

    def save():
        progress.parent.mkdir(parents=True, exist_ok=True)
        temporary = progress.with_suffix('.tmp')
        temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=json_value) + '\n')
        temporary.replace(progress)

    def stage(label):
        evidence['stage'] = label
        save()
        print(label, flush=True)

    def wait(read, predicate, label, timeout=45):
        stage(label)
        deadline = time.monotonic() + timeout
        while True:
            value = read()
            if predicate(value):
                return value
            if time.monotonic() >= deadline:
                raise AssertionError('bounded wait expired: ' + label)
            time.sleep(.3)

    def rows(sql, params=()):
        with connect_from_env() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def http(client, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == 200, f'{method} {path}: HTTP {response.status_code}'
        return response.json()

    def session(client):
        auth = http(client, 'GET', '/api/assistant/session')
        # The strict model takes a tuple; identity comes from the live Java bridge.
        actor = ActorContext.model_validate({**auth['actor'], 'permissions': tuple(auth['actor']['permissions'])})
        return actor, {'Origin': str(client.base_url).rstrip('/'), 'X-CSRF-Token': auth['csrf_token']}

    try:
        config = parse_env(ENV_FILE)
        assert config.get('SMARTLECT_PAYMENT_MODE') == 'mock', 'mock payment configuration required'
        for key, value in config.items():
            if key.startswith(('SMARTLECT_GROWTH_MYSQL_', 'SMARTLECT_MYSQL_')):
                os.environ[key] = value
        f2_files = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'artifacts').glob('f2-*.json')}
        assert output.resolve() not in {p.resolve() for p in f2_files}, 'F2 evidence must be preserved'
        java, ledger = CommerceClient(config), Ledger()
        attribution = AttributionStore(connect_from_env, secret=config.get('SMARTLECT_ATTRIBUTION_SECRET'))
        stage('Initialize owned demo sessions 76 and 77 through Java fixture APIs')
        java.request('admin', '/internal/demo/seed')
        users = [java.request('admin', '/internal/demo/session', form={
            'userIndex': index, 'password': config['SMARTLECT_DEMO_PASSWORD']}) for index in (76, 77)]
        ids = sorted(p for p in java.request('product', '/internal/product/listOnSaleProductIds')
                     if p.startswith('910000000000'))
        snapshot = java.request('product', '/internal/product/snapshotBatch', data={'productIds': ids})
        catalogue = {(s['productId'], s['propertyValueIdHash']): s for s in snapshot['skus']}
        assert len({s['productId'] for s in catalogue.values()}) >= 2, 'two owned Java products required'
        base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
        growth_url = 'http://127.0.0.1:' + config['SMARTLECT_GROWTH_PORT']

        def stock(sku):
            return java.request('stock', '/internal/stock/getBatch', data=[{
                'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}])[0]['stock']

        def projection(pay_id):
            return rows('''SELECT e.event_id,e.event_type,e.schema_version,e.status,e.pay_order_id,
                e.order_id,e.order_item_id,e.user_id,e.product_id,e.sku_key,e.amount_cents,e.source,
                p.execution_scope_id,p.category,p.calculation_status,p.reason,p.rule_version,p.context_id,
                p.order_created_at,p.traffic_channel,p.ad_click_id,p.campaign_id,p.creative_id,
                p.recommendation_click_id,p.recommendation_id,p.recommendation_assist_id,
                p.assignment_id,p.strategy_version FROM commerce_event e
                LEFT JOIN commerce_attribution p USING(event_id)
                WHERE e.pay_order_id=%s AND e.event_type IN ('PAYMENT','REFUND') ORDER BY e.event_id''', (pay_id,))

        for case_name, user in zip(('ad_a_recommended_b_natural_revisit', 'natural_without_ad'), users):
            case = {'name': case_name, 'user_id': user['userId']}
            evidence['cases'].append(case)
            stage(case_name + ': entry and authoritative recommendations')
            with httpx.Client(base_url=base, timeout=25, trust_env=False) as browser:
                if case_name == 'natural_without_ad':
                    browser.cookies.set('token', user['token'])
                actor, headers = session(browser)

                def post(path, payload):
                    return http(browser, 'POST', path, json=payload, headers=headers)

                conversation = post('/api/assistant/conversations', {})['conversation_id']
                case['conversation_id'] = conversation
                landing = post('/api/assistant/traffic/landing', {'entry_id': evidence['run_id'] + '-initial'})
                assert post('/api/assistant/traffic/landing', {'entry_id': evidence['run_id'] + '-initial'})['touch_id'] == landing['touch_id']
                recommendation = http(browser, 'GET', '/api/assistant/recommendations',
                                      params={'max_price_cents': 2000, 'limit': 8})
                assert recommendation['items'] and recommendation['diagnostics']['final_revalidation']
                assert all(item['stock'] > 0 and item['price_cents'] <= 2000 for item in recommendation['items'])
                sku = next((item for item in recommendation['items'] if
                            (item['productId'], item['propertyValueIdHash']) in catalogue), None)
                assert sku is not None, 'recommendation must include an owned Java SKU'
                authoritative = catalogue[sku['productId'], sku['propertyValueIdHash']]
                assert (sku['propertyValueIds'], sku['price_cents']) == (authoritative['propertyValueIds'], cents(authoritative['price']))
                rec_id, position = recommendation['recommendation_id'], sku['position']
                case.update(recommendation=recommendation, product_id=sku['productId'], sku_key=sku['propertyValueIdHash'])
                ad = None
                if case_name.startswith('ad_'):
                    assert actor.subject_type == 'visitor' and actor.execution_scope_id == 'store'
                    visitor_cookie = browser.cookies.get('smartlect_visitor')
                    ad_sku = next(s for s in catalogue.values() if s['productId'] != sku['productId'] and stock(s) > 0)
                    ad_arguments = {'click_key': evidence['run_id'] + '-ad', 'campaign_id': evidence['run_id'] + '-campaign',
                        'creative_id': evidence['run_id'] + '-creative', 'product_id': ad_sku['productId'],
                        'sku_key': ad_sku['propertyValueIdHash'], 'origin': 'f3_fixture',
                        'metadata': {'synthetic': True, 'phase': 'F3', 'spend_cents': 0,
                                     'ad_mode': 'synthetic_fixture_no_spend', 'run_id': evidence['run_id']}}
                    ad = attribution.record_ad_click(actor, **ad_arguments)
                    assert attribution.record_ad_click(actor, **ad_arguments)['touch_id'] == ad['touch_id']
                    case['ad_fixture'] = {key: ad[key] for key in ('touch_id', 'product_id', 'sku_key', 'campaign_id',
                        'creative_id', 'occurred_at', 'origin', 'metadata')}
                    assert ad['product_id'] != sku['productId']
                exposed = post(f'/api/assistant/recommendations/{rec_id}/exposures', {'positions': [position]})['touches'][0]
                clicked = post(f'/api/assistant/recommendations/{rec_id}/clicks', {'position': position})['touches'][0]
                if ad:
                    # This is the same current browser that held the anonymous proof.
                    browser.cookies.set('token', user['token'])
                    actor, headers = session(browser)
                    assert actor.actor_id == user['userId'] and actor.visitor_id == ad['actor_id']
                    binding = post('/api/assistant/traffic/bind', {})
                    assert binding['bound'] and conversation in binding['conversation_ids']
                    assert post('/api/assistant/traffic/bind', {})['bound']
                    actor, headers = session(browser)
                    owned = http(browser, 'GET', '/api/assistant/conversations/' + conversation)
                    assert owned['subject_type'] == 'user' and owned['actor_id'] == user['userId']
                    after = http(browser, 'GET', '/api/assistant/recommendations', params={'max_price_cents': 2000, 'limit': 8})
                    assert after['assignment'] == recommendation['assignment'], 'login must preserve the visitor assignment'
                    assert after['recommendation_id'] != rec_id, 'each served list has its own receipt'
                    with httpx.Client(base_url=base, cookies={'smartlect_visitor': visitor_cookie}, timeout=15, trust_env=False) as prior:
                        assert prior.get('/api/assistant/conversations/' + conversation).status_code == 404
                    with httpx.Client(base_url=base, cookies={'token': users[1]['token'], 'smartlect_visitor': visitor_cookie},
                                      timeout=15, trust_env=False) as other:
                        _, other_headers = session(other)
                        assert other.get('/api/assistant/conversations/' + conversation).status_code == 404
                        assert other.post(f'/api/assistant/recommendations/{rec_id}/clicks', json={'position': position},
                                          headers=other_headers).status_code == 404
                        assert other.post('/api/assistant/traffic/bind', json={}, headers=other_headers).status_code == 409
                    case['visitor_binding'] = {**binding, 'assignment_preserved': True, 'former_visitor_denied': True,
                                               'other_user_denied': True, 'different_account_bind_denied': True}
                assert actor.subject_type == 'user' and actor.actor_id == user['userId']
                assert post(f'/api/assistant/recommendations/{rec_id}/exposures', {'positions': [position]})['touches'][0]['touch_id'] == exposed['touch_id']
                assert post(f'/api/assistant/recommendations/{rec_id}/clicks', {'position': position})['touches'][0]['touch_id'] == clicked['touch_id']
                case.update(exposure_id=exposed['touch_id'], recommendation_click_id=clicked['touch_id'])
                revisit = post('/api/assistant/traffic/landing', {'entry_id': evidence['run_id'] + '-return'})
                assert revisit['traffic_channel'] == 'NATURAL'
                case['natural_revisit_id'] = revisit['touch_id']
                checks = rows('SELECT kind,COUNT(*) AS count FROM traffic_touch WHERE recommendation_id=%s GROUP BY kind', (rec_id,))
                assert {r['kind']: r['count'] for r in checks} == {'REC_CLICK': 1, 'REC_IMPRESSION': 1}

                # Product-only legacy carriers cannot prove a click on this exact SKU.
                legacy_item = {'requestId': rec_id, 'productId': sku['productId'], 'position': position}
                with httpx.Client(base_url=growth_url, headers={'X-Internal-Token': config['SMARTLECT_INTERNAL_TOKEN']},
                                  timeout=10, trust_env=False) as internal:
                    valid = http(internal, 'POST', '/internal/attribution/validateBatch', json={'userId': user['userId'],
                        'items': [{**legacy_item, 'skuKey': sku['propertyValueIdHash']}, legacy_item,
                                  {**legacy_item, 'skuKey': 'wrong-sku-for-f3'}]})
                assert valid['status'] == 'success' and valid['code'] == 200 and len(valid['data']) == 1
                assert valid['data'][0]['skuKey'] == sku['propertyValueIdHash']
                case['legacy_validation'] = valid['data']
                stage(case_name + ': produce VIEW through Java product page API')
                view_sql = "SELECT event_id,schema_version,event_type,user_id,product_id,source,status,amount_cents FROM commerce_event WHERE user_id=%s AND product_id=%s AND event_type='VIEW'"
                view_params = (user['userId'], sku['productId'])
                prior_views = {row['event_id'] for row in rows(view_sql, view_params)}
                detail = http(browser, 'POST', '/api/product/getProduct', data={'productId': sku['productId']})
                assert detail['status'] == 'success' and detail['data']['productInfo']['productId'] == sku['productId']
                views = wait(lambda: [row for row in rows(view_sql, view_params) if row['event_id'] not in prior_views],
                             bool, case_name + ': wait for new Java VIEW')
                assert all(row['schema_version'] == 2 and row['source'] == 'PRODUCT_BROWSE'
                           and row['status'] == 'APPLIED' and row['amount_cents'] is None for row in views)
                case['java_view_events'] = views

                stage(case_name + ': structured proposal and explicit order confirmation')
                initial_stock = stock(sku)
                assert initial_stock > 0
                payload = {'message_id': evidence['run_id'] + '-order', 'action_type': 'order', 'parameters': {
                    'payMethod': 'mock', 'addressId': user['addressId'], 'orderFrom': 0, 'orderList': [{
                        'productId': sku['productId'], 'propertyValueIds': sku['propertyValueIds'], 'buyCount': 1}]}}
                proposed = post(f'/api/assistant/conversations/{conversation}/proposals', payload)
                proposal = proposal_from(proposed)
                assert proposed['state'] == 'WAIT_USER' and proposal['status'] == 'PROPOSED'
                assert proposal['quote_total_cents'] == sku['price_cents'] and stock(sku) == initial_stock
                assert post(f'/api/assistant/conversations/{conversation}/proposals', payload)['agent_run_id'] == proposed['agent_run_id']
                case.update(order_proposal_id=proposal['proposal_id'], initial_stock=initial_stock)
                save()

                def confirm(p):
                    return proposal_from(post(f"/api/assistant/proposals/{p['proposal_id']}/confirm", {
                        'proposal_version': p.get('decision_version') or p['version'], 'approved': True}))

                confirmed = wait(lambda: confirm(proposal), lambda value: value['status'] in {'SUCCEEDED', 'FAILED'},
                                 case_name + ': wait for confirmed order')
                assert confirmed['status'] == 'SUCCEEDED'
                receipt = confirmed['receipt']
                pay_id, amount = receipt['payOrderId'], receipt['amountCents']
                case.update(pay_order_id=pay_id, amount_cents=amount, order_receipt=receipt)
                save()
                assert amount == proposal['quote_total_cents'] and receipt['paymentStatus'] == 'PENDING'
                assert confirm(proposal)['receipt'] == receipt and stock(sku) == initial_stock - 1
                pending = http(browser, 'GET', f'/api/assistant/payments/{pay_id}')
                assert pending['paymentStatus'] == 'PENDING' and pending['commandStatus'] == 'business_pending'
                stage(case_name + ': separate public mock-payment confirmation')
                post(f'/api/assistant/payments/{pay_id}/complete', {'expected_amount_cents': amount})
                paid = wait(lambda: http(browser, 'GET', f'/api/assistant/payments/{pay_id}'),
                    lambda value: value['commandStatus'] == 'business_completed', case_name + ': wait for Java payment synchronization')
                assert paid['paymentStatus'] == 'PAID' and paid['orderSynchronized']
                assert post(f'/api/assistant/payments/{pay_id}/complete', {'expected_amount_cents': amount})['paymentStatus'] == 'PAID'
                case['payment_receipt'] = paid
                later_ad = None
                if ad:
                    later_ad = attribution.record_ad_click(actor, **{**ad_arguments,
                        'click_key': evidence['run_id'] + '-later-ad', 'campaign_id': evidence['run_id'] + '-later-campaign',
                        'creative_id': evidence['run_id'] + '-later-creative'})
                    case['post_order_ad_fixture'] = {key: later_ad[key] for key in (
                        'touch_id', 'campaign_id', 'product_id', 'occurred_at', 'origin', 'metadata')}
                orders = java.request('order', '/internal/order/commerce/listOrders', session=user, data={'limit': 100})
                items = [item for order in orders if order['payOrderId'] == pay_id for item in order['items']]
                assert len(items) == 1 and cents(items[0]['paidAmount']) == amount
                item = items[0]
                case['order_item_id'] = item['orderItemId']
                refund = proposal_from(post(f'/api/assistant/conversations/{conversation}/proposals', {
                    'message_id': evidence['run_id'] + '-refund', 'action_type': 'refund', 'parameters': {
                        'orderItemId': item['orderItemId'], 'refundAmountCents': amount, 'reason': '合成F3归因验收全额退款'}}))
                case['refund_proposal_id'] = refund['proposal_id']
                save()
                final = wait(lambda: confirm(refund), lambda value: value['status'] in {'SUCCEEDED', 'FAILED'},
                             case_name + ': wait for confirmed Java refund')
                assert final['status'] == 'SUCCEEDED' and final['receipt']['refundStatus'] == 'COMPLETED'
                assert confirm(refund)['receipt'] == final['receipt']
                case['refund_receipt'] = final['receipt']
                case['final_stock'] = wait(lambda: stock(sku), lambda value: value == initial_stock,
                                           case_name + ': wait for refund stock restoration')
                financial = wait(lambda: ledger.summary(pay_id), lambda value:
                    value['paidCents'] == value['refundedCents'] == amount,
                    case_name + ': reconcile worker payment/refund ledger')
                assert financial['netCents'] == 0 and financial['paymentConversions'] == 1
                projected = wait(lambda: projection(pay_id), lambda values: len(values) == 2 and all(
                    value['calculation_status'] == 'FINAL' for value in values), case_name + ': reconcile v2 per-item attribution')
                payment, refunded = ({p['event_type']: p for p in projected}[kind] for kind in ('PAYMENT', 'REFUND'))
                expected_category = 'AD_ATTRIBUTED' if ad else 'NATURAL_VERIFIED'
                for fact in projected:
                    assert fact['schema_version'] == 2 and fact['status'] == 'APPLIED'
                    assert fact['execution_scope_id'] == actor.execution_scope_id
                    assert (fact['pay_order_id'], fact['order_item_id'], fact['user_id'], fact['product_id'], fact['sku_key'],
                            fact['amount_cents']) == (pay_id, item['orderItemId'], user['userId'], sku['productId'], sku['propertyValueIdHash'], amount)
                    assert fact['category'] == expected_category and fact['traffic_channel'] == 'NATURAL'
                    assert fact['recommendation_click_id'] == clicked['touch_id'] and fact['recommendation_id'] == rec_id
                    assert fact['assignment_id'] == recommendation['assignment_id'] and fact['strategy_version'] == str(recommendation['strategy_version'])
                    assert fact['ad_click_id'] == (ad['touch_id'] if ad else None)
                    assert fact['campaign_id'] == (ad['campaign_id'] if ad else None)
                inherited = ('context_id', 'order_created_at', 'execution_scope_id', 'category', 'traffic_channel', 'ad_click_id',
                             'campaign_id', 'creative_id', 'recommendation_click_id', 'recommendation_id', 'assignment_id',
                             'strategy_version', 'rule_version')
                assert all(payment[key] == refunded[key] for key in inherited)
                assert refunded['reason'] == 'refund_inherits_payment'
                frozen = rows('SELECT snapshot_json FROM attribution_context WHERE context_id=%s', (payment['context_id'],))
                references = {ref['touch_id'] for ref in json.loads(frozen[0]['snapshot_json'])['references']}
                assert {clicked['touch_id'], exposed['touch_id'], revisit['touch_id']} <= references
                if ad:
                    assert ad['touch_id'] in references and later_ad['touch_id'] not in references
                # Reuse actual worker-ingested Java facts; never fabricate payment receipts.
                originals = rows("SELECT raw_json FROM commerce_event WHERE pay_order_id=%s AND event_type IN ('PAYMENT','REFUND') ORDER BY event_id", (pay_id,))
                batch = canonical({'schema_version': 2, 'events': [json.loads(row['raw_json']) for row in originals]}).encode()
                ledger.ingest(batch)
                ledger.ingest(batch)
                assert ledger.summary(pay_id) == financial and projection(pay_id) == projected
                case.update(ledger=financial, attribution=projected, duplicate_receipts_unchanged=True,
                            replay_mode='actual_v2_facts_via_Ledger.ingest_not_broker_replay')
                evidence['checks'].append(case_name + ': Java VIEW, SKU click, explicit order/payment/refund, per-item v2 attribution and idempotence passed')
                save()
        assert all(path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in f2_files.items())
        evidence['f2_evidence_preserved'] = True
        evidence['status'] = 'PASSED'
        stage('F3 HTTP attribution probe passed')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=json_value) + '\n')
        print('Evidence: ' + str(output), flush=True)
        return 0
    except Exception as error:
        evidence.update(status='FAILED', error_type=type(error).__name__)
        if isinstance(error, AssertionError):
            evidence['assertion'] = str(error)
        save()
        # Exception bodies may contain HTTP payloads; keep credentials out of logs.
        print('F3 probe failed at ' + evidence.get('stage', 'initialization') + ': ' + type(error).__name__, flush=True)
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/f3-live-attribution.json')
    parser.add_argument('--progress', type=Path, default=ROOT / 'artifacts/local/f3-progress.json')
    args = parser.parse_args()
    raise SystemExit(main(args.output, args.progress))
