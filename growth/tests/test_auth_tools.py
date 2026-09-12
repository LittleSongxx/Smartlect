import unittest
from unittest.mock import Mock

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import ValidationError

from smartlect.auth import ActorContext, IdentityBridge
from smartlect.app import execute_proposal
from smartlect.commerce import AsyncCommerceClient, CommerceError
from smartlect.tools import CreateOrderArgs, RefundArgs, ToolReceipt, invoke, schemas


class AuthToolTests(unittest.IsolatedAsyncioTestCase):
    def test_merchant_csrf_cannot_be_reused_after_scope_selection(self):
        bridge = IdentityBridge({'SMARTLECT_USER_PORT':'18105','SMARTLECT_INTERNAL_TOKEN':'synthetic',
            'SMARTLECT_VISITOR_SECRET':'s'*48,'SMARTLECT_ALLOWED_ORIGINS':'http://smartlect.test'})
        actor = ActorContext(subject_type='merchant',actor_id='admin',session_id='session',permissions=('admin:legacy',))
        def request(proof):
            return Request({'type':'http','method':'POST','headers':[
                (b'origin',b'http://smartlect.test'),(b'x-csrf-token',proof.encode())]})
        old = request(bridge.csrf_token(actor))
        bridge.require_csrf(old,actor)
        selected = actor.model_copy(update={'execution_scope_id':'another-authorized-branch'})
        with self.assertRaises(HTTPException) as denied:
            bridge.require_csrf(old,selected)
        self.assertEqual(denied.exception.status_code,403)
        bridge.require_csrf(request(bridge.csrf_token(selected)),selected)

    async def test_cookie_bridge_visitor_and_csrf_bound_to_session(self):
        calls = []

        def java(request):
            calls.append(request)
            if request.headers['cookie'] == 'token=invalid':
                return httpx.Response(401)
            return httpx.Response(200, json={'status': 'success', 'data': {
                'subjectType': 'user', 'actorId': 'alice', 'sessionId': 'java-session-hash',
                'permissions': ['shopping:read', 'orders:read', 'orders:write']}})

        bridge = IdentityBridge({'SMARTLECT_USER_PORT': '18105', 'SMARTLECT_INTERNAL_TOKEN': 'synthetic',
                                 'SMARTLECT_VISITOR_SECRET': 's' * 48, 'SMARTLECT_ALLOWED_ORIGINS': 'http://smartlect.test'},
                                transport=httpx.MockTransport(java))
        app = FastAPI()

        @app.get('/session')
        async def session(request: Request, response: Response):
            actor = await bridge.authenticate(request, response)
            return {'actor': actor.model_dump(), 'csrf': bridge.csrf_token(actor)}

        @app.post('/write')
        async def write(request: Request, response: Response):
            actor = await bridge.authenticate(request, response)
            bridge.require_csrf(request, actor)
            actor.require('orders:write')
            return {'actor': actor.actor_id}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://smartlect.test') as client:
            guest = await client.get('/session', headers={'X-Smartlect-User-Id': 'admin', 'X-Admin-Permissions': '*'})
            self.assertEqual(guest.json()['actor']['subject_type'], 'visitor')
            self.assertIn('HttpOnly', guest.headers['set-cookie'])
            self.assertEqual(calls, [])
            self.assertEqual((await client.get('/session')).json()['actor'], guest.json()['actor'])
            guest_headers = {'Origin': 'http://smartlect.test', 'X-CSRF-Token': guest.json()['csrf']}
            self.assertEqual((await client.post('/write', headers=guest_headers)).status_code, 403)
            client.cookies.set('token', 'invalid')
            self.assertEqual((await client.get('/session')).status_code, 401)
            client.cookies.set('token', 'valid')
            ambiguous = await client.get('/session', headers={'Cookie': 'token=invalid; token=valid'})
            self.assertEqual(ambiguous.status_code, 401)
            user = (await client.get('/session', headers={'token': 'forged-header'})).json()
            self.assertEqual(user['actor']['actor_id'], 'alice')
            self.assertEqual(calls[-1].headers['cookie'], 'token=valid')
            self.assertNotIn('token', calls[-1].headers)
            self.assertEqual((await client.post('/write', headers=guest_headers)).status_code, 403)
            headers = {'Origin': 'http://smartlect.test', 'X-CSRF-Token': user['csrf']}
            self.assertEqual((await client.post('/write', headers=headers)).status_code, 200)
            self.assertEqual((await client.post('/write', headers={**headers, 'Origin': 'https://untrusted.test'})).status_code, 403)
            self.assertEqual((await client.post('/write')).status_code, 403)

    async def test_registry_cannot_grant_write_or_accept_actor_fields(self):
        guest = ActorContext(subject_type='visitor', actor_id='guest', session_id='proof', permissions=('shopping:read',))
        self.assertEqual([t['function']['name'] for t in schemas(guest)],
                         ['load_skill', 'request_handoff', 'search_knowledge', 'search_skus', 'recommend_skus', 'compare_skus', 'get_conversation_memory', 'get_product_offer'])
        self.assertEqual(schemas(guest, allowed=[]), [])
        with self.assertRaises(HTTPException):
            await invoke('propose_cancel', {'orderId': 'other'}, actor=guest, commerce=Mock(), store=Mock(), lease={})
        with self.assertRaises(ValueError):
            await invoke('execute_confirmed_action', {}, actor=guest, commerce=Mock(), store=Mock(), lease={})
        with self.assertRaises(ValidationError):
            await invoke('request_handoff', {'answer': 'transfer', 'actor_id': 'another-user'},
                         actor=guest, commerce=Mock(), store=Mock(), lease={})
        for params in ({'orderItemId': 'x', 'refundAmountCents': True}, {'orderItemId': 'x', 'refundAmountCents': 100, 'userId': 'other'}):
            with self.assertRaises(ValidationError):
                RefundArgs.model_validate(params)
        params = {'addressId': 'a', 'orderList': [{'productId': 'p', 'propertyValueIds': 'v', 'buyCount': True}]}
        with self.assertRaises(ValidationError):
            CreateOrderArgs.model_validate(params)
        params['orderList'][0]['buyCount'] = 1
        params['payMethod'] = '1'
        with self.assertRaises(ValidationError):
            CreateOrderArgs.model_validate(params)

    async def test_preference_tool_uses_current_exact_amount_and_trusted_lease(self):
        actor = ActorContext(subject_type='user', actor_id='alice', session_id='proof', permissions=('orders:write',))
        store, memory = Mock(), Mock()
        store.start_tool_call.return_value = {'outcome': 'started'}
        store.get_run.return_value = {'message_id': 'current-message'}
        memory.set_preference.return_value = {'preference_key': 'budget_max_cents', 'value': 10000, 'source': 'inferred'}
        lease = {'agent_run_id': 'trusted-run', 'conversation_id': 'trusted-conversation'}

        async def remember(text, arguments):
            memory.context.return_value = {'messages': [{'message_id': 'current-message', 'role': 'user', 'content': text}]}
            return await invoke('remember_preference', arguments, actor=actor, commerce=Mock(), store=store,
                                lease=lease, memory=memory)

        arguments = {'key': 'budget_max_cents', 'amount_cents': 10000, 'evidence_quote': '预算100元'}
        await remember('这次预算100元', arguments)
        saved = memory.set_preference.call_args
        self.assertEqual(saved.args, (actor, 'budget_max_cents', 10000))
        self.assertEqual(saved.kwargs['source'], 'inferred')
        self.assertEqual(saved.kwargs['evidence_ids'], ['current-message'])
        self.assertEqual(saved.kwargs['conversation_id'], 'trusted-conversation')
        self.assertIs(saved.kwargs['lease'], lease)
        memory.set_preference.reset_mock()

        for text, quote, cents in [('预算1100元', '100元', 10000), ('预算1,000元', '1,000元', 0),
                                   ('预算100.001元', '100.001元', 100), ('预算-100元', '-100元', 10000)]:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'preference_budget_requires_explicit_currency'):
                await remember(text, {'key': 'budget_max_cents', 'amount_cents': cents, 'evidence_quote': quote})
        for extra in ({'lease': lease}, {'userId': 'another'}, {'source': 'explicit'}, {'amount_cents': '10000'}):
            with self.assertRaises(ValidationError):
                await remember('这次预算100元', {**arguments, **extra})
        with self.assertRaises(ValidationError):
            await remember('我喜欢轻便', {'key': 'likes', 'list_value': [], 'evidence_quote': '喜欢轻便'})
        with self.assertRaisesRegex(ValueError, 'exactly_one_preference_value_required'):
            await remember('这次预算100元', {**arguments, 'text_value': '预算100元'})
        with self.assertRaisesRegex(ValueError, 'preference_requires_current_user_evidence'):
            await remember('这次预算200元', arguments)
        memory.set_preference.assert_not_called()
        from smartlect.state import StateError
        for code, error_type in [('explicit_preference_has_priority', ValueError), ('lease_lost', StateError),
                                  ('run_not_running', StateError), ('conversation_not_found', StateError)]:
            memory.set_preference.side_effect = StateError(code)
            with self.assertRaisesRegex(error_type, code):
                await remember('这次预算100元', arguments)

    async def test_refund_zero_and_java_timeout_are_not_false_rejections(self):
        actor = ActorContext(subject_type='user', actor_id='alice', session_id='proof', permissions=('orders:write',))
        store = Mock()
        store.start_tool_call.return_value = {"outcome": "started"}
        store.create_proposal.return_value = {'proposal_id': 'p', 'status': 'PROPOSED'}
        config = {'SMARTLECT_INTERNAL_TOKEN': 'synthetic', 'SMARTLECT_ORDER_PORT': '18104'}
        for zero in (None, 0, '0.00'):
            def java(request):
                self.assertEqual(request.headers['X-Smartlect-User-Id'], 'alice')
                return httpx.Response(200, json={'status': 'success', 'data': {'paidAmount': 10, 'refundedAmount': zero}})
            commerce = AsyncCommerceClient(config, transport=httpx.MockTransport(java))
            result = await invoke('propose_refund', {'orderItemId': 'item', 'refundAmountCents': 1000},
                                  actor=actor, commerce=commerce, store=store, lease={})
            self.assertEqual(result['data']['status'], 'PROPOSED')

        def timeout(request):
            raise httpx.ReadTimeout('synthetic timeout', request=request)

        commerce = AsyncCommerceClient(config, transport=httpx.MockTransport(timeout))
        with self.assertRaises(CommerceError):
            await invoke('propose_refund', {'orderItemId': 'item', 'refundAmountCents': 1000},
                         actor=actor, commerce=commerce, store=store, lease={})
        self.assertEqual(store.finish_tool_call.call_args.kwargs['outcome'], 'unknown')

    async def test_refund_query_pending_and_recovery_query_rejection(self):
        actor = ActorContext(subject_type='user', actor_id='alice', session_id='proof', permissions=('orders:read',))
        store = Mock()
        store.start_tool_call.return_value = {'outcome': 'started'}
        config = {'SMARTLECT_INTERNAL_TOKEN': 'synthetic', 'SMARTLECT_ORDER_PORT': '18104'}
        commerce = AsyncCommerceClient(config, transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={'status': 'success', 'data': [{'status': 'PENDING_PAYMENT'}]})))
        result = await invoke('get_refund_status', {'orderId': 'order'}, actor=actor, commerce=commerce, store=store, lease={})
        self.assertTrue(result['tool_succeeded'])
        self.assertEqual(result['command_status'], 'business_pending')
        self.assertEqual(result['schema_version'], 'tool-receipt-v1')
        with self.assertRaises(ValidationError):
            ToolReceipt.model_validate({**result, 'command_status': 'SUCCESS'})
        params = {'orderItemId': 'item', 'refundAmountCents': 1000, 'reason': 'confirmed reason'}

        def rejected_query(request):
            import json
            self.assertTrue(request.url.path.endswith('/actionStatus'))
            self.assertEqual(json.loads(request.content)['params'], params)
            return httpx.Response(403, json={'status': 'error', 'info': 'query forbidden'})

        commerce = AsyncCommerceClient(config, transport=httpx.MockTransport(rejected_query))
        with self.assertRaises(CommerceError) as error:
            await execute_proposal({'action_type': 'refund', 'parameters': params, 'recover_only': True,
                                    'idempotency_key': 'original-action'}, actor, commerce)
        self.assertEqual(str(error.exception), 'commerce_outcome_unknown')

    async def test_list_my_coupons_returns_unused_only(self):
        actor = ActorContext(subject_type='user', actor_id='alice', session_id='proof', permissions=('orders:read',))
        store = Mock()
        store.start_tool_call.return_value = {'outcome': 'started'}
        config = {'SMARTLECT_INTERNAL_TOKEN': 'synthetic', 'SMARTLECT_COUPON_PORT': '18106'}
        commerce = AsyncCommerceClient(config, transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={'status': 'success', 'data': [
                {'userCouponId': 'u1', 'status': 0}, {'userCouponId': 'u2', 'status': 1}]})))
        result = await invoke('list_my_coupons', {}, actor=actor, commerce=commerce, store=store, lease={})
        self.assertEqual(result['data'], [{'userCouponId': 'u1', 'status': 0}])

    async def test_order_attribution_failure_is_visible_and_does_not_block(self):
        actor = ActorContext(subject_type='user', actor_id='alice', session_id='proof', permissions=('orders:write',))
        config = {'SMARTLECT_INTERNAL_TOKEN': 'synthetic', 'SMARTLECT_ORDER_PORT': '18104'}
        commerce = AsyncCommerceClient(config, transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={'status': 'success', 'data': {'commandStatus': 'business_completed', 'orderId': 'o1'}})))

        class BrokenAttribution:
            def freeze_context(self, _actor, _action_id):
                raise RuntimeError('freeze failed')

        receipt = await execute_proposal({
            'action_type': 'order', 'parameters': {'addressId': 'a1'}, 'recover_only': False,
            'idempotency_key': 'k1', 'quote_id': 'q1', 'quote_total_cents': 100, 'action_id': 'act1',
        }, actor, commerce, BrokenAttribution())
        self.assertEqual(receipt['attribution_attached'], False)
        self.assertEqual(receipt['commandStatus'], 'business_completed')


if __name__ == '__main__':
    unittest.main()
