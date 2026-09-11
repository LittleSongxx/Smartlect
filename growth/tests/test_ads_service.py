"""Lightweight HTTP/Java observation boundaries; durable concurrency is tested separately."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from pydantic import ValidationError

from smartlect.ads.service import AdsService, ActionRequest, AdClickRequest, GrantRequest, rank_ads
from smartlect.auth import IdentityBridge, ActorContext
from smartlect.commerce import AsyncCommerceClient
from smartlect.config import Settings
from smartlect.state import StateError


TARGET = {'product_id': 'product', 'sku_key': 'hash'}
CAMPAIGN = {**TARGET, 'campaign_id': 'campaign', 'name': '推广', 'budget_cents': 100, 'cpc_cents': 1}
ACTION = {'action_id': 'action', 'idempotency_key': 'action-key', 'grant_id': 'grant',
          'plan_id': 'plan', 'plan_version': 1, 'reason_code': 'merchant_approved', 'actions': [
              {'action_type': 'activate_campaign', 'campaign_id': 'campaign', 'expected_version': 1}]}


class AdsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_ads_rank_owned_available_skus_by_preferences_without_recording_traffic(self):
        from test_recommendation import FakeCommerce
        commerce = FakeCommerce()
        actor = ActorContext(subject_type='user', actor_id='alice', session_id='test',
                             execution_scope_id='scope', permissions=('shopping:read',))
        rows = [{'creative_id': 'ad-' + key, 'campaign_id': 'campaign-' + key, 'product_id': key,
                 'sku_key': 'hash-' + key, 'copy_text': '推广：查看规格', 'campaign_version': 1,
                 'creative_version': 2} for key in ('content', 'new', 'outside')]
        store = Mock()
        store.delivery_candidates.return_value = rows
        store.product_scope.return_value = {'include': ['content', 'new'], 'exclude': ['outside']}
        service = AdsService(commerce, store)
        keyboard = await service.recommend(actor, preferences=[{'preference_key': 'likes', 'value': ['键盘']}])
        mouse = await service.recommend(actor, preferences=[{'preference_key': 'likes', 'value': ['鼠标']}])
        self.assertEqual(keyboard['items'][0]['productId'], 'content')
        self.assertEqual(mouse['items'][0]['productId'], 'new')
        self.assertEqual(mouse['items'][0]['propertyValueIds'], 'vnew')
        self.assertEqual(mouse['items'][0]['sku_key'], 'hash-new')
        self.assertEqual(mouse['ranking_mode'], 'ad-fatigue-pacing-v1')
        self.assertTrue(all(row['productId'] != 'outside' for row in mouse['items']))
        excluded = await service.recommend(actor, preferences=[{'preference_key': 'avoid', 'value': ['鼠标'], 'source': 'explicit'}])
        self.assertEqual([row['productId'] for row in excluded['items']], ['content'])
        commerce.stocks['content'] = 0
        commerce.stocks['new'] = 0
        self.assertEqual((await service.recommend(actor))['items'], [])
        self.assertFalse(store.expose.called)
        self.assertFalse(store.click.called)

    def pair(self, name, *, rule_score=1.0, seen=0, clicked=0, budget=1000, spent=0):
        return ({'rule_score': rule_score},
                {'campaign_id': 'c-' + name, 'creative_id': name, 'viewer_impressions': seen,
                 'viewer_clicks': clicked, 'budget_cents': budget, 'spent_cents': spent})

    def order(self, pairs):
        return [candidate['creative_id'] for _, candidate, _ in rank_ads(pairs)]

    def test_ad_order_uses_viewer_fatigue_and_pacing_not_relevance_alone(self):
        # Relevance alone is the plain recommendation signal. An ad slot also has to stop
        # repeating a creative this viewer ignored and stop one campaign owning the slot.
        self.assertEqual(self.order([self.pair('ignored', seen=6), self.pair('fresh')]),
                         ['fresh', 'ignored'])
        # Having clicked before is interest, so it is not treated as fatigue.
        self.assertEqual(self.order([self.pair('engaged', seen=6, clicked=2), self.pair('fresh')]),
                         ['engaged', 'fresh'])
        # Same fatigue, so the campaign with budget headroom leads.
        self.assertEqual(self.order([self.pair('drained', spent=950), self.pair('funded', spent=100)]),
                         ['funded', 'drained'])
        # Relevance still counts, but a less relevant ad is never dropped from an eligible set.
        scored = rank_ads([self.pair('vague', rule_score=0), self.pair('matched', rule_score=1)])
        self.assertEqual([candidate['creative_id'] for _, candidate, _ in scored], ['matched', 'vague'])
        self.assertTrue(all(score > 0 for _, _, score in scored))

    def test_ad_order_is_deterministic_and_tolerates_missing_counters(self):
        pairs = [self.pair('b'), self.pair('a')]
        self.assertEqual(self.order(pairs), ['a', 'b'])
        self.assertEqual(self.order(list(reversed(pairs))), ['a', 'b'])
        bare = ({}, {'campaign_id': 'c', 'creative_id': 'bare'})
        self.assertEqual(self.order([bare]), ['bare'])
        negative = ({'rule_score': -5}, {'campaign_id': 'c', 'creative_id': 'odd',
                    'viewer_impressions': -1, 'viewer_clicks': -1, 'budget_cents': 10, 'spent_cents': 99})
        self.assertEqual(self.order([negative]), ['odd'])
        self.assertGreaterEqual(rank_ads([negative])[0][2], 0)

    async def test_ad_preview_discards_creative_changed_while_java_facts_were_loading(self):
        from test_recommendation import FakeCommerce
        store = Mock()
        row = {'creative_id': 'ad', 'campaign_id': 'campaign', 'product_id': 'content', 'sku_key': 'hash-content',
               'copy_text': '原素材', 'campaign_version': 1, 'creative_version': 1}
        store.delivery_candidates.side_effect = [[row], [{**row, 'creative_version': 2, 'copy_text': '新素材'}]]
        store.product_scope.return_value = {'include': ['content'], 'exclude': []}
        actor = ActorContext(subject_type='visitor', actor_id='visitor', session_id='test',
                             execution_scope_id='scope', permissions=('shopping:read',))
        self.assertEqual((await AdsService(FakeCommerce(), store).recommend(actor))['items'], [])

    async def test_observation_commits_before_rejected_action_and_replay_skips_java(self):
        log = []
        store = Mock()
        ticket = {**TARGET, 'generation': 7, 'query_started_at': datetime.now(timezone.utc).isoformat()}
        store.action_replay.return_value = None
        store.action_targets.return_value = [TARGET]
        store.begin_observation.side_effect = lambda *args: (log.append('begin_committed'), ticket)[1]

        async def stock(*args, **kwargs):
            self.assertEqual(log, ['begin_committed'])
            log.append('java_network')
            self.assertEqual(kwargs['data'], [{'productId': 'product', 'propertyValueIdHash': 'hash'}])
            return [{'productId': 'product', 'propertyValueIdHash': 'hash', 'stock': 0}]

        def finish(actor, current, stock, completed, elapsed_ms):
            self.assertIs(current, ticket)
            self.assertEqual(stock, 0)
            self.assertGreaterEqual(datetime.fromisoformat(completed), datetime.fromisoformat(ticket['query_started_at']))
            self.assertGreaterEqual(elapsed_ms, 0)
            log.append('protection_committed')
            return {**ticket, 'stock': stock}

        def reject(*args):
            self.assertEqual(log[-1], 'protection_committed')
            raise StateError('resource_version_conflict')

        store.finish_observation.side_effect = finish
        store.execute_action.side_effect = reject
        commerce = SimpleNamespace(request=AsyncMock(side_effect=stock))
        service = AdsService(commerce, store)
        with self.assertRaisesRegex(StateError, 'resource_version_conflict'):
            await service.execute_action('trusted-actor', ACTION)
        self.assertEqual(log, ['begin_committed', 'java_network', 'protection_committed'])
        receipt = {'click_id': 'click', 'fee_cents': 1, 'touch_id': 'touch'}
        store.click_replay.return_value = receipt
        self.assertIs(await service.click('trusted-actor', {'click_id': 'click', 'exposure_id': 'exposure'}), receipt)
        store.click_target.assert_not_called()
        self.assertEqual(commerce.request.await_count, 1)

    async def test_stock_missing_duplicate_invalid_or_transport_failure_is_unknown(self):
        row = {'productId': 'product', 'propertyValueIdHash': 'hash', 'stock': 2}
        config = {'SMARTLECT_INTERNAL_TOKEN': 'synthetic-only', 'SMARTLECT_STOCK_PORT': '18103'}
        cases = [[], None, {}, [row, row], [{**row, 'stock': None}], [{**row, 'stock': True}],
                 [{**row, 'stock': '2'}], [{**row, 'stock': -1}], [{**row, 'stock': 2147483648}],
                 [{**row, 'productId': 'other'}], 'malformed-envelope', 'timeout']
        for value in cases:
            with self.subTest(value=value):
                def java(request):
                    if value == 'timeout':
                        raise httpx.ReadTimeout('synthetic timeout', request=request)
                    return httpx.Response(200, json=[] if value == 'malformed-envelope'
                                          else {'status': 'success', 'data': value})
                store = Mock()
                store.begin_observation.return_value = {**TARGET, 'generation': 1,
                    'query_started_at': datetime.now(timezone.utc).isoformat()}
                store.finish_observation.side_effect = lambda actor, ticket, stock, done, duration: {'stock': stock}
                result = await AdsService(AsyncCommerceClient(config, transport=httpx.MockTransport(java)), store).observe('actor', TARGET)
                self.assertIsNone(result['stock'])
                store.finish_observation.assert_called_once()

    async def test_conservative_age_starts_before_query_and_old_zero_still_protects(self):
        for stock in (1, 0):
            with self.subTest(stock=stock):
                store = Mock()
                store.begin_observation.return_value = {**TARGET, 'generation': 2, 'query_started_at': '2026-01-01T00:00:00Z'}
                store.finish_observation.side_effect = lambda actor, ticket, value, done, duration: {'stock': value, 'elapsed_ms': duration}
                commerce = SimpleNamespace(request=AsyncMock(return_value=[{
                    'productId': 'product', 'propertyValueIdHash': 'hash', 'stock': stock}]))
                with patch('smartlect.ads.service.time', SimpleNamespace(monotonic=Mock(side_effect=[1.0, 2.01]))):
                    result = await AdsService(commerce, store).observe('actor', TARGET)
                self.assertEqual(result['stock'], 0 if stock == 0 else None)
                self.assertAlmostEqual(result['elapsed_ms'], 1010)

    async def test_real_sku_required_for_draft_without_requiring_positive_inventory(self):
        store = Mock()
        store.create_campaign.return_value = {'campaign_id': 'campaign', 'status': 'DRAFT'}
        commerce = SimpleNamespace(request=AsyncMock(return_value={'skus': [
            {'productId': 'product', 'propertyValueIdHash': 'hash'}]}))
        service = AdsService(commerce, store)
        self.assertEqual((await service.create_campaign('actor', CAMPAIGN))['status'], 'DRAFT')
        commerce.request.assert_awaited_once_with('product', '/internal/product/snapshotBatch', data={'productIds': ['product']})
        commerce.request.return_value = {'skus': []}
        with self.assertRaisesRegex(StateError, 'advertised_sku_not_found'):
            await service.create_campaign('actor', CAMPAIGN)
        with self.assertRaisesRegex(StateError, 'advertised_sku_not_found'):
            await service.create_campaign('actor', {**CAMPAIGN, 'sku_key': 'other'})
        self.assertEqual(store.create_campaign.call_count, 1)

    async def test_http_real_cookie_realm_csrf_and_strict_money_identity_fields(self):
        from smartlect.app import create_app
        origin = 'http://smartlect.test'
        config = {'SMARTLECT_USER_PORT': '18105', 'SMARTLECT_INTERNAL_TOKEN': 'synthetic-only',
                  'SMARTLECT_VISITOR_SECRET': 's' * 48, 'SMARTLECT_ALLOWED_ORIGINS': origin}

        def java(request):
            realm = json.loads(request.content)['realm']
            cookie = request.headers['cookie']
            actor_id = cookie.split('=', 1)[1]
            permissions = ['admin:legacy'] if actor_id == 'admin' else ['analytics:read'] if realm == 'merchant' else ['shopping:read']
            return httpx.Response(200, json={'status': 'success', 'data': {
                'subjectType': realm, 'actorId': actor_id, 'sessionId': actor_id + '-session', 'permissions': permissions}})

        bridge = IdentityBridge(config, transport=httpx.MockTransport(java))
        ads = SimpleNamespace(store=Mock(), create_campaign=AsyncMock(return_value={'status': 'DRAFT'}),
                              execute_action=AsyncMock(return_value={'status': 'APPLIED'}),
                              recommend=AsyncMock(return_value={'items': [], 'ranking_mode': 'rule'}),
                              expose=AsyncMock(return_value={'exposure_id': 'exposure'}),
                              click=AsyncMock(return_value={'click_id': 'click'}))
        attribution = SimpleNamespace(resolve_actor=lambda actor: actor)
        app = create_app(Settings(), config=config, store=SimpleNamespace(connect=lambda: None),
                         identity=bridge, attribution=attribution, ads=ads,
                         memory=SimpleNamespace(preferences=lambda actor: [{'preference_key': 'likes', 'value': ['杯']}]),
                         merchant=SimpleNamespace(store=SimpleNamespace(selected_actor=lambda actor: actor)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=origin) as client:
            path = '/admin-api/assistant/ads/campaigns'
            self.assertEqual((await client.post(path, json=CAMPAIGN, headers={'X-Admin-Permissions': '*'})).status_code, 401)
            client.cookies.set('token', 'user')
            self.assertEqual((await client.post(path, json=CAMPAIGN)).status_code, 401)
            client.cookies.set('adminToken', 'analyst')
            session = (await client.get('/admin-api/assistant/session')).json()
            headers = {'Origin': origin, 'X-CSRF-Token': session['csrf_token']}
            self.assertEqual((await client.post(path, json=CAMPAIGN, headers=headers)).status_code, 403)
            client.cookies.set('adminToken', 'admin')
            self.assertEqual((await client.post(path, json=CAMPAIGN, headers=headers)).status_code, 403)
            session = (await client.get('/admin-api/assistant/session')).json()
            headers['X-CSRF-Token'] = session['csrf_token']
            self.assertEqual((await client.post(path, json=CAMPAIGN)).status_code, 403)
            for change in ({'budget_cents': True}, {'budget_cents': 0.5}, {'budget_cents': '10'},
                           {'budget_cents': -1}, {'cpc_cents': 0}, {'actor_id': 'other'},
                           {'execution_scope_id': 'other'}, {'status': 'ACTIVE'}):
                self.assertEqual((await client.post(path, json={**CAMPAIGN, **change}, headers=headers)).status_code, 422)
            self.assertEqual((await client.post(path, json=CAMPAIGN, headers=headers)).status_code, 200)
            self.assertEqual(ads.create_campaign.call_args.args[0].actor_id, 'admin')
            self.assertEqual(ads.create_campaign.call_count, 1)
            user_session = (await client.get('/api/assistant/session')).json()
            preview = await client.get('/api/assistant/ads/recommendations?limit=2')
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(ads.recommend.call_args.args[0].actor_id, 'user')
            self.assertEqual(ads.recommend.call_args.kwargs['preferences'][0]['value'], ['杯'])
            self.assertFalse(ads.expose.called)
            self.assertFalse(ads.click.called)
            headers['X-CSRF-Token'] = user_session['csrf_token']
            click_path = '/api/assistant/ads/clicks'
            click = {'click_id': 'click', 'exposure_id': 'exposure'}
            self.assertEqual((await client.post(click_path, json={**click, 'fee_cents': 0}, headers=headers)).status_code, 422)
            self.assertEqual((await client.post(click_path, json=click, headers=headers)).status_code, 200)
            self.assertEqual(ads.click.call_args.args[0].actor_id, 'user')


class AdsSchemaTests(unittest.TestCase):
    def test_actions_cannot_hide_status_approval_or_wrong_resource_arguments(self):
        self.assertEqual(ActionRequest.model_validate(ACTION).actions[0].action_type, 'activate_campaign')
        for change in ({'expected_version': True}, {'budget_cents': 0}, {'copy_text': 'hidden edit'},
                       {'creative_id': 'other'}, {'status': 'ACTIVE'}, {'approve': True}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ActionRequest.model_validate({**ACTION, 'actions': [{**ACTION['actions'][0], **change}]})
        with self.assertRaises(ValidationError):
            ActionRequest.model_validate({**ACTION, 'actions': ACTION['actions'] * 9})
        with self.assertRaises(ValidationError):
            AdClickRequest.model_validate({'click_id': 'click', 'exposure_id': 'exposure', 'occurred_at': '2026-01-01'})

    def test_approval_requires_exact_reviewed_resource_version_maps(self):
        grant = {'grant_id': 'grant', 'initial_plan_id': 'plan', 'initial_plan_version': 1,
                 'expected_campaign_versions': {'campaign': 1}, 'expected_creative_versions': {'creative': 1},
                 'envelope': {'objective': '在已确认预算内模拟推广', 'product_scope': ['product'],
                     'allowed_action_types': ['activate_campaign', 'activate_creative'],
                     'budget_cap_cents': 100, 'max_budget_change_cents': 10, 'valid_until': '2027-01-01T00:00:00Z'}}
        self.assertEqual(GrantRequest.model_validate(grant).expected_campaign_versions, {'campaign': 1})
        for field in ('expected_campaign_versions', 'expected_creative_versions'):
            missing = {key: value for key, value in grant.items() if key != field}
            with self.assertRaises(ValidationError):
                GrantRequest.model_validate(missing)
            for value in (True, 0, '1', 1.0, 9223372036854775808):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    GrantRequest.model_validate({**grant, field: {'resource': value}})


if __name__ == '__main__':
    unittest.main()
