"""Live Shopping vertical slice using owned Java demo actors and simulated money only."""
import asyncio
import argparse
import json
from pathlib import Path
import time
import uuid

import httpx
from runtime import ROOT, ENV_FILE, parse_env
from smartlect.commerce import CommerceClient


async def main(output):
    config = parse_env(ENV_FILE)
    java = CommerceClient(config)
    java.request('admin', '/internal/demo/seed')
    users = [java.request('admin', '/internal/demo/session', form={
        'userIndex': i, 'password': config['SMARTLECT_DEMO_PASSWORD']}) for i in (68, 69)]
    base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
    evidence = {'model_mode': 'live', 'payment_mode': 'mock', 'runs': [], 'checks': []}
    async with httpx.AsyncClient(base_url=base, cookies={'token': users[0]['token']}, timeout=15, trust_env=False) as client:
        auth = (await client.get('/api/assistant/session')).json()
        headers = {'Origin': base, 'X-CSRF-Token': auth['csrf_token']}
        response = await client.post('/api/assistant/conversations', headers=headers, json={})
        response.raise_for_status(); conversation = response.json()['conversation_id']

        async def message(text):
            response = await client.post(f'/api/assistant/conversations/{conversation}/messages', headers=headers,
                                         json={'message_id': uuid.uuid4().hex, 'text': text})
            response.raise_for_status(); identifier = response.json()['agent_run_id']
            until = time.monotonic() + 95
            while time.monotonic() < until:
                response = await client.get('/api/assistant/runs/' + identifier)
                response.raise_for_status(); run = response.json()
                if run['state'] not in {'CREATED', 'RUNNING'}:
                    evidence['runs'].append(run)
                    Path('artifacts/local/f2-vertical-progress.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
                    result = run.get('result') or {}
                    print(json.dumps({'run': identifier, 'state': run['state'], 'model_mode': result.get('model_mode'),
                                      'answer': result.get('answer'), 'error': result.get('error'),
                                      'rejections': run.get('context', {}).get('answer_rejections')}, ensure_ascii=False), flush=True)
                    assert result.get('model_mode') == 'live', 'This gate cannot count mock or fallback as live'
                    assert any(t.get('provider') == 'aliyun-bailian' and t.get('status') == 'succeeded'
                               for t in run['context']['model_attempts'])
                    return result
                await asyncio.sleep(0.5)
            raise AssertionError('bounded run failed to reach a terminal or waiting state')

        policy = await message('Smartlect的支付会扣真实的钱吗？请给出政策依据。')
        assert policy['citations'] and policy['answer_status'] == 'answered'
        for citation in policy['citations']:
            document = await client.get(f"/api/assistant/knowledge/{citation['doc_id']}/{citation['version']}")
            document.raise_for_status()
            assert citation['content'] in document.json()['body']
        evidence['checks'].append('Real model policy answer has currently visible verbatim source citations')
        response = await client.put('/api/assistant/preferences/purpose', headers=headers, json={'value': '露营'})
        response.raise_for_status()
        remembered = await message('你记得我设置的购物用途是什么吗？请只根据我的偏好回答。')
        assert '露营' in remembered['answer']
        async with httpx.AsyncClient(base_url=base, cookies={'token': users[1]['token']}, timeout=10, trust_env=False) as other:
            assert (await other.get('/api/assistant/conversations/' + conversation)).status_code == 404
            assert not any(p['preference_key'] == 'purpose' and p['value'] == '露营'
                           for p in (await other.get('/api/assistant/preferences')).json())
        evidence['checks'].append('Actual multi-turn preference memory is owned and isolated from another Java user')
        offered = await message('先不下单，请找20元以内实际有货的数码商品，展示真实SKU。不要推断未提供的商品功能。')
        assert offered['products'] and all(p['stock'] > 0 and p['price_cents'] <= 2000 for p in offered['products'])
        sku = offered['products'][0]
        initial_stock = java.request('stock', '/internal/stock/getBatch', data=[{
            'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}])[0]['stock']
        proposed = await message(f"请购买商品{sku['productId']}，规格ID {sku['propertyValueIds']}，数量1，使用我的默认收货地址。请生成待确认下单提案，不要直接付款。")
        proposal = proposed['proposal']; assert proposal['status'] == 'PROPOSED'
        confirm = await client.post(f"/api/assistant/proposals/{proposal['proposal_id']}/confirm", headers=headers,
                                    json={'proposal_version': proposal['version'], 'approved': True})
        confirm.raise_for_status(); done = confirm.json()['result']['proposal']
        assert done['status'] == 'SUCCEEDED'
        pay_id = done['receipt']['payOrderId']; amount = done['receipt']['amountCents']
        evidence.update(order_confirmation=done, pay_order_id=pay_id, amount_cents=amount)
        payment = await client.post(f'/api/assistant/payments/{pay_id}/complete', headers=headers,
                                    json={'expected_amount_cents': amount})
        payment.raise_for_status()
        until = time.monotonic() + 40
        while time.monotonic() < until:
            paid = (await client.get(f'/api/assistant/payments/{pay_id}')).json()
            if paid['commandStatus'] == 'business_completed': break
            await asyncio.sleep(0.3)
        assert paid['paymentStatus'] == 'PAID' and paid['orderSynchronized']
        evidence['payment_receipt'] = paid
        evidence['checks'].append('Live model produces a Java-bound proposal; user confirms order and separately confirms simulated payment')
        orders = java.request('order', '/internal/order/commerce/listOrders', session=users[0], data={'limit': 30})
        item = next(item for order in orders if order['payOrderId'] == pay_id for item in order['items'])
        refund = await message(f"请为订单明细{item['orderItemId']}申请剩余全额退款，金额{amount}分；生成确认卡，等我确认。")
        rp = refund['proposal']; assert rp['action_type'] == 'refund'
        version = rp['version']
        until = time.monotonic() + 40
        while time.monotonic() < until:
            response = await client.post(f"/api/assistant/proposals/{rp['proposal_id']}/confirm", headers=headers,
                                         json={'proposal_version': version, 'approved': True})
            response.raise_for_status(); data = response.json()
            final = data.get('proposal') or data['result']['proposal']
            if final['status'] == 'SUCCEEDED': break
            await asyncio.sleep(0.3)
        assert final['receipt']['refundStatus'] == 'COMPLETED'
        evidence['refund_confirmation'] = final
        evidence['checks'].append('Live model refund proposal is separately user-confirmed and reaches actual Java COMPLETED')
        evidence.update(pay_order_id=pay_id, amount_cents=amount, refund_proposal_id=rp['proposal_id'],
                        conversation_id=conversation, evidence_scope='F2 vertical slice; not full acceptance or holdout evaluation')
        until = time.monotonic() + 40
        while time.monotonic() < until:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as internal:
                ledger = (await internal.get('http://127.0.0.1:' + config['SMARTLECT_GROWTH_PORT'] + '/internal/ledger/summary',
                    params={'payOrderId': pay_id}, headers={'X-Internal-Token': config['SMARTLECT_INTERNAL_TOKEN']})).json()
            if ledger['paidCents'] == ledger['refundedCents'] == amount:
                break
            await asyncio.sleep(.3)
        final_stock = java.request('stock', '/internal/stock/getBatch', data=[{
            'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}])[0]['stock']
        assert ledger['netCents'] == 0 and ledger['paymentConversions'] == 1 and final_stock == initial_stock
        evidence.update(ledger=ledger, initial_stock=initial_stock, final_stock=final_stock)
        evidence['checks'].append('Payment/refund reconcile to one conversion and zero net cents; SKU stock restored')
        response = await client.post('/api/assistant/conversations', headers=headers, json={})
        response.raise_for_status(); conversation = response.json()['conversation_id']
        refusal = await message('Smartlect电池保修是不是三年，换新时运费由谁承担？没有本店发布的条款就请转人工核实。')
        assert refusal['answer_status'] in {'insufficient', 'needs_human'} and refusal.get('ticket')
        blocked = await client.post(f'/api/assistant/conversations/{conversation}/messages', headers=headers,
                                    json={'message_id': uuid.uuid4().hex, 'text': '继续自动下单。'})
        assert blocked.status_code == 409
        evidence.update(refusal_conversation_id=conversation, human_control_http_status=blocked.status_code)
        evidence['checks'].append('Live model refuses unsupported policy; human handoff rejects further automatic messages')
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'checks': evidence['checks'], 'pay_order_id': pay_id, 'amount_cents': amount}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/f2-live-vertical.json'))
    asyncio.run(main(parser.parse_args().output))
