"""F1 live Java/MySQL confirmation gate. All users/SKUs/payment are owned demo resources."""
import json
import argparse
from pathlib import Path
import subprocess
import uuid

import httpx

from demo import cents, wait_for
from runtime import ROOT, ENV_FILE, parse_env
from smartlect.commerce import CommerceClient, CommerceError


def main(output=ROOT / 'artifacts/f1-live-confirmation.json'):
    env = parse_env(ENV_FILE)
    java = CommerceClient(env)
    java.request('admin', '/internal/demo/seed')
    session = java.request('admin', '/internal/demo/session', form={
        'userIndex': 61, 'password': env['SMARTLECT_DEMO_PASSWORD']})
    other = java.request('admin', '/internal/demo/session', form={
        'userIndex': 62, 'password': env['SMARTLECT_DEMO_PASSWORD']})
    ids = sorted(p for p in java.request('product', '/internal/product/listOnSaleProductIds') if p.startswith('910000000000'))
    snapshot = java.request('product', '/internal/product/snapshotBatch', data={'productIds': ids})

    def stock(sku):
        return java.request('stock', '/internal/stock/getBatch', data=[{
            'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}])[0]['stock']

    sku = next(sku for sku in snapshot['skus'] if stock(sku) > 0)
    initial_stock = stock(sku)
    run_id = 'f1-' + uuid.uuid4().hex
    base = 'http://127.0.0.1:' + env['SMARTLECT_GATEWAY_PORT']
    checks = []
    with httpx.Client(base_url=base, timeout=25, trust_env=False) as browser:
        browser.cookies.set('token', session['token'])
        auth = browser.get('/api/assistant/session', headers={'X-Smartlect-User-Id': other['userId'], 'X-Admin-Roles': 'SUPER_ADMIN'}).json()
        assert auth['actor']['actor_id'] == session['userId']
        headers = {'Origin': base, 'X-CSRF-Token': auth['csrf_token']}
        checks.append('Gateway strips forged actor headers; Java cookie bridge resolves actual user')

        def post(path, data):
            response = browser.post(path, json=data, headers=headers)
            if response.status_code != 200:
                raise AssertionError(f'{path}: HTTP {response.status_code}: {response.text[:500]}')
            return response.json()

        conversation = post('/api/assistant/conversations', {})['conversation_id']
        order = {'payMethod': 'mock', 'addressId': session['addressId'], 'orderFrom': 0, 'orderList': [{
            'productId': sku['productId'], 'propertyValueIds': sku['propertyValueIds'], 'buyCount': 1}]}
        payload = {'message_id': run_id + '-propose', 'action_type': 'order', 'parameters': order}
        proposed = post(f'/api/assistant/conversations/{conversation}/proposals', payload)
        assert proposed['state'] == 'WAIT_USER'
        proposal = proposed['result']['proposal']
        assert stock(sku) == initial_stock
        assert proposal['quote_total_cents'] == cents(sku['price'])
        replay = post(f'/api/assistant/conversations/{conversation}/proposals', payload)
        assert replay['agent_run_id'] == proposed['agent_run_id']
        checks.append('Proposal contains Java price/quote; repeated message does not reserve or deduct stock')
        try:
            java.request('order', '/internal/order/commerce/v2/createConfirmed', session=session,
                         key=run_id + '-tampered', data={'quoteId': proposal['quote_id'],
                             'confirmedAmountCents': proposal['quote_total_cents'] + 1, 'order': proposal['parameters']})
        except CommerceError:
            pass
        else:
            raise AssertionError('Java accepted a changed confirmed amount')
        assert stock(sku) == initial_stock
        checks.append('Java rejects changed confirmed amount without stock effect')

        # Restart only the owned AI API. Durable WAIT_USER survives; financial worker stays running.
        code = ("from runtime import *; env=parse_env(ENV_FILE); records=load_processes(); "
                "stop_process(records['growth']); start_app('growth',env,records); wait_apps(['growth'],records)")
        subprocess.run(['/usr/bin/python3', '-c', code], cwd=ROOT / 'scripts', check=True)
        saved = browser.get('/api/assistant/proposals/' + proposal['proposal_id']).json()
        assert saved['status'] == 'PROPOSED' and saved['proposal_hash'] == proposal['proposal_hash']
        checks.append('Owned API restart preserves proposal, quote, owner and parameter hash')
        confirm_path = f"/api/assistant/proposals/{proposal['proposal_id']}/confirm"
        confirmation = {'proposal_version': proposal['version'], 'approved': True}
        assert browser.post(confirm_path, json=confirmation).status_code == 403
        with httpx.Client(base_url=base, timeout=10, trust_env=False) as attacker:
            attacker.cookies.set('token', other['token'])
            assert attacker.get('/api/assistant/proposals/' + proposal['proposal_id']).status_code == 404
        completed = post(confirm_path, confirmation)
        receipt = completed['result']['proposal']['receipt']
        assert completed['result']['proposal']['status'] == 'SUCCEEDED'
        assert receipt['paymentStatus'] == 'PENDING' and stock(sku) == initial_stock - 1
        duplicate = post(confirm_path, confirmation)
        assert duplicate['proposal']['receipt']['payOrderId'] == receipt['payOrderId']
        assert stock(sku) == initial_stock - 1
        checks.append('CSRF/owner checks reject; one confirmed order with separate unpaid status, duplicate has no second effect')
        pay_id = receipt['payOrderId']
        status_query = {'actionType': 'PAYMENT', 'params': {'payOrderId': pay_id}}
        pending = java.request('order', '/internal/order/commerce/v2/actionStatus', session=session, data=status_query)
        assert pending['commandStatus'] == 'business_pending'
        # Explicit simulator action playing the user, never a model tool or real money transfer.
        java.request('pay', '/internal/pay/mock/complete', data={'payOrderId': pay_id})
        paid = wait_for(lambda: java.request('order', '/internal/order/commerce/v2/actionStatus', session=session,
                                            data=status_query), lambda x: x['commandStatus'] == 'business_completed', 'payment+order synchronization')
        orders = java.request('order', '/internal/order/commerce/listOrders', session=session, data={'limit': 30})
        item = next(item for order in orders if order['payOrderId'] == pay_id for item in order['items'])
        refund_run = post(f'/api/assistant/conversations/{conversation}/proposals', {
            'message_id': run_id + '-refund', 'action_type': 'refund', 'parameters': {
                'orderItemId': item['orderItemId'], 'refundAmountCents': cents(item['paidAmount']), 'reason': '合成F1验收退款'}})
        refund = refund_run['result']['proposal']
        refund_path = f"/api/assistant/proposals/{refund['proposal_id']}/confirm"
        refund_confirm = {'proposal_version': refund['version'], 'approved': True}
        result = post(refund_path, refund_confirm)
        def refund_result():
            response = post(refund_path, refund_confirm)
            return response.get('proposal', response.get('result', {}).get('proposal'))
        final = wait_for(refund_result, lambda x: x['status'] == 'SUCCEEDED', 'confirmed refund terminal')
        assert final['receipt']['refundStatus'] == 'COMPLETED'
        wait_for(lambda: stock(sku), lambda value: value == initial_stock, 'refund stock restoration')
        checks.append('Explicit simulated payment synchronizes; confirmed refund reaches Java COMPLETED and restores stock once')
        events = browser.get(f"/api/assistant/runs/{completed['agent_run_id']}/events")
        assert events.status_code == 200 and 'event: completed' in events.text
        assert stock(sku) == initial_stock
        checks.append('Persisted SSE replay displays result without re-execution')
        def ledger_summary():
            return httpx.get('http://127.0.0.1:' + env['SMARTLECT_GROWTH_PORT'] + '/internal/ledger/summary',
                             params={'payOrderId': pay_id}, headers={'X-Internal-Token': env['SMARTLECT_INTERNAL_TOKEN']},
                             timeout=5, trust_env=False).json()
        ledger = wait_for(ledger_summary, lambda value: value['paidCents'] == value['refundedCents'] == proposal['quote_total_cents'], 'ledger')
        assert ledger['netCents'] == 0 and ledger['paymentConversions'] == 1
        checks.append('Java payment/refund facts reconcile in the independent unchanged ledger')
        evidence = {'phase': 'F1', 'run_id': run_id, 'checks': checks, 'model_mode': 'rule-fallback',
                    'live_model_called': False, 'java_http': True, 'ai_api_restarted': True,
                    'pay_order_id': pay_id, 'paid_cents': ledger['paidCents'], 'refunded_cents': ledger['refundedCents'],
                    'net_cents': ledger['netCents'], 'initial_stock': initial_stock, 'final_stock': stock(sku)}
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/f1-live-confirmation.json')
    main(parser.parse_args().output)
