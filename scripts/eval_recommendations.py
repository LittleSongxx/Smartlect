"""Fixed repeated recommendation checks through Java/HTTP and the existing semantic callback seam."""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import time
import traceback
import unicodedata
import uuid

from check_f3 import json_value
from demo import cents
from eval_rag import freeze_bindings
from runtime import ROOT
from scenario_client import ScenarioClient, now
from smartlect.auth import ActorContext
from smartlect.commerce import AsyncCommerceClient
from smartlect.events import canonical
from smartlect.privacy import redact_text
from smartlect.provider import Provider
from smartlect.recommendation.service import RecommendationRequest, RecommendationService, constraints, validate_rerank
from smartlect.recommendation.store import StrategyStore, strategy_config

MANIFEST=ROOT/'evals/recommendations-manifest.json'


def require(condition, reason):
    if not condition: raise AssertionError(reason)


def folded(value):return unicodedata.normalize('NFKC',value).casefold()


def sku_key(row):return row['productId']+':'+row['propertyValueIdHash']


def violations(items, catalog, stocks, allowed_products, limits):
    source={sku_key(row):row for row in catalog['skus']};errors=[];seen=set()
    for card in items:
        key=sku_key(card)
        if key in seen:errors.append('duplicate_sku')
        seen.add(key)
        row=source.get(key)
        if row is None or card['productId'] not in allowed_products:errors.append('unknown_or_foreign_sku');continue
        if card['sku_key']!=key or card['propertyValueIds']!=row['propertyValueIds']:errors.append('sku_identity_mismatch')
        if card['price_cents']!=cents(row['price']):errors.append('java_price_mismatch')
        if stocks.get(key,0)<limits['quantity'] or card['stock']!=stocks[key]:errors.append('java_stock_mismatch')
        if card['price_cents']<limits['min_price_cents'] or limits['max_price_cents'] is not None and card['price_cents']>limits['max_price_cents']:errors.append('budget_violation')
        text=folded(card['productName']+' '+card['specification'])
        if any(folded(term) in text for term in limits['excluded_terms']):errors.append('avoid_violation')
        if any(folded(term) not in text for term in limits['required_terms']):errors.append('required_term_violation')
        if card['productId'] in limits['excluded_product_ids'] or key in limits['excluded_sku_keys']:errors.append('excluded_identity')
        if limits['category_id'] is not None and card['categoryId']!=limits['category_id']:errors.append('category_violation')
    return errors


def list_metrics(items, likes, top_k):
    selected=items[:top_k];size=len(selected);counts=Counter(card['categoryId'] for card in selected)
    return {'returned_count':len(items),'evaluated_top_k':size,'unique_products_at_k':len({c['productId'] for c in selected}),
        'unique_categories_at_k':len(counts),
        'category_pair_diversity_at_k':1-sum(n*(n-1) for n in counts.values())/(size*(size-1)) if size>1 else None,
        'explicit_terms_match_at_1':sum(folded(term) in folded(selected[0]['productName']+' '+selected[0]['specification'])
                                      for term in likes)/len(likes) if selected and likes else None}


def stocks(client):
    rows=client.java.request('stock','/internal/stock/getBatch',data=[{'productId':s['productId'],
        'propertyValueIdHash':s['propertyValueIdHash']} for s in client.manifest['skus']])
    return {sku_key(row):row['stock'] for row in rows}


def switch_user(client,index):
    session=client.java.request('admin','/internal/demo/scenario/session',data={'executionScopeId':client.scope,
        'userIndex':index,'password':client.config['SMARTLECT_DEMO_PASSWORD']})
    client.user.cookies.clear();client.user.cookies.set('token',session['token'])
    response=client.user.get('/api/assistant/session');response.raise_for_status();identity=response.json()
    actor=identity['actor']
    require(actor['actor_id']==client.manifest['users'][index]['userId'] and actor['execution_scope_id']==client.scope,'java_identity_scope_mismatch')
    client.session=session;client.actor=actor;client.uheaders={'Origin':client.base,'X-CSRF-Token':identity['csrf_token']}
    client.evidence.setdefault('identity_checks',[]).append({'user_index':index,'actor_id':actor['actor_id'],'execution_scope_id':client.scope})
    client.save()


