"""F4 money and stock fences on a disposable MySQL; stock observations are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
import os
from threading import Barrier
import unittest
import uuid
from unittest.mock import patch

from smartlect.ads.store import AdsStore, MAX_MONEY, _money, policy_range
from smartlect.ads.service import PolicyRequest
from smartlect.recommendation.store import StrategyStore, DEFAULT_STRATEGIES
from smartlect.auth import ActorContext
from smartlect.state import StateError
import test_ledger_mysql


class AdsInputTests(unittest.TestCase):
    def test_all_policy_group_requires_an_explicit_distinct_envelope_value(self):
        limits = {'rankings':['rule'],'groups':['all'],'max_weight':20,'max_quota':20}
        self.assertEqual(policy_range(limits)['groups'], ['all'])
        old = {**limits,'groups':['control','treatment']}
        self.assertNotIn('all', policy_range(old)['groups'])
        self.assertEqual(PolicyRequest(strategy_version='v1',config=DEFAULT_STRATEGIES['rules-v1'],group='all').group,'all')
        for groups in (['unknown'], 'all', []):
            with self.subTest(groups=groups), self.assertRaises(StateError):
                policy_range({**limits,'groups':groups})

    def test_money_is_bounded_integer_cents_without_coercion(self):
        self.assertEqual(_money(0), 0)
        self.assertEqual(_money(MAX_MONEY), MAX_MONEY)
        for value in (True, False, -1, 0.01, 10.0, '10', None, MAX_MONEY + 1):
            with self.subTest(value=value), self.assertRaises(StateError):
                _money(value)

    def test_reusable_fresh_rejects_missing_row_and_nonpositive_stock(self):
        now = datetime(2026, 9, 9, 12)
        self.assertFalse(AdsStore._reusable_fresh(None, now))
        fresh = {'query_started_at': now - timedelta(seconds=2), 'query_completed_at': now,
                 'elapsed_ms': 0, 'observed_generation': 2, 'pause_generation': 0, 'stock': 5}
        self.assertTrue(AdsStore._reusable_fresh(fresh, now))
        self.assertFalse(AdsStore._reusable_fresh({**fresh, 'stock': 0}, now))
        self.assertFalse(AdsStore._reusable_fresh({k: v for k, v in fresh.items() if k != 'query_completed_at'}, now))
        self.assertFalse(AdsStore._reusable_fresh({**fresh, 'query_completed_at': now - timedelta(seconds=2)}, now))
        self.assertTrue(AdsStore._reusable_fresh({**fresh, 'query_completed_at': now + timedelta(milliseconds=400)}, now))
        self.assertFalse(AdsStore._reusable_fresh({**fresh, 'query_completed_at': now + timedelta(seconds=2)}, now))
        self.assertTrue(AdsStore._within_fresh_window(now, now + timedelta(milliseconds=400)))
        self.assertFalse(AdsStore._within_fresh_window(now, now - timedelta(seconds=2)))
        self.assertFalse(AdsStore._within_fresh_window(now, None))


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS') == '1',
                     'set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL')
class AdsMySQLTests(unittest.TestCase):
    setUpClass = classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    def setUp(self):
        self.now = datetime(2026, 9, 9, 12)
        self.scope = 'ads-' + uuid.uuid4().hex
        self.store = AdsStore(self.connect, clock=lambda: self.now)
        self.product = 'p-' + uuid.uuid4().hex
        self.sku = 'standard'
        self.merchant = ActorContext(subject_type='merchant', actor_id='merchant-' + uuid.uuid4().hex,
            session_id='synthetic-admin-session', permissions=('admin:legacy',), execution_scope_id=self.scope)
        self.user = ActorContext(subject_type='user', actor_id='user-' + uuid.uuid4().hex,
            session_id='synthetic-user-session', permissions=('shopping:read',), execution_scope_id=self.scope)
        self.store.register_scope(self.scope, scenario_run_id=self.scope, branch_id='contract',
                                  users=[self.user.actor_id], products=[self.product])
        self.campaigns = []
        self.creatives = []
        self.grant = None

    def snapshot(self):
        return self.store.snapshot(self.merchant)

    def campaign(self, budget=100, cpc=10):
        campaign = self.store.create_campaign(self.merchant, {
            'campaign_id': uuid.uuid4().hex, 'name': 'Synthetic contract campaign',
            'product_id': self.product, 'sku_key': self.sku, 'budget_cents': budget, 'cpc_cents': cpc})
        creative = self.store.create_creative(self.merchant, {'creative_id': uuid.uuid4().hex,
            'campaign_id': campaign['campaign_id'], 'copy_text': '推广：合成测试素材'})
        self.campaigns.append(campaign['campaign_id'])
        self.creatives.append(creative['creative_id'])
        return campaign, creative

    def approve(self, cap=100, **changes):
        snapshot = self.snapshot()
        request = {'grant_id': uuid.uuid4().hex, 'initial_plan_id': uuid.uuid4().hex,
            'initial_plan_version': 1,
            'expected_campaign_versions': {c['campaign_id']: c['version'] for c in snapshot['campaigns']},
            'expected_creative_versions': {c['creative_id']: c['version'] for c in snapshot['creatives']},
            'envelope': {'objective': 'Synthetic local acceptance',
            'product_scope': [self.product], 'allowed_action_types': [
                'activate_campaign', 'activate_creative', 'resume_campaign', 'resume_creative',
                'pause_campaign', 'pause_creative', 'set_budget', 'replace_creative'],
            'budget_cap_cents': cap, 'max_budget_change_cents': cap,
            'valid_until': (self.now + timedelta(hours=1)).isoformat() + 'Z'}, **changes}
        self.grant = self.store.approve_grant(self.merchant, request)
        return request, self.grant

    def observe(self, stock=5, ticket=None):
        ticket = ticket or self.store.begin_observation(self.user, self.product, self.sku)
        return self.store.finish_observation(self.user, ticket, stock, self.now, 0)

    def request(self, actions, **changes):
        return {'action_id': uuid.uuid4().hex, 'idempotency_key': uuid.uuid4().hex,
            'grant_id': self.grant['grant_id'] if self.grant else 'not-approved',
            'plan_id': uuid.uuid4().hex, 'plan_version': 1, 'reason_code': 'contract_test',
            'evidence_ids': [], 'actions': actions, **changes}

    def item(self, action_type, index=0, **changes):
        state = self.snapshot()
        campaign = next(c for c in state['campaigns'] if c['campaign_id'] == self.campaigns[index])
        creative = next(c for c in state['creatives'] if c['creative_id'] == self.creatives[index])
        target = creative if action_type.endswith('creative') else campaign
        result = {'action_type': action_type, 'campaign_id': campaign['campaign_id'],
                  'expected_version': target['version'], **changes}
        if target is creative:
            result['creative_id'] = creative['creative_id']
        return result

    def execute(self, *actions, observations=None, **changes):
        request = self.request(list(actions), **changes)
        result = self.store.execute_action(self.merchant, request,
                                          observations=observations if observations is not None else [self.observe()])
        self.assertEqual(result['status'], 'APPLIED')
        return request, result

    def rejected(self, operation):
        try:
            result = operation()
        except StateError:
            return
        self.assertEqual(result['status'], 'REJECTED')

    def active(self, budget=100, cpc=10):
        self.campaign(budget, cpc)
        self.approve(budget)
        self.execute(self.item('activate_campaign'))
        self.execute(self.item('activate_creative'))

    def exposure(self, index=0, observation=None):
        request = {'exposure_id': uuid.uuid4().hex, 'creative_id': self.creatives[index]}
        receipt = self.store.expose(self.user, request, observation or self.observe())
        return request, receipt

    def test_candidate_read_never_charges_and_tracks_scope_grant_pause_exhaustion(self):
        self.campaign(budget=20, cpc=10)
        self.assertEqual(self.store.delivery_candidates(self.user), [])
        self.approve(20)
        self.assertEqual(self.store.delivery_candidates(self.user), [])
        self.execute(self.item('activate_campaign'), self.item('activate_creative'))
        before = self.snapshot()
        candidates = self.store.delivery_candidates(self.user)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['creative_id'], self.creatives[0])
        self.assertEqual(self.snapshot(), before)
        other = self.user.model_copy(update={'execution_scope_id': 'other-scope'})
        self.assertEqual(self.store.delivery_candidates(other), [])
        self.execute(self.item('pause_creative'))
        self.assertEqual(self.store.delivery_candidates(self.user), [])
        self.execute(self.item('resume_creative'))
        for _ in range(2):
            _, exposure = self.exposure()
            self.click(exposure)
        self.assertEqual(self.store.delivery_candidates(self.user), [])
        self.assertEqual(self.snapshot()['account']['spent_cents'], 20)

    def test_visible_ad_versions_match_display_and_old_receipt_replays_after_edit(self):
        self.active()
        displayed = self.store.delivery_candidates(self.user)[0]
        request = {'exposure_id': uuid.uuid4().hex, 'creative_id': displayed['creative_id'],
                   'expected_campaign_version': displayed['campaign_version'],
                   'expected_creative_version': displayed['creative_version']}
        original = self.store.expose(self.user, request, self.observe())
        self.execute(self.item('replace_creative', copy_text='更新后素材'))
        self.assertEqual(self.store.expose(self.user, request, self.observe()), original)
        with self.assertRaisesRegex(StateError, 'ad_exposure_version_changed'):
            self.store.expose(self.user, {**request, 'exposure_id': uuid.uuid4().hex}, self.observe())
        with self.assertRaisesRegex(StateError, 'ad_exposure_version_changed'):
            self.store.expose(self.user, {**request, 'expected_creative_version': displayed['creative_version'] + 1}, self.observe())
        with self.assertRaisesRegex(StateError, 'ad_exposure_version_changed'):
            self.click(original)
        current = self.store.delivery_candidates(self.user)[0]
        updated = self.store.expose(self.user, {**request, 'exposure_id': uuid.uuid4().hex,
                                   'expected_creative_version': current['creative_version']}, self.observe())
        self.assertEqual(updated['copy_text'], '更新后素材')
        self.click(updated)
        self.assertEqual(self.snapshot()['account']['spent_cents'], 10)

    def click(self, exposure, click_id=None, observation=None):
        request = {'click_id': click_id or uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}
        return request, self.store.click(self.user, request, observation or self.observe())

    def counts(self):
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents),0) AS cents FROM ad_spend WHERE execution_scope_id=%s', (self.scope,))
            spend = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS n FROM traffic_touch WHERE execution_scope_id=%s AND kind='AD_CLICK'", (self.scope,))
            return int(spend['n']), int(spend['cents']), int(cursor.fetchone()['n'])

    def test_drafts_cannot_spend_and_grant_is_immutable_and_owned(self):
        campaign, creative = self.campaign()
        self.assertEqual((campaign['status'], creative['status']), ('DRAFT', 'DRAFT'))
        self.rejected(lambda: self.store.execute_action(self.merchant,
            self.request([self.item('activate_campaign')]), observations=[self.observe()]))
        self.rejected(lambda: self.exposure()[1])
        request, grant = self.approve()
        self.assertEqual(self.store.approve_grant(self.merchant, request), grant)
        self.rejected(lambda: self.store.approve_grant(self.merchant,
            {**request, 'envelope': {**request['envelope'], 'budget_cap_cents': 200}}))
        stranger = self.merchant.model_copy(update={'actor_id': 'other-merchant'})
        self.rejected(lambda: self.store.approve_grant(stranger, request))
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_all_policy_switch_is_atomic_explicit_and_preserves_assignment(self):
        self.campaign()
        strategies = StrategyStore(self.connect)
        before_assignment = strategies.assign(self.user)
        def salt():
            with self.connect() as connection, connection.cursor() as cursor:
                cursor.execute('SELECT salt FROM recommendation_experiment WHERE execution_scope_id=%s',(self.scope,))
                return cursor.fetchone()['salt']
        before_salt = salt()
        envelope={'objective':'Synthetic local acceptance','product_scope':[self.product],
            'allowed_action_types':['set_recommendation_policy'],'budget_cap_cents':100,'max_budget_change_cents':100,
            'valid_until':(self.now+timedelta(hours=1)).isoformat()+'Z',
            'recommendation_policy_range':{'rankings':['rule','content'],'groups':['control','treatment'],'max_weight':20,'max_quota':20}}
        self.approve(envelope=envelope)
        action={'action_type':'set_recommendation_policy','expected_version':1,
                'policy':{'group':'all','strategy_version':'all-rules-v1','config':deepcopy(DEFAULT_STRATEGIES['rules-v1'])}}
        with self.assertRaisesRegex(StateError,'policy_outside_grant'):
            self.store.execute_action(self.merchant,self.request([action]),[])
        original_grant=self.grant['grant_id']
        self.approve(envelope={**envelope,'recommendation_policy_range':{
            **envelope['recommendation_policy_range'],'groups':['all']}},replaces_grant_id=original_grant)
        request=self.request([action])
        receipt=self.store.execute_action(self.merchant,request,[])
        self.assertEqual(self.store.execute_action(self.merchant,request,[]),receipt)
        current=self.snapshot()['recommendation']
        self.assertEqual((current['control_strategy_version'],current['treatment_strategy_version'],current['revision']),
                         ('all-rules-v1','all-rules-v1',2))
        after_assignment=strategies.assign(self.user)
        self.assertEqual((before_assignment['assignment_id'],before_assignment['group'],before_assignment['bucket']),
                         (after_assignment['assignment_id'],after_assignment['group'],after_assignment['bucket']))
        self.assertEqual(after_assignment['strategy_version'],'all-rules-v1')
        self.assertEqual(salt(),before_salt)
        with self.assertRaisesRegex(StateError,'experiment_revision_conflict'):
            self.store.execute_action(self.merchant,self.request([action]),[])
        partial=deepcopy(action);partial['expected_version']=2;partial['policy']['group']='control'
        with self.assertRaisesRegex(StateError,'policy_outside_grant'):
            self.store.execute_action(self.merchant,self.request([partial]),[])
        changed=deepcopy(action);changed['expected_version']=2;changed['policy']['config']['weights']['content']+=1
        with self.assertRaisesRegex(StateError,'strategy_version_immutable'):
            self.store.execute_action(self.merchant,self.request([changed]),[])
        changed['policy']['strategy_version']='all-rules-v2'
        with patch.object(self.store,'_save_action',side_effect=RuntimeError('receipt failure')):
            with self.assertRaisesRegex(RuntimeError,'receipt failure'):
                self.store.execute_action(self.merchant,self.request([changed]),[])
        self.assertEqual(self.snapshot()['recommendation'],current)
        self.assertEqual(self.snapshot()['account']['spent_cents'],0)

    def test_fresh_positive_observation_is_reused_instead_of_invalidating_peers(self):
        self.active()
        first = self.observe(5)
        with ThreadPoolExecutor(max_workers=4) as pool:
            tickets = list(pool.map(lambda _: self.store.begin_observation(self.user, self.product, self.sku), range(4)))
        self.assertTrue(all(ticket['generation'] == first['generation'] for ticket in tickets))
        _, exposure = self.exposure(observation=first)
        request = {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda ticket: self.store.click(self.user, request, ticket), tickets))
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertEqual(self.counts(), (1, 10, 1))
        self.now += timedelta(seconds=2)
        stale = self.store.begin_observation(self.user, self.product, self.sku)
        self.assertGreater(stale['generation'], first['generation'])
        self.observe(0)
        after_zero = self.store.begin_observation(self.user, self.product, self.sku)
        self.assertGreater(after_zero['generation'], stale['generation'])

    def test_reused_generation_stays_servable_after_original_start_ages(self):
        self.active()
        first = self.observe(5)
        self.now += timedelta(milliseconds=900)
        reused = self.store.begin_observation(self.user, self.product, self.sku)
        self.assertEqual(reused['generation'], first['generation'])
        self.assertEqual(reused['query_started_at'], first['query_started_at'])
        later = self.store.finish_observation(self.user, reused, 5, self.now, 20)
        self.now += timedelta(milliseconds=200)
        _, exposure = self.exposure(observation=later)
        self.assertEqual(exposure['inventory_observation']['generation'], first['generation'])
        self.assertEqual(self.snapshot()['impressions'], 1)

    def test_expired_observation_concurrent_begins_join_one_in_flight_generation(self):
        self.active()
        first = self.observe(5)
        self.now += timedelta(seconds=2)
        barrier = Barrier(4)
        def start(_):
            barrier.wait()
            return self.store.begin_observation(self.user, self.product, self.sku)
        with ThreadPoolExecutor(max_workers=4) as pool:
            tickets = list(pool.map(start, range(4)))
        generations = {ticket['generation'] for ticket in tickets}
        self.assertEqual(len(generations), 1)
        self.assertGreater(tickets[0]['generation'], first['generation'])
        finished = [self.store.finish_observation(self.user, ticket, 5, self.now, 10) for ticket in tickets]
        self.assertTrue(all(item['accepted'] for item in finished))
        _, exposure = self.exposure(observation=finished[0])
        self.assertEqual(exposure['inventory_observation']['generation'], tickets[0]['generation'])

    def test_clock_rewind_within_window_reuses_and_stays_servable(self):
        self.active()
        first = self.observe(5)
        self.now -= timedelta(milliseconds=400)
        reused = self.store.begin_observation(self.user, self.product, self.sku)
        self.assertEqual(reused['generation'], first['generation'])
        later = self.store.finish_observation(self.user, reused, 5, first['query_completed_at'], 20)
        _, exposure = self.exposure(observation=later)
        self.assertEqual(exposure['inventory_observation']['generation'], first['generation'])
        self.assertEqual(self.snapshot()['impressions'], 1)

    def test_clock_rewind_joins_in_flight_generation(self):
        self.active()
        first = self.observe(5)
        self.now += timedelta(seconds=2)
        stale = self.store.begin_observation(self.user, self.product, self.sku)
        self.assertGreater(stale['generation'], first['generation'])
        self.now -= timedelta(milliseconds=400)
        joined = self.store.begin_observation(self.user, self.product, self.sku)
        self.assertEqual(joined['generation'], stale['generation'])
        finished = self.store.finish_observation(self.user, joined, 5, self.now, 10)
        self.assertTrue(finished['accepted'])
        _, exposure = self.exposure(observation=finished)
        self.assertEqual(exposure['inventory_observation']['generation'], stale['generation'])

    def test_click_atomicity_concurrent_replay_and_replay_after_pause(self):
        self.active()
        _, exposure = self.exposure()
        request = {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}
        observation = self.observe()
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: self.store.click(self.user, request, observation), range(8)))
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertEqual(self.counts(), (1, 10, 1))
        self.execute(self.item('pause_campaign'))
        restarted = AdsStore(self.connect, clock=lambda: self.now)
        self.assertEqual(restarted.click(self.user, request, None), receipts[0])
        self.rejected(lambda: self.exposure()[1])
        self.rejected(lambda: restarted.click(self.user, {**request, 'exposure_id': 'forged'}, None))
        self.rejected(lambda: restarted.click(self.user.model_copy(update={'actor_id': 'other'}), request, None))
        self.rejected(lambda: restarted.click(self.user.model_copy(update={'execution_scope_id': 'other'}), request, None))
        self.assertEqual(self.counts(), (1, 10, 1))

    def test_touch_failure_rolls_back_click_fee_account_and_retry_is_first_effect(self):
        self.active()
        _, exposure = self.exposure()
        request = {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}
        original_touch = self.store._touch

        def inserted_then_failed(*args, **kwargs):
            original_touch(*args, **kwargs)
            raise RuntimeError('injected failure after touch insertion')

        with patch.object(self.store, '_touch', side_effect=inserted_then_failed):
            with self.assertRaises(RuntimeError):
                self.store.click(self.user, request, self.observe())
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(self.snapshot()['account']['spent_cents'], 0)
        self.store.click(self.user, request, self.observe())
        self.assertEqual(self.counts(), (1, 10, 1))

    def test_two_campaigns_compete_without_overspend_and_exhausted_replays_recover(self):
        self.campaign(10, 10)
        self.campaign(10, 10)
        self.approve(20)
        for index in range(2):
            self.execute(self.item('activate_campaign', index))
            self.execute(self.item('activate_creative', index))
        requests = []
        for index in range(16):
            _, exposure = self.exposure(index % 2)
            requests.append({'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']})
        observation = self.observe()

        def attempt(request):
            try:
                return request, self.store.click(self.user, request, observation)
            except StateError:
                return request, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, requests))
        succeeded = [(request, result) for request, result in results if result and result.get('status') != 'REJECTED']
        self.assertEqual(len(succeeded), 2)
        self.assertEqual(self.counts(), (2, 20, 2))
        self.assertEqual(self.snapshot()['account']['spent_cents'], 20)
        for campaign in self.snapshot()['campaigns']:
            self.assertLessEqual(campaign['spent_cents'], campaign['budget_cents'])
        for request, receipt in succeeded:
            self.assertEqual(self.store.click(self.user, request, None), receipt)

    def test_batch_budget_is_aggregate_atomic_versioned_and_cannot_fall_below_spend(self):
        self.campaign(50)
        self.campaign(50)
        self.approve(100)
        before = self.snapshot()['campaigns']
        oversized = self.request([self.item('set_budget', 0, budget_cents=60),
                                  self.item('set_budget', 1, budget_cents=60)])
        self.rejected(lambda: self.store.execute_action(self.merchant, oversized, observations=[]))
        self.assertEqual(self.store.get_action(self.merchant, oversized['action_id'])['result']['status'], 'REJECTED')
        self.assertEqual(self.snapshot()['campaigns'], before)
        stale = self.request([self.item('set_budget', 0, budget_cents=40),
            self.item('set_budget', 1, budget_cents=60, expected_version=999)])
        self.rejected(lambda: self.store.execute_action(self.merchant, stale, observations=[]))
        self.assertEqual(self.store.get_action(self.merchant, stale['action_id'])['result']['reason_code'], 'ads_version_conflict')
        self.assertEqual(self.snapshot()['campaigns'], before)
        request, receipt = self.execute(self.item('set_budget', 0, budget_cents=40),
                                       self.item('set_budget', 1, budget_cents=60), observations=[])
        self.assertEqual(self.store.execute_action(self.merchant, request, observations=[]), receipt)
        self.rejected(lambda: self.store.execute_action(self.merchant,
            {**request, 'reason_code': 'changed'}, observations=[]))
        self.execute(self.item('activate_campaign'))
        self.execute(self.item('activate_creative'))
        _, exposure = self.exposure()
        self.click(exposure)
        self.rejected(lambda: self.store.execute_action(self.merchant,
            self.request([self.item('set_budget', budget_cents=9)]), observations=[]))
        self.assertEqual(self.counts(), (1, 10, 1))

    def test_lowering_budget_to_spend_exhausts_and_raising_requires_explicit_resume(self):
        self.active()
        self.click(self.exposure()[1])
        self.execute(self.item('set_budget',budget_cents=10),observations=[])
        self.assertEqual(self.snapshot()['campaigns'][0]['status'],'EXHAUSTED')
        self.execute(self.item('set_budget',budget_cents=20),observations=[])
        self.assertEqual(self.snapshot()['campaigns'][0]['status'],'EXHAUSTED')
        with self.assertRaises(StateError): self.exposure()
        self.execute(self.item('resume_campaign'))
        self.click(self.exposure()[1])
        self.assertEqual(self.snapshot()['account']['spent_cents'],20)

    def test_new_grant_plan_run_and_round_cannot_reset_lifetime_spend(self):
        self.active()
        _, exposure = self.exposure()
        self.click(exposure)
        original = self.snapshot()['account']
        old_grant = self.grant['grant_id']
        self.approve(100, replaces_grant_id=old_grant)
        self.execute(self.item('pause_campaign'), agent_run_id='new-agent-run', round_id='new-round', plan_version=9)
        self.execute(self.item('resume_campaign'), agent_run_id='another-run', round_id='another-round')
        self.execute(self.item('resume_creative'), agent_run_id='another-run', round_id='another-round')
        _, exposure = self.exposure()
        self.click(exposure)
        after = AdsStore(self.connect, clock=lambda: self.now).snapshot(self.merchant)['account']
        self.assertEqual(after['account_id'], original['account_id'])
        self.assertEqual(after['spent_cents'], 20)
        self.assertEqual(self.counts(), (2, 20, 2))

    def test_creative_and_campaign_pause_require_explicit_fresh_resume(self):
        self.active()
        self.execute(self.item('pause_creative'))
        self.rejected(lambda: self.exposure()[1])
        self.execute(self.item('pause_campaign'))
        self.rejected(lambda: self.store.execute_action(self.merchant,
            self.request([self.item('resume_creative')]), observations=[self.observe()]))
        self.execute(self.item('resume_campaign'))
        self.rejected(lambda: self.exposure()[1])
        self.execute(self.item('resume_creative'))
        _, exposure = self.exposure()
        self.click(exposure)
        self.assertEqual(self.counts(), (1, 10, 1))

    def test_stock_age_unknown_and_late_positive_cannot_cross_sold_out_pause(self):
        self.active()
        observation = self.observe()
        self.now += timedelta(seconds=1)
        self.exposure(observation=observation)
        self.now += timedelta(microseconds=1)
        self.rejected(lambda: self.exposure(observation=observation)[1])
        self.rejected(lambda: self.exposure(observation=self.observe(None))[1])
        old_positive = self.store.begin_observation(self.user, self.product, self.sku)
        self.observe(0)
        late = self.observe(5, ticket=old_positive)
        state = self.snapshot()
        self.assertEqual(state['campaigns'][0]['status'], 'PAUSED')
        self.rejected(lambda: self.exposure(observation=late)[1])
        self.rejected(lambda: self.store.execute_action(self.merchant,
            self.request([self.item('resume_campaign')]), observations=[late]))
        self.observe(5)
        self.assertEqual(self.snapshot()['campaigns'][0]['status'], 'PAUSED')
        self.execute(self.item('resume_campaign'))
        if self.snapshot()['creatives'][0]['status'] == 'PAUSED':
            self.execute(self.item('resume_creative'))
        self.exposure()

    def test_sold_out_protection_commits_even_when_following_action_is_rejected(self):
        self.active()
        action = self.request([self.item('resume_campaign', expected_version=999)])
        zero = self.observe(0)
        self.rejected(lambda: self.store.execute_action(self.merchant, action, observations=[zero]))
        restarted = AdsStore(self.connect, clock=lambda: self.now)
        self.assertEqual(restarted.snapshot(self.merchant)['campaigns'][0]['status'], 'PAUSED')
        action = self.request([self.item('resume_campaign')], grant_id='invalid-grant')
        self.rejected(lambda: restarted.execute_action(self.merchant, action, observations=[self.observe(0)]))
        self.assertEqual(restarted.snapshot(self.merchant)['campaigns'][0]['status'], 'PAUSED')
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_expired_and_revoked_grants_stop_new_flow_without_erasing_spend(self):
        self.active()
        _, exposure = self.exposure()
        request, receipt = self.click(exposure)
        self.now += timedelta(hours=1)
        self.rejected(lambda: self.exposure()[1])
        self.assertEqual(self.store.click(self.user, request, None), receipt)
        self.approve(100, replaces_grant_id=self.grant['grant_id'])
        self.execute(self.item('resume_campaign'))
        self.execute(self.item('resume_creative'))
        revoked = self.store.revoke_grant(self.merchant, self.grant['grant_id'], {
            'action_id': uuid.uuid4().hex, 'idempotency_key': uuid.uuid4().hex,
            'expected_version': self.grant['version'], 'reason_code': 'local_merchant_revocation'})
        self.assertEqual(revoked['status'], 'APPLIED')
        self.rejected(lambda: self.exposure()[1])
        self.assertEqual(self.snapshot()['campaigns'][0]['status'], 'PAUSED')
        self.assertEqual(self.store.click(self.user, request, None), receipt)
        self.assertEqual(self.counts(), (1, 10, 1))

    def test_distinct_click_id_cannot_recharge_one_exposure(self):
        self.active()
        _, exposure = self.exposure()
        self.click(exposure)
        self.rejected(lambda: self.click(exposure)[1])
        self.assertEqual(self.counts(), (1, 10, 1))

    def test_unapproved_large_draft_cannot_block_pausing_an_active_campaign(self):
        self.active()
        self.rejected(lambda: self.campaign(100)[0])
        self.assertEqual(len(self.snapshot()['campaigns']), 1)
        self.execute(self.item('pause_campaign', 0), observations=[])
        self.assertEqual(next(c for c in self.snapshot()['campaigns']
                              if c['campaign_id'] == self.campaigns[0])['status'], 'PAUSED')
        self.rejected(lambda: self.exposure(0)[1])
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_grant_approval_rejects_resources_changed_since_merchant_review(self):
        self.campaign()
        reviewed, original = self.approve()
        self.execute(self.item('replace_creative', copy_text='推广：修改后需要重新核对版本'), observations=[])
        stale = {**reviewed, 'grant_id': uuid.uuid4().hex, 'replaces_grant_id': original['grant_id']}
        self.rejected(lambda: self.store.approve_grant(self.merchant, stale))
        state = self.snapshot()
        self.assertEqual(state['account']['grant_id'], original['grant_id'])
        self.assertEqual(len(state['grants']), 1)
        self.approve(replaces_grant_id=original['grant_id'])
        self.assertEqual(len(self.snapshot()['grants']), 2)

    def test_cross_scope_global_identifier_race_rolls_back_and_returns_conflict(self):
        other_scope = 'ads-' + uuid.uuid4().hex
        other_product = 'p-' + uuid.uuid4().hex
        self.store.register_scope(other_scope, scenario_run_id=other_scope, branch_id='other',
            users=['user-' + uuid.uuid4().hex], products=[other_product])
        other = self.merchant.model_copy(update={'execution_scope_id': other_scope, 'actor_id': 'merchant-' + uuid.uuid4().hex})
        shared_id = uuid.uuid4().hex
        boundary = Barrier(2)
        original_insert = self.store._insert

        def collide(cursor, table, row):
            if table == 'ads_campaign' and row['campaign_id'] == shared_id:
                boundary.wait(timeout=10)  # Both transactions have already observed an absent global ID.
            return original_insert(cursor, table, row)

        def create(actor_and_product):
            actor, product = actor_and_product
            try:
                result = self.store.create_campaign(actor, {'campaign_id': shared_id, 'name': 'Global ID collision',
                    'product_id': product, 'sku_key': self.sku, 'budget_cents': 10, 'cpc_cents': 10})
                return {'result': result}
            except StateError as error:
                return {'error': error.code, 'status': error.status}

        with patch.object(self.store, '_insert', side_effect=collide), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, [(self.merchant, self.product), (other, other_product)]))
        successes = [r['result'] for r in results if 'result' in r]
        self.assertEqual(len(successes), 1)
        self.assertEqual([r for r in results if 'error' in r], [{'error': 'ads_identifier_conflict', 'status': 409}])
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT execution_scope_id FROM ads_campaign WHERE campaign_id=%s', (shared_id,))
            self.assertEqual(cursor.fetchall(), [{'execution_scope_id': successes[0]['execution_scope_id']}])
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_exhaustion_increments_resource_version_but_ordinary_spend_preserves_exposures(self):
        self.active(budget=20, cpc=10)
        initial = self.snapshot()['campaigns'][0]
        _, first = self.exposure()
        _, second = self.exposure()
        self.click(first)
        after_first = self.snapshot()['campaigns'][0]
        self.assertEqual((after_first['status'], after_first['version']), ('ACTIVE', initial['version']))
        request, receipt = self.click(second)
        exhausted = self.snapshot()['campaigns'][0]
        self.assertEqual((exhausted['status'], exhausted['pause_reason'], exhausted['version']),
                         ('EXHAUSTED', 'budget_exhausted', initial['version'] + 1))
        self.assertEqual(self.store.click(self.user, request, None), receipt)
        self.assertEqual(self.counts(), (2, 20, 2))

    def test_fractional_observation_receipts_equal_persisted_replays_exactly(self):
        self.active()
        ticket = self.store.begin_observation(self.user, self.product, self.sku)
        observation = self.store.finish_observation(self.user, ticket, 5, self.now, 24.433608999970602)
        exposure_request = {'exposure_id': uuid.uuid4().hex, 'creative_id': self.creatives[0]}
        exposure = self.store.expose(self.user, exposure_request, observation)
        with self.subTest(receipt='exposure'):
            self.assertEqual(self.store.expose(self.user, exposure_request, observation), exposure)
        click_request = {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}
        clicked = self.store.click(self.user, click_request, observation)
        with self.subTest(receipt='click'):
            self.assertEqual(self.store.click(self.user, click_request, None), clicked)
        restarted = AdsStore(self.connect, clock=lambda: self.now)
        with self.subTest(receipt='click_after_store_recreation'):
            self.assertEqual(restarted.click(self.user, click_request, None), clicked)
        self.assertEqual(self.counts(), (1, 10, 1))


if __name__ == '__main__':
    unittest.main()
