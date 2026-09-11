"""Merchant durability and grants on owned MySQL; inventory inputs are explicit synthetic observations."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
import asyncio
import json
import os
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from pymysql.err import OperationalError

from smartlect.auth import ActorContext
from smartlect.agents.merchant import _model_payload, validate_candidate
from smartlect.events import canonical
from smartlect.merchant.service import MerchantService
from smartlect.merchant.store import MerchantStore, plan_batches, plan_action_request
from smartlect.recommendation.store import DEFAULT_STRATEGIES, StrategyStore
from smartlect.state import StateError
import test_ledger_mysql
from test_payment_attempt_events import payment_attempt


OBJECTIVE = '根据真实经营观测决定下一轮动作'
POLICY_RANGE = {'rankings': ['rule', 'content'], 'groups': ['control', 'treatment'], 'max_weight': 20, 'max_quota': 20}


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS') == '1', 'requires dedicated MySQL')
class MerchantMySQLTests(unittest.TestCase):
    setUpClass = classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    def setUp(self):
        self.now = datetime(2026, 9, 9, 12)
        self.scope = 'merchant-' + uuid.uuid4().hex
        self.products = ['p-' + uuid.uuid4().hex, 'p-' + uuid.uuid4().hex]
        self.store = MerchantStore(self.connect, clock=lambda: self.now)
        self.merchant = ActorContext(subject_type='merchant', actor_id='m-' + uuid.uuid4().hex,
            session_id=uuid.uuid4().hex, permissions=('admin:legacy',), execution_scope_id=self.scope)
        self.user = ActorContext(subject_type='user', actor_id='u-' + uuid.uuid4().hex,
            session_id=uuid.uuid4().hex, permissions=('shopping:read',), execution_scope_id=self.scope)
        self.store.register_scope(self.scope, scenario_run_id=self.scope, branch_id='contract',
                                  users=[self.user.actor_id], products=self.products)
        self.campaign = self.store.create_campaign(self.merchant, {'campaign_id': uuid.uuid4().hex,
            'name': 'Synthetic Merchant contract campaign', 'product_id': self.products[0],
            'sku_key': 'standard', 'budget_cents': 100, 'cpc_cents': 10})
        self.creative = self.store.create_creative(self.merchant, {'creative_id': uuid.uuid4().hex,
            'campaign_id': self.campaign['campaign_id'], 'copy_text': '推广：检查商品规格'})
        self.grant = None
        self.stock(5)

    def stock(self, value):
        ticket = self.store.begin_observation(self.user, self.products[0], 'standard')
        return self.store.finish_observation(self.user, ticket, value, self.now, 0)

    def approve(self, *, products=None, allowed=None, merchant_plan=None, **envelope_changes):
        snapshot = self.store.snapshot(self.merchant)
        selected = self.products if products is None else products
        request = {'grant_id': uuid.uuid4().hex, 'initial_plan_id': uuid.uuid4().hex, 'initial_plan_version': 1,
            'expected_campaign_versions': {c['campaign_id']: c['version'] for c in snapshot['campaigns'] if c['product_id'] in selected},
            'expected_creative_versions': {c['creative_id']: c['version'] for c in snapshot['creatives']
                if c['campaign_id'] in {a['campaign_id'] for a in snapshot['campaigns'] if a['product_id'] in selected}},
            'envelope': {'objective': OBJECTIVE, 'product_scope': selected, 'budget_cap_cents': 100,
                'max_budget_change_cents': 100, 'valid_until': (self.now + timedelta(hours=1)).isoformat() + 'Z',
                'allowed_action_types': allowed if allowed is not None else ['activate_campaign', 'activate_creative',
                    'pause_campaign', 'pause_creative', 'resume_campaign', 'resume_creative', 'set_budget',
                    'replace_creative', 'set_recommendation_policy'], 'recommendation_policy_range': deepcopy(POLICY_RANGE),
                **envelope_changes}}
        if self.grant:
            request['replaces_grant_id'] = self.grant['grant_id']
        if merchant_plan:
            request.update(merchant_plan_id=merchant_plan['plan_id'],initial_plan_id=merchant_plan['plan_id'],
                           initial_plan_version=merchant_plan['version'])
        self.grant = self.store.approve_grant(self.merchant, request)
        return self.grant

    def item(self, kind, **changes):
        snapshot = self.store.snapshot(self.merchant)
        campaign = next(c for c in snapshot['campaigns'] if c['campaign_id'] == self.campaign['campaign_id'])
        creative = next(c for c in snapshot['creatives'] if c['creative_id'] == self.creative['creative_id'])
        resource = creative if kind.endswith('_creative') else campaign
        return {'action_type': kind, 'campaign_id': campaign['campaign_id'], 'expected_version': resource['version'],
                **({'creative_id': creative['creative_id']} if resource is creative else {}), **changes}

    def ad_request(self, actions, **changes):
        return {'action_id': uuid.uuid4().hex, 'idempotency_key': uuid.uuid4().hex,
                'grant_id': self.grant['grant_id'], 'plan_id': uuid.uuid4().hex, 'plan_version': 1,
                'reason_code': 'merchant_contract', 'evidence_ids': [], 'actions': actions, **changes}

    def execute(self, *actions, **changes):
        request = self.ad_request(list(actions), **changes)
        return request, self.store.execute_action(self.merchant, request, [self.stock(5)])

    def active(self):
        self.approve()
        self.execute(self.item('activate_campaign'), self.item('activate_creative'))

    def expose(self):
        return self.store.expose(self.user, {'exposure_id': uuid.uuid4().hex,
            'creative_id': self.creative['creative_id']}, self.stock(5))

    def recommend(self, actor=None, product=None):
        actor=actor or self.user
        assignment=StrategyStore(self.connect).assign(actor)
        return self.store.save_recommendation(actor,{**assignment,'ranking_mode':'rule','items':[{
            'productId':product or self.products[0],'propertyValueIdHash':'standard','propertyValueIds':'synthetic-standard',
            'price_cents':1000,'stock':5}]})

    def context(self, *, observation=None, objective=OBJECTIVE, products=None, budget=100):
        observation = observation or self.store.observation(self.merchant)
        request = {'request_id': uuid.uuid4().hex, 'objective': objective,
                   'product_scope': self.products if products is None else products, 'planned_budget_cents': budget}
        conversation = self.store.create_conversation(self.merchant)
        run = self.store.create_run(self.merchant, conversation['conversation_id'], request['request_id'], objective, model_mode='mock')
        self.store.prepare_run_context(self.merchant, run, observation, request)
        lease = self.store.claim_run(self.merchant, run['agent_run_id'], owner='merchant-contract', ttl_seconds=90)
        context = self.store.get_merchant_context(self.merchant, run['agent_run_id'])
        return request, run, lease, context

    def spec(self, context, *, actions=(), experience=None):
        observation = context['observation']
        budgets = {c['campaign_id']: c['budget_cents'] for c in observation['campaigns']
                   if c['product_id'] in context['plan_meta']['product_scope']}
        for action in actions:
            if action['action_type'] == 'set_budget':
                budgets[action['campaign_id']] = action['budget_cents']
        return {**context['plan_meta'], 'planned_budget_cents': sum(budgets.values()), 'observation_id': observation['observation_id'],
                'watermark': observation['watermark'], 'summary': '依据已保存事实等待或执行', 'diagnosis': [],
                'evidence_ids': [f['evidence_id'] for f in observation['facts']], 'actions': list(actions),
                'experience_draft': experience, 'expected_signals': ['下一轮出现新的外部观测'],
                'schema_version': 'merchant-plan-v1', 'prompt_version': 'merchant-plan-v1', 'skill_versions': {}}

    def plan(self, *, actions=(), experience=None, **context_arguments):
        request, run, lease, context = self.context(**context_arguments)
        spec = self.spec(context, actions=actions, experience=experience)
        plan = self.store.save_merchant_plan(lease, spec)
        self.store.finish_run(lease, state='COMPLETED', result={'plan_id': plan['plan_id']})
        return request, run, spec, plan

    def advance(self, value):
        self.now += timedelta(seconds=1)
        self.stock(value)
        return self.store.observation(self.merchant)

    def test_scope_selection_requires_membership_and_does_not_cross_sessions_or_actors(self):
        base = self.merchant.model_copy(update={'execution_scope_id': 'store'})
        self.assertEqual(self.store.selected_actor(base).execution_scope_id, 'store')
        with self.assertRaises(StateError):
            self.store.select_scope(base, self.scope)
        self.store.grant_scope_access(base.actor_id, self.scope, 'Contract branch')
        selected = self.store.select_scope(base, self.scope)
        self.assertEqual(selected.execution_scope_id, self.scope)
        self.assertEqual(self.store.selected_actor(base).execution_scope_id, self.scope)
        self.assertEqual(self.store.selected_actor(base.model_copy(update={'session_id': 'another-session'})).execution_scope_id, 'store')
        other = base.model_copy(update={'actor_id': 'another-merchant', 'session_id': 'another-session'})
        with self.assertRaises(StateError):
            self.store.select_scope(other, self.scope)
        self.assertIs(self.store.selected_actor(self.user), self.user)
        self.store.select_scope(base, 'store')
        self.assertEqual(self.store.selected_actor(base).execution_scope_id, 'store')

    def test_external_watermark_ignores_refresh_time_and_merchant_actions(self):
        self.active()
        original = self.store.observation(self.merchant)
        self.now += timedelta(seconds=5)
        self.stock(5)
        self.assertEqual(self.store.observation(self.merchant), original)
        self.execute(self.item('set_budget', budget_cents=90), agent_run_id='merchant-own-run')
        self.assertEqual(self.store.observation(self.merchant), original)
        rejected = self.ad_request([self.item('set_budget', expected_version=999, budget_cents=80)], agent_run_id='merchant-own-run')
        with self.assertRaises(StateError):
            self.store.execute_action(self.merchant, rejected, [])
        self.assertEqual(self.store.observation(self.merchant), original)
        exposure = self.expose()
        next_round = self.store.observation(self.merchant)
        self.assertEqual(next_round['round_number'], original['round_number'] + 1)
        self.assertEqual(next_round['summary']['impressions'], 1)
        self.store.click(self.user, {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}, self.stock(5))
        clicked = self.store.observation(self.merchant)
        self.assertEqual((clicked['round_number'], clicked['summary']['clicks'], clicked['summary']['spend_cents']),
                         (next_round['round_number'] + 1, 1, 10))
        sold_out = self.advance(0)
        self.assertEqual(sold_out['round_number'], clicked['round_number'] + 1)
        self.assertEqual(sold_out['campaigns'][0]['metrics']['stock'], 0)

    def test_observation_time_does_not_replace_click_or_java_business_time(self):
        self.active()
        exposed=self.expose()
        self.now += timedelta(seconds=10)
        self.stock(5)
        observation=self.store.observation(self.merchant)
        facts={f['metric']:f for f in observation['facts'] if f.get('campaign_id')==self.campaign['campaign_id']}
        self.assertEqual(facts['impressions']['occurred_at'],exposed['created_at'])
        self.assertNotEqual(facts['impressions']['occurred_at'],observation['observed_at'])
        self.assertIsNone(facts['stock']['occurred_at'])
        self.assertIsNone(facts['paid_cents']['occurred_at'])
        self.assertIn('query_started_at',facts['stock']['inventory_observation'])
        self.assertEqual(facts['impressions']['source_total_count'],1)
        self.assertFalse(facts['impressions']['source_ids_truncated'])

    def test_recommendation_touches_form_new_observations_once_and_stay_in_their_scope(self):
        self.active()
        before=self.store.snapshot(self.merchant)
        original=self.store.observation(self.merchant)
        recommendation=self.recommend()
        self.assertEqual(self.store.observation(self.merchant),original,'Creating a receipt alone is not a viewed or clicked recommendation')
        impression=self.store.interact(self.user,recommendation['recommendation_id'],[1])['touches'][0]
        viewed=self.store.observation(self.merchant)
        self.assertEqual(viewed['round_number'],original['round_number']+1)
        self.assertEqual((viewed['summary']['recommendation_impressions'],viewed['summary']['recommendation_clicks']),(1,0))
        self.assertEqual(self.store.interact(self.user,recommendation['recommendation_id'],[1])['touches'][0],impression)
        self.assertEqual(self.store.observation(self.merchant),viewed)
        self.now+=timedelta(seconds=1)
        click=self.store.interact(self.user,recommendation['recommendation_id'],[1],clicked=True)['touches'][0]
        clicked=self.store.observation(self.merchant)
        self.assertEqual(clicked['round_number'],viewed['round_number']+1)
        self.assertEqual((clicked['summary']['clicks'],clicked['summary']['recommendation_clicks']),(0,1))
        facts={f['metric']:f for f in clicked['facts'] if f['kind']=='recommendation'}
        for metric,touch in (('recommendation_impressions',impression),('recommendation_clicks',click)):
            self.assertEqual(facts[metric]['source_ids'],[touch['touch_id']])
            self.assertEqual(facts[metric]['source_total_count'],1)
            self.assertEqual(facts[metric]['occurred_at'],touch['occurred_at'])
            self.assertNotIn('campaign_id',facts[metric])
        self.assertEqual(self.store.interact(self.user,recommendation['recommendation_id'],[1],clicked=True)['touches'][0],click)
        self.assertEqual(self.store.observation(self.merchant),clicked)
        other_scope='recommendation-other-'+uuid.uuid4().hex;other_product='other-'+uuid.uuid4().hex
        other=self.user.model_copy(update={'actor_id':'other-'+uuid.uuid4().hex,'execution_scope_id':other_scope})
        self.store.register_scope(other_scope,scenario_run_id=other_scope,branch_id='other',users=[other.actor_id],products=[other_product])
        other_receipt=self.recommend(other,other_product)
        self.store.interact(other,other_receipt['recommendation_id'],[1])
        self.store.interact(other,other_receipt['recommendation_id'],[1],clicked=True)
        self.assertEqual(self.store.observation(self.merchant),clicked)
        after=self.store.snapshot(self.merchant)
        for key in ('account','grants','campaigns','creatives','clicks','spend_cents'):
            self.assertEqual(after[key],before[key])

    def test_real_recommendation_sample_is_independent_advice_and_plan_preserves_budget_and_authorization(self):
        self.active()
        for _ in range(10):
            exposure=self.expose()
            self.store.click(self.user,{'click_id':uuid.uuid4().hex,'exposure_id':exposure['exposure_id']},self.stock(5))
        advertising=self.store.observation(self.merchant)
        self.assertEqual((advertising['summary']['clicks'],advertising['summary']['recommendation_clicks']),(10,0))
        _, run, lease, context=self.context(observation=advertising)
        self.assertEqual(_model_payload(context)['recommendation']['allowed_actions'],['set_recommendation_policy'])
        self.assertFalse(_model_payload(context)['recommendation']['screening']['sample_mature'])
        self.store.finish_run(lease,state='COMPLETED',result={'fixture':'advertising-only-observation'})
        money_before=self.store.snapshot(self.merchant)
        touch_ids=[]
        for index in range(10):
            receipt=self.recommend()
            self.store.interact(self.user,receipt['recommendation_id'],[1])
            touch=self.store.interact(self.user,receipt['recommendation_id'],[1],clicked=True)['touches'][0]
            touch_ids.append(touch['touch_id'])
            self.store.interact(self.user,receipt['recommendation_id'],[1],clicked=True)
            if index==8:
                nine=self.store.observation(self.merchant)
                _, _, nine_lease, nine_context=self.context(observation=nine)
                self.assertEqual(_model_payload(nine_context)['recommendation']['allowed_actions'],['set_recommendation_policy'])
                self.assertFalse(_model_payload(nine_context)['recommendation']['screening']['sample_mature'])
                self.store.finish_run(nine_lease,state='COMPLETED',result={'fixture':'nine-recommendation-clicks'})
        observed=self.store.observation(self.merchant)
        self.assertEqual((observed['summary']['recommendation_impressions'],observed['summary']['recommendation_clicks']),(10,10))
        fact=next(f for f in observed['facts'] if f['metric']=='recommendation_clicks')
        self.assertEqual(set(fact['source_ids']),set(touch_ids));self.assertEqual(fact['source_total_count'],10)
        _, _, plan_lease, context=self.context(observation=observed)
        self.assertEqual(_model_payload(context)['recommendation']['allowed_actions'],['set_recommendation_policy'])
        candidate={'summary':'依据独立推荐触点评估授权内试验。','diagnosis':[{'code':'other',
            'explanation':'已观察推荐点击，收益原因仍不作结论。','evidence_ids':[fact['evidence_id']]}],
            'actions':[{'action_type':'set_recommendation_policy','policy':{'group':'treatment','strategy_version':'rec-click-fixture',
                'config':deepcopy(DEFAULT_STRATEGIES['content-v1'])}}]}
        spec=validate_candidate(candidate,context,skill_versions={})
        plan=self.store.save_merchant_plan(plan_lease,spec)
        self.store.finish_run(plan_lease,state='COMPLETED',result={'plan_id':plan['plan_id'],'execution':'not_requested_by_this_test'})
        self.assertEqual(plan['spec']['actions'][0]['action_type'],'set_recommendation_policy')
        after=self.store.snapshot(self.merchant)
        for key in ('account','grants','campaigns','creatives','clicks','spend_cents'):
            self.assertEqual(after[key],money_before[key])
        self.assertEqual((after['account']['budget_cap_cents'],after['account']['spent_cents']),(100,100))

    def test_reference_only_plan_binds_exact_selected_facts_and_rejects_tampered_persistence(self):
        _, run, lease, context=self.context()
        fact=next(f for f in context['observation']['facts'] if f['metric']=='clicks')
        candidate={'summary':'等待新证据。','diagnosis':[{'code':'insufficient_evidence',
            'explanation':'当前点击样本有限，继续观察。','evidence_ids':[fact['evidence_id']]}],'actions':[]}
        compiled=validate_candidate(candidate,context,skill_versions={})
        self.assertEqual(compiled['diagnosis'][0]['observed_facts'],[fact])
        self.assertEqual(compiled['evidence_ids'],[fact['evidence_id']])
        for field,value in (('value',999),('metric','impressions'),('source_ids',['invented-source'])):
            tampered=deepcopy(compiled)
            tampered['diagnosis'][0]['observed_facts'][0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(StateError,'merchant_evidence_binding_mismatch'):
                self.store.save_merchant_plan(lease,tampered)
        tampered=deepcopy(compiled);tampered['evidence_ids']=[]
        with self.assertRaisesRegex(StateError,'merchant_evidence_binding_mismatch'):
            self.store.save_merchant_plan(lease,tampered)
        saved=self.store.save_merchant_plan(lease,compiled)
        self.assertEqual(saved['spec'],compiled)
        self.assertEqual([f['metric'] for f in saved['diagnosis'][0]['observed_facts']],['clicks'],
                         'Omitted impressions remain omitted, not silently supplied by the compiler')
        self.assertEqual(self.store.save_merchant_plan(lease,compiled)['spec'],compiled)
        self.store.finish_run(lease,state='COMPLETED',result={'plan_id':saved['plan_id']})
        recreated=MerchantStore(self.connect,clock=lambda:self.now)
        self.assertEqual(recreated.get_plan(self.merchant,saved['plan_id'])['spec'],compiled)

    def test_free_copy_plan_preserves_original_text_and_does_not_execute_during_persistence(self):
        self.active()
        _, _, lease, context = self.context()
        selected = [f['evidence_id'] for f in context['observation']['facts']
                    if f.get('campaign_id') == self.campaign['campaign_id'] and f['metric'] == 'stock']
        text = 'Choose the specification that suits your needs.'
        candidate = {'summary': '按目标改写，效果待新流量验证。', 'diagnosis': [{'code': 'other',
            'explanation': '已确认可售库存，提出文案试验。', 'evidence_ids': selected}],
            'actions': [{'action_type': 'replace_creative', 'campaign_id': self.campaign['campaign_id'],
                         'creative_id': self.creative['creative_id'], 'copy_text': text}]}
        compiled = validate_candidate(candidate, context, skill_versions={'creative_copy': '1.5.0'})
        saved = self.store.save_merchant_plan(lease, compiled)
        self.assertEqual(saved['spec']['actions'][0]['copy_text'], text)
        self.assertNotIn('creative_variants', saved['spec'])
        self.store.finish_run(lease, state='COMPLETED', result={'plan_id': saved['plan_id']})
        recreated = MerchantStore(self.connect, clock=lambda: self.now)
        self.assertEqual(recreated.get_plan(self.merchant, saved['plan_id'])['spec'], compiled)
        self.assertEqual(recreated.snapshot(self.merchant)['creatives'][0]['copy_text'], self.creative['copy_text'])

    def test_recommendation_planning_snapshot_survives_real_revision_change_and_store_recreation(self):
        for _ in range(10):
            receipt=self.recommend()
            self.store.interact(self.user,receipt['recommendation_id'],[1],clicked=True)
        _, run, lease, context=self.context()
        original=deepcopy(context['ads']['recommendation'])
        fact=next(f for f in context['observation']['facts'] if f['metric']=='recommendation_clicks')
        candidate={'summary':'依据推荐触点提出有限策略试验。','diagnosis':[{'code':'other',
            'explanation':'样本满足当前试验门槛，效果仍须观察。','evidence_ids':[fact['evidence_id']]}],
            'actions':[{'action_type':'set_recommendation_policy','policy':{'group':'treatment',
                'strategy_version':'pinned-contract-version','config':deepcopy(DEFAULT_STRATEGIES['content-v1'])}}]}
        advanced=StrategyStore(self.connect).configure_experiment(self.merchant,
            control_version=original['control_strategy_version'],treatment_version=original['treatment_strategy_version'],
            expected_revision=original['revision'])
        self.assertEqual(advanced['revision'],original['revision']+1)
        recreated=MerchantStore(self.connect,clock=lambda:self.now)
        resumed=recreated.get_merchant_context(self.merchant,run['agent_run_id'])
        self.assertEqual(resumed['recommendation_snapshot'],original)
        self.assertEqual(resumed['ads']['recommendation'],original)
        self.assertEqual(recreated.snapshot(self.merchant)['recommendation']['revision'],advanced['revision'])
        self.assertEqual(_model_payload(resumed)['recommendation']['revision'],original['revision'])
        compiled=validate_candidate(candidate,resumed,skill_versions={})
        self.assertEqual(compiled['actions'][0]['expected_version'],original['revision'])
        tampered=deepcopy(compiled);tampered['actions'][0]['expected_version']=advanced['revision']
        with self.assertRaisesRegex(StateError,'merchant_recommendation_snapshot_mismatch'):
            recreated.save_merchant_plan(lease,tampered)
        saved=recreated.save_merchant_plan(lease,compiled)
        self.assertEqual(saved['spec']['actions'][0]['expected_version'],original['revision'])
        self.store.finish_run(lease,state='COMPLETED',result={'plan_id':saved['plan_id']})

    def test_parallel_observers_share_one_round_and_only_one_effective_plan(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            observations = list(workers.map(lambda _: self.store.observation(self.merchant), range(4)))
        self.assertTrue(all(value == observations[0] for value in observations))
        _, _, _, first = self.plan(observation=observations[0])
        with self.assertRaises(StateError):
            self.plan(observation=observations[0])
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM merchant_plan WHERE execution_scope_id=%s AND observation_id=%s',
                           (self.scope, observations[0]['observation_id']))
            self.assertEqual(cursor.fetchone()['n'], 1)
        self.assertEqual(self.store.get_plan(self.merchant, first['plan_id'])['spec']['observation_id'], observations[0]['observation_id'])

    def test_saved_spec_is_immutable_and_trusted_metadata_cannot_be_replaced(self):
        _, run, lease, context = self.context()
        spec = self.spec(context)
        for field, forged in (('actor_id', 'other'), ('execution_scope_id', 'other'), ('scope', 'other'),
                              ('agent_run_id', uuid.uuid4().hex), ('round_id', 'invented-round'),
                              ('watermark', 'invented-watermark'), ('planned_budget_cents', 101),
                              ('product_scope', [self.products[1]]), ('objective', 'invented-objective')):
            with self.subTest(field=field), self.assertRaises(StateError):
                self.store.save_merchant_plan(lease, {**spec, field: forged})
        saved = self.store.save_merchant_plan(lease, spec)
        self.assertEqual(self.store.save_merchant_plan(lease, deepcopy(spec)), saved)
        with self.assertRaises(StateError):
            self.store.save_merchant_plan(lease, {**spec, 'summary': 'changed after save'})
        other = self.merchant.model_copy(update={'actor_id': 'other'})
        with self.assertRaises(StateError):
            self.store.get_plan(other, saved['plan_id'])
        with self.assertRaises(StateError):
            self.store.get_merchant_context(other, run['agent_run_id'])

    def test_plan_versions_parent_links_and_request_replay_survive_store_recreation(self):
        request, run, _, first = self.plan()
        restarted = MerchantStore(self.connect, clock=lambda: self.now)
        self.assertEqual(restarted.request_replay(self.merchant, request)['agent_run_id'], run['agent_run_id'])
        with self.assertRaises(StateError):
            restarted.request_replay(self.merchant, {**request, 'objective': 'changed'})
        self.advance(4)
        _, _, _, second = self.plan()
        self.assertEqual((second['version'], second['parent_plan_id'], second['parent_plan_version']),
                         (first['version'] + 1, first['plan_id'], first['version']))
        self.assertEqual(restarted.get_plan(self.merchant, first['plan_id'])['version'], first['version'])

    def test_run_context_cannot_attach_another_owner_observation_or_run(self):
        other = self.merchant.model_copy(update={'actor_id': 'other-' + uuid.uuid4().hex, 'session_id': uuid.uuid4().hex})
        own_observation = self.store.observation(self.merchant)
        foreign_observation = self.store.observation(other)
        request = {'request_id': uuid.uuid4().hex, 'objective': OBJECTIVE,
                   'product_scope': self.products, 'planned_budget_cents': 100}
        for owner, observation in ((self.merchant, foreign_observation), (other, own_observation)):
            with self.subTest(owner=owner.actor_id):
                conversation = self.store.create_conversation(owner)
                run = self.store.create_run(owner, conversation['conversation_id'], uuid.uuid4().hex, OBJECTIVE)
                with self.assertRaises(StateError):
                    self.store.prepare_run_context(self.merchant, run, observation, request)
                with self.connect() as connection, connection.cursor() as cursor:
                    cursor.execute('SELECT COUNT(*) AS n FROM merchant_run_context WHERE agent_run_id=%s', (run['agent_run_id'],))
                    self.assertEqual(cursor.fetchone()['n'], 0)

    def test_sensitive_goal_is_redacted_before_durable_context(self):
        secret = 'synthetic-merchant-private-value'
        with patch.dict(os.environ, SMARTLECT_MYSQL_PASSWORD=secret):
            _, run, lease, context = self.context(objective='检查业务，附注 ' + secret)
            self.assertNotIn(secret, canonical(context))
            spec = self.spec(context)
            self.store.save_merchant_plan(lease, spec)
            snapshot = self.store.merchant_snapshot(self.merchant)
            self.assertNotIn(secret, canonical(snapshot['memories']))
            self.assertNotIn(secret, canonical(self.store.get_merchant_context(self.merchant, run['agent_run_id'])))

    def test_no_action_waits_for_observation_without_asking_for_grant(self):
        _, _, _, plan = self.plan()
        self.assertEqual(plan['spec']['schema_version'],'merchant-plan-v1')
        original=deepcopy(plan['spec'])
        result = self.store.claim_plan(self.merchant, plan['plan_id'], plan['version'])
        self.assertEqual(result['plan']['status'], 'WAIT_OBSERVATION')
        self.assertIsNone(result['token'])
        self.assertFalse(result['plan']['authorization']['required'])
        self.assertIsNone(self.store.snapshot(self.merchant)['account'])
        self.assertEqual(self.store.get_plan(self.merchant,plan['plan_id'])['spec'],original)

    def test_goal_budget_and_action_outside_grant_wait_for_approval(self):
        self.approve(allowed=['set_budget'], max_budget_change_cents=5)
        cases = [({'objective': '新的目标'}, [self.item('set_budget', budget_cents=99)]),
                 ({'budget': 101}, [self.item('set_budget', budget_cents=101)]),
                 ({}, [self.item('pause_campaign')]), ({}, [self.item('set_budget', budget_cents=90)])]
        for index, (arguments, actions) in enumerate(cases):
            with self.subTest(index=index):
                self.advance(6 + index)
                _, _, _, plan = self.plan(actions=actions, **arguments)
                result = self.store.claim_plan(self.merchant, plan['plan_id'], plan['version'])
                self.assertEqual(result['plan']['status'], 'WAIT_APPROVAL')
                self.assertIsNone(result['token'])
                self.assertFalse(result['plan']['authorization']['within_grant'])
        self.assertEqual(self.store.snapshot(self.merchant)['account']['spent_cents'], 0)

    def test_requested_ceiling_is_not_mistaken_for_actual_planned_spend(self):
        self.approve(allowed=['set_budget'], max_budget_change_cents=5)
        _, _, spec, plan = self.plan(budget=101, actions=[self.item('set_budget', budget_cents=99)])
        self.assertEqual(spec['planned_budget_cents'], 99)
        claim = self.store.claim_plan(self.merchant, plan['plan_id'], plan['version'])
        self.assertEqual(claim['plan']['status'], 'EXECUTING')
        self.assertTrue(claim['plan']['authorization']['within_grant'])

    def test_replacement_approval_executes_original_plan_after_only_its_protective_pause(self):
        self.approve(allowed=['activate_campaign','activate_creative','set_budget'],max_budget_change_cents=5)
        self.execute(self.item('activate_campaign'),self.item('activate_creative'))
        exposure=self.expose()
        self.store.click(self.user,{'click_id':uuid.uuid4().hex,'exposure_id':exposure['exposure_id']},self.stock(5))
        _, _, _, plan=self.plan(actions=[self.item('set_budget',budget_cents=99),
            self.item('replace_creative',copy_text='推广：先核对商品规格再选择')])
        ads=SimpleNamespace(execute_action=AsyncMock(side_effect=lambda actor,request:self.store.execute_action(actor,request,[])))
        service=MerchantService(self.store,ads,None,{})
        refused=asyncio.run(service.execute_plan(self.merchant,plan['plan_id'],plan['version']))
        self.assertEqual(refused['status'],'WAIT_APPROVAL')
        self.assertIsNone(refused['grant_id'])
        self.assertEqual(refused['action_receipts'],[])
        ads.execute_action.assert_not_awaited()
        self.assertEqual(self.store.snapshot(self.merchant)['campaigns'][0]['budget_cents'],100)
        grant=self.approve(merchant_plan=refused)
        paused=self.store.snapshot(self.merchant)
        self.assertEqual((paused['campaigns'][0]['status'],paused['creatives'][0]['status']),('PAUSED','PAUSED'))
        self.assertEqual(paused['account']['spent_cents'],10)
        completed=asyncio.run(service.execute_plan(self.merchant,plan['plan_id'],plan['version']))
        self.assertEqual(completed['status'],'WAIT_OBSERVATION')
        self.assertEqual(completed['spec'],plan['spec'])
        self.assertEqual(completed['grant_id'],grant['grant_id'])
        self.assertEqual(len(completed['action_receipts']),2)
        after=self.store.snapshot(self.merchant)
        self.assertEqual((after['account']['spent_cents'],after['account']['budget_cap_cents']),(10,100))
        self.assertEqual((after['campaigns'][0]['budget_cents'],after['creatives'][0]['copy_text']),
                         (99,'推广：先核对商品规格再选择'))
        self.assertEqual((after['campaigns'][0]['status'],after['creatives'][0]['status']),('PAUSED','PAUSED'))
        self.assertEqual(asyncio.run(service.execute_plan(self.merchant,plan['plan_id'],plan['version'])),completed)
        self.assertEqual(ads.execute_action.await_count,2)
        self.assertEqual(completed['authorization']['approval_snapshot_hash'],grant['plan_snapshot_hash'])
        for index,receipt in enumerate(completed['action_receipts']):
            self.assertEqual(receipt['receipt']['changes'][0]['before']['version'],plan['spec']['actions'][index]['expected_version']+1)
        self.advance(4)
        _, _, _, next_plan=self.plan(actions=[self.item('set_budget',budget_cents=98)])
        next_completed=asyncio.run(service.execute_plan(self.merchant,next_plan['plan_id'],next_plan['version']))
        self.assertEqual(next_completed['status'],'WAIT_OBSERVATION')
        self.assertNotIn('approval_resource_transitions',next_completed['authorization'])
        self.assertEqual(next_completed['action_receipts'][0]['receipt']['changes'][0]['before']['version'],
                         next_plan['spec']['actions'][0]['expected_version'])
        self.assertEqual(self.store.snapshot(self.merchant)['account']['spent_cents'],10)

    def test_bound_approval_rejects_an_independent_edit_before_approval_without_pausing(self):
        self.active()
        _, _, _, plan=self.plan(actions=[self.item('set_budget',budget_cents=90)])
        self.execute(self.item('set_budget',budget_cents=95))
        before=self.store.snapshot(self.merchant)
        with self.assertRaisesRegex(StateError,'merchant_plan_resource_version_conflict'):
            self.approve(merchant_plan=plan)
        self.assertEqual(self.store.snapshot(self.merchant),before)
        self.assertEqual(self.store.get_plan(self.merchant,plan['plan_id'])['spec'],plan['spec'])

    def test_bound_approval_does_not_hide_an_independent_edit_after_its_pause(self):
        self.active()
        _, _, _, plan=self.plan(actions=[self.item('set_budget',budget_cents=90),
            self.item('replace_creative',copy_text='推广：不应执行的后续素材修改')])
        self.approve(merchant_plan=plan)
        self.execute(self.item('set_budget',budget_cents=95))
        ads=SimpleNamespace(execute_action=AsyncMock(side_effect=lambda actor,request:self.store.execute_action(actor,request,[])))
        completed=asyncio.run(MerchantService(self.store,ads,None,{}).execute_plan(self.merchant,plan['plan_id'],plan['version']))
        self.assertEqual(completed['status'],'FAILED')
        self.assertEqual(completed['action_receipts'][0]['reason'],'ads_version_conflict')
        ads.execute_action.assert_awaited_once()
        after=self.store.snapshot(self.merchant)
        self.assertEqual(after['campaigns'][0]['budget_cents'],95)
        self.assertEqual(after['creatives'][0]['copy_text'],self.creative['copy_text'])

    def test_unbound_replacement_does_not_rewrite_a_merchant_plan_version(self):
        self.active()
        _, _, _, plan=self.plan(actions=[self.item('set_budget',budget_cents=90)])
        grant=self.approve()
        self.assertNotIn('approval_resource_transitions',grant['plan_snapshot'])
        ads=SimpleNamespace(execute_action=AsyncMock(side_effect=lambda actor,request:self.store.execute_action(actor,request,[])))
        completed=asyncio.run(MerchantService(self.store,ads,None,{}).execute_plan(self.merchant,plan['plan_id'],plan['version']))
        self.assertEqual(completed['status'],'FAILED')
        self.assertEqual(completed['action_receipts'][0]['reason'],'ads_version_conflict')
        self.assertNotIn('approval_resource_transitions',completed['authorization'])
        self.assertEqual(self.store.snapshot(self.merchant)['campaigns'][0]['budget_cents'],100)

    def test_policy_requires_allowed_parameters_and_entire_registered_product_scope(self):
        limits = {'rankings': ['content'], 'groups': ['treatment'], 'max_weight': 8, 'max_quota': 16}
        self.approve(products=[self.products[0]], recommendation_policy_range=limits)
        config = deepcopy(DEFAULT_STRATEGIES['content-v1'])
        action = {'action_type': 'set_recommendation_policy', 'expected_version': 1,
                  'policy': {'group': 'treatment', 'strategy_version': 'candidate-v2', 'config': config}}
        _, _, _, incomplete = self.plan(actions=[action], products=[self.products[0]])
        result = self.store.claim_plan(self.merchant, incomplete['plan_id'], incomplete['version'])
        self.assertEqual(result['plan']['status'], 'WAIT_APPROVAL')
        self.approve(recommendation_policy_range=limits)
        for index, mutate in enumerate((lambda a: a['policy'].update(group='control'),
                                        lambda a: a['policy']['config'].update(ranking='rule'),
                                        lambda a: a['policy']['config']['weights'].update(content=9),
                                        lambda a: a['policy']['config']['quotas'].update(content=17))):
            candidate = deepcopy(action)
            mutate(candidate)
            self.advance(7 + index)
            _, _, _, plan = self.plan(actions=[candidate])
            result = self.store.claim_plan(self.merchant, plan['plan_id'], plan['version'])
            self.assertEqual(result['plan']['status'], 'WAIT_APPROVAL')
            self.assertIsNone(result['token'])
        self.advance(12)
        _, _, _, valid = self.plan(actions=[action])
        authorized = self.store.claim_plan(self.merchant, valid['plan_id'], valid['version'])
        self.assertEqual(authorized['plan']['status'], 'EXECUTING')
        self.assertIsNotNone(authorized['token'])

    def test_experience_stays_draft_until_explicit_owner_approval(self):
        _, _, _, first = self.plan(experience='等待额外观测后再评估文案变化。')
        snapshot = self.store.merchant_snapshot(self.merchant)
        memory = snapshot['memories'][0]
        self.assertEqual(memory['status'], 'DRAFT')
        self.advance(4)
        _, run, lease, context = self.context()
        self.assertEqual(context['approved_experiences'], [])
        with self.assertRaises(StateError):
            self.store.approve_experience(self.merchant.model_copy(update={'actor_id': 'other'}), memory['memory_id'], memory['version'])
        approved = self.store.approve_experience(self.merchant, memory['memory_id'], memory['version'])
        self.assertEqual(approved['status'], 'APPROVED')
        self.assertEqual(self.store.approve_experience(self.merchant, memory['memory_id'], memory['version']), approved)
        self.assertEqual(self.store.get_merchant_context(self.merchant, run['agent_run_id'])['approved_experiences'][0]['memory_id'], memory['memory_id'])
        self.store.finish_run(lease, state='COMPLETED', result={})

    def test_reviewed_experience_preserves_draft_and_replays_only_the_approved_content(self):
        draft={'content':'支付拒付可能源于库存不足。'}
        _, _, _, plan = self.plan(experience=draft)
        memory = self.store.merchant_snapshot(self.merchant)['memories'][0]
        reviewed='已确认渠道拒付，具体原因尚无证据。'
        for invalid in ('', ' ', '文'*2001, '文\0字'):
            with self.subTest(invalid_length=len(invalid)), self.assertRaises(StateError):
                self.store.approve_experience(self.merchant,memory['memory_id'],memory['version'],invalid)
        approved=self.store.approve_experience(self.merchant,memory['memory_id'],memory['version'],reviewed)
        self.assertEqual((approved['status'],approved['content'],approved['version']),('APPROVED',reviewed,memory['version']+1))
        self.assertEqual(self.store.get_plan(self.merchant,plan['plan_id'])['spec'],plan['spec'])
        self.assertEqual(self.store.approve_experience(self.merchant,memory['memory_id'],memory['version'],reviewed),approved)
        for version,content in ((memory['version'],None),(memory['version'],draft['content']),
                                (memory['version'],reviewed+' 应先增加预算。'),(approved['version'],reviewed)):
            with self.subTest(version=version,content=content), self.assertRaisesRegex(StateError,'experience_version_conflict'):
                self.store.approve_experience(self.merchant,memory['memory_id'],version,content)
        self.advance(4)
        _, run, lease, context = self.context()
        self.assertEqual(context['approved_experiences'][0]['content'],reviewed)
        self.assertNotEqual(context['approved_experiences'][0]['content'],draft['content'])
        from smartlect.agents.merchant import _model_payload
        self.assertNotIn(draft['content'],canonical(_model_payload(context)))
        self.assertEqual(_model_payload(context)['approved_experiences'][0]['summary'],reviewed)
        self.store.finish_run(lease,state='COMPLETED',result={})

    def test_reviewed_experience_is_redacted_before_persistence_and_reuse(self):
        self.plan(experience='等待新证据。')
        memory=self.store.merchant_snapshot(self.merchant)['memories'][0]
        reviewed='先核对渠道记录。 password=synthetic-private-value'
        approved=self.store.approve_experience(self.merchant,memory['memory_id'],memory['version'],reviewed)
        self.assertEqual(approved['content'],'先核对渠道记录。 password=[REDACTED]')
        self.assertEqual(self.store.approve_experience(self.merchant,memory['memory_id'],memory['version'],reviewed),approved)

    def test_execution_lease_recovers_same_action_without_resetting_spend(self):
        self.active()
        exposure = self.expose()
        self.store.click(self.user, {'click_id': uuid.uuid4().hex, 'exposure_id': exposure['exposure_id']}, self.stock(5))
        _, _, spec, plan = self.plan(actions=[self.item('set_budget', budget_cents=90)])
        claimed = self.store.claim_plan(self.merchant, plan['plan_id'], plan['version'])
        request = self.ad_request(spec['actions'], plan_id=plan['plan_id'], plan_version=plan['version'],
                                  action_id=plan['plan_id'], idempotency_key='merchant:' + plan['plan_id'])
        receipt = self.store.execute_action(self.merchant, request, [])
        restarted = MerchantStore(self.connect, clock=lambda: self.now)
        with self.assertRaises(StateError):
            restarted.claim_plan(self.merchant, plan['plan_id'], plan['version'])
        self.now += timedelta(seconds=31)
        recovered = restarted.claim_plan(self.merchant, plan['plan_id'], plan['version'])
        self.assertNotEqual(recovered['token'], claimed['token'])
        self.assertEqual(restarted.execute_action(self.merchant, request, []), receipt)
        with self.assertRaises(StateError):
            restarted.finish_plan(self.merchant, plan['plan_id'], claimed['token'], 'WAIT_OBSERVATION', [receipt])
        final = restarted.finish_plan(self.merchant, plan['plan_id'], recovered['token'], 'WAIT_OBSERVATION', [receipt])
        self.assertEqual(final['status'], 'WAIT_OBSERVATION')
        account = restarted.snapshot(self.merchant)['account']
        self.assertEqual((account['spent_cents'], account['budget_cap_cents'], account['account_id']), (10, 100, self.scope))
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM growth_action WHERE action_id=%s', (request['action_id'],))
            self.assertEqual(cursor.fetchone()['n'], 1)

    def test_committed_plan_recovers_after_revocation_without_new_writes(self):
        self.active()
        _, _, _, plan = self.plan(actions=[self.item('set_budget', budget_cents=90)])
        claimed = self.store.claim_plan(self.merchant,plan['plan_id'],plan['version'])
        request = plan_action_request(claimed['plan'],0,plan_batches(claimed['plan'])[0])
        receipt = self.store.execute_action(self.merchant,request,[])
        self.store.revoke_grant(self.merchant,self.grant['grant_id'],{
            'action_id':uuid.uuid4().hex,'idempotency_key':uuid.uuid4().hex,
            'expected_version':self.grant['version'],'reason_code':'explicit_revocation'})
        self.now += timedelta(seconds=31)
        restarted = MerchantStore(self.connect,clock=lambda:self.now)
        recovered = restarted.recover_completed_plan(self.merchant,plan['plan_id'],plan['version'])
        self.assertEqual(recovered['status'],'WAIT_OBSERVATION')
        self.assertEqual(recovered['action_receipts'][0]['receipt'],receipt)
        self.assertEqual(restarted.snapshot(self.merchant)['account']['spent_cents'],0)
        with self.connect() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM growth_action WHERE action_id=%s',(request['action_id'],))
            self.assertEqual(cursor.fetchone()['n'],1)

    def test_partial_committed_plan_keeps_receipts_but_revocation_blocks_the_rest(self):
        self.active()
        _, _, _, plan = self.plan(actions=[self.item('set_budget',budget_cents=90),
            self.item('replace_creative',copy_text='推广：未获得剩余执行权限的新文案')])
        claimed = self.store.claim_plan(self.merchant,plan['plan_id'],plan['version'])
        request = plan_action_request(claimed['plan'],0,plan_batches(claimed['plan'])[0])
        self.store.execute_action(self.merchant,request,[])
        self.store.revoke_grant(self.merchant,self.grant['grant_id'],{
            'action_id':uuid.uuid4().hex,'idempotency_key':uuid.uuid4().hex,
            'expected_version':self.grant['version'],'reason_code':'explicit_revocation'})
        self.now += timedelta(seconds=31)
        self.assertIsNone(self.store.recover_completed_plan(self.merchant,plan['plan_id'],plan['version']))
        result = self.store.claim_plan(self.merchant,plan['plan_id'],plan['version'])
        self.assertIsNone(result['token'])
        self.assertEqual(result['plan']['status'],'PARTIALLY_APPLIED')
        self.assertEqual(len(result['plan']['action_receipts']),1)
        self.assertFalse(result['plan']['authorization']['within_grant'])
        self.assertEqual(self.store.snapshot(self.merchant)['creatives'][0]['copy_text'],self.creative['copy_text'])

    def test_uncommitted_unknown_plan_waits_for_approval_after_revocation(self):
        self.active()
        _, _, _, plan = self.plan(actions=[self.item('set_budget',budget_cents=90)])
        ads = SimpleNamespace(execute_action=AsyncMock(side_effect=OperationalError(2013,'connection lost before commit')))
        service = MerchantService(self.store,ads,None,{})
        uncertain = asyncio.run(service.execute_plan(self.merchant,plan['plan_id'],plan['version']))
        self.assertEqual(uncertain['status'],'EXECUTING')
        self.assertEqual(uncertain['action_receipts'][0]['command_status'],'unknown')
        request = ads.execute_action.call_args.args[1]
        self.assertIsNone(self.store.action_replay(self.merchant,request))
        self.store.revoke_grant(self.merchant,self.grant['grant_id'],{
            'action_id':uuid.uuid4().hex,'idempotency_key':uuid.uuid4().hex,
            'expected_version':self.grant['version'],'reason_code':'explicit_revocation'})
        recovered = asyncio.run(service.execute_plan(self.merchant,plan['plan_id'],plan['version']))
        self.assertEqual(recovered['status'],'WAIT_APPROVAL')
        self.assertEqual(recovered['action_receipts'],[])
        self.assertFalse(recovered['authorization']['within_grant'])
        self.assertEqual(recovered['grant_id'],self.grant['grant_id'])
        ads.execute_action.assert_awaited_once()
        snapshot = self.store.snapshot(self.merchant)
        self.assertEqual(snapshot['campaigns'][0]['budget_cents'],100)
        self.assertEqual(snapshot['account']['spent_cents'],0)
        self.assertIsNone(self.store.action_replay(self.merchant,request))

    def test_unknown_response_recovers_persisted_rejection_without_partial_success(self):
        self.active()
        _, _, _, plan = self.plan(actions=[self.item('set_budget',expected_version=999,budget_cents=90)])
        claimed = self.store.claim_plan(self.merchant,plan['plan_id'],plan['version'])
        request = plan_action_request(claimed['plan'],0,plan_batches(claimed['plan'])[0])
        with self.assertRaises(StateError):
            self.store.execute_action(self.merchant,request,[])
        self.store.finish_plan(self.merchant,plan['plan_id'],claimed['token'],'EXECUTING',[
            {'batch':0,'command_status':'unknown','action_id':request['action_id'],'reason':'response_lost'}])
        self.store.revoke_grant(self.merchant,self.grant['grant_id'],{
            'action_id':uuid.uuid4().hex,'idempotency_key':uuid.uuid4().hex,
            'expected_version':self.grant['version'],'reason_code':'explicit_revocation'})
        recovered = self.store.recover_completed_plan(self.merchant,plan['plan_id'],plan['version'])
        self.assertEqual(recovered['status'],'FAILED')
        self.assertEqual(recovered['action_receipts'][0]['command_status'],'rejected')
        self.assertEqual(recovered['action_receipts'][0]['receipt']['status'],'REJECTED')
        self.assertEqual(self.store.snapshot(self.merchant)['campaigns'][0]['budget_cents'],100)

    def test_java_decline_evidence_is_nonfinancial_and_scoped(self):
        previous = self.store.observation(self.merchant)
        event = payment_attempt(uuid.uuid4().hex, user_id=self.user.actor_id)
        self.ledger.ingest(json.dumps({'schema_version': 2, 'events': [event]}).encode())
        observation = self.store.observation(self.merchant)
        self.assertEqual(observation['round_number'], previous['round_number'] + 1)
        self.assertEqual((observation['summary']['payment_failures'], observation['summary']['paid_cents']), (1, 0))
        evidence = next(f for f in observation['facts'] if f['metric'] == 'payment_failures')
        self.assertEqual((evidence['kind'], evidence['source_ids']), ('payment_attempt', [event['eventId']]))
        self.assertEqual(datetime.fromisoformat(observation['payment_attempts'][0]['occurred_at'].replace('Z', '+00:00')),
                         datetime.fromisoformat(event['occurredAt'].replace('Z', '+00:00')))
        another = payment_attempt(uuid.uuid4().hex, user_id='unregistered-other-user')
        self.ledger.ingest(json.dumps({'schema_version': 2, 'events': [another]}).encode())
        self.assertEqual(self.store.observation(self.merchant), observation)


if __name__ == '__main__':
    unittest.main()
