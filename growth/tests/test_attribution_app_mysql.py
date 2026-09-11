"""Opt-in HTTP contracts: real Growth stores, synthetic recommendations and Java identity."""
import asyncio
import json
import os
import unittest
import uuid

import httpx

from smartlect.app import create_app
from smartlect.attribution import AttributionStore
from smartlect.auth import IdentityBridge
from smartlect.commerce import AsyncCommerceClient
from smartlect.config import Settings
from smartlect.memory import MemoryStore
from smartlect.recommendation.service import RecommendationRequest, constraints
from smartlect.recommendation.store import StrategyStore
from smartlect.state import SessionStore
import test_ledger_mysql


class FakeRecommendationService:
    """Only candidate generation is fake; assignment and receipt persistence are real."""
    def __init__(self, connect, product_id):
        self.strategies = StrategyStore(connect)
        self.product_id = product_id
        self.calls = []

    async def recommend(self, actor, request, *, preferences=(), seed_product_id=None,
                        subject_key=None, product_scope=None):
        self.calls.append(dict(actor=actor, request=request, preferences=preferences,
                               seed_product_id=seed_product_id, subject_key=subject_key,
                               product_scope=product_scope))
        assignment = await asyncio.to_thread(self.strategies.assign, actor, subject_key=subject_key)
        return {**assignment, 'ranking_mode': 'synthetic-http-fixture',
                'hard_constraints': constraints(request, preferences), 'items': [{
                    'productId': self.product_id, 'propertyValueIdHash': 'standard',
                    'propertyValueIds': 'variant', 'sku_key': self.product_id + ':standard',
                    'price_cents': 1500, 'stock': 5}]}


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS') == '1',
                     'set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL')
