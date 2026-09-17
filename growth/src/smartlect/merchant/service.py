"""Read Java before planning; approved plans use the same CPC executor as humans."""
import asyncio
import uuid

from pydantic import Field
from pymysql.err import OperationalError

from smartlect.agents.merchant import run_merchant
from smartlect.observability import gen_ai_span
from smartlect.commerce import PRODUCT_SNAPSHOT_BATCH_PATH, STOCK_BATCH_PATH, CommerceError
from smartlect.events import canonical
from smartlect.privacy import redact_text
from smartlect.state import StateError
from smartlect.tools import Arguments
from smartlect.ads.service import ProductId, Cents
from smartlect.merchant.store import action_priority, plan_batches, plan_action_request


class MerchantRunRequest(Arguments):
    request_id: str = Field(min_length=1,max_length=128)
    objective: str = Field(min_length=1,max_length=1000)
    mode: str = 'live'
    product_scope: list[ProductId] | None = Field(default=None,min_length=1,max_length=100)
    planned_budget_cents: Cents | None = None


class PlanExecuteRequest(Arguments):
    expected_version: int = Field(ge=1,le=9223372036854775807)


class ExperienceApproveRequest(PlanExecuteRequest):
    reviewed_content: str | None = Field(default=None,min_length=1,max_length=2000)


class ScopeSelectRequest(Arguments):
    execution_scope_id: str = Field(min_length=1,max_length=128)



