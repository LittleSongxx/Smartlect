"""HTTP confirmation recovery with real MySQL and explicitly mocked Java transport."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import unittest

import httpx

from smartlect.app import create_app
from smartlect.auth import IdentityBridge
from smartlect.commerce import AsyncCommerceClient
from smartlect.config import Settings
from smartlect.state import SessionStore
import test_ledger_mysql


@unittest.skipUnless(os.getenv("SMARTLECT_RUN_MYSQL_TESTS") == "1", "set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL")
class AppMySQLTests(unittest.TestCase):
    setUpClass = classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    def test_confirm_restart_recovers_original_action_and_sse_never_reexecutes(self):
        asyncio.run(self.exercise_http())

    async def exercise_http(self):
        writes, queries = [], []

        def java(request):
            path = request.url.path
            body = json.loads(request.content)
            if path.endswith('/identity/introspect'):
                actor = request.headers['cookie'].split('=', 1)[1]
                return httpx.Response(200, json={'status': 'success', 'data': {
                    'subjectType': 'user', 'actorId': actor, 'sessionId': actor + '-session',
                    'permissions': ['shopping:read', 'orders:read', 'orders:write']}})
            if path.endswith('/quote'):
                data = {'quoteId': 'mock-java-quote', 'totalAmountCents': 1500, 'order': body,
                        'expiresAt': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}
            elif path.endswith('/createConfirmed'):
                self.assertEqual(body['confirmedAmountCents'], 1500)
                self.assertEqual(request.headers['X-Smartlect-User-Id'], 'alice')
                writes.append(request.headers['Idempotency-Key'])
                # The authority committed, then the response was lost. Do not submit another order.
                raise httpx.ReadTimeout('after commit', request=request)
            elif path.endswith('/actionStatus'):
                queries.append(body['idempotencyKey'])
                self.assertEqual(body['idempotencyKey'], writes[0])
                data = {'commandStatus': 'business_completed', 'status': 'SUCCESS', 'payOrderId': 'mock-paid-intent',
                        'paymentStatus': 'PENDING', 'amountCents': 1500}
            elif path.endswith('/getOrderItem'):
                self.assertEqual(body, {'orderItemId': 'owned-item'})
                self.assertEqual(request.headers['X-Smartlect-User-Id'], 'alice')
                data = {'orderId': 'owned-order', 'orderItemId': 'owned-item', 'productName': 'Purchased item',
                        'propertyInfo': 'Standard', 'buyCount': 1, 'paidAmount': '15', 'refundedAmount': '0'}
            else:
                raise AssertionError(path)
            return httpx.Response(200, json={'status': 'success', 'data': data})

        config = {'SMARTLECT_USER_PORT': '18105', 'SMARTLECT_ORDER_PORT': '18104',
                  'SMARTLECT_INTERNAL_TOKEN': 'synthetic', 'SMARTLECT_VISITOR_SECRET': 's' * 48,
                  'SMARTLECT_ALLOWED_ORIGINS': 'http://smartlect.test'}
        transport = httpx.MockTransport(java)

        def app():
            return create_app(Settings(), config=config, store=SessionStore(self.connect),
                              identity=IdentityBridge(config, transport=transport),
                              commerce=AsyncCommerceClient(config, transport=transport))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url='http://smartlect.test') as client:
            client.cookies.set('token', 'alice')
            session = (await client.get('/api/assistant/session')).json()
            headers = {'Origin': 'http://smartlect.test', 'X-CSRF-Token': session['csrf_token']}
            response = await client.post('/api/assistant/conversations', json={}, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            conversation = response.json()['conversation_id']
            path = f'/api/assistant/conversations/{conversation}/proposals'
            body = {'message_id': 'explicit-order', 'action_type': 'order', 'parameters': {
                'addressId': 'address', 'orderList': [{'productId': 'sku', 'propertyValueIds': 'variant', 'buyCount': 1}]}}
            response = await client.post(path, json=body, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            run = response.json()
            self.assertEqual(run['state'], 'WAIT_USER')
            self.assertEqual((await client.post(path, json=body, headers=headers)).json()['agent_run_id'], run['agent_run_id'])
            proposal = run['result']['proposal']
            confirm_path = f"/api/assistant/proposals/{proposal['proposal_id']}/confirm"
            confirm = {'proposal_version': proposal['version'], 'approved': True}
            self.assertEqual((await client.post(confirm_path, json=confirm)).status_code, 403)
            self.assertEqual((await client.post(confirm_path, json={**confirm, 'amount': 1}, headers=headers)).status_code, 422)
            pending = await client.post(confirm_path, json=confirm, headers=headers)
            self.assertEqual(pending.status_code, 200, pending.text)
            self.assertEqual(pending.json()['state'], 'WAIT_OUTCOME')
            self.assertEqual(pending.json()['result']['proposal']['status'], 'UNKNOWN')
            self.assertEqual(len(writes), 1)

        # New app/Store instance, same persisted proposal/confirmation/idempotency key.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url='http://smartlect.test') as client:
            client.cookies.set('token', 'alice')
            session = (await client.get('/api/assistant/session')).json()
            headers = {'Origin': 'http://smartlect.test', 'X-CSRF-Token': session['csrf_token']}
            recovered = await client.post(confirm_path, json=confirm, headers=headers)
            self.assertEqual(recovered.status_code, 200, recovered.text)
            result = recovered.json()
            self.assertEqual(result['state'], 'COMPLETED')
            self.assertEqual(result['result']['proposal']['status'], 'SUCCEEDED')
            self.assertEqual(result['result']['proposal']['receipt']['paymentStatus'], 'PENDING')
            self.assertEqual(len(writes), 1)
            self.assertEqual(queries, writes)
            run_id = result['agent_run_id']
            replay = await client.get(f'/api/assistant/runs/{run_id}/events')
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertIn('event: completed', replay.text)
            self.assertIn('id: 1', replay.text)
            self.assertEqual((await client.post(confirm_path, json=confirm, headers=headers)).json()['proposal']['status'], 'SUCCEEDED')
            self.assertEqual(len(writes), 1)
            refund = await client.post(path, headers=headers, json={'message_id': 'explicit-refund',
                'action_type': 'refund', 'parameters': {'orderItemId': 'owned-item', 'refundAmountCents': 1500}})
            self.assertEqual(refund.status_code, 200, refund.text)
            refund_id = refund.json()['result']['proposal']['proposal_id']
            display_path = f'/api/assistant/proposals/{refund_id}/display'
            display = await client.get(display_path)
            self.assertEqual(display.status_code, 200, display.text)
            self.assertEqual(display.json()['order']['items'][0]['productName'], 'Purchased item')
            client.cookies.set('token', 'bob')
            self.assertEqual((await client.get(display_path)).status_code, 404)
            self.assertEqual((await client.get(f'/api/assistant/runs/{run_id}')).status_code, 404)
            self.assertEqual((await client.get(f'/api/assistant/runs/{run_id}/events')).status_code, 404)
            self.assertEqual(len(writes), 1)


if __name__ == '__main__':
    unittest.main()