class AttributionAppMySQLTests(unittest.IsolatedAsyncioTestCase):
    setUpClass = classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    async def asyncSetUp(self):
        self.origin = 'http://smartlect.test'
        suffix = uuid.uuid4().hex
        self.alice, self.bob = 'alice-' + suffix, 'bob-' + suffix
        self.product_id, self.seed = 'product-' + suffix, 'seed-' + suffix
        self.java_calls = []
        self.config = {'SMARTLECT_USER_PORT': '18105', 'SMARTLECT_ORDER_PORT': '18104',
                       'SMARTLECT_INTERNAL_TOKEN': 'synthetic-http-internal-token',
                       'SMARTLECT_VISITOR_SECRET': 'synthetic-http-visitor-secret-' + 's' * 32,
                       'SMARTLECT_ALLOWED_ORIGINS': self.origin}

        def java(request):
            self.assertEqual(request.headers['X-Internal-Token'], self.config['SMARTLECT_INTERNAL_TOKEN'])
            self.java_calls.append(request)
            if request.url.path == '/internal/identity/introspect':
                self.assertEqual(json.loads(request.content), {'realm': 'user'})
                user = request.headers['cookie'].removeprefix('token=')
                self.assertIn(user, (self.alice, self.bob))
                data = {'subjectType': 'user', 'actorId': user, 'sessionId': user + '-session',
                        'permissions': ['shopping:read', 'orders:read', 'orders:write']}
            elif request.url.path == '/internal/user/commerce/latestBrowseProductId':
                self.assertIn(request.headers['X-Smartlect-User-Id'], (self.alice, self.bob))
                self.assertEqual(json.loads(request.content), {})
                data = {'productId': self.seed}
            else:
                raise AssertionError('Unexpected Java call: ' + request.url.path)
            return httpx.Response(200, json={'status': 'success', 'data': data})

        transport = httpx.MockTransport(java)
        self.identity = IdentityBridge(self.config, transport=transport)
        self.attribution = AttributionStore(self.connect)
        self.recommendations = FakeRecommendationService(self.connect, self.product_id)
        self.app = create_app(Settings(), config=self.config, store=SessionStore(self.connect),
                              memory=MemoryStore(self.connect), attribution=self.attribution,
                              identity=self.identity, recommendations=self.recommendations,
                              commerce=AsyncCommerceClient(self.config, transport=transport))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(self.app), base_url=self.origin)
        self.addAsyncCleanup(self.client.aclose)

    def body(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    async def session(self, client=None):
        client = client or self.client
        session = self.body(await client.get('/api/assistant/session'))
        client.headers.update({'Origin': self.origin, 'X-CSRF-Token': session['csrf_token']})
        return session['actor']

    async def test_visitor_receipt_touch_idempotency_and_forged_fields(self):
        actor = await self.session()
        self.assertEqual(actor['subject_type'], 'visitor')
        landing_path = '/api/assistant/traffic/landing'
        landing = self.body(await self.client.post(landing_path, json={'entry_id': 'entry'}))
        self.assertEqual(self.body(await self.client.post(landing_path, json={'entry_id': 'entry'})), landing)
        self.assertEqual((landing['actor_id'], landing['traffic_channel']), (actor['actor_id'], 'NATURAL'))
        receipt = self.body(await self.client.get('/api/assistant/recommendations'))
        recommendation_id = receipt['recommendation_id']
        self.assertEqual((receipt['items'][0]['recommendation_id'], receipt['items'][0]['position']),
                         (recommendation_id, 1))
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT actor_id,result_json FROM recommendation_receipt WHERE recommendation_id=%s',
                           (recommendation_id,))
            saved = cursor.fetchone()
            self.assertEqual((saved['actor_id'], json.loads(saved['result_json'])), (actor['actor_id'], receipt))
            cursor.execute('SELECT COUNT(*) AS count FROM traffic_touch WHERE recommendation_id=%s', (recommendation_id,))
            self.assertEqual(cursor.fetchone()['count'], 0)

        exposure_path = f'/api/assistant/recommendations/{recommendation_id}/exposures'
        click_path = f'/api/assistant/recommendations/{recommendation_id}/clicks'
        for path, payload, kind in [(exposure_path, {'positions': [1, 1]}, 'REC_IMPRESSION'),
                                    (click_path, {'position': 1}, 'REC_CLICK')]:
            first = self.body(await self.client.post(path, json=payload))
            self.assertEqual(self.body(await self.client.post(path, json=payload)), first)
            self.assertEqual(len(first['touches']), 1)
            touch = first['touches'][0]
            self.assertEqual((touch['kind'], touch['product_id'], touch['sku_key']),
                             (kind, self.product_id, 'standard'))
        for path, payload in [(landing_path, {'entry_id': 'forged'}),
                              (exposure_path, {'positions': [1]}), (click_path, {'position': 1})]:
            for field, value in [('actor_id', self.bob), ('userId', self.bob), ('visitor_id', uuid.uuid4().hex),
                                 ('execution_scope_id', 'forged'), ('occurred_at', '2000-01-01T00:00:00Z'),
                                 ('price_cents', 1)]:
                with self.subTest(path=path, field=field):
                    self.body(await self.client.post(path, json={**payload, field: value}), 422)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS count FROM traffic_touch WHERE actor_id=%s', (actor['actor_id'],))
            self.assertEqual(cursor.fetchone()['count'], 3)
        self.assertEqual(self.java_calls, [])

    async def test_bind_moves_same_conversation_and_rejects_another_account_claim(self):
        visitor = await self.session()
        proof = self.client.cookies.get('smartlect_visitor')
        conversation = self.body(await self.client.post('/api/assistant/conversations', json={}))['conversation_id']
        path = '/api/assistant/conversations/' + conversation
        receipt = self.body(await self.client.get('/api/assistant/recommendations'))
        self.client.cookies.set('token', self.alice)
        logged_in = await self.session()
        self.assertEqual((logged_in['actor_id'], logged_in['visitor_id']), (self.alice, visitor['actor_id']))
        bind_path = '/api/assistant/traffic/bind'
        for forged in ({'visitor_id': uuid.uuid4().hex}, {'userId': self.bob}, {'conversation_id': conversation}):
            self.body(await self.client.post(bind_path, json=forged), 422)
        bound = self.body(await self.client.post(bind_path, json={}))
        self.assertEqual((bound['bound'], bound['conversation_ids']), (True, [conversation]))
        owned = self.body(await self.client.get(path))
        self.assertEqual((owned['conversation_id'], owned['subject_type'], owned['actor_id']),
                         (conversation, 'user', self.alice))
        after_login = self.body(await self.client.get('/api/assistant/recommendations'))
        self.assertEqual(after_login['assignment_id'], receipt['assignment_id'])
        self.assertEqual(self.body(await self.client.post(bind_path, json={}))['conversation_ids'], [])

        async with httpx.AsyncClient(transport=httpx.ASGITransport(self.app), base_url=self.origin) as other:
            other.cookies.set('smartlect_visitor', proof, domain='smartlect.test', path='/')
            self.assertEqual((await self.session(other))['actor_id'], visitor['actor_id'])
            self.body(await other.get(path), 404)
            self.assertNotIn(conversation, [row['conversation_id'] for row in self.body(
                await other.get('/api/assistant/conversations'))])
            other.cookies.set('token', self.bob)
            await self.session(other)
            self.body(await other.get(path), 404)
            response = await other.post(bind_path, json={})
            self.assertEqual(self.body(response, 409)['error'], 'visitor_already_bound_to_another_account')
            self.assertIn('Max-Age=0', response.headers['set-cookie'])
            self.assertIsNone(other.cookies.get('smartlect_visitor'))
            remaining = await self.session(other)
            self.assertEqual((remaining['actor_id'], remaining['visitor_id']), (self.bob, None))
            self.body(await other.get(path), 404)

    async def test_stale_optional_visitor_and_saved_avoid_survive_get_recommendations(self):
        stale = self.identity._sign('visitor', {'id': uuid.uuid4().hex, 'expires': 1})
        for proof in ('malformed-proof', stale):
            with self.subTest(proof_kind='expired' if proof == stale else 'malformed'):
                self.client.cookies.clear()
                self.client.cookies.set('token', self.alice)
                self.client.cookies.set('smartlect_visitor', proof, domain='smartlect.test', path='/')
                actor = await self.session()
                self.assertEqual((actor['subject_type'], actor['actor_id'], actor['visitor_id']), ('user', self.alice, None))
                self.assertIsNone(self.client.cookies.get('smartlect_visitor'))
        self.body(await self.client.put('/api/assistant/preferences/avoid', json={'value': ['羊毛']}))
        for value in (self.alice, [self.alice]):
            self.body(await self.client.put('/api/assistant/preferences/purpose', json={'value': value}), 422)
        self.assertEqual(len(self.body(await self.client.get('/api/assistant/preferences'))), 1)
        receipt = self.body(await self.client.get('/api/assistant/recommendations',
                               params={'query': '外套', 'max_price_cents': 5000, 'limit': 2}))
        call = self.recommendations.calls[-1]
        self.assertIsInstance(call['request'], RecommendationRequest)
        self.assertNotIn('excluded_terms', call['request'].model_fields_set)
        self.assertEqual(receipt['hard_constraints']['excluded_terms'], ['羊毛'])
        self.assertEqual(receipt['hard_constraints']['max_price_cents'], 5000)
        self.assertEqual(call['seed_product_id'], self.seed)
        self.assertEqual(call['subject_key'], 'user:' + self.alice)
        for params in ({'max_price_cents': -1}, {'limit': 9}, {'query': 'x' * 201}):
            self.body(await self.client.get('/api/assistant/recommendations', params=params), 422)
        self.assertEqual(len(self.recommendations.calls), 1)

    async def test_proposal_scope_denied_before_java_quote(self):
        scope = 'scope-' + uuid.uuid4().hex
        self.attribution.register_scope(scope, scenario_run_id='http-scenario', branch_id='isolated',
                                        users=[self.alice], products=[self.product_id])
        for user, denied_product in [(self.alice, 'outside-' + uuid.uuid4().hex), (self.bob, self.product_id)]:
            with self.subTest(user=user):
                self.client.cookies.set('token', user)
                actor = await self.session()
                self.assertEqual(actor['execution_scope_id'], scope if user == self.alice else 'store')
                conversation = self.body(await self.client.post('/api/assistant/conversations', json={}))['conversation_id']
                path = f'/api/assistant/conversations/{conversation}'
                payload = {'message_id': 'outside-scope', 'action_type': 'order', 'parameters': {
                    'addressId': 'address', 'orderList': [{'productId': denied_product,
                                                         'propertyValueIds': 'variant', 'buyCount': 1}]}}
                rejected = self.body(await self.client.post(path + '/proposals', json=payload), 403)
                self.assertEqual(rejected['error'], 'product_scope_denied')
                saved = self.body(await self.client.get(path))
                self.assertEqual(saved['proposals'], [])
                self.assertEqual(saved['runs'][0]['state'], 'FAILED')
        self.assertTrue(all(request.url.path == '/internal/identity/introspect' for request in self.java_calls))

    async def test_internal_validation_requires_token_clicked_sku_and_owner(self):
        self.client.cookies.set('token', self.alice)
        await self.session()
        receipt = self.body(await self.client.get('/api/assistant/recommendations'))
        recommendation_id = receipt['recommendation_id']
        item = {'requestId': recommendation_id, 'productId': self.product_id, 'skuKey': 'standard', 'position': 1}
        path = '/internal/attribution/validateBatch'
        payload = {'userId': self.alice, 'items': [item]}
        self.body(await self.client.post(path, json=payload), 401)
        self.body(await self.client.post(path, json=payload, headers={'X-Internal-Token': 'wrong'}), 401)
        headers = {'X-Internal-Token': self.config['SMARTLECT_INTERNAL_TOKEN']}
        self.body(await self.client.post(f'/api/assistant/recommendations/{recommendation_id}/exposures',
                                        json={'positions': [1]}))
        self.assertEqual(self.body(await self.client.post(path, json=payload, headers=headers))['data'], [])
        click = self.body(await self.client.post(f'/api/assistant/recommendations/{recommendation_id}/clicks',
                                                json={'position': 1}))['touches'][0]
        variants = [item, {**item, 'skuKey': 'other'}, {key: value for key, value in item.items() if key != 'skuKey'},
                    {**item, 'productId': 'other'}, {**item, 'position': 2}]
        valid = self.body(await self.client.post(path, json={**payload, 'items': variants}, headers=headers))
        self.assertEqual(valid, {'status': 'success', 'code': 200, 'data': [{
            **item, 'source': 'recommendation_click', 'occurredAt': click['occurred_at']}]})
        self.assertEqual(self.body(await self.client.post(path, json={**payload, 'userId': self.bob},
                                                         headers=headers))['data'], [])
        self.body(await self.client.post(path, json={**payload, 'items': [{**item, 'userId': self.bob}]},
                                         headers=headers), 422)


if __name__ == '__main__':
    unittest.main()