def http_recommend(client,params):
    started=time.monotonic();result=client.request('recommendations',params=params)
    return {'transport':'public_authenticated_http','request':params,'latency_ms':round((time.monotonic()-started)*1000,3),'result':result}


def configure_all(client,plan):
    client.stage('Record fixed user assignments, then explicitly approve the same content policy for both groups')
    assignments={}
    for profile in plan['profiles']:
        switch_user(client,profile['user_index'])
        result=http_recommend(client,plan['request'])
        assignments[profile['profile_id']]=result['result']['assignment']
    client.evidence['assignments_before_policy']=assignments
    review=client.request('ads',merchant=True)
    require(not review['campaigns'] and review['account'] is None,'fresh_recommendation_scope_required')
    grant_id=uuid.uuid4().hex;policy_plan=uuid.uuid4().hex
    grant=client.request('ads/grants',{'grant_id':grant_id,'initial_plan_id':policy_plan,'initial_plan_version':1,
        'expected_campaign_versions':{},'expected_creative_versions':{},'envelope':{
            'objective':'冻结推荐功能评测：统一两组配置，保留既有分桶，不投放广告或花费预算。',
            'product_scope':client.manifest['products'],'allowed_action_types':['set_recommendation_policy'],
            'budget_cap_cents':0,'max_budget_change_cents':0,
            'valid_until':(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),
            'recommendation_policy_range':{'rankings':['content'],'groups':['all'],'max_weight':20,'max_quota':20}}},merchant=True)
    review=client.request('ads',merchant=True)
    action_id=uuid.uuid4().hex
    applied=client.request('ads/actions',{'action_id':action_id,'idempotency_key':'recommendation-eval:'+action_id,
        'grant_id':grant_id,'plan_id':policy_plan,'plan_version':1,'reason_code':'frozen_recommendation_evaluation',
        'evidence_ids':[hashlib.sha256(canonical(client.manifest).encode()).hexdigest()],
        'actions':[{'action_type':'set_recommendation_policy','expected_version':review['recommendation']['revision'],
            'policy':{'group':'all','strategy_version':plan['strategy_version'],'config':plan['strategy_config']}}]},merchant=True)
    require(applied['status']=='APPLIED','approved_strategy_not_applied')
    client.evidence['policy']={'grant':grant,'action':applied,'group_selection':'all_without_bucket_resampling'};client.save()
    return assignments


async def semantic_compare(client,plan,profile,preferences,record,total_attempts):
    actor=ActorContext.model_validate_json(canonical(client.actor))
    service=RecommendationService(AsyncCommerceClient(client.config),StrategyStore(client.store.connect))
    provider=Provider(client.config);policy=plan['semantic'];attempts=[];callback_record={}
    record.update(transport='direct_existing_RecommendationService_with_Java_HTTP',callback=callback_record,model_attempts=attempts,actual_provider_attempts=0)
    async def before_attempt():
        require(record['actual_provider_attempts']<policy['max_attempts_per_call'] and total_attempts[0]<policy['max_attempts_per_run'],'provider_attempt_budget_exhausted')
        record['actual_provider_attempts']+=1;total_attempts[0]+=1;client.save()
    async def trace(value):attempts.append(value);client.save()
    async def rerank(payload):
        callback_record.update(input=deepcopy(payload),input_sha256=hashlib.sha256(canonical(payload).encode()).hexdigest(),started_at=now())
        client.save()
        require(len(payload['candidates'])<=12 and len(canonical(payload).encode())<=policy['max_context_bytes'],'rerank_context_limit')
        response=await provider.chat([{'role':'system','content':policy['system_prompt']},{'role':'user','content':canonical(payload)}],
            response_format={'type':'json_object'},before_attempt=before_attempt,on_trace=trace,
            max_attempts=policy['max_attempts_per_call'],max_tokens=policy['max_completion_tokens'],
            prompt_version=policy['prompt_version'],schema_version=policy['schema_version'],skill_versions={})
        callback_record.update(raw_model_message=response['message'],response_metadata=response['metadata'],completed_at=now())
        client.save()
        value=json.loads(response['message']['content']);callback_record['output']=value;client.save()
        return value
    started=time.monotonic()
    result=await service.recommend(actor,RecommendationRequest(**plan['request']),preferences=preferences,
        subject_key=actor.recommendation_subject_key,product_scope=client.store.product_scope(actor),
        semantic_rerank=rerank if client.mode=='live' else None)
    record.update(latency_ms=round((time.monotonic()-started)*1000,3),result=result)
    if client.mode=='live' and callback_record.get('output') is not None:
        callback_record['validated_full_permutation']=validate_rerank(callback_record['output'],callback_record['input']['candidates'])
    client.save()
    return result


