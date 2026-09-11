"""Audit a completed owned reset using Java facts, scoped Growth rows, and real broker redelivery."""
import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import httpx

from reset_demo import event_ids, write_json
from runtime import ROOT, ENV_FILE, parse_env
from smartlect.events import canonical, connect_from_env


def require(value, reason):
    if not value: raise AssertionError(reason)


def safe(value):
    def encode(item):
        if isinstance(item,(date,datetime)): return item.isoformat()
        if isinstance(item,Decimal): return str(item)
        raise TypeError(type(item).__name__)
    return json.loads(json.dumps(value,ensure_ascii=False,default=encode))


def digest(value):
    return hashlib.sha256(canonical(safe(value)).encode()).hexdigest()


def validate_source(source):
    require(source.get('status')=='PASSED','completed_reset_evidence_required')
    result=source.get('result') or {}
    require(result.get('mode')=='retire_and_replace','owned_retirement_receipt_required')
    require(result.get('retiredRunId') not in {None,'store',result.get('replacementRunId')},'distinct_owned_runs_required')
    identifiers=event_ids(result.get('watermark') or {})
    require(identifiers,'nonempty_original_java_event_ids_required')
    require(len(identifiers)<=1000,'bounded_replay_event_limit')
    return result,identifiers


def validate_java(result, old, fresh):
    require(old['state']=='RETIRED' and sorted(old['scopeIds'])==sorted(result['retiredScopeIds']),'old_java_run_not_retired')
    require(fresh['state']=='ACTIVE' and fresh['ready'],'replacement_java_run_not_initial')
    require(fresh['scenarioRunId']==result['replacementRunId'] and fresh['branches']==result['replacementManifests'],'replacement_manifest_changed')
    old_users={u['userId'] for m in old['branches'] for u in m['users']}
    old_products={p for m in old['branches'] for p in m['products']}
    old_skus={(s['productId'],s['propertyValueIdHash']) for m in old['branches'] for s in m['skus']}
    new_users={u['userId'] for m in fresh['branches'] for u in m['users']}
    new_products={p for m in fresh['branches'] for p in m['products']}
    new_skus={(s['productId'],s['propertyValueIdHash']) for m in fresh['branches'] for s in m['skus']}
    require(old_users and old_products and old_skus and not old_users&new_users and not old_products&new_products and not old_skus&new_skus,'replacement_resources_overlap')
    require(old['watermark']['users'] and all(r['status']==0 for r in old['watermark']['users']),'old_users_not_disabled')
    require(old['watermark']['products'] and all(r['status'] in {0,-1} for r in old['watermark']['products']),'old_products_still_on_sale')
    require({r['userId'] for r in old['watermark']['users']}==old_users,'old_user_inventory_incomplete')
    require({r['userId'] for r in fresh['watermark']['users']}==new_users and all(r['status']==1 for r in fresh['watermark']['users']),'replacement_users_not_initial')
    require({r['product_id'] for r in fresh['watermark']['products']}==new_products and all(r['status']==1 for r in fresh['watermark']['products']),'replacement_products_not_initial')
    stocks={(r['product_id'],r['property_value_id_hash']):r for r in fresh['watermark']['skus']}
    require(set(stocks)==new_skus,'replacement_sku_inventory_incomplete')
    for manifest in fresh['branches']:
        for sku in manifest['skus']:
            row=stocks[(sku['productId'],sku['propertyValueIdHash'])]
            require(row['stock']==sku['initialStock'] and Decimal(str(row['price']))*100==sku['priceCents'],'replacement_sku_not_initial')
    for name in ('orders','items','payments','refunds','commands','outbox'):
        require(not fresh['watermark'][name],'replacement_has_existing_'+name)
    # Compare original Java financial/stock/Outbox facts against the pre-retirement receipt.
    for name in ('orders','items','payments','refunds','commands','skus'):
        require(old['watermark'][name]==result['watermark'][name],'original_java_'+name+'_changed')
    current_outbox={(r['service'],r['id']):r for r in old['watermark']['outbox']}
    require(all(current_outbox.get((r['service'],r['id']))==r for r in result['watermark']['outbox']),'original_java_outbox_changed')


