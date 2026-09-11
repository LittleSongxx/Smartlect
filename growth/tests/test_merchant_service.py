"""Controller scheduling and uncertain execution without network or databases."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from pymysql.err import OperationalError

from smartlect.merchant.service import MerchantService
from smartlect.state import StateError


class MerchantServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(actor_id='owner')
        self.store = Mock()
        self.ads = SimpleNamespace(observe=AsyncMock(), execute_action=AsyncMock())
        self.service = MerchantService(self.store,self.ads,Mock(),{'SMARTLECT_MODEL_MODE':'live'})
        self.request = {'request_id':'request','objective':'依据真实观测','mode':'live'}
        self.store.request_replay.return_value = None
        self.store.snapshot.return_value = {'campaigns':[{'owner_id':'owner','product_id':'p','sku_key':'s'}]}
        self.store.observation.return_value = {'observation_id':'observation'}
        self.store.merchant_snapshot.return_value = {'plans':[]}
        self.store.create_conversation.return_value = {'conversation_id':'conversation'}
        self.store.create_run.return_value = {'agent_run_id':'run'}
        self.store.claim_run.return_value = {'token':'lease'}

    async def test_expired_lease_reclaims_original_run_without_resetting_attempts(self):
        original={'agent_run_id':'run','state':'RUNNING','context':{'model_calls':3},'deadline':'original-deadline'}
        self.store.request_replay.return_value = original
        self.store.get_run.return_value = original
        run,lease=await self.service.prepare_run(self.actor,self.request)
        self.assertEqual(run,original)
        self.assertEqual(lease,{'token':'lease'})
        self.assertEqual(self.store.claim_run.call_args.kwargs['ttl_seconds'],30)
        self.store.create_run.assert_not_called()
        self.ads.observe.assert_not_awaited()

    async def test_context_rejection_releases_claimed_run_instead_of_holding_lease(self):
        self.store.prepare_run_context.side_effect=StateError('product_outside_scope',403)
        with self.assertRaisesRegex(StateError,'product_outside_scope'):
            await self.service.prepare_run(self.actor,self.request)
        self.store.finish_run.assert_called_once_with({'token':'lease'},state='FAILED',result={'error':'product_outside_scope'})

    async def test_new_observation_cannot_start_another_plan_over_unknown_execution(self):
        pending={'plan_id':'pending','status':'EXECUTING'}
        self.store.merchant_snapshot.return_value={'plans':[pending]}
        result,lease=await self.service.prepare_run(self.actor,self.request)
        self.assertTrue(result['plan_recovery_required'])
        self.assertEqual(result['latest_plan'],pending)
        self.assertIsNone(lease)
        self.store.create_run.assert_not_called()

    async def test_committed_results_recover_before_a_new_grant_is_checked(self):
        recovered={'plan_id':'plan','status':'WAIT_OBSERVATION','grant_id':'revoked-original'}
        self.store.recover_completed_plan.return_value=recovered
        self.assertEqual(await self.service.execute_plan(self.actor,'plan',1),recovered)
        self.store.claim_plan.assert_not_called()
        self.ads.execute_action.assert_not_awaited()

    async def test_unknown_database_outcome_stays_recoverable_with_original_action_id(self):
        plan={'plan_id':'plan','version':1,'agent_run_id':'run','grant_id':'grant',
              'spec':{'round_id':'round','evidence_ids':[],
                      'actions':[{'action_type':'set_budget','campaign_id':'campaign','expected_version':1,'budget_cents':90}]}}
        self.store.recover_completed_plan.return_value=None
        self.store.claim_plan.return_value={'plan':plan,'token':'plan-lease'}
        self.ads.execute_action.side_effect=OperationalError(2013,'lost response after commit')
        self.store.finish_plan.return_value={'plan_id':'plan','status':'EXECUTING'}
        result=await self.service.execute_plan(self.actor,'plan',1)
        self.assertEqual(result['status'],'EXECUTING')
        args=self.store.finish_plan.call_args.args
        self.assertEqual(args[3],'EXECUTING')
        self.assertEqual(args[4][0]['command_status'],'unknown')
        self.assertEqual(args[4][0]['action_id'],self.ads.execute_action.call_args.args[1]['action_id'])


if __name__=='__main__':
    unittest.main()