def evaluate_profiles(client,plan,assignments):
    template={sku_key(s):str(s['productIndex'])+':'+str(s['specIndex']) for s in client.manifest['skus']}
    all_keys=set(template);seen_http=[];total_attempts=[0]
    client.evidence['profiles']=[]
    ordered=deepcopy(plan['profiles']);random.Random(client.evidence['seed']).shuffle(ordered)
    client.evidence['profile_order']=[p['profile_id'] for p in ordered]
    for profile in ordered:
        switch_user(client,profile['user_index'])
        record={'profile':profile,'user_id':client.actor['actor_id'],'status':'RUNNING'}
        client.evidence['profiles'].append(record);client.save()
        require(not client.request('preferences'),'fresh_personal_preferences_required')
        record['explicit_edit']=client.request('preferences/likes',{'value':profile['likes']},method='PUT')
        preferences=client.request('preferences');record['saved_preferences']=preferences
        require(len(preferences)==1 and preferences[0]['source']=='explicit' and preferences[0]['value']==profile['likes']
            and any(e.get('actor_id')==client.actor['actor_id'] for e in preferences[0]['evidence_ids']),'owned_explicit_preference_not_persisted')
        current_stocks=stocks(client);record['java_stock_before']=current_stocks
        baseline=http_recommend(client,plan['request']);record['http_rule']=baseline
        actual=baseline['result'];assignment=actual['assignment'];before=assignments[profile['profile_id']]
        require(all(assignment[k]==before[k] for k in ('assignment_id','bucket','group')),'assignment_resampled_or_changed')
        require(actual['strategy_version']==plan['strategy_version'] and actual['ranking_mode']=='content_rule','unexpected_http_strategy_or_ranking_mode')
        require(set(actual['diagnostics']['rerank_candidate_keys'])==set(sku_key(c) for c in actual['items'])==all_keys,'http_profiles_not_same_legal_candidate_set')
        record['rule_order_templates']=[template[sku_key(c)] for c in actual['items']]
        require(record['rule_order_templates'][0]==str(profile['expected_product_index'])+':'+str(profile['expected_spec_index']),'explicit_preference_did_not_affect_top_rank')
        seen_http.append(record['rule_order_templates'])
        limits=constraints(RecommendationRequest(**plan['request']),preferences)
        record['rule_constraint_violations']=violations(actual['items'],client.catalog,current_stocks,client.manifest['products'],limits)
        record['rule_metrics']=list_metrics(actual['items'],profile['likes'],plan['metric_top_k'])
        record['semantic']={};client.save()
        semantic=asyncio.run(semantic_compare(client,plan,profile,preferences,record['semantic'],total_attempts))
        require(semantic['candidate_snapshot_hash']==actual['candidate_snapshot_hash'] and
                semantic['diagnostics']['rerank_candidate_keys']==actual['diagnostics']['rerank_candidate_keys'],'comparison_candidate_snapshot_changed')
        payload=record['semantic']['callback'].get('input')
        if payload:
            baseline_cards={c['sku_key']:c for c in actual['items']}
            require([c['sku_key'] for c in payload['candidates']]==actual['diagnostics']['rerank_candidate_keys'] and
                    all(c=={k:baseline_cards[c['sku_key']][k] for k in c} for c in payload['candidates']),
                    'semantic_callback_did_not_receive_the_http_candidate_facts')
        record['semantic_constraint_violations']=violations(semantic['items'],client.catalog,current_stocks,client.manifest['products'],limits)
        record['semantic_metrics']=list_metrics(semantic['items'],profile['likes'],plan['metric_top_k'])
        record['semantic_order_templates']=[template[sku_key(c)] for c in semantic['items']]
        record['errors']=record['rule_constraint_violations']+record['semantic_constraint_violations']
        if client.mode=='live':
            callback=record['semantic']['callback'];attempts=record['semantic']['model_attempts']
            if semantic['ranking_mode']!='content_llm' or callback.get('validated_full_permutation') is None:record['errors'].append('semantic_live_permutation_not_verified')
            if not attempts or any(a.get('status')!='succeeded' or type(a.get('usage',{}).get('input_tokens')) is not int
                                  or type(a.get('usage',{}).get('output_tokens')) is not int for a in attempts):record['errors'].append('actual_usage_or_success_missing')
        record['status']='FAILED' if record['errors'] else 'PASSED' if client.mode=='live' else 'PASSED_MOCK_CONTRACT'
        client.save()
    require(len({tuple(order) for order in seen_http})==len(plan['profiles']),'explicit_profiles_have_no_ranking_difference')


