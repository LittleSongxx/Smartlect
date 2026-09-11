"""Retire one registered local demo run through Java, preserving old facts and IDs."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import httpx

from runtime import ROOT, ENV_FILE, parse_env
from smartlect.attribution import AttributionStore
from smartlect.events import canonical, connect_from_env
from smartlect.state import StateError


def event_ids(watermark):
    return sorted({identifier for row in watermark.get('outbox',[]) for identifier in row.get('eventIds',[])})


def coordinate(run_id, request_id, store, java, state, save):
    """The Java-call marker is durable before HTTP, so a lost local file cannot reset identity."""
    guard=store.scope_reset_status(run_id)
    receipt=java('/reset-result',{'scenarioRunId':run_id})
    previous=(receipt or {}).get('resetRequestId') or (guard or {}).get('reset_request_id') or state.get('request_id')
    if request_id and previous and request_id!=previous: raise StateError('scope_reset_conflict',409)
    request_id=request_id or previous or 'reset-'+uuid.uuid4().hex
    if state.get('run_id',run_id)!=run_id: raise StateError('scope_reset_conflict',409)
    def abort_before_java():
        current=store.scope_reset_status(run_id)
        if receipt is None and current and current['reset_request_id']==request_id and not current['java_call_started'] and current['state']=='QUIESCING':
            store.abort_scope_reset(run_id,request_id)
            state['phase']='ABORTED_BEFORE_JAVA'; save()
    state.update(run_id=run_id,request_id=request_id,phase='INSPECTING'); save()
    try:
        inspected=java('/inspect-run',{'scenarioRunId':run_id})
        manifests=inspected['branches']
        if not receipt and not inspected['ready']: raise StateError('java_scenario_not_quiescent',409)
        source_watermark=receipt['watermark'] if receipt else inspected['watermark']
        if not guard or guard['state']!='RETIRED':
            readiness=store.inspect_scope_reset(run_id,manifests,event_ids(source_watermark))
            if not readiness['ready']: raise StateError('scope_reset_busy',409)
        guard=store.begin_scope_reset(run_id,request_id,manifests,event_ids(source_watermark))
    except Exception:
        abort_before_java()
        raise
    try:
        state.update(phase='QUIESCING',scope_ids=inspected['scopeIds']); save()
        if not receipt:
            if guard['java_call_started']:
                expected=guard['expected_watermark_hash']
            else:
                # Recheck after new API writes are fenced; no fixed sleep is taken as proof.
                inspected=java('/inspect-run',{'scenarioRunId':run_id})
                if not inspected['ready']: raise StateError('java_scenario_not_quiescent',409)
                readiness=store.inspect_scope_reset(run_id,inspected['branches'],event_ids(inspected['watermark']))
                if not readiness['ready']: raise StateError('scope_reset_busy',409)
                expected=inspected['watermarkHash']
                guard=store.mark_scope_reset_call(run_id,request_id,expected,event_ids(inspected['watermark']))
            state.update(phase='JAVA_CALL_STARTED',expected_watermark_hash=expected); save()
            try:
                receipt=java('/reset',{'scenarioRunId':run_id,'resetRequestId':request_id,'expectedWatermarkHash':expected})
            except Exception:
                # One bounded read-only recovery. Never issue a new reset ID after an unknown call.
                receipt=java('/reset-result',{'scenarioRunId':run_id})
                if receipt is None: raise
        else:
            state.update(phase='RECOVER_JAVA_RESULT',expected_watermark_hash=receipt['watermarkHash']); save()
            guard=store.mark_scope_reset_call(run_id,request_id,receipt['watermarkHash'],event_ids(receipt['watermark']))
        if receipt is None: raise StateError('java_reset_outcome_unknown',503)
        final=store.finish_scope_reset(run_id,request_id,receipt)
        state.update(phase='RETIRED',result=final['result']); save()
        return {'status':'PASSED','run_id':run_id,'reset_request_id':request_id,'result':final['result'],
                'old_scope_state':'RETIRED','historical_facts_deleted':False,'model_calls':0,
                'boundary':'Growth write guard and new Java resources; no claim that every previously admitted cross-service request vanished'}
    except Exception:
        abort_before_java()
        raise


def write_json(path, value, *, private=False):
    if path.is_symlink(): raise ValueError('symlink_output_refused')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with os.fdopen(os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600 if private else 0o644),'w') as stream:
        stream.write(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def main(run_id, request_id=None, output=None):
    if not run_id or run_id=='store' or len(run_id)>64 or '\0' in run_id:
        raise ValueError('registered_run_id_required')
    if request_id is not None and (not request_id.strip() or len(request_id)>64 or '\0' in request_id):
        raise ValueError('invalid_reset_request_id')
    if ENV_FILE.is_symlink() or not ENV_FILE.is_file() or ENV_FILE.stat().st_mode & 0o777 != 0o600:
        raise ValueError('private_runtime_configuration_required')
    config=parse_env(ENV_FILE)
    if config.get('SMARTLECT_PAYMENT_MODE')!='mock': raise ValueError('mock_payment_required')
    os.environ.update(config)
    store=AttributionStore(connect_from_env,secret=config.get('SMARTLECT_ATTRIBUTION_SECRET'))
    key=hashlib.sha256(run_id.encode()).hexdigest()[:32]
    directory=ROOT/'run/reset-demo'
    if directory.is_symlink(): raise ValueError('symlink_state_directory_refused')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    state_path=directory/(key+'.json')
    output=Path(output) if output else ROOT/'artifacts'/('reset-'+key+'.json')
    if state_path.is_symlink() or output.is_symlink(): raise ValueError('symlink_output_refused')
    if state_path.exists() and state_path.stat().st_mode & 0o777 != 0o600: raise ValueError('private_reset_state_required')
    lock_path=directory/(key+'.lock')
    if lock_path.is_symlink(): raise ValueError('symlink_lock_refused')
    with os.fdopen(os.open(lock_path,os.O_RDWR|os.O_CREAT,0o600),'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        state=json.loads(state_path.read_text()) if state_path.exists() else {'run_id':run_id,'history':[]}
        if output.exists():
            previous=json.loads(output.read_text())
            if previous.get('status')!='PASSED' or previous.get('run_id')!=run_id or request_id and previous.get('reset_request_id')!=request_id:
                raise ValueError('use_unused_output_path')
        def save(): write_json(state_path,state,private=True)
        with httpx.Client(base_url='http://127.0.0.1:'+config['SMARTLECT_ADMIN_PORT'],timeout=30,trust_env=False,
                          headers={'X-Internal-Token':config['SMARTLECT_INTERNAL_TOKEN']}) as client:
            def java(path,data):
                response=client.post('/internal/demo/scenario'+path,json={**data,'password':config['SMARTLECT_DEMO_PASSWORD']})
                if response.status_code>=500: raise StateError('java_reset_outcome_unknown',503)
                result=response.json()
                if response.status_code>=400 or result.get('status')!='success':
                    reason=result.get('info','')
                    raise StateError(reason if isinstance(reason,str) and re.fullmatch('[a-z][a-z0-9_]{1,80}',reason) else 'java_reset_rejected',
                                     response.status_code if response.status_code>=400 else 409)
                return result.get('data')
            try:
                evidence=coordinate(run_id,request_id,store,java,state,save)
                if output.exists() and canonical(json.loads(output.read_text()))!=canonical(evidence):
                    raise ValueError('output_receipt_conflict')
                if not output.exists(): write_json(output,evidence)
                print(json.dumps({'status':'PASSED','retired_run_id':run_id,
                                  'replacement_run_id':evidence['result']['replacementRunId'],'output':str(output)},ensure_ascii=False))
                return 0
            except Exception as error:
                reason=error.code if isinstance(error,StateError) else type(error).__name__
                state.setdefault('history',[]).append({'phase':state.get('phase'),'error':reason})
                save()
                failure={'status':'FAILED','run_id':run_id,'request_id':state.get('request_id'),
                         'phase':state.get('phase'),'error':reason,'model_calls':0}
                failed=output.with_name(output.stem+'-failed-'+uuid.uuid4().hex[:8]+output.suffix)
                write_json(failed,failure)
                print(json.dumps({**failure,'output':str(failed)},ensure_ascii=False))
                return 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--request-id')
    parser.add_argument('--output',type=Path)
    arguments=parser.parse_args()
    raise SystemExit(main(arguments.run_id,arguments.request_id,arguments.output))
