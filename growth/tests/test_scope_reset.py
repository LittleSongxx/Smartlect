"""Reset orchestration and HTTP admission checks without Java, MySQL, or model calls."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import httpx

from smartlect.auth import IdentityBridge
from smartlect.config import Settings
from smartlect.state import StateError

SCRIPTS=Path(__file__).resolve().parents[2]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('smartlect_reset_cli',SCRIPTS/'reset_demo.py')
reset_cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(reset_cli)


class ResetCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.guard=None;self.saved=[];self.writes=[];self.receipt=None;self.timeout=False;self.inspect_count=0;self.block_second=False
        self.inspection={'branches':[{'executionScopeId':'old'}],'scopeIds':['old'],'watermark':{'outbox':[]},'watermarkHash':'a'*64,'ready':True}
        self.result={'resetRequestId':'stable','retiredRunId':'run','retiredScopeIds':['old'],'replacementRunId':'replacement',
                     'replacementManifests':[],'watermark':{'outbox':[]},'watermarkHash':'a'*64,'mode':'retire_and_replace'}
        self.store=Mock()
        self.store.scope_reset_status.side_effect=lambda run:deepcopy(self.guard)
        self.store.inspect_scope_reset.return_value={'ready':True}
        def begin(run,request,manifests,events):
            if not self.guard:self.guard={'reset_request_id':request,'state':'QUIESCING','java_call_started':False}
            return deepcopy(self.guard)
        def mark(run,request,watermark,events):
            self.guard.update(java_call_started=True,expected_watermark_hash=watermark)
            return deepcopy(self.guard)
        def finish(run,request,result):
            self.guard.update(state='RETIRED',result=deepcopy(result));return deepcopy(self.guard)
        self.store.begin_scope_reset.side_effect=begin;self.store.mark_scope_reset_call.side_effect=mark;self.store.finish_scope_reset.side_effect=finish
        self.store.abort_scope_reset.side_effect=lambda *args:setattr(self,'guard',None)

    def java(self,path,data):
        if path=='/reset-result':return deepcopy(self.receipt)
        if path=='/inspect-run':
            self.inspect_count+=1
            return {**deepcopy(self.inspection),'ready':self.inspection['ready'] and not(self.block_second and self.inspect_count==2)}
        self.assertEqual(path,'/reset');self.writes.append(deepcopy(data))
        if self.timeout:raise TimeoutError('synthetic timeout')
        self.receipt=deepcopy(self.result);return deepcopy(self.receipt)

    def execute(self,state,request=None):
        return reset_cli.coordinate('run',request,self.store,self.java,state,lambda:self.saved.append(deepcopy(state)))

    def test_unknown_call_keeps_guard_and_file_loss_retries_exact_request_and_hash(self):
        self.timeout=True
        with self.assertRaises(TimeoutError):self.execute({},'stable')
        self.assertTrue(self.guard['java_call_started']);self.store.abort_scope_reset.assert_not_called()
        self.timeout=False;self.inspection['watermarkHash']='b'*64
        result=self.execute({})
        self.assertEqual(result['status'],'PASSED');self.assertEqual(self.writes[0],self.writes[1])
        self.assertEqual(self.writes[1]['expectedWatermarkHash'],'a'*64)
        self.assertEqual(self.store.mark_scope_reset_call.call_count,1)

    def test_java_receipt_recovers_without_reissuing_reset_even_when_local_file_is_lost(self):
        self.guard={'state':'QUIESCING','reset_request_id':'stable','java_call_started':True,'expected_watermark_hash':'a'*64}
        self.receipt=deepcopy(self.result);self.inspection['ready']=False
        result=self.execute({})
        self.assertEqual(result['result'],self.result);self.assertEqual(self.writes,[])
        self.store.abort_scope_reset.assert_not_called()

    def test_conflict_before_java_releases_only_the_accepted_request_guard(self):
        self.block_second=True;state={}
        with self.assertRaisesRegex(StateError,'java_scenario_not_quiescent'):self.execute(state,'stable')
        self.assertIsNone(self.guard);self.assertEqual(state['phase'],'ABORTED_BEFORE_JAVA');self.assertEqual(self.writes,[])
        self.guard={'state':'QUIESCING','reset_request_id':'owner','java_call_started':False}
        self.store.abort_scope_reset.reset_mock()
        with self.assertRaisesRegex(StateError,'scope_reset_conflict'):self.execute({},'another')
        self.store.abort_scope_reset.assert_not_called();self.assertEqual(self.guard['reset_request_id'],'owner')


class ScopeResetHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_retired_business_writes_and_new_recommendations_are_blocked_but_history_and_csrf_scope_exit_work(self):
        from smartlect.app import create_app
        origin='http://smartlect.test'; selected=['retired']
        config={'SMARTLECT_USER_PORT':'18105','SMARTLECT_INTERNAL_TOKEN':'synthetic-only','SMARTLECT_VISITOR_SECRET':'v'*48,'SMARTLECT_ALLOWED_ORIGINS':origin}
        def identity(request):
            realm=request.content.decode();merchant='merchant' in realm
            return httpx.Response(200,json={'status':'success','data':{'subjectType':'merchant' if merchant else 'user',
                'actorId':'owner' if merchant else 'user','sessionId':'session','permissions':['admin:legacy'] if merchant else ['shopping:read']}})
        bridge=IdentityBridge(config,transport=httpx.MockTransport(identity))
        attribution=SimpleNamespace(resolve_actor=lambda actor:actor.model_copy(update={'execution_scope_id':'retired'}),
            assert_scope_writable=Mock(side_effect=StateError('execution_scope_retired',410)))
        def select(actor,scope):selected[0]=scope;return actor.model_copy(update={'execution_scope_id':scope})
        merchant=SimpleNamespace(store=SimpleNamespace(selected_actor=lambda actor:actor.model_copy(update={'execution_scope_id':selected[0]}),select_scope=Mock(side_effect=select)))
        ads=SimpleNamespace(store=SimpleNamespace(snapshot=Mock(return_value={'history':'retained'})),create_campaign=AsyncMock())
        recommendations=SimpleNamespace(recommend=AsyncMock())
        app=create_app(Settings(),config=config,store=SimpleNamespace(connect=lambda:None),identity=bridge,
                       attribution=attribution,ads=ads,merchant=merchant,recommendations=recommendations)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url=origin) as client:
            client.cookies.set('adminToken','synthetic-admin');client.cookies.set('token','synthetic-user')
            session=(await client.get('/admin-api/assistant/session')).json()
            headers={'Origin':origin,'X-CSRF-Token':session['csrf_token']}
            body={'campaign_id':'c','name':'retired','product_id':'p','sku_key':'s','budget_cents':10,'cpc_cents':1}
            self.assertEqual((await client.post('/admin-api/assistant/ads/campaigns',json=body,headers=headers)).status_code,410)
            ads.create_campaign.assert_not_awaited()
            self.assertEqual((await client.get('/admin-api/assistant/ads')).json(),{'history':'retained'})
            self.assertEqual((await client.get('/api/assistant/recommendations')).status_code,410)
            recommendations.recommend.assert_not_awaited()
            self.assertEqual((await client.post('/admin-api/assistant/scopes/select',json={'execution_scope_id':'store'})).status_code,403)
            merchant.store.select_scope.assert_not_called()
            switched=await client.post('/admin-api/assistant/scopes/select',json={'execution_scope_id':'store'},headers=headers)
            self.assertEqual(switched.status_code,200);self.assertEqual(switched.json()['actor']['execution_scope_id'],'store')
            self.assertNotEqual(switched.json()['csrf_token'],session['csrf_token'])


if __name__=='__main__':unittest.main()