def evaluate_constraints(client,plan):
    client.stage('Explicit budget and avoidance preferences restrict the authoritative HTTP results')
    records=[];client.evidence['constraint_checks']=records
    client.request('preferences/budget_max_cents',{'value':plan['constraint_budget_cents']},method='PUT')
    params={'query':plan['request']['query'],'limit':8}
    record=http_recommend(client,params);records.append(record)
    record['saved_preferences']=client.request('preferences')
    record['violations']=violations(record['result']['items'],client.catalog,stocks(client),client.manifest['products'],
        constraints(RecommendationRequest(**params),record['saved_preferences']))
    require(record['result']['items'] and not record['violations'] and all(c['price_cents']<=plan['constraint_budget_cents'] for c in record['result']['items']),'explicit_budget_not_respected')
    client.request('preferences/budget_max_cents',method='DELETE')
    client.request('preferences/avoid',{'value':plan['constraint_avoid']},method='PUT')
    record=http_recommend(client,plan['request']);records.append(record)
    record['saved_preferences']=client.request('preferences')
    record['violations']=violations(record['result']['items'],client.catalog,stocks(client),client.manifest['products'],
        constraints(RecommendationRequest(**plan['request']),record['saved_preferences']))
    require(record['result']['items'] and len(record['result']['items'])<len(client.manifest['skus']) and not record['violations'],'explicit_avoid_not_respected')
    client.request('preferences/avoid',method='DELETE');client.save()