class MerchantService:
    def __init__(self,store,ads_service,provider,config):
        self.store,self.ads,self.provider,self.config=store,ads_service,provider,config

    async def prepare_run(self,actor,request):
        request={**request,'objective':redact_text(request['objective'])}
        mode=request.get('mode','live')
        if mode not in {'live','rule','mock'}: raise StateError('invalid_merchant_mode',422)
        if mode=='live' and self.config.get('SMARTLECT_MODEL_MODE')!='live': raise StateError('live_model_not_configured',503)
        if mode=='mock' and self.config.get('SMARTLECT_MODEL_MODE')!='mock': raise StateError('mock_not_configured',422)
        previous=await asyncio.to_thread(self.store.request_replay,actor,request)
        if previous:
            if previous['state'] in {'CREATED','RUNNING'}:
                try:
                    lease=await asyncio.to_thread(self.store.claim_run,actor,previous['agent_run_id'],owner='merchant:'+uuid.uuid4().hex,ttl_seconds=30)
                except StateError as error:
                    if error.code!='conversation_busy': raise
                    return previous,None
                return await asyncio.to_thread(self.store.get_run,actor,previous['agent_run_id']),lease
            return previous,None
        ads=await asyncio.to_thread(self.store.snapshot,actor)
        campaigns=[c for c in ads['campaigns'] if c['owner_id']==actor.actor_id]
        if not campaigns: raise StateError('merchant_campaign_draft_required',409)
        # Bound the Java batch, without holding Growth locks during network calls.
        targets={(c['product_id'],c['sku_key']):{'product_id':c['product_id'],'sku_key':c['sku_key']} for c in campaigns}
        for start in range(0,len(targets),8):
            await asyncio.gather(*(self.ads.observe(actor,t) for t in list(targets.values())[start:start+8]))
        observation=await asyncio.to_thread(self.store.observation,actor)
        state=await asyncio.to_thread(self.store.merchant_snapshot,actor)
        unresolved=next((p for p in state['plans'] if p['status']=='EXECUTING'),None)
        if unresolved:
            return {'state':'WAIT_OUTCOME','plan_recovery_required':True,'latest_plan':unresolved},None
        latest=state['plans'][0] if state['plans'] else None
        if latest and latest['observation_id']==observation['observation_id']:
            return {'state':'WAIT_OUTCOME','unchanged_observation':True,'latest_plan':latest},None
        conversation=await asyncio.to_thread(self.store.create_conversation,actor,identity_key='merchant-operator-v1')
        actual_mode='rule-fallback' if mode=='rule' else mode
        run=await asyncio.to_thread(self.store.create_run,actor,conversation['conversation_id'],request['request_id'],canonical(request),
                                  parent_run_id=latest['agent_run_id'] if latest else None,model_mode=actual_mode)
        lease=await asyncio.to_thread(self.store.claim_run,actor,run['agent_run_id'],owner='merchant:'+uuid.uuid4().hex,ttl_seconds=30)
        try:
            await asyncio.to_thread(self.store.prepare_run_context,actor,run,observation,request)
            run=await asyncio.to_thread(self.store.get_run,actor,run['agent_run_id'])
        except StateError as error:
            await asyncio.to_thread(self.store.finish_run,lease,state='FAILED',result={'error':error.code})
            raise
        return run,lease

    async def run(self,actor,run,lease):
        async def heartbeat():
            while True:
                await asyncio.sleep(10)
                await asyncio.to_thread(self.store.renew_lease,lease,ttl_seconds=30)
        heartbeat_task=asyncio.create_task(heartbeat())
        try:
            with gen_ai_span(
                "invoke_agent merchant",
                kind="invoke_agent",
                attributes={
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": "merchant",
                    "session.id": run.get("conversation_id"),
                    "agent_run_id": run.get("agent_run_id"),
                },
            ):
                await run_merchant(actor=actor,run=run,lease=lease,store=self.store,provider=self.provider,
                                   ads_service=self.ads,mode=run['model_mode'],config=self.config,execute_plan=self.execute_plan)
        except asyncio.CancelledError:
            raise  # Durable model-attempt counters and any saved plan survive shutdown.
        except Exception as error:
            try:
                await asyncio.to_thread(self.store.finish_run,lease,state='FAILED',result={
                    'error':getattr(error,'code',type(error).__name__),'plan_recovery':'query_saved_plan_before_retry'})
            except (StateError,OperationalError):
                pass  # A lost lease cannot rewrite its successor; GET enforces the original deadline.
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task,return_exceptions=True)


    async def execute_plan(self,actor,plan_id,expected_version):
        recovered=await asyncio.to_thread(self.store.recover_completed_plan,actor,plan_id,expected_version)
        if recovered is not None: return recovered
        claimed=await asyncio.to_thread(self.store.claim_plan,actor,plan_id,expected_version)
        plan,token=claimed['plan'],claimed['token']
        if token is None: return plan
        receipts=[];applied=0
        for index,batch in enumerate(plan_batches(plan)):
            request=plan_action_request(plan,index,batch)
            identifier=request['action_id']
            try:
                result=await self.ads.execute_action(actor,request)
                receipts.append({'batch':index,'command_status':'business_completed','receipt':result})
                applied+=len(batch)
            except (StateError,CommerceError,OperationalError) as error:
                receipts.append({'batch':index,'command_status':'rejected' if isinstance(error,StateError) else 'unknown',
                                 'action_id':identifier,'reason':getattr(error,'code','commerce_outcome_unknown')})
                status=('PARTIALLY_APPLIED' if applied else 'FAILED') if isinstance(error,StateError) else 'EXECUTING'
                return await asyncio.to_thread(self.store.finish_plan,actor,plan_id,token,status,receipts)
        return await asyncio.to_thread(self.store.finish_plan,actor,plan_id,token,'WAIT_OBSERVATION',receipts)

    async def catalog(self,actor):
        scope=await asyncio.to_thread(self.store.product_scope,actor)
        ids=await self.ads.commerce.request('product','/internal/product/listOnSaleProductIds')
        if not isinstance(ids,list): raise CommerceError('commerce_outcome_unknown')
        ids=[identifier for identifier in ids if identifier not in scope['exclude'] and (scope['include'] is None or identifier in scope['include'])][:100]
        if not ids: return {'items':[],'observed_at':None}
        snapshot=await self.ads.commerce.request('product',PRODUCT_SNAPSHOT_BATCH_PATH,data={'productIds':ids})
        if not isinstance(snapshot,dict) or not isinstance(snapshot.get('skus'),list): raise CommerceError('commerce_outcome_unknown')
        names={r['productId']:r.get('productName',r['productId']) for r in snapshot.get('products',[])}
        skus=snapshot['skus']
        stocks=await self.ads.commerce.request('stock',STOCK_BATCH_PATH,data=[{'productId':r['productId'],'propertyValueIdHash':r['propertyValueIdHash']} for r in skus])
        stock_map={(r['productId'],r['propertyValueIdHash']):r.get('stock') for r in stocks} if isinstance(stocks,list) else {}
        from smartlect.ads.analytics import to_cents
        from smartlect.attribution import iso
        items=[{'product_id':r['productId'],'sku_key':r['propertyValueIdHash'],'product_name':names[r['productId']],
                'sku_name':r.get('propertyValueIds',r['propertyValueIdHash']),'price_cents':to_cents(str(r['price'])),
                'stock':stock_map.get((r['productId'],r['propertyValueIdHash']))} for r in skus]
        return {'items':items,'observed_at':iso(self.store.clock()),'stock_display_only':True}