def validate_scope(snapshot, manifest, *, fresh=False):
    scope=snapshot['scope']['execution_scope_id']
    require(snapshot['scope'] and snapshot['resources'],'missing_growth_scope_resources')
    require(scope==manifest['executionScopeId'] and snapshot['scope']['scenario_run_id']==manifest['scenarioRunId'],'growth_scope_manifest_mismatch')
    expected={('user',u['userId']) for u in manifest['users']} | {('product',p) for p in manifest['products']}
    resources={(r['resource_type'],r['resource_id']) for r in snapshot['resources']}
    require(all(kind in {'user','product','visitor'} for kind,_ in resources),'unexpected_growth_resource_type')
    require({r for r in resources if r[0]!='visitor'}==expected,'growth_resources_differ_from_java_manifest')
    if fresh:
        require(not any(kind=='visitor' for kind,_ in resources),'replacement_inherited_visitor_mapping')
        require(snapshot['guard'] is None,'replacement_growth_scope_not_active')
        for name in ('facts','projections','metadata','accounts','campaigns','creatives','spend','touches','exposures','recommendations','conversations','plans'):
            require(not snapshot[name],'replacement_growth_not_initial_'+name)
    else:
        require(snapshot['guard'] and snapshot['guard']['state']=='RETIRED','old_growth_scope_not_retired')
    users={r['resource_id'] for r in snapshot['resources'] if r['resource_type']=='user'}
    require(all(r['user_id'] in users and r['raw_sha256']==r['fingerprint'] for r in snapshot['facts']),'scoped_raw_fact_identity_or_hash_mismatch')
    require(all(r['execution_scope_id']==scope for r in [*snapshot['projections'],*snapshot['metadata']]),'cross_scope_projection_detected')
    projections={r['event_id']:r for r in snapshot['projections']}
    require(all(r['event_id'] in projections and projections[r['event_id']]['calculation_status']=='FINAL'
                for r in snapshot['facts'] if r['event_type'] in {'PAYMENT','REFUND'}),'financial_projection_not_final')
    spend={r['click_id']:r for r in snapshot['spend']}
    touches={r['touch_id']:r for r in snapshot['touches'] if r['kind']=='AD_CLICK' and r['origin']=='ads_executor'}
    require({r['touch_id'] for r in spend.values()}==set(touches),'charged_touch_spend_mismatch')
    for click,row in spend.items():
        metadata=json.loads(touches[row['touch_id']]['metadata_json'])
        require(row['execution_scope_id']==scope and metadata['click_id']==click and metadata['amount_cents']==row['amount_cents'],'charged_touch_amount_mismatch')
    spent=sum(r['amount_cents'] for r in spend.values())
    require(len(snapshot['accounts'])<=1,'duplicate_scoped_account')
    if snapshot['accounts']:
        account=snapshot['accounts'][0]
        require(account['account_id']==scope and account['spent_cents']==spent and 0<=spent<=account['budget_cap_cents'],'old_account_ledger_mismatch')
    else: require(spent==0,'charged_spend_without_account')
    for campaign in snapshot['campaigns']:
        require(campaign['spent_cents']==sum(r['amount_cents'] for r in spend.values() if r['campaign_id']==campaign['campaign_id']),'campaign_spend_ledger_mismatch')
    facts=snapshot['facts'];paid=sum(r['amount_cents'] for r in facts if r['status']=='APPLIED' and r['event_type']=='PAYMENT')
    refunded=sum(r['amount_cents'] for r in facts if r['status']=='APPLIED' and r['event_type']=='REFUND')
    return {'scope_id':scope,'paid_cents':paid,'refunded_cents':refunded,'net_cents':paid-refunded,
            'spent_cents':spent,'click_ids':sorted(spend),'event_ids':[r['event_id'] for r in facts],
            'payment_ids':sorted({r['pay_order_id'] for r in facts if r['status']=='APPLIED' and r['event_type']=='PAYMENT'})}


def validate_replay(replay, identifiers, version):
    for name in ('persisted_before_ack','broker_redelivered','consumer_restarted','attribution_unchanged','ledger_unchanged','broker_ack_verified'):
        require(replay.get(name) is True,'actual_replay_gate_missing_'+name)
    require(replay.get('schema_version')==version and replay.get('replayed_event_count')==len(identifiers)
            and sorted(replay.get('replayed_event_ids',[]))==sorted(identifiers),'actual_replayed_ids_mismatch')


