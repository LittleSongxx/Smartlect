"""Merchant graph contracts use synthetic snapshots and a fake provider; no model quality claim."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from smartlect.ads.analytics import CampaignMetrics, LOW_CTR_PER_MILLE, detect_anomalies
from smartlect.agents.merchant import (InvalidPlan, PlanCandidate, _model_payload, _skills,
                                      rule_candidate, run_merchant, validate_candidate)
from smartlect.auth import ActorContext
from smartlect.business_skills import catalog, load_skill
from smartlect.events import canonical
from smartlect.provider import ProviderError
from smartlect.recommendation.store import DEFAULT_STRATEGIES
from smartlect.state import StateError


ACTOR = ActorContext(subject_type='merchant', actor_id='merchant', session_id='synthetic-session',
                     execution_scope_id='contract-scope', permissions=('admin:legacy',))
SKILLS = {name: '1.0.0' for name in ('campaign_plan', 'performance_review', 'creative_copy')}


def source(**changes):
    metrics = {'stock': 5, 'impressions': 100, 'clicks': 20, 'spend_cents': 20,
        'paid_cents': 1000, 'refunded_cents': 0, 'payment_conversions': 1,
        'payment_failures': 0, 'cancelled_orders': 0, 'empty_recommendations': 0, 'stock_rejections': 0,
        'recommendation_impressions':0,'recommendation_clicks':0, **changes}
    kinds = {'stock': 'inventory', 'impressions': 'ads', 'clicks': 'ads', 'spend_cents': 'ads',
             'payment_failures': 'payment_attempt', 'empty_recommendations': 'recommendation',
             'recommendation_impressions':'recommendation','recommendation_clicks':'recommendation'}
    facts = [{'evidence_id': 'fact-' + metric, 'kind': kinds.get(metric, 'commerce'),
        'metric': metric, 'value': value, 'campaign_id': 'campaign', 'source': 'synthetic_contract',
        'occurred_at': '2026-09-09T12:00:00Z'} for metric, value in metrics.items()]
    for fact in facts:
        if fact['metric'].startswith('recommendation_'):fact.pop('campaign_id')
    return {'observation': {'observation_id': 'observation', 'watermark': 'new-facts', 'round_id': 'round-2',
        'observed_at': '2026-09-09T12:00:00Z', 'facts': facts, 'summary': metrics,
        'maturity': {'minimum_clicks': 10, 'minimum_creative_impressions': 100,
                     'minimum_recommendation_clicks':10,
                     'financial_sample_maturity':'not_established_by_click_screening',
                     'creative_low_ctr_per_mille': LOW_CTR_PER_MILLE}, 'campaigns': [{
            'campaign_id': 'campaign', 'product_id': 'product', 'sku_key': 'hash', 'status': 'ACTIVE', 'version': 3,
            'budget_cents': 100, 'spent_cents': 20, 'cpc_cents': 10,
            'metrics': {key:value for key,value in metrics.items() if not key.startswith('recommendation_')},
            'creatives': [{'creative_id': 'creative', 'status': 'ACTIVE', 'version': 2, 'copy_text': '推广：查看具体规格'}],
            'evidence_ids': [f['evidence_id'] for f in facts]}]},
        'ads': {'account': {'budget_cap_cents': 100, 'spent_cents': 20}, 'grants': [],
                'recommendation': {'revision': 2, 'strategies': []}},
        'goal': {'objective': '评估现有模拟经营观测'}, 'previous_plan': None, 'current_plan': None,
        'approved_experiences': [], 'plan_meta': {'plan_id': 'plan', 'version': 2, 'parent_plan_id': 'plan',
            'parent_plan_version': 1, 'actor_id': 'merchant', 'agent_run_id': 'run', 'scope': 'contract-scope',
            'round_id': 'round-2', 'period': 'scope_lifetime', 'objective': '评估现有模拟经营观测',
            'product_scope': ['product'], 'planned_budget_cents': 100}}


def policy_candidate(context):
    candidate=rule_candidate(context)
    fact=next(f for f in context['observation']['facts'] if f['metric']=='recommendation_clicks')
    candidate['diagnosis'].append({'code':'other','explanation':'依据独立推荐触点评估策略试验，尚不作收益结论。',
        'evidence_ids':[fact['evidence_id']]})
    candidate['actions']=[{'action_type':'set_recommendation_policy','policy':{
        'strategy_version':'plan-strategy','group':'treatment','config':deepcopy(DEFAULT_STRATEGIES['content-v1'])}}]
    return candidate


class FakeStore:
    def __init__(self, data):
        self.source = data
        self.context = {}
        self.saved = []
        self.finished = []
        self.executions = []
        self.execute_status = 'WAIT_OBSERVATION'

    def get_merchant_context(self, actor, run_id):
        return deepcopy(self.source)

    def save_context(self, lease, context):
        self.context = deepcopy(context)

    def save_merchant_plan(self, lease, plan):
        self.saved.append(deepcopy(plan))
        return {'plan_id': plan['plan_id'], 'version': plan['version'], 'status': 'VALIDATED', 'spec': deepcopy(plan)}

    async def execute_plan(self, actor, plan_id, expected_version):
        self.executions.append((actor.actor_id, plan_id, expected_version))
        return {'plan_id': plan_id, 'version': expected_version, 'status': self.execute_status,
                'spec': deepcopy(self.saved[-1]) if self.saved else {}}

    def finish_run(self, lease, *, state, result):
        value = {'state': state, 'result': result, 'context': deepcopy(self.context)}
        self.finished.append(value)
        return value


class FakeProvider:
    def __init__(self, store, responses, attempts_per_call=1):
        self.store, self.responses = store, responses
        self.attempts_per_call = attempts_per_call
        self.messages, self.options = [], []
        self.actual_attempts = 0

    async def chat(self, messages, **options):
        index = len(self.messages)
        self.messages.append(deepcopy(messages))
        self.options.append(options)
        for attempt in range(self.attempts_per_call):
            await options['before_attempt']()
            self.actual_attempts += 1
            assert self.store.context['model_calls'] >= self.actual_attempts, 'attempt must be durable before HTTP'
            await options['on_trace']({'provider': 'fake-contract-test', 'model_id': 'fake-model', 'model_mode': 'mock',
                'status': 'failed' if attempt + 1 < self.attempts_per_call else 'succeeded',
                'attempt': attempt + 1, 'usage': {'input_tokens': None, 'output_tokens': None, 'total_tokens': None}})
        response = self.responses[min(index, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return {'message': {'role': 'assistant', 'content': response if isinstance(response, str) else canonical(response)}}


def invocation(context=None, deadline=None):
    return {'agent_run_id': 'run', 'context': context or {},
            'deadline': (deadline or datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()}


class MerchantValidationTests(unittest.TestCase):
    def test_five_diagnostic_scenarios_reference_actual_typed_metrics(self):
        for changes, code in [({'stock': 0}, 'stockout'), ({'clicks': 1, 'impressions': 250}, 'creative_underperforming'),
                ({'payment_failures': 2}, 'payment_failures'), ({'refunded_cents': 100}, 'refunds'),
                ({'clicks': 1, 'impressions': 5}, 'insufficient_evidence')]:
            with self.subTest(code=code):
                data = source(**changes)
                plan = validate_candidate(rule_candidate(data), data, skill_versions=SKILLS)
                self.assertIn(code, {d['code'] for d in plan['diagnosis']})
                self.assertTrue(plan['evidence_ids'])
                self.assertTrue(all(d['interpretation'] == 'candidate_not_causal' for d in plan['diagnosis']))
                self.assertLessEqual(len(plan['actions']), 8)

    def test_rule_baseline_keeps_shared_screening_without_restricting_model_proposals(self):
        for impressions, weak in ((200, False), (250, True)):
            data = source(clicks=1, impressions=impressions)
            candidate = rule_candidate(data)
            self.assertEqual('creative_underperforming' in {d['code'] for d in candidate['diagnosis']}, weak)
            metric = CampaignMetrics('campaign', 100, impressions=impressions, clicks=1)
            self.assertEqual(any(a['reason_code'] == 'low_ctr' for a in detect_anomalies([metric])), weak)
        # Retires the old model hard gate: a hypothesis is not a confirmed low-CTR fact.
        candidate = rule_candidate(source(clicks=1, impressions=250))
        plan = validate_candidate(candidate, source(clicks=1, impressions=200), skill_versions=SKILLS)
        self.assertEqual(plan['diagnosis'][0]['interpretation'], 'candidate_not_causal')

    def test_hypothesis_label_does_not_replace_selected_evidence_or_authorize_other_campaigns(self):
        data = source(clicks=1, impressions=250)
        candidate = rule_candidate(data)
        diagnosis = next(d for d in candidate['diagnosis'] if d['code'] == 'creative_underperforming')
        diagnosis['evidence_ids'] = ['fact-stock']
        plan = validate_candidate(candidate, data, skill_versions=SKILLS)
        self.assertEqual(plan['diagnosis'][0]['observed_facts'][0]['metric'], 'stock')
        diagnosis['evidence_ids'] = ['outside-observation']
        with self.assertRaisesRegex(InvalidPlan, 'unknown_or_duplicate_diagnosis_evidence'):
            validate_candidate(candidate, data, skill_versions=SKILLS)

    def test_partial_evidence_selection_is_preserved_without_automatic_groups(self):
        for changes,code,selected in (({'clicks':0,'impressions':1},'insufficient_evidence','fact-clicks'),
                                      ({'refunded_cents':1000},'refunds','fact-refunded_cents')):
            data=source(**changes)
            candidate={'summary':'依据所选观察保留判断。','diagnosis':[{'code':code,
                'explanation':'仍须核对相关观测，不能据此推断原因。','evidence_ids':[selected]}],'actions':[]}
            before=deepcopy(data)
            compiled=validate_candidate(candidate,data,skill_versions=SKILLS)
            expected=next(f for f in data['observation']['facts'] if f['evidence_id']==selected)
            self.assertEqual(compiled['diagnosis'][0]['observed_facts'],[expected])
            self.assertEqual(compiled['evidence_ids'],[selected])
            self.assertEqual(candidate['diagnosis'][0]['evidence_ids'],[selected])
            self.assertNotIn('observed_facts',candidate['diagnosis'][0])
            self.assertEqual(data,before)
            self.assertEqual(compiled['schema_version'],'merchant-plan-v2')
            self.assertEqual(compiled['proposal_schema_version'],'merchant-proposal-v1')
            self.assertEqual(compiled['evidence_binding_version'],'selected-observation-v1')
        with self.assertRaisesRegex(InvalidPlan,'refund_requires_confirmed_refund_fact'):
            validate_candidate(candidate,source(refunded_cents=0),skill_versions=SKILLS)

    def test_fact_binding_preserves_null_provenance_and_never_mutates_the_snapshot(self):
        data=source(stock=None)
        fact=next(f for f in data['observation']['facts'] if f['metric']=='stock')
        fact.update(source_ids=['original-source'],source_total_count=1,source_ids_truncated=False)
        candidate={'summary':'库存尚待核对。','diagnosis':[{'code':'other','explanation':'保留库存判断。',
                   'evidence_ids':['fact-stock']}],'actions':[]}
        compiled=validate_candidate(candidate,data,skill_versions=SKILLS)
        bound=compiled['diagnosis'][0]['observed_facts'][0]
        self.assertEqual(bound,fact)
        self.assertIsNone(bound['value'])
        bound['source_ids'].append('only-output')
        self.assertEqual(fact['source_ids'],['original-source'])
        for ids in (['old-observation:id'],['fact-stock','fact-stock']):
            candidate['diagnosis'][0]['evidence_ids']=ids
            with self.subTest(ids=ids),self.assertRaisesRegex(InvalidPlan,'unknown_or_duplicate_diagnosis_evidence'):
                validate_candidate(candidate,data,skill_versions=SKILLS)

    def test_model_cannot_inject_bound_values_or_cross_product_evidence(self):
        data=source()
        candidate={'summary':'核对观察。','diagnosis':[{'code':'other','explanation':'暂时保留判断。',
                   'evidence_ids':['fact-stock']}],'actions':[]}
        for value in (0,True,1.0,None):
            forged=deepcopy(candidate)
            forged['diagnosis'][0]['observed_facts']=[{'evidence_id':'fact-stock','metric':'stock','value':value}]
            with self.subTest(value=value),self.assertRaises(ValidationError):
                validate_candidate(forged,data,skill_versions=SKILLS)
        other=deepcopy(data['observation']['campaigns'][0]);other.update(campaign_id='foreign',product_id='outside')
        data['observation']['campaigns'].append(other)
        data['observation']['facts'].append({'evidence_id':'foreign-stock','kind':'inventory','metric':'stock','value':0,'campaign_id':'foreign'})
        candidate['diagnosis'][0]['evidence_ids']=['foreign-stock']
        with self.assertRaisesRegex(InvalidPlan,'unknown_or_duplicate_diagnosis_evidence'):
            validate_candidate(candidate,data,skill_versions=SKILLS)

    def test_rule_baseline_uses_the_same_reference_only_contract_and_bound(self):
        data=source(clicks=0,impressions=1,refunded_cents=1000)
        candidate=rule_candidate(data)
        compiled=validate_candidate(candidate,data,skill_versions=SKILLS)
        for selected,bound in zip(candidate['diagnosis'],compiled['diagnosis']):
            self.assertNotIn('observed_facts',selected)
            self.assertLessEqual(len(selected['evidence_ids']),16)
            self.assertEqual(selected['evidence_ids'],[f['evidence_id'] for f in bound['observed_facts']])

    def test_payment_attempt_input_preserves_authority_and_bounds_detail_without_raw_order_ids(self):
        data=source(payment_failures=7,cancelled_orders=2)
        data['observation']['payment_attempts']=[{'event_id':f'java-{i}','attemptStatus':'DECLINED',
            'reasonCode':'MOCK_CHANNEL_DECLINED','paymentMode':'mock','occurred_at':'2026-09-09T12:00:00Z',
            'payOrderId':'unneeded-order-reference'} for i in range(7)]
        payload=_model_payload(data)
        self.assertEqual([r['event_id'] for r in payload['java_payment_attempts']], [f'java-{i}' for i in range(2,7)])
        self.assertTrue(all(r['reasonCode']=='MOCK_CHANNEL_DECLINED' for r in payload['java_payment_attempts']))
        self.assertNotIn('unneeded-order-reference',canonical(payload))
        self.assertEqual(next(f['value'] for f in payload['facts'] if f['metric']=='payment_failures'),7)
        self.assertEqual(next(f['value'] for f in payload['facts'] if f['metric']=='cancelled_orders'),2)

    def test_scope_diagnosis_does_not_authorize_unreferenced_campaign_action(self):
        data = source(payment_failures=2)
        next(f for f in data['observation']['facts'] if f['metric'] == 'payment_failures').pop('campaign_id')
        candidate = rule_candidate(data)
        candidate['actions'] = [{'action_type': 'pause_campaign', 'campaign_id': 'campaign'}]
        with self.assertRaisesRegex(InvalidPlan, 'action_requires_resource_evidence'):
            validate_candidate(candidate, data, skill_versions=SKILLS)

    def test_uncertainty_does_not_block_a_budget_proposal_or_bypass_the_business_ceiling(self):
        candidate = {'summary': '小样本试验建议。', 'diagnosis': [{'code': 'insufficient_evidence',
            'explanation': '当前库存充足，效果需要下一轮验证。', 'evidence_ids': ['fact-stock']}],
            'actions': [{'action_type': 'set_budget', 'campaign_id': 'campaign', 'budget_cents': 90}]}
        for code in ('insufficient_evidence', 'other'):
            candidate['diagnosis'][0]['code'] = code
            plan = validate_candidate(candidate, source(clicks=0, impressions=1), skill_versions=SKILLS)
            self.assertEqual(plan['planned_budget_cents'], 90)
        candidate['actions'][0]['budget_cents'] = 101
        with self.assertRaisesRegex(InvalidPlan, 'plan_budget_outside_user_constraint'):
            validate_candidate(candidate, source(), skill_versions=SKILLS)

    def test_cancel_unknown_and_mismatched_numbers_cannot_be_payment_failure(self):
        data = source(cancelled_orders=2, payment_failures=None)
        wrong = {'summary': '请人工检查支付环节。', 'diagnosis': [{'code': 'payment_failures',
            'explanation': '存在失败，需要检查。', 'evidence_ids': ['fact-cancelled_orders']}]}
        with self.assertRaisesRegex(InvalidPlan, 'payment_failure_requires_java_attempt_fact'):
            validate_candidate(wrong, data, skill_versions=SKILLS)
        for value in (1, True, 1.0):
            changed = deepcopy(wrong)
            changed['diagnosis'][0].update(evidence_ids=['fact-payment_failures'], observed_facts=[
                {'evidence_id': 'fact-payment_failures', 'metric': 'payment_failures', 'value': value}])
            with self.subTest(value=value), self.assertRaises((InvalidPlan, ValidationError)):
                validate_candidate(changed, data, skill_versions=SKILLS)

    def test_plan_cannot_forge_identity_authorization_resources_or_versions(self):
        data = source(stock=0)
        candidate = rule_candidate(data)
        for field in ('actor_id', 'execution_scope_id', 'grant_id', 'approved', 'plan_id'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                PlanCandidate.model_validate({**candidate, field: 'forged'})
        for key, value in [('campaign_id', 'other')]:
            changed = deepcopy(candidate)
            changed['actions'][0][key] = value
            with self.subTest(key=key), self.assertRaises(InvalidPlan):
                validate_candidate(changed, data, skill_versions=SKILLS)
        changed = deepcopy(candidate)
        changed['actions'] *= 9
        with self.assertRaises(ValidationError):
            validate_candidate(changed, data, skill_versions=SKILLS)

    def test_immature_sample_waits_but_positive_budget_draft_can_bootstrap(self):
        data = source(clicks=0, impressions=0)
        self.assertEqual(rule_candidate(data)['actions'], [])
        campaign = data['observation']['campaigns'][0]
        campaign['status'] = campaign['creatives'][0]['status'] = 'DRAFT'
        plan = validate_candidate(rule_candidate(data), data, skill_versions=SKILLS)
        self.assertEqual([a['action_type'] for a in plan['actions']], ['activate_campaign', 'activate_creative'])
        invalid = rule_candidate(data)
        invalid['actions'] = [{'action_type': 'set_budget', 'campaign_id': 'campaign', 'expected_version': 3, 'budget_cents': 80}]
        self.assertEqual(validate_candidate(invalid, data, skill_versions=SKILLS)['planned_budget_cents'], 80)
        campaign['status'] = 'ACTIVE'
        invalid['actions'] = [{'action_type': 'pause_campaign', 'campaign_id': 'campaign', 'expected_version': 3}]
        self.assertEqual(validate_candidate(invalid, data, skill_versions=SKILLS)['actions'][0]['action_type'], 'pause_campaign')

    def test_unspent_draft_can_propose_initial_budget_and_project_activation_version(self):
        data=source(clicks=0,impressions=0,spend_cents=0,paid_cents=0,payment_conversions=0)
        campaign=data['observation']['campaigns'][0]
        campaign['status']=campaign['creatives'][0]['status']='DRAFT'
        campaign['spent_cents']=0
        data['plan_meta']['planned_budget_cents']=120
        candidate=rule_candidate(data)
        candidate['actions'].insert(0,{'action_type':'set_budget','campaign_id':'campaign','expected_version':3,'budget_cents':120})
        plan=validate_candidate(candidate,data,skill_versions=SKILLS)
        self.assertEqual(plan['planned_budget_cents'],120)
        self.assertEqual([a['expected_version'] for a in plan['actions']],[3,4,2])
        self.assertEqual(plan['dependencies'][1]['depends_on'],[0])
        campaign['status']='ACTIVE'
        candidate['actions']=candidate['actions'][:1]
        self.assertEqual(validate_candidate(candidate,data,skill_versions=SKILLS)['planned_budget_cents'],120)

    def test_one_plan_cannot_treat_shared_experiment_revision_as_two_independent_groups(self):
        data=source(recommendation_clicks=10)
        candidate=policy_candidate(data)
        candidate['actions']=[{'action_type':'set_recommendation_policy','expected_version':2,
            'policy':{'group':group,'strategy_version':'candidate-'+group,'config':deepcopy(DEFAULT_STRATEGIES['rules-v1'])}}
            for group in ('control','treatment')]
        with self.assertRaisesRegex(InvalidPlan,'duplicate_action_target'):
            validate_candidate(candidate,data,skill_versions=SKILLS)

    def test_campaign_delivery_requires_existing_or_planned_active_creative(self):
        data=source(clicks=0,impressions=0,spend_cents=0,paid_cents=0,payment_conversions=0)
        campaign=data['observation']['campaigns'][0]
        campaign['status']=campaign['creatives'][0]['status']='DRAFT'
        campaign['spent_cents']=0
        candidate=rule_candidate(data)
        candidate['actions']=[a for a in candidate['actions'] if a['action_type']=='activate_campaign']
        with self.assertRaisesRegex(InvalidPlan,'delivery_requires_active_creative'):
            validate_candidate(candidate,data,skill_versions=SKILLS)
        campaign['status']='PAUSED'
        campaign['creatives'][0]['status']='ACTIVE'
        candidate['actions'][0]['action_type']='resume_campaign'
        validate_candidate(candidate,data,skill_versions=SKILLS)

    def test_controller_binds_versions_from_planning_snapshot_not_model_guesses(self):
        data=source(stock=0)
        candidate=rule_candidate(data)
        candidate['actions'][0]['expected_version']=999
        data['ads']['campaigns']=[{'campaign_id':'campaign','version':888}]
        compiled=validate_candidate(candidate,data,skill_versions=SKILLS)
        self.assertEqual(compiled['actions'][0]['expected_version'],3)
        candidate['actions'][0].pop('expected_version')
        self.assertEqual(validate_candidate(candidate,data,skill_versions=SKILLS)['actions'][0]['expected_version'],3)

    def test_free_copy_and_numeric_explanations_remain_reviewable_without_template_binding(self):
        data = source(clicks=1, impressions=250)
        for copy_text in ('推广：比较规格后再选择。', 'Choose the specification that meets your needs.', '先看已有商品信息；不必立刻购买。'):
            candidate = rule_candidate(data)
            candidate['diagnosis'][0]['explanation'] = '250次曝光和1次点击，改写效果仍待验证。'
            candidate['actions'][0]['copy_text'] = copy_text
            plan = validate_candidate(candidate, data, skill_versions=SKILLS)
            self.assertEqual(plan['actions'][0]['copy_text'], copy_text)
            self.assertNotIn('creative_variants', plan)
        candidate['actions'][0]['copy_text'] = data['observation']['campaigns'][0]['creatives'][0]['copy_text']
        with self.assertRaisesRegex(InvalidPlan, 'creative_copy_unchanged'):
            validate_candidate(candidate, data, skill_versions=SKILLS)

    def test_draft_creative_can_be_written_before_first_exposure_and_keeps_version_dependencies(self):
        data = source(clicks=0, impressions=0)
        data['observation']['campaigns'][0]['creatives'][0]['status'] = 'DRAFT'
        candidate = rule_candidate(data)
        candidate['actions'] = [{'action_type': 'replace_creative', 'campaign_id': 'campaign',
            'creative_id': 'creative', 'copy_text': '按实际需求比较商品规格。'},
            {'action_type': 'activate_creative', 'campaign_id': 'campaign', 'creative_id': 'creative'}]
        plan = validate_candidate(candidate, data, skill_versions=SKILLS)
        self.assertEqual([a['expected_version'] for a in plan['actions']], [2, 3])
        self.assertEqual(plan['dependencies'][1]['depends_on'], [0])

    def test_payload_marks_default_store_policy_unsupported_without_granting_other_scope(self):
        data = source()
        payload = _model_payload(data)
        self.assertTrue(payload['recommendation']['change_supported'])
        self.assertIsNone(payload['grant'])
        self.assertEqual(payload['maturity']['creative_low_ctr_per_mille'], LOW_CTR_PER_MILLE)
        data['plan_meta']['scope'] = 'store'
        payload = _model_payload(data)
        self.assertFalse(payload['recommendation']['change_supported'])
        self.assertEqual(payload['execution_scope_id'], 'store')
        self.assertEqual(payload['campaigns'][0]['creatives'][0]['allowed_actions'],
                         ['replace_creative', 'pause_creative'])

    def test_screening_is_advice_while_free_copy_remains_available_across_samples(self):
        for impressions, clicks, weak in ((0, 0, False), (99, 0, False), (100, 0, True),
                                         (200, 1, False), (250, 1, True), (100, 20, False)):
            data = source(impressions=impressions, clicks=clicks)
            campaign = _model_payload(data)['campaigns'][0]
            self.assertIn('replace_creative', campaign['creatives'][0]['allowed_actions'])
            self.assertIn('creative_copy', _skills(data))
            self.assertEqual(any(a['action_type'] == 'replace_creative' for a in rule_candidate(data)['actions']), weak)
            candidate = {'summary': '本轮尝试改写，不承诺收益。', 'diagnosis': [{'code': 'other',
                'explanation': '现有商品信息可重新组织，效果待新流量验证。', 'evidence_ids': ['fact-impressions']}],
                'actions': [{'action_type': 'replace_creative', 'campaign_id': 'campaign',
                    'creative_id': 'creative', 'copy_text': '查看商品信息后选择所需规格。'}]}
            self.assertEqual(validate_candidate(candidate, data, skill_versions=SKILLS)['actions'][0]['copy_text'],
                             candidate['actions'][0]['copy_text'])

    def test_free_copy_reuses_executor_field_validation_and_resource_binding(self):
        data = source(clicks=0, impressions=0)
        candidate = rule_candidate(data)
        candidate['actions'] = [{'action_type': 'replace_creative', 'campaign_id': 'campaign',
            'creative_id': 'creative', 'copy_text': '根据用途选规格。'}]
        original = deepcopy(candidate)
        compiled = validate_candidate(candidate, data, skill_versions=SKILLS)
        self.assertEqual(candidate, original)
        self.assertEqual(compiled['actions'][0]['expected_version'], 2)
        for value in ('', 'x' * 1001, None):
            candidate['actions'][0]['copy_text'] = value
            with self.assertRaises(ValidationError):
                validate_candidate(candidate, data, skill_versions=SKILLS)
        candidate = deepcopy(original)
        candidate['actions'][0]['creative_id'] = 'foreign'
        with self.assertRaises(InvalidPlan):
            validate_candidate(candidate, data, skill_versions=SKILLS)

    def test_payload_separates_sample_advice_from_action_availability_and_policy_enums(self):
        data = source(clicks=1, impressions=250)
        original = deepcopy(data)
        payload = _model_payload(data)
        campaign = payload['campaigns'][0]
        self.assertTrue(campaign['screening']['low_ctr_sample'])
        self.assertFalse(campaign['screening']['budget_sample_mature'])
        self.assertEqual(campaign['allowed_actions'], ['set_budget', 'pause_campaign'])
        self.assertEqual(campaign['creatives'][0]['allowed_actions'], ['replace_creative', 'pause_creative'])
        self.assertEqual(payload['recommendation']['allowed_actions'], ['set_recommendation_policy'])
        self.assertEqual(payload['recommendation']['policy_enums'],
                         {'group': ['control', 'treatment', 'all'], 'ranking': ['rule', 'content']})
        self.assertEqual(data, original)
        candidate = policy_candidate(data)
        validate_candidate(candidate, data, skill_versions=SKILLS)
        candidate['actions'][0]['policy']['group'] = 'everyone'
        with self.assertRaises(ValidationError):
            validate_candidate(candidate, data, skill_versions=SKILLS)

    def test_payload_bootstrap_declares_dependencies_without_grant_or_creative_optimization(self):
        data = source(clicks=0, impressions=0)
        campaign = data['observation']['campaigns'][0]
        campaign.update(status='DRAFT', budget_cents=0, spent_cents=0)
        campaign['creatives'][0]['status'] = 'DRAFT'
        payload = _model_payload(data)
        campaign = payload['campaigns'][0]
        self.assertIsNone(payload['grant'])
        self.assertEqual(campaign['allowed_actions'], ['set_budget', 'activate_campaign'])
        self.assertEqual(campaign['creatives'][0]['allowed_actions'], ['replace_creative', 'activate_creative'])
        self.assertIn('draft_cannot_pause', campaign['blocked_actions']['pause_campaign'])
        self.assertEqual(campaign['action_requirements']['activate_campaign'],
                         ['set_budget_before_delivery_within_planned_budget_limit', 'activate_or_resume_a_creative_in_same_plan'])
        self.assertEqual(campaign['creatives'][0]['action_requirements']['activate_creative'],
                         ['set_budget_before_delivery_within_planned_budget_limit', 'activate_campaign_in_same_plan'])
        validate_candidate(rule_candidate(data), data, skill_versions=SKILLS)

    def test_payload_stock_and_scope_blockers_preserve_protection_and_explicit_resume(self):
        for stock in (0, None, 5):
            with self.subTest(stock=stock):
                data = source(stock=stock, clicks=0, impressions=0)
                data['plan_meta']['scope'] = 'store'
                campaign = data['observation']['campaigns'][0]
                campaign['status'] = campaign['creatives'][0]['status'] = 'PAUSED'
                payload = _model_payload(data)
                campaign = payload['campaigns'][0]
                self.assertIn('policy_requires_registered_scope',
                              payload['recommendation']['blocked_actions']['set_recommendation_policy'])
                if stock == 5:
                    self.assertEqual(campaign['allowed_actions'], ['set_budget', 'resume_campaign', 'pause_campaign'])
                    self.assertEqual(campaign['creatives'][0]['allowed_actions'], ['replace_creative', 'resume_creative', 'pause_creative'])
                else:
                    self.assertIn('positive_stock_required_for_delivery', campaign['blocked_actions']['resume_campaign'])
                    self.assertEqual(campaign['allowed_actions'], ['set_budget', 'pause_campaign'])
        mature = _model_payload(source(recommendation_clicks=10))
        self.assertEqual(mature['recommendation']['allowed_actions'], ['set_recommendation_policy'])
        self.assertEqual(len(mature['action_types']), 9)

    def test_stock_restoration_proposes_explicit_resume_but_preserves_manual_pause(self):
        data = source(stock=5, clicks=0, impressions=0)
        campaign = data['observation']['campaigns'][0]
        campaign.update(status='PAUSED', pause_reason='stockout')
        campaign['creatives'][0].update(status='PAUSED', pause_reason='stockout')
        plan = validate_candidate(rule_candidate(data), data, skill_versions=SKILLS)
        self.assertEqual([a['action_type'] for a in plan['actions']], ['resume_campaign', 'resume_creative'])
        campaign['pause_reason'] = 'merchant_manual_pause'
        self.assertEqual(rule_candidate(data)['actions'], [])

    def test_recommendation_policy_requires_current_revision_and_valid_integer_config(self):
        data = source(recommendation_clicks=10)
        candidate = policy_candidate(data)
        candidate['actions'] = [{'action_type': 'set_recommendation_policy', 'expected_version': 2,
            'policy': {'strategy_version': 'plan-strategy', 'group': 'treatment', 'config': deepcopy(DEFAULT_STRATEGIES['content-v1'])}}]
        validate_candidate(candidate, data, skill_versions=SKILLS)
        candidate['actions'][0]['expected_version'] = 3
        compiled=validate_candidate(candidate, data, skill_versions=SKILLS)
        self.assertEqual(compiled['actions'][0]['expected_version'],2)
        candidate['actions'][0]['expected_version'] = 2
        candidate['actions'][0]['policy']['config']['weights']['content'] = 1.1
        with self.assertRaisesRegex(InvalidPlan, 'integer_values'):
            validate_candidate(candidate, data, skill_versions=SKILLS)
        for field, values in [('weights', {key: 0 for key in DEFAULT_STRATEGIES['content-v1']['weights']}),
                              ('quotas', {key: 20 for key in DEFAULT_STRATEGIES['content-v1']['quotas']})]:
            candidate['actions'][0]['policy']['config'] = deepcopy(DEFAULT_STRATEGIES['content-v1'])
            candidate['actions'][0]['policy']['config'][field] = values
            with self.subTest(field=field), self.assertRaisesRegex(InvalidPlan, 'invalid_recommendation_configuration'):
                validate_candidate(candidate, data, skill_versions=SKILLS)

    def test_advertising_and_recommendation_screening_stay_independent_without_a_policy_gate(self):
        for recommendation_clicks in (0, 9):
            data = source(clicks=10, impressions=100, refunded_cents=1000, recommendation_clicks=recommendation_clicks)
            payload = _model_payload(data)
            self.assertTrue(payload['campaigns'][0]['screening']['budget_sample_mature'])
            self.assertFalse(payload['recommendation']['screening']['sample_mature'])
            self.assertEqual(payload['recommendation']['screening']['recommendation_clicks'], recommendation_clicks)
            validate_candidate(policy_candidate(data), data, skill_versions=SKILLS)
        data = source(recommendation_clicks=0)
        data['observation']['summary']['recommendation_clicks'] = 100
        self.assertFalse(_model_payload(data)['recommendation']['screening']['sample_mature'])

    def test_recommendation_facts_remain_available_without_forcing_a_specific_reference(self):
        data=source(clicks=0,impressions=0,recommendation_impressions=10,recommendation_clicks=10)
        original=deepcopy(data)
        payload=_model_payload(data)
        self.assertEqual(payload['recommendation']['allowed_actions'],['set_recommendation_policy'])
        self.assertFalse(payload['campaigns'][0]['screening']['budget_sample_mature'])
        self.assertFalse(payload['campaigns'][0]['screening']['creative_sample_mature'])
        self.assertEqual(payload['recommendation']['evidence_ids'],['fact-recommendation_clicks'])
        candidate=policy_candidate(data)
        compiled=validate_candidate(candidate,data,skill_versions=SKILLS)
        self.assertEqual(compiled['actions'][0]['action_type'],'set_recommendation_policy')
        self.assertEqual(compiled['planned_budget_cents'],100)
        self.assertEqual(data,original)
        candidate['diagnosis'].pop()
        validate_candidate(candidate,data,skill_versions=SKILLS)  # Relevant evidence selection is a model judgement, not a fixed click checklist.
        candidate['diagnosis'][0]['evidence_ids'].append('fact-recommendation_impressions')
        validate_candidate(candidate,data,skill_versions=SKILLS)  # Relevant evidence selection is a model judgement, not a fixed click checklist.

    def test_recommendation_sample_can_be_insufficient_when_advertising_clicks_are_mature(self):
        data=source(clicks=20,recommendation_clicks=0)
        candidate={'summary':'等待实际推荐结果。','diagnosis':[{'code':'insufficient_evidence',
            'explanation':'推荐样本不足，暂不调整推荐策略。','evidence_ids':['fact-recommendation_clicks']}],'actions':[]}
        validate_candidate(candidate,data,skill_versions=SKILLS)

    def test_confirmed_decline_can_share_uncertainty_without_forcing_every_fact_into_every_task(self):
        data=source(payment_failures=1,recommendation_clicks=0)
        uncertain={'code':'insufficient_evidence','explanation':'推荐样本不足，失败原因仍应保留判断。',
            'evidence_ids':['fact-payment_failures','fact-recommendation_clicks']}
        candidate={'summary':'等待新证据。','diagnosis':[uncertain],'actions':[]}
        compiled=validate_candidate(candidate,data,skill_versions=SKILLS)
        self.assertEqual(len(compiled['diagnosis']),1)
        self.assertEqual(compiled['actions'],[])
        missing=deepcopy(candidate);missing['diagnosis'][0]['evidence_ids']=['fact-recommendation_clicks']
        self.assertEqual(validate_candidate(missing,data,skill_versions=SKILLS)['evidence_ids'], ['fact-recommendation_clicks'])
        for code in ('payment_failures','other'):
            acknowledged={'code':code,'explanation':'Java已经确认渠道拒付，具体原因仍不确定。',
                'evidence_ids':['fact-payment_failures']}
            compiled=validate_candidate({**candidate,'diagnosis':[acknowledged,uncertain]},data,skill_versions=SKILLS)
            self.assertEqual(compiled['actions'],[])
            mature=source(payment_failures=1,recommendation_clicks=10)
            cause_unknown=deepcopy(uncertain)
            cause_unknown['explanation']='已确认失败的具体原因证据仍不充分。'
            for diagnoses in ([acknowledged,cause_unknown],[cause_unknown,acknowledged]):
                validate_candidate({**candidate,'diagnosis':diagnoses},mature,skill_versions=SKILLS)
        for value in (0,None):
            unconfirmed=source(payment_failures=value,cancelled_orders=1,recommendation_clicks=0)
            assessment=deepcopy(candidate)
            validate_candidate(assessment,unconfirmed,skill_versions=SKILLS)

    def test_merchant_skills_do_not_expand_the_shopping_skill_domain(self):
        self.assertEqual({s['skill_id'] for s in catalog()}, {'shopping_advice', 'support_policy', 'order_service'})
        self.assertEqual({s['skill_id'] for s in catalog(domain='merchant')}, set(SKILLS))
        for name in SKILLS:
            skill = load_skill(name, domain='merchant')
            self.assertTrue(all(key in skill for key in ('version', 'intents', 'knowledge', 'tools', 'output_contract', 'instructions', 'stop_conditions')))
            with self.assertRaises(ValueError):
                load_skill(name)
        with self.assertRaises(ValueError):
            load_skill('shopping_advice', domain='merchant')

    def test_skill_text_only_promises_mechanisms_the_code_still_has(self):
        # Skill text goes straight into the system prompt. When a mechanism is removed but its
        # description is left behind, the prompt contradicts itself and the model turns
        # conservative for a reason that looks like a model limitation but is stale text.
        from smartlect.tools import REGISTRY
        removed = ('copy_options', 'copy_variant', 'COPY_VARIANTS')
        for domain, names in (('shopping', {s['skill_id'] for s in catalog()}), ('merchant', set(SKILLS))):
            for name in names:
                skill = load_skill(name, domain=domain)
                text = json.dumps(skill, ensure_ascii=False)
                for mechanism in removed:
                    self.assertNotIn(mechanism, text, f'{name} still describes removed {mechanism}')
                if domain == 'shopping':
                    self.assertLessEqual(set(skill['tools']), set(REGISTRY), f'{name} declares an unknown tool')


class MerchantGraphTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, store, provider=None, mode='live', run=None, actor=ACTOR):
        return await run_merchant(actor=actor, run=run or invocation(), lease={'agent_run_id': 'run'}, store=store,
            provider=provider, ads_service=None, mode=mode, config={}, execute_plan=store.execute_plan)

    async def test_no_grant_waits_for_merchant_through_same_executor_and_does_not_approve(self):
        data = source(clicks=0, impressions=0)
        data['observation']['campaigns'][0]['status'] = 'DRAFT'
        data['observation']['campaigns'][0]['creatives'][0]['status'] = 'DRAFT'
        store = FakeStore(data)
        store.execute_status = 'WAIT_APPROVAL'
        result = await self.execute(store, mode='mock')
        self.assertEqual(result['state'], 'WAIT_USER')
        self.assertEqual(result['result']['wait_reason'], 'WAIT_MERCHANT')
        self.assertEqual(len(store.saved), 1)
        self.assertEqual(len(store.executions), 1)
        self.assertEqual(store.context['model_calls'], 0)
        self.assertNotIn('approved', store.saved[0])
        self.assertEqual(store.saved[0]['actor_id'], ACTOR.actor_id)

    async def test_live_graph_repairs_once_counts_provider_retries_and_keeps_fake_mode_explicit(self):
        store = FakeStore(source())
        provider = FakeProvider(store, ['invalid JSON', rule_candidate(store.source)], attempts_per_call=2)
        result = await self.execute(store, provider)
        self.assertEqual((provider.actual_attempts, store.context['model_calls'], store.context['plan_repairs']), (4, 4, 1))
        self.assertEqual(result['state'], 'WAIT_OUTCOME')
        self.assertEqual(result['result']['model_mode'], 'mock')
        self.assertEqual(len(store.saved), 1)
        self.assertTrue(all(option.get('tools') is None and option['max_attempts'] == 2 for option in provider.options))
        accepted = store.context['accepted_candidate']
        self.assertFalse(accepted['truncated'])
        self.assertEqual(json.loads(accepted['text']), rule_candidate(store.source))
        self.assertNotIn('observed_facts', json.loads(accepted['text'])['diagnosis'][0])
        self.assertIn('observed_facts', store.saved[0]['diagnosis'][0])
        self.assertEqual(_model_payload(store.source)['money'],
                         {'currency': 'CNY', 'amount_unit': 'minor_units', 'minor_units_per_major_unit': 100})

    async def test_accepted_model_trace_has_a_byte_limit_without_truncating_the_saved_plan(self):
        store = FakeStore(source())
        candidate = rule_candidate(store.source)
        candidate['summary'] = '界' * 1200
        candidate['diagnosis'] = [{'code': 'other', 'explanation': '界' * 600,
            'evidence_ids': [store.source['observation']['facts'][0]['evidence_id']]} for _ in range(6)]
        await self.execute(store, FakeProvider(store, [candidate]))
        trace = store.context['accepted_candidate']
        self.assertTrue(trace['truncated'])
        self.assertLessEqual(len(trace['text'].encode('utf-8')), 12000)
        self.assertEqual(len(trace['sha256']), 64)
        self.assertEqual(store.saved[0]['summary'], candidate['summary'])
        self.assertEqual(len(store.saved[0]['diagnosis']), 6)

    async def test_two_invalid_plans_fall_back_without_a_third_model_call(self):
        store = FakeStore(source())
        provider = FakeProvider(store, ['invalid JSON'], attempts_per_call=2)
        result = await self.execute(store, provider)
        self.assertEqual((len(provider.messages), provider.actual_attempts), (2, 4))
        self.assertEqual(result['result']['model_mode'], 'rule-fallback')
        self.assertEqual(len(store.context['plan_rejections']), 2)
        self.assertEqual(len(store.executions), 1)

    async def test_restart_keeps_spent_model_attempt_budget_and_recovers_saved_plan_without_model(self):
        store = FakeStore(source())
        provider = FakeProvider(store, [rule_candidate(store.source)], attempts_per_call=2)
        result = await self.execute(store, provider, run=invocation({'model_calls': 3, 'plan_repairs': 1}))
        self.assertEqual((provider.actual_attempts, store.context['model_calls']), (1, 4))
        self.assertEqual(result['result']['model_mode'], 'rule-fallback')
        store.source['current_plan'] = {'plan_id': 'saved-plan', 'version': 7, 'status': 'EXECUTING', 'spec': {
            'model_mode': 'rule-fallback', 'proposal_schema_version': 'merchant-proposal-v1',
            'actions': [{'action_type': 'replace_creative', 'campaign_id': 'campaign',
                         'creative_id': 'creative', 'expected_version': 2, 'copy_text': '推广：原已保存文案'}]}}
        original = deepcopy(store.source['current_plan'])
        saved_count = len(store.saved)
        before_calls = provider.actual_attempts
        with patch('smartlect.agents.merchant.validate_candidate', side_effect=AssertionError('Saved plans must not recompile')):
            await self.execute(store, provider, run=invocation(store.context))
        self.assertEqual(store.source['current_plan'], original)
        self.assertEqual(len(store.saved), saved_count)
        self.assertEqual(provider.actual_attempts, before_calls)
        self.assertEqual(store.executions[-1], ('merchant', 'saved-plan', 7))

    async def test_unchanged_watermark_never_creates_or_executes_another_plan(self):
        store = FakeStore(source())
        store.source['previous_plan'] = {'plan_id': 'prior', 'version': 1, 'spec': {'watermark': 'new-facts'}}
        result = await self.execute(store, mode='mock')
        self.assertEqual(result['result']['wait_reason'], 'no_new_observation')
        self.assertEqual((store.saved, store.executions), ([], []))
        store.source['observation']['watermark'] = 'newer-external-facts'
        result = await self.execute(store, mode='mock')
        self.assertEqual(len(store.saved), 1)
        self.assertEqual(store.saved[0]['parent_plan_version'], 1)
        self.assertEqual(store.saved[0]['watermark'], 'newer-external-facts')

    async def test_unapproved_experience_and_credentials_stay_out_of_model_context(self):
        data = source()
        data['approved_experiences'] = [{'experience_id': 'draft', 'status': 'DRAFT', 'summary': 'UNAPPROVED_DO_NOT_LOAD'},
            {'memory_id': 'approved', 'version': 2, 'status': 'APPROVED', 'content': '人工认可的候选经验'}]
        data['plan_meta']['objective'] = '评估并保护 synthetic-password-value'
        store = FakeStore(data)
        provider = FakeProvider(store, [rule_candidate(data)])
        with patch.dict('os.environ', SMARTLECT_MYSQL_PASSWORD='synthetic-password-value'):
            result = await self.execute(store, provider)
        content = canonical(provider.messages)
        self.assertNotIn('UNAPPROVED_DO_NOT_LOAD', content)
        self.assertNotIn('synthetic-password-value', content)
        self.assertIn('人工认可的候选经验', content)
        self.assertEqual(result['context']['model_input_experiences'], [{'memory_id':'approved','version':2}])
        self.assertEqual(result['result']['model_mode'], 'mock')

    async def test_oversized_model_context_falls_back_without_provider_attempt(self):
        data = source()
        data['approved_experiences'] = [{'status': 'APPROVED', 'summary': '非常长的经验' * 4000}]
        store = FakeStore(data)
        provider = FakeProvider(store, [rule_candidate(data)])
        result = await self.execute(store, provider)
        self.assertEqual(provider.actual_attempts, 0)
        self.assertEqual(result['result']['model_mode'], 'rule-fallback')
        self.assertEqual(store.context['fallback_reason'], 'merchant_context_limit')

    async def test_execution_timeout_remains_pending_and_does_not_invent_failure(self):
        store = FakeStore(source())

        async def pending(*args):
            await asyncio.sleep(.1)
            raise AssertionError('deadline should cancel waiting')

        store.execute_plan = pending
        result = await self.execute(store, mode='mock', run=invocation(deadline=datetime.now(timezone.utc) - timedelta(seconds=1)))
        self.assertEqual(result['state'], 'WAIT_OUTCOME')
        self.assertEqual(result['result']['execution_status'], 'UNKNOWN')
        self.assertEqual(len(store.saved), 1)

    async def test_wrong_actor_or_plan_scope_cannot_run_model_or_save_plan(self):
        store = FakeStore(source())
        with self.assertRaises(StateError):
            await self.execute(store, mode='mock', actor=ACTOR.model_copy(update={'subject_type': 'user'}))
        store.source['plan_meta']['scope'] = 'other-scope'
        with self.assertRaises(StateError):
            await self.execute(store, mode='mock')
        self.assertEqual(store.saved, [])

    async def test_trusted_product_subset_filters_unrelated_campaigns_before_planning(self):
        data = source(stock=0)
        unrelated = deepcopy(data['observation']['campaigns'][0])
        unrelated.update(campaign_id='unrelated-campaign', product_id='unrelated-product')
        data['observation']['campaigns'].append(unrelated)
        data['observation']['facts'].append({'evidence_id': 'other-stock', 'kind': 'inventory', 'metric': 'stock',
                                          'value': 0, 'campaign_id': 'unrelated-campaign'})
        store = FakeStore(data)
        provider = FakeProvider(store, [rule_candidate(data)])
        result = await self.execute(store, provider)
        self.assertNotIn('unrelated-product', canonical(provider.messages))
        self.assertNotIn('other-stock', store.saved[0]['evidence_ids'])
        self.assertTrue(all(a['campaign_id'] == 'campaign' for a in store.saved[0]['actions']))
        self.assertEqual(store.saved[0]['planned_budget_cents'], 100)


if __name__ == '__main__':
    unittest.main()