def evaluate_stockout(client,plan):
    client.stage('User reviews and confirms one exact multi-SKU inventory reservation; no payment is made')
    record={'before':stocks(client),'payment_confirmation_sent':False};client.evidence['stockout']=record;client.save()
    require(set(record['before'])=={sku_key(s) for s in client.manifest['skus']} and all(v>0 for v in record['before'].values()),'all_skus_must_start_in_stock')
    conversation=client.conversation()
    parameters={'payMethod':'mock','addressId':client.session['addressId'],'orderFrom':0,'orderList':[
        {'productId':s['productId'],'propertyValueIds':s['propertyValueIds'],'buyCount':record['before'][sku_key(s)]} for s in client.manifest['skus']]}
    proposal=client.propose(conversation,'order',parameters);record['order_proposal']=proposal;client.save()
    expected=sum(s['priceCents']*record['before'][sku_key(s)] for s in client.manifest['skus'])
    require(proposal['quote_total_cents']==expected and proposal['status']=='PROPOSED' and stocks(client)==record['before'],'reviewable_quote_changed_or_reserved_before_confirmation')
    order=client.confirm(proposal);record['confirmed_order']=order;pay_id=order['receipt']['payOrderId'];record['pay_order_id']=pay_id;client.save()
    try:
        record['sold_out']=client.wait(lambda:stocks(client),lambda values:values and all(v==0 for v in values.values()),'Observe every Java SKU at zero stock')
        record['pending_payment']=client.request('payments/'+pay_id)
        require(record['pending_payment']['paymentStatus']=='PENDING','reservation_implicitly_paid')
        record['empty_http']=http_recommend(client,plan['request'])
        require(record['empty_http']['result']['items']==[] and record['empty_http']['result']['diagnostics']['empty_reason']=='no_eligible_sku','out_of_stock_recommendations_not_empty')
    finally:
        # Cleanup is another explicit user confirmation for the actual owned Java order/payment group.
        pending=client.request('payments/'+pay_id)
        require(pending['paymentStatus']=='PENDING','unexpected_payment_state_requires_review')
        orders=client.java.request('order','/internal/order/commerce/listOrders',session=client.session,data={'limit':30})
        owned=sorted((o for o in orders if o['payOrderId']==pay_id),key=lambda o:o['orderId'])
        require(owned,'confirmed_owned_order_not_found')
        record['java_parent_orders']=owned
        cancellation=client.propose(conversation,'cancel',{'orderId':owned[0]['orderId']});record['cancel_proposal']=cancellation;client.save()
        cancelled=client.confirm(cancellation);record['cancelled']=cancelled
        require(cancelled['receipt']['stockRestored'] is True,'java_cancellation_stock_not_confirmed')
        record['restored']=client.wait(lambda:stocks(client),lambda values:values==record['before'],'Confirmed Java cancellation restores the original stock once')
        replay=client.confirm(cancellation)
        require(replay['receipt']==cancelled['receipt'] and stocks(client)==record['before'],'cancellation_replay_refilled_stock')
        record['restored_http']=http_recommend(client,plan['request'])
        require(set(sku_key(c) for c in record['restored_http']['result']['items'])==set(record['before']),'restored_skus_not_recommended')
        record['ledger']=client.ledger.summary(pay_id)
        require(record['ledger']['paidCents']==record['ledger']['refundedCents']==0,'unpaid_reservation_created_financial_facts')
        record['java_watermark']=client.wait(lambda:client.java.request('admin','/internal/demo/scenario/inspect-run',
            data={'scenarioRunId':client.evidence['run_id'],'password':client.config['SMARTLECT_DEMO_PASSWORD']}),
            lambda value:value['ready'],'Java confirms no pending reservation, command, or Outbox')
        identifiers={identifier for row in record['java_watermark']['watermark']['outbox'] for identifier in row['eventIds']}
        require(identifiers,'cancelled_reservation_has_no_java_event_watermark')
        record['consumed_events']=client.wait(lambda:client.rows('SELECT event_id,event_type,status FROM commerce_event WHERE user_id=%s ORDER BY event_id',
            (client.session['userId'],)),lambda values:identifiers<={r['event_id'] for r in values if r['status']=='APPLIED'},
            'Consume the actual Java cancellation watermark before classifying payment failures')
        failures=client.rows("SELECT event_id FROM commerce_event WHERE user_id=%s AND event_type='PAYMENT_ATTEMPT'",(client.session['userId'],))
        require(not failures,'unpaid_or_cancelled_order_misclassified_as_payment_failure')
        record['java_declined_attempt_count']=len(failures);client.save()