def scope_snapshot(scope):
    with connect_from_env() as connection,connection.cursor() as cursor:
        def rows(sql,args=(scope,)):
            cursor.execute(sql,args);return list(cursor.fetchall())
        registered=rows('SELECT * FROM execution_scope WHERE execution_scope_id=%s')
        require(len(registered)==1,'missing_registered_scope')
        guards=rows('SELECT scenario_run_id,reset_request_id,state,manifest_hash,expected_watermark_hash FROM execution_scope_reset WHERE scenario_run_id=%s',
                    (registered[0]['scenario_run_id'],))
        result={'scope':registered[0],'guard':guards[0] if guards else None,
                'resources':rows('SELECT resource_type,resource_id FROM execution_resource WHERE execution_scope_id=%s ORDER BY resource_type,resource_id')}
        facts=rows('''SELECT e.* FROM commerce_event e
            LEFT JOIN execution_resource r ON r.resource_type='user' AND r.resource_id=e.user_id
            LEFT JOIN commerce_attribution a USING(event_id) LEFT JOIN commerce_attribution_meta m USING(event_id)
            WHERE r.execution_scope_id=%s OR a.execution_scope_id=%s OR m.execution_scope_id=%s ORDER BY e.event_id''',(scope,scope,scope))
        result['facts']=[]
        for fact in facts:
            raw=fact.pop('raw_json')
            fact['raw_sha256']=hashlib.sha256(raw.encode()).hexdigest()
            result['facts'].append(fact)
        identifiers=[r['event_id'] for r in facts]
        for key,table in (('projections','commerce_attribution'),('metadata','commerce_attribution_meta')):
            result[key]=rows('SELECT * FROM '+table+' WHERE execution_scope_id=%s'+
                (' OR event_id IN ('+','.join(['%s']*len(identifiers))+')' if identifiers else '')+' ORDER BY event_id',
                (scope,*identifiers))
        for key,table,order in (('accounts','ads_account','account_id'),('campaigns','ads_campaign','campaign_id'),
                               ('creatives','ads_creative','creative_id'),('spend','ad_spend','click_id'),('touches','traffic_touch','touch_id')):
            result[key]=rows('SELECT * FROM '+table+' WHERE execution_scope_id=%s ORDER BY '+order)
        for key,table,identifier in (('exposures','ad_interaction','exposure_id'),('recommendations','recommendation_receipt','recommendation_id')):
            selected=rows('SELECT * FROM '+table+' WHERE execution_scope_id=%s ORDER BY '+identifier)
            result[key]=[{identifier:r[identifier],'row_sha256':digest(r)} for r in selected]
        result['conversations']=rows('SELECT conversation_id,subject_type,actor_id,version FROM conversation WHERE execution_scope_id=%s ORDER BY conversation_id')
        result['plans']=rows('SELECT plan_id,version,status,agent_run_id,grant_id,envelope_hash,SHA2(spec_json,256) AS spec_sha256,SHA2(action_receipts_json,256) AS receipts_sha256 FROM merchant_plan WHERE execution_scope_id=%s ORDER BY plan_id')
        return safe(result)


def replay_selected(output, identifiers, version, record):
    require(not output.exists(),'use_unused_replay_output')
    ids_path=output.with_name(output.stem+'-event-ids.json')
    require(not ids_path.exists(),'use_unused_replay_id_file')
    write_json(ids_path,identifiers)
    log=ROOT/'artifacts/local'/(output.stem+'.log');log.parent.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,str(ROOT/'scripts/check_event_replay.py'),'--schema-version',str(version),
             '--event-ids-file',str(ids_path),'--output',str(output)]
    record.update(status='RUNNING',command=command,output=str(output),log=str(log),selected_event_ids=identifiers)
    try:
        with log.open('w') as stream:
            try:
                completed=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=330)
            except subprocess.TimeoutExpired:
                record.update(status='UNKNOWN',actual_replay_status='helper_timed_out',exit_code=None)
                # Restore only the same owned worker if the bounded helper was terminated mid-check.
                recovery="from runtime import *; env=parse_env(ENV_FILE); records=load_processes(); start_app('growth-worker',env,records); wait_apps(['growth-worker'],records)"
                restored=subprocess.run(['/usr/bin/python3','-c',recovery],cwd=ROOT/'scripts',stdout=stream,stderr=subprocess.STDOUT,timeout=260)
                record['worker_recovery_exit_code']=restored.returncode
                raise
        record['exit_code']=completed.returncode
        if output.exists():record['result']=json.loads(output.read_text())
        require(completed.returncode==0 and 'result' in record,'actual_broker_replay_failed')
        validate_replay(record['result'],identifiers,version)
        record.update(status='PASSED',actual_replay_status='verified_committed_unacked_redelivered_and_worker_acked')
    except Exception:
        if record['status']=='RUNNING':record.update(status='FAILED',actual_replay_status='not_verified_see_log')
        raise
    return record


