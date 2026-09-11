"""Owned Growth reset boundaries on real MySQL; Java manifest/result inputs are synthetic fixtures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
import unittest
import uuid

from smartlect.attribution import AttributionStore
from smartlect.auth import ActorContext
from smartlect.events import canonical
from smartlect.state import StateError
import test_ledger_mysql
from test_events import outcome


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS')=='1','requires dedicated MySQL')
class ScopeResetMySQLTests(unittest.TestCase):
    setUpClass=classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass=classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    def setUp(self):
        self.store=AttributionStore(self.connect)
        self.run='reset-run-'+uuid.uuid4().hex;self.request=uuid.uuid4().hex
        self.manifests=[self.manifest(self.run,branch) for branch in ('a','b')]
        self.visitor=uuid.uuid4().hex
        for index,m in enumerate(self.manifests):
            self.store.register_scope(m['executionScopeId'],scenario_run_id=self.run,branch_id=m['branchId'],
                users=[u['userId'] for u in m['users']],products=m['products'],visitors=[self.visitor] if index==0 else [])
        self.user=ActorContext(subject_type='user',actor_id=self.manifests[0]['users'][0]['userId'],session_id=uuid.uuid4().hex,
            execution_scope_id=self.manifests[0]['executionScopeId'],permissions=('shopping:read','orders:read','orders:write'))

    @staticmethod
    def manifest(run,branch):
        scope='reset-scope-'+uuid.uuid4().hex;product='p-'+uuid.uuid4().hex
        return {'executionScopeId':scope,'scenarioRunId':run,'branchId':branch,'manifestVersion':'demo-scenario-v1',
            'initialStock':5,'users':[{'userId':'u-'+uuid.uuid4().hex,'addressId':'fixture-address','index':0}],
            'products':[product],'skus':[{'productId':product,'propertyValueIdHash':'standard','initialStock':5}]}

    def result(self):
        replacement='replacement-'+uuid.uuid4().hex
        return {'resetRequestId':self.request,'retiredRunId':self.run,'retiredScopeIds':[m['executionScopeId'] for m in self.manifests],
            'replacementRunId':replacement,'replacementManifests':[self.manifest(replacement,b) for b in ('a','b')],
            'watermarkHash':'a'*64,'watermark':{'outbox':[]},'mode':'retire_and_replace'}

    def test_missing_branch_resource_mismatch_and_unsettled_work_do_not_create_guard(self):
        with self.assertRaisesRegex(StateError,'reset_scope_ownership_conflict'):
            self.store.begin_scope_reset(self.run,self.request,self.manifests[:1])
        changed=deepcopy(self.manifests);changed[0]['products']=['unowned-product']
        with self.assertRaisesRegex(StateError,'reset_resource_ownership_conflict'):
            self.store.begin_scope_reset(self.run,self.request,changed)
        conversation=self.store.create_conversation(self.user)
        run=self.store.create_run(self.user,conversation['conversation_id'],uuid.uuid4().hex,'owned synthetic reset blocker')
        with self.assertRaisesRegex(StateError,'scope_reset_busy'):
            self.store.begin_scope_reset(self.run,self.request,self.manifests)
        self.assertIsNone(self.store.scope_reset_status(self.run))
        lease=self.store.claim_run(self.user,run['agent_run_id'],owner='reset-contract')
        proposal=self.store.create_proposal(lease,action_type='cancel',parameters={'orderId':'synthetic-order'},
            expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
        self.store.finish_run(lease,state='WAIT_USER',result={})
        self.store.confirm_proposal(self.user,proposal['proposal_id'],proposal['version'],approved=True)
        with self.assertRaisesRegex(StateError,'scope_reset_busy'):
            self.store.begin_scope_reset(self.run,self.request,self.manifests)
        self.assertIsNone(self.store.scope_reset_status(self.run))

    def test_unstarted_guard_can_only_be_aborted_by_its_owner_and_called_guard_is_preserved(self):
        self.store.begin_scope_reset(self.run,self.request,self.manifests)
        with self.assertRaisesRegex(StateError,'execution_scope_quiescing'):self.store.assert_scope_writable(self.user)
        with self.assertRaisesRegex(StateError,'scope_reset_conflict'):self.store.abort_scope_reset(self.run,'another-request')
        self.store.abort_scope_reset(self.run,self.request);self.store.assert_scope_writable(self.user)
        self.store.begin_scope_reset(self.run,self.request,self.manifests)
        self.store.mark_scope_reset_call(self.run,self.request,'a'*64)
        restarted=AttributionStore(self.connect)
        self.assertEqual(restarted.scope_reset_status(self.run)['expected_watermark_hash'],'a'*64)
        with self.assertRaisesRegex(StateError,'scope_reset_outcome_requires_recovery'):restarted.abort_scope_reset(self.run,self.request)
        with self.assertRaisesRegex(StateError,'scope_reset_conflict'):restarted.mark_scope_reset_call(self.run,self.request,'b'*64)

    def test_retirement_keeps_old_event_and_identity_mappings_and_registers_fresh_resources_once(self):
        event=outcome('PAYMENT',uuid.uuid4().hex,uuid.uuid4().hex,userId=self.user.actor_id,
            productId=self.manifests[0]['products'][0],skuKey='standard',orderId='order-'+uuid.uuid4().hex)
        with self.assertRaisesRegex(StateError,'reset_ledger_watermark_pending'):
            self.store.begin_scope_reset(self.run,self.request,self.manifests,[event['eventId']])
        self.assertIsNone(self.store.scope_reset_status(self.run))
        batch=canonical({'schema_version':2,'events':[event]}).encode();self.ledger.ingest(batch)
        with self.connect() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT raw_json,fingerprint FROM commerce_event WHERE event_id=%s',(event['eventId'],));before=cursor.fetchone()
            cursor.execute('INSERT INTO merchant_scope_access VALUES (%s,%s,%s)',('reset-owner',self.user.execution_scope_id,'owned branch'))
            connection.commit()
        self.store.begin_scope_reset(self.run,self.request,self.manifests,[event['eventId']])
        self.store.mark_scope_reset_call(self.run,self.request,'a'*64,[event['eventId']])
        result=self.result();final=self.store.finish_scope_reset(self.run,self.request,result)
        self.assertEqual(final['state'],'RETIRED');self.assertEqual(self.store.finish_scope_reset(self.run,self.request,result),final)
        with self.assertRaisesRegex(StateError,'execution_scope_retired'):self.store.assert_scope_writable(self.user)
        resolved=self.store.resolve_actor(self.user.model_copy(update={'execution_scope_id':'store'}))
        self.assertEqual(resolved.execution_scope_id,self.user.execution_scope_id)
        visitor=self.user.model_copy(update={'subject_type':'visitor','actor_id':self.visitor,'execution_scope_id':'store'})
        self.assertEqual(self.store.resolve_actor(visitor).execution_scope_id,self.user.execution_scope_id)
        newcomer=self.user.model_copy(update={'actor_id':result['replacementManifests'][0]['users'][0]['userId'],'execution_scope_id':'store'})
        newcomer=self.store.resolve_actor(newcomer);self.store.assert_scope_writable(newcomer)
        self.assertEqual(newcomer.execution_scope_id,result['replacementManifests'][0]['executionScopeId'])
        self.ledger.ingest(batch)
        with self.connect() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT raw_json,fingerprint FROM commerce_event WHERE event_id=%s',(event['eventId'],));self.assertEqual(cursor.fetchone(),before)
            cursor.execute('SELECT execution_scope_id FROM commerce_attribution WHERE event_id=%s',(event['eventId'],))
            self.assertEqual(cursor.fetchone()['execution_scope_id'],self.user.execution_scope_id)
            cursor.execute('SELECT COUNT(*) AS n FROM execution_scope WHERE scenario_run_id=%s',(result['replacementRunId'],));self.assertEqual(cursor.fetchone()['n'],2)
            cursor.execute('SELECT COUNT(*) AS n FROM merchant_scope_access WHERE actor_id=%s AND execution_scope_id=%s',('reset-owner',newcomer.execution_scope_id))
            self.assertEqual(cursor.fetchone()['n'],1)


if __name__=='__main__':unittest.main()