def summary(runs,plan):
    records=[p for run in runs for p in run.get('profiles',[])]
    result={'planned_runs':len(runs),'completed_runs':sum(r.get('status') in {'PASSED','PASSED_MOCK_CONTRACT'} for r in runs),
            'constraint_violations':sum(len(p.get(k,[])) for p in records for k in ('rule_constraint_violations','semantic_constraint_violations')),
            'ranking_modes':dict(Counter(p.get('semantic',{}).get('result',{}).get('ranking_mode','not_completed') for p in records)),
            'metric_definition':'Coverage uses top-k template SKU/product identities across independent fixtures; category diversity is distinct-category pair fraction. No template index is a utility score.',
            'conversion_or_revenue_lift_measured':False,'coverage':{},'repeat_variation':[]}
    for mode,field in (('http_rule','rule_order_templates'),('semantic','semantic_order_templates')):
        exposed={identifier for p in records for identifier in p.get(field,[])[:plan['metric_top_k']]}
        result['coverage'][mode]={'template_sku_count':len(exposed),'universe_skus':plan['universe']['skus'],
            'sku_coverage':len(exposed)/plan['universe']['skus'],'template_product_count':len({v.split(':')[0] for v in exposed}),
            'universe_products':plan['universe']['products']}
    for seed in sorted({run['seed'] for run in runs}):
        selected=[run for run in runs if run['seed']==seed]
        for profile in plan['profiles']:
            values=[next((p for p in run.get('profiles',[]) if p['profile']['profile_id']==profile['profile_id']),None) for run in selected]
            available=len(values)==2 and all(p and p['status']=='PASSED' for p in values)
            result['repeat_variation'].append({'seed':seed,'profile_id':profile['profile_id'],'status':'MEASURED' if available else 'UNAVAILABLE',
                'semantic_order_changed':values[0]['semantic_order_templates']!=values[1]['semantic_order_templates'] if available else None})
    attempts=[a for p in records for a in p.get('semantic',{}).get('model_attempts',[])]
    result['provider_attempts']=len(attempts);result['unpriced_attempts']=sum(a.get('cost_estimate_cny') is None for a in attempts)
    result['known_cost_estimate_cny']=sum(a.get('cost_estimate_cny') or 0 for a in attempts)
    result['known_usage_totals']={key:sum(a.get('usage',{}).get(key) or 0 for a in attempts) for key in ('input_tokens','output_tokens')}
    result['usage_unknown_attempts']=sum(any(a.get('usage',{}).get(key) is None for key in ('input_tokens','output_tokens')) for a in attempts)
    result['latency_ms']={}
    for name in ('http_rule','semantic'):
        values=sorted(p[name]['latency_ms'] for p in records if 'latency_ms' in p.get(name,{}))
        result['latency_ms'][name]={'count':len(values),'p50':values[(len(values)-1)//2] if values else None,
            'p95':values[max(0,(95*len(values)+99)//100-1)] if values else None,'user_wait_ms':0,
            'first_visible_text_ms':None,'reason':'nonstream recommendation results; driver confirms immediately'}
    return result


def main(mode,seeds,output):
    output=output.resolve();freeze_path=output.with_name(output.stem+'-freeze.json')
    require(not output.exists() and not freeze_path.exists(),'use_unused_evaluation_output')
    output.parent.mkdir(parents=True,exist_ok=True)
    def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=json_value)+'\n')
    plan=json.loads(MANIFEST.read_text());require(plan['repeats']==2 and 1<=len(seeds)<=3 and len(set(seeds))==len(seeds),'fixed_seed_repeat_limits')
    strategy_config(plan['strategy_config'])
    require(plan['semantic']['system_prompt'] in (ROOT/'growth/src/smartlect/agents/shopping.py').read_text(),'production_rerank_prompt_changed')
    try:original_bindings=freeze_bindings(mode)
    except Exception as error:
        write(output,{'phase':'F6-recommendation-evaluation','status':'FAILED','stage':'freeze_bindings',
            'error_type':type(error).__name__,'model_calls':0,'requested_mode':mode,'seeds':seeds})
        print('FAILED: freeze binding; evidence: '+str(output));return 1
    bindings=deepcopy(original_bindings)
    bindings.update(prompt_version=plan['semantic']['prompt_version'],schema_version=plan['semantic']['schema_version'])
    bindings['model'].update(max_completion_tokens=plan['semantic']['max_completion_tokens'],
        max_attempts_per_call=plan['semantic']['max_attempts_per_call'],max_attempts_per_run=plan['semantic']['max_attempts_per_run'])
    freeze={'schema_version':'recommendation-evaluation-freeze-v1','frozen_at':now(),'seeds':seeds,'plan':plan,'bindings':bindings,
        'manifest_sha256':hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write(freeze_path,freeze)
    evidence={'phase':'F6-recommendation-evaluation','status':'RUNNING','requested_mode':mode,'freeze':str(freeze_path),
        'freeze_sha256':hashlib.sha256(freeze_path.read_bytes()).hexdigest(),'runs':[],
        'transport_boundary':'Preference/constraint/stockout use public authenticated HTTP. Same-candidate semantic comparison directly invokes the existing deterministic service with Java HTTP and configured Provider; no production debug endpoint.',
        'selection':'Fixed original user slots; group=all changes the policy under explicit grant without changing assigned bucket/group.'}
    def save():write(output,evidence)
    save()
    for seed in seeds:
        for repeat in range(1,3):
            record={'run_id':'rec-eval-'+uuid.uuid4().hex,'scenario':'recommendation-evaluation','seed':seed,'repeat':repeat,'status':'RUNNING','started_at':now()}
            evidence['runs'].append(record);client=None;save()
            try:
                current=freeze_bindings(mode)
                require(current==original_bindings,'source_or_configuration_changed_after_freeze')
                client=ScenarioClient(record,save,requested_mode=mode);client.setup(actor_ref='user_a')
                require(len(client.manifest['skus'])==4 and len(client.manifest['products'])==2,'frozen_fixture_shape_changed')
                assignments=configure_all(client,plan)
                evaluate_profiles(client,plan,assignments);evaluate_constraints(client,plan);evaluate_stockout(client,plan)
                require(all(p['status']!='FAILED' for p in record['profiles']),'one_or_more_fixed_profile_checks_failed')
                record.update(status='PASSED' if mode=='live' else 'PASSED_MOCK_CONTRACT',ai_capability_verified=mode=='live',completed_at=now())
            except Exception as error:
                record.update(status='FAILED',completed_at=now(),error_type=type(error).__name__,error=redact_text(str(error),client.config.values() if client else ()),
                    failure_frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(error.__traceback__)],
                    recovery='Keep original scope, grant, proposal and action IDs. No profile/bucket resampling or automatic repeat was added.')
            finally:
                if client:client.close()
                save()
    evidence['summary']=summary(evidence['runs'],plan)
    evidence['status']=('PASSED' if mode=='live' else 'PASSED_MOCK_CONTRACT') if all(r['status']!='FAILED' for r in evidence['runs']) else 'FAILED'
    try:
        if freeze_bindings(mode)!=original_bindings:evidence.update(status='FAILED',binding_error='source_or_configuration_changed_during_evaluation')
    except Exception as error:evidence.update(status='FAILED',binding_error='final_binding_check_failed',binding_error_type=type(error).__name__)
    evidence['completed_at']=now();save()
    print(json.dumps({'status':evidence['status'],'output':str(output),'runs':len(evidence['runs']),'provider_attempts':evidence['summary']['provider_attempts']},ensure_ascii=False))
    return 0 if evidence['status']!='FAILED' else 1


def self_test():
    # HTTP JSON has arrays; the internal immutable identity model requires tuples.
    actor=ActorContext.model_validate_json(canonical({'subject_type':'user','actor_id':'synthetic',
        'session_id':'synthetic-session','execution_scope_id':'synthetic-scope','permissions':['shopping:read']}))
    require(actor.permissions==('shopping:read',),'http_actor_permissions_not_preserved')
    plan=json.loads(MANIFEST.read_text());strategy_config(plan['strategy_config'])
    require(plan['semantic']['system_prompt'] in (ROOT/'growth/src/smartlect/agents/shopping.py').read_text(),'production_rerank_prompt_changed')
    require(plan['repeats']==2 and len(plan['profiles'])==2 and len({p['user_index'] for p in plan['profiles']})==2,'fixed_profiles_required')
    card={'productId':'p','propertyValueIdHash':'s','propertyValueIds':'value','sku_key':'p:s','price_cents':100,
          'stock':2,'productName':'数码','specification':'标准','categoryId':'c'}
    catalogue={'skus':[{'productId':'p','propertyValueIdHash':'s','propertyValueIds':'value','price':'1.00'}]}
    limits=constraints(RecommendationRequest(max_price_cents=100))
    require(not violations([card],catalogue,{'p:s':2},['p'],limits),'valid_java_card_rejected')
    for changed in ({**card,'price_cents':101},{**card,'stock':0},{**card,'propertyValueIds':'fabricated'}):
        require(bool(violations([changed],catalogue,{'p:s':2},['p'],limits)),'invalid_card_passed')
    require(list_metrics([card],['数码','标准'],2)['explicit_terms_match_at_1']==1,'explicit_term_metric_changed')
    require(validate_rerank({'sku_keys':['p:s']},[card])==['p:s'],'legal_permutation_rejected')
    try:validate_rerank({'sku_keys':['invented']},[card])
    except ValueError:pass
    else:raise AssertionError('invented_permutation_passed')
    result=summary([{'seed':42,'status':'FAILED','profiles':[{'profile':plan['profiles'][0],'status':'FAILED',
        'rule_order_templates':['0:0','0:1'],'semantic_order_templates':['0:1','0:0']}]}],plan)
    require(result['coverage']['http_rule']['template_sku_count']==2 and result['repeat_variation'][0]['status']=='UNAVAILABLE','failed_repeat_falsely_counted_as_variation')
    print('Recommendation evaluation self-test passed; no config, DB, Java, service or model calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['live','mock'],default='live')
    parser.add_argument('--seeds',type=int,nargs='+',default=[42,73,101])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:self_test()
    else:raise SystemExit(main(args.mode,args.seeds,args.output or ROOT/'artifacts'/('f6-recommendations-'+uuid.uuid4().hex+'.json')))