def main(source_path, output):
    source_path=source_path.resolve();output=output.resolve()
    require(not output.exists() and output!=source_path,'use_unused_audit_output')
    evidence={'phase':'F6-reset-isolation','status':'RUNNING','source':str(source_path),
              'source_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'model_calls':0,'replays':[],'checks':[],'parameters':{'reset_result':str(source_path),'output':str(output)}}
    def stage(name): evidence['stage']=name;write_json(output,evidence);print(name,flush=True)
    try:
        result,identifiers=validate_source(json.loads(source_path.read_text()))
        evidence['retired_run_id']=result['retiredRunId'];evidence['replacement_run_id']=result['replacementRunId']
        evidence['original_java_event_ids']=identifiers
        require(ENV_FILE.is_file() and not ENV_FILE.is_symlink() and ENV_FILE.stat().st_mode & 0o777==0o600,'private_runtime_configuration_required')
        config=parse_env(ENV_FILE);require(config.get('SMARTLECT_PAYMENT_MODE')=='mock','mock_payment_required');os.environ.update(config)
        old_scopes=sorted(result['retiredScopeIds']);new_scopes=sorted(m['executionScopeId'] for m in result['replacementManifests'])
        with httpx.Client(base_url='http://127.0.0.1:'+config['SMARTLECT_ADMIN_PORT'],timeout=30,trust_env=False,
                          headers={'X-Internal-Token':config['SMARTLECT_INTERNAL_TOKEN']}) as client:
            def java(path,data):
                response=client.post('/internal/demo/scenario'+path,json=data)
                require(response.status_code==200,'java_'+path.strip('/')+'_http_'+str(response.status_code))
                value=response.json();require(value.get('status')=='success','java_'+path.strip('/')+'_rejected');return value.get('data')
            def inspect(run):return java('/inspect-run',{'scenarioRunId':run,'password':config['SMARTLECT_DEMO_PASSWORD']})
            stage('Read the original Java receipt, old retirement, and replacement initial state')
            authority=java('/reset-result',{'scenarioRunId':result['retiredRunId'],'password':config['SMARTLECT_DEMO_PASSWORD']})
            require(authority==result,'original_reset_receipt_differs_from_java')
            old=inspect(result['retiredRunId']);fresh=inspect(result['replacementRunId']);validate_java(result,old,fresh)
            manifests={m['executionScopeId']:m for m in [*old['branches'],*fresh['branches']]}
            evidence['java_before']={'old':old,'replacement':fresh}
            for manifest in [*old['branches'],*fresh['branches']]:
                require(java('/read',{'executionScopeId':manifest['executionScopeId']})==manifest,'registered_manifest_read_mismatch')
            evidence['old_session_probes']=[]
            for manifest in old['branches']:
                response=client.post('/internal/demo/scenario/session',json={'executionScopeId':manifest['executionScopeId'],
                    'userIndex':0,'password':config['SMARTLECT_DEMO_PASSWORD']})
                require(response.status_code==410 and response.json().get('info')=='scenario_run_retired','old_scenario_session_not_denied_as_retired')
                evidence['old_session_probes'].append({'scope_id':manifest['executionScopeId'],'user_id':manifest['users'][0]['userId'],'http_status':410,'reason':'scenario_run_retired'})
            before={scope:scope_snapshot(scope) for scope in [*old_scopes,*new_scopes]}
            summaries={scope:validate_scope(value,manifests[scope],fresh=scope in new_scopes) for scope,value in before.items()}
            facts={r['event_id']:r for scope in old_scopes for r in before[scope]['facts']}
            require(set(identifiers)<=set(facts),'original_java_events_missing_from_old_scopes')
            require(all(facts[i]['status']=='APPLIED' and facts[i]['schema_version'] in {1,2} for i in identifiers),'original_event_unknown_or_unsettled')
            require({'PAYMENT','REFUND'} <= {facts[i]['event_type'] for i in identifiers},'authoritative_payment_and_refund_required')
            require(sum(summaries[s]['paid_cents'] for s in old_scopes)>0 and sum(summaries[s]['refunded_cents'] for s in old_scopes)>0,'positive_original_financial_facts_required')
            require(any(summaries[s]['spent_cents']>0 for s in old_scopes),'original_billed_account_required_for_budget_retention_gate')
            evidence['growth_before']=before;evidence['scope_balances_before']=summaries
            stage('Replay the exact completed reset; verify unchanged manifests, stock and scoped records')
            repeated=java('/reset',{'scenarioRunId':result['retiredRunId'],'resetRequestId':result['resetRequestId'],
                'expectedWatermarkHash':result['watermarkHash'],'password':config['SMARTLECT_DEMO_PASSWORD']})
            require(repeated==result,'repeated_reset_receipt_changed')
            after_repeat={'old':inspect(result['retiredRunId']),'replacement':inspect(result['replacementRunId'])}
            require(after_repeat==evidence['java_before'],'repeated_reset_changed_java_records_or_observed_stock')
            require({scope:scope_snapshot(scope) for scope in before}==before,'repeated_reset_changed_scoped_growth_records')
            evidence['checks'].extend(['authoritative_old_facts_and_outbox_hashes_preserved_from_reset_watermark',
                'old_users_disabled_and_registered_session_rejected','replacement_resources_disjoint_and_initial',
                'exact_reset_retry_preserved_manifest_stock_and_growth_rows'])
            stage('Replay only original Java event IDs through committed-unACKed delivery and the real worker')
            for version in sorted({facts[i]['schema_version'] for i in identifiers}):
                selected=sorted(i for i in identifiers if facts[i]['schema_version']==version)
                for offset in range(0,len(selected),100):
                    replay_path=output.with_name(output.stem+f'-schema-{version}-batch-{offset//100+1}-replay.json')
                    attempt={'status':'NOT_STARTED','schema_version':version,'selected_event_ids':selected[offset:offset+100]}
                    evidence['replays'].append(attempt);write_json(output,evidence)
                    replay_selected(replay_path,selected[offset:offset+100],version,attempt)
                    current={scope:scope_snapshot(scope) for scope in before}
                    require(current==before,'broker_replay_changed_scoped_raw_facts_attribution_or_accounts')
                    write_json(output,evidence)
            after={scope:scope_snapshot(scope) for scope in before}
            evidence['growth_after']=after
            evidence['scope_balances_after']={scope:validate_scope(value,manifests[scope],fresh=scope in new_scopes) for scope,value in after.items()}
            evidence['java_after']={'old':inspect(result['retiredRunId']),'replacement':inspect(result['replacementRunId'])}
            require(evidence['java_after']==evidence['java_before'],'broker_replay_changed_java_records')
            require(evidence['scope_balances_after']==summaries,'scoped_balance_changed')
            require(sum(r['result']['replayed_event_count'] for r in evidence['replays'])==len(identifiers),'original_events_not_actually_replayed')
            evidence['checks'].extend(['all_original_ids_actually_redelivered_and_acked_after_worker_restart',
                'old_scoped_raw_hashes_and_attribution_unchanged','old_cumulative_account_matches_spend_and_trusted_touches',
                'replacement_scopes_received_no_old_facts'])
            evidence.update(status='PASSED',stage='Complete',
                boundary='Growth raw/account baseline is captured after initial reset, before exact retry/redelivery; original Java facts are compared with the stored pre-retirement watermark. No depleted-replacement-stock mutation was introduced.')
    except Exception as error:
        evidence.update(status='FAILED',failure_type=type(error).__name__,failure=str(error) if isinstance(error,AssertionError) else 'operation_failed_check_local_runtime')
    write_json(output,evidence)
    print(json.dumps({'status':evidence['status'],'stage':evidence.get('stage'),'output':str(output),'replay_batches':len(evidence['replays'])},ensure_ascii=False))
    return 0 if evidence['status']=='PASSED' else 1


def self_test():
    try:validate_source({'status':'PASSED','result':{'mode':'retire_and_replace','retiredRunId':'old','replacementRunId':'new','watermark':{'outbox':[]}}})
    except AssertionError as error:require(str(error)=='nonempty_original_java_event_ids_required','empty_event_guard_failed')
    else:raise AssertionError('empty_event_set_passed')
    replay={key:True for key in ('persisted_before_ack','broker_redelivered','consumer_restarted','attribution_unchanged','ledger_unchanged','broker_ack_verified')}
    replay.update(schema_version=2,replayed_event_count=1,replayed_event_ids=['actual'])
    validate_replay(replay,['actual'],2)
    for changed in ({**replay,'broker_ack_verified':False},{**replay,'replayed_event_ids':['other']},{**replay,'replayed_event_count':0}):
        try:validate_replay(changed,['actual'],2)
        except AssertionError:pass
        else:raise AssertionError('incomplete_replay_passed')
    manifest={'executionScopeId':'old','scenarioRunId':'old-run','users':[{'userId':'user'}],'products':['product']}
    scope={'scope':{'execution_scope_id':'old','scenario_run_id':'old-run'},'resources':[{'resource_type':'user','resource_id':'user'},
           {'resource_type':'product','resource_id':'product'}],
           'guard':{'state':'RETIRED'},'facts':[],'projections':[],'metadata':[],
           'accounts':[{'account_id':'old','spent_cents':3,'budget_cap_cents':10}],
           'campaigns':[{'campaign_id':'campaign','spent_cents':3}],
           'spend':[{'click_id':'click','touch_id':'touch','execution_scope_id':'old','campaign_id':'campaign','amount_cents':3}],
           'touches':[{'touch_id':'touch','kind':'AD_CLICK','origin':'ads_executor','metadata_json':'{"click_id":"click","amount_cents":3}'}],
           'creatives':[],'exposures':[],'recommendations':[],'conversations':[],'plans':[]}
    require(validate_scope(scope,manifest)['spent_cents']==3,'retained_account_fixture_failed')
    for changed in ({**scope,'accounts':[{'account_id':'old','spent_cents':0,'budget_cap_cents':10}]},
                    {**scope,'touches':[]},{**scope,'metadata':[{'event_id':'event','execution_scope_id':'new'}]}):
        try:validate_scope(changed,manifest)
        except AssertionError:pass
        else:raise AssertionError('scoped_balance_or_projection_corruption_passed')
    try:validate_scope({**scope,'guard':None},manifest,fresh=True)
    except AssertionError:pass
    else:raise AssertionError('old_account_leak_into_replacement_passed')
    for resources in (scope['resources'][:1],scope['resources']+[{'resource_type':'product','resource_id':'foreign-product'}]):
        try:validate_scope({**scope,'resources':resources},manifest)
        except AssertionError as error:require(str(error)=='growth_resources_differ_from_java_manifest','unexpected_mapping_rejection')
        else:raise AssertionError('incomplete_or_foreign_mapping_passed')
    initial={**scope,'guard':None,**{key:[] for key in ('facts','projections','metadata','accounts','campaigns','creatives','spend','touches','exposures','recommendations','conversations','plans')}}
    require(validate_scope(initial,manifest,fresh=True)['spent_cents']==0,'valid_initial_mapping_rejected')
    try:validate_scope({**initial,'resources':initial['resources']+[{'resource_type':'visitor','resource_id':'old-signed-visitor'}]},manifest,fresh=True)
    except AssertionError as error:require(str(error)=='replacement_inherited_visitor_mapping','unexpected_visitor_rejection')
    else:raise AssertionError('copied_visitor_mapping_passed')
    print('Reset isolation self-test passed; no database, Java, broker, worker, or model calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset-result',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--self-test',action='store_true')
    arguments=parser.parse_args()
    if arguments.self_test:self_test()
    else:
        if not arguments.reset_result:parser.error('--reset-result is required unless --self-test is used')
        raise SystemExit(main(arguments.reset_result,arguments.output or ROOT/'artifacts'/('f6-reset-isolation-'+uuid.uuid4().hex+'.json')))
