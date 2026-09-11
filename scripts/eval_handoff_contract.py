"""Frozen 8 x 2 handoff development probe; no RAG case or holdout loading.

Uses existing ScenarioClient tracing and freeze/provenance helpers. One message
per independent scope, no resampling, no service management or transaction confirmation.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import traceback
import uuid

from eval_rag import citation_errors, digest, freeze_bindings, timestamp, verify_attempts, write_json
from scenario_client import ROOT, ScenarioClient, now
from smartlect.tools import REGISTRY

MANIFEST = ROOT / 'evals/handoff-contract-manifest.json'
MANIFEST_SHA256 = '78e22e04fbd7bd3c78dc738795a583227a37e4c7e461dac412218168c08fff09'


def contract():
    if digest(MANIFEST) != MANIFEST_SHA256:
        raise ValueError('frozen_handoff_manifest_changed')
    value = json.loads(MANIFEST.read_text())
    if len(value['cases']) != 8 or len({c['case_id'] for c in value['cases']}) != 8:
        raise ValueError('exactly_eight_distinct_cases_required')
    return value


def score(case, data):
    record = data['model_runs'][0]
    run, calls = record['run'], record.get('tool_receipts', [])
    result, context = run.get('result') or {}, run.get('context') or {}
    handoffs = [(i, call, json.loads(call['receipt_json']) if isinstance(call.get('receipt_json'), str)
                 else call.get('receipt_json') or {}) for i, call in enumerate(calls) if call['tool_name'] == 'request_handoff']
    completed = [(i, call, receipt) for i, call, receipt in handoffs if receipt.get('tool_succeeded') is True
                 and receipt.get('command_status') in {'command_accepted', 'business_completed'}
                 and receipt.get('data', {}).get('ticket', {}).get('ticket_id')]
    tickets = [t for t in data['tickets_after'] if t['conversation_id'] == data['conversation_id']]
    live = result.get('model_mode') == 'live'
    checks = {'live_final_mode': live, 'message_contract_preserved': not data.get('message_contract_error'),
        'runtime_trace_matches_freeze': not data.get('version_errors'),
        'no_proposal_or_preference_tool': not any(REGISTRY.get(c['tool_name']) and
            REGISTRY[c['tool_name']].kind in {'proposal', 'memory'} for c in calls),
        'no_proposal_created': not data['conversation_after'].get('proposals') and not result.get('proposal')}
    if case['expected_action'] == 'handoff':
        actual = completed[0] if len(completed) == 1 else None
        actual_id = actual[2]['data']['ticket']['ticket_id'] if actual else None
        checks['model_chose_real_handoff'] = bool(actual) and result.get('handoff_origin') == 'model_tool' and (
            result.get('ticket', {}).get('ticket_id') == actual_id and len(tickets) == 1
            and tickets[0]['ticket_id'] == actual_id and actual[2].get('evidence_id') == actual[1]['call_id']
            and actual[1]['call_id'] in result.get('tool_evidence_ids', []))
        checks['handoff_terminal_status'] = result.get('answer_status') == 'needs_human'
        checks['no_activity_after_handoff'] = bool(actual) and actual[0] == len(calls) - 1 and all(
            a.get('started_at') and timestamp(a['started_at']) <= timestamp(actual[2]['observed_at'])
            for a in context.get('model_attempts', []))
    else:
        checks['model_kept_policy_only'] = not handoffs and not tickets and not result.get('ticket')
        checks['plain_answer_status'] = result.get('answer_status') == 'answered'
    documents = {(d['doc_id'], d['version']): d for d in data.get('documents', [])}
    cited = result.get('citations', [])
    provenance = [{'doc_id': c.get('doc_id'), 'errors': citation_errors(c, documents, data['actor'], run['updated_at'])}
                  for c in cited]
    checks['citation_provenance'] = all(not c['errors'] for c in provenance)
    checks['required_policy_citations'] = set(case['required_citation_doc_ids']) <= {c.get('doc_id') for c in cited}
    return {'deterministic_checks': checks, 'deterministic_checks_passed': all(checks.values()),
        'actual_mode': result.get('model_mode'), 'handoff_origin': result.get('handoff_origin'),
        'actual_ticket_ids': [t['ticket_id'] for t in tickets],
        'service_handoff_exists': bool(tickets), 'successful_model_handoff_receipt_count': len(completed),
        'citation_provenance': provenance,
        'efficiency_only': {'pure_handoff_case': case['pure_handoff'], 'model_calls': context.get('model_calls'),
            'tool_calls': context.get('tool_calls'), 'knowledge_searches': sum(c['tool_name'] == 'search_knowledge' for c in calls),
            'skill_loads': sum(c['tool_name'] == 'load_skill' for c in calls),
            'note': 'Prior read-only work is not a strong-contract failure; terminal continuation is.'},
        'semantic_review': {'status': 'PENDING_INDEPENDENT_REVIEW', 'rubric': case['semantic_rubric'],
            'instruction': 'Judge actual explanation and citation support; do not infer success from substrings or status alone.'}}


def main(args):
    protocol = contract()
    repeats = [args.repeat_id] if args.repeat_id else protocol['repeat_ids']
    binding = freeze_bindings('live')  # Only metadata/checksums; does not load either RAG JSONL.
    driver_hash = digest(Path(__file__))
    document_hashes = {f'fixtures/knowledge/{name}.md': binding['corpus_sha256'][f'fixtures/knowledge/{name}.md']
        for name in sorted({name for case in protocol['cases'] for name in case['documents']})}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    write_json(args.output_dir / 'freeze.json', {'frozen_at': now(), 'manifest': protocol,
        'manifest_sha256': MANIFEST_SHA256, 'driver_sha256': driver_hash,
        'knowledge_document_sha256': document_hashes, 'runtime': binding})
    summary = {'suite': 'handoff-development-contract-v1', 'status': 'RUNNING', 'repeat_ids': repeats,
        'expected_full_count': 16, 'affects_rag_denominator': False, 'acceptance_complete': False, 'cases': []}
    write_json(args.output_dir / 'summary.json', summary)
    for repeat in repeats:
        for case in protocol['cases']:
            path = args.output_dir / f"{case['case_id']}-r{repeat}.json"
            data = {'case_id': case['case_id'], 'expected': case, 'repeat_id': repeat, 'status': 'RUNNING',
                'run_id': 'handoff-' + uuid.uuid4().hex, 'scenario': 'handoff-development', 'seed': protocol['seed'],
                'started_at': now(), 'documents': []}
            def save():
                write_json(path.with_suffix('.tmp'), data)
                path.with_suffix('.tmp').replace(path)
            client = None
            save()
            try:
                if freeze_bindings('live') != binding or digest(Path(__file__)) != driver_hash or digest(MANIFEST) != MANIFEST_SHA256:
                    raise ValueError('frozen_versions_changed')
                client = ScenarioClient(data, save, requested_mode='live')
                client.setup(actor_ref=case['actor_ref'])
                data['actor'] = {key: client.actor[key] for key in ('subject_type', 'actor_id', 'execution_scope_id', 'permissions')}
                for name in case['documents']:
                    source = ROOT / 'fixtures/knowledge' / (name + '.md')
                    body = source.read_text()
                    draft = client.request('knowledge', {'doc_id': name, 'title': body.splitlines()[0].lstrip('# '),
                        'source_uri': str(source.relative_to(ROOT)), 'body': body, 'acl': 'PUBLIC',
                        'valid_from': (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                        'valid_until': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}, merchant=True)
                    data['documents'].append(client.request(f"knowledge/{name}/{draft['version']}/publish", {}, merchant=True))
                client.collect_index_usage()
                conversation = client.conversation()
                data['conversation_id'] = conversation
                try:
                    client.message(conversation, case['question'], label=case['category'])
                except AssertionError as error:
                    data['message_contract_error'] = str(error)
                    if not data['model_runs'] or not data['model_runs'][-1].get('run', {}).get('result'):
                        raise
                # Keep fallback outcomes and real tickets after the helper's live-mode assertion fails.
                data['conversation_after'] = client.request('conversations/' + conversation)
                data['tickets_after'] = client.request('support', merchant=True)
                data['version_errors'] = verify_attempts(data['model_runs'][0], binding)
                data['scores'] = score(case, data)
                data['scores']['deterministic_checks']['end_freeze_matches'] = (freeze_bindings('live') == binding
                    and digest(Path(__file__)) == driver_hash and digest(MANIFEST) == MANIFEST_SHA256)
                data['scores']['deterministic_checks_passed'] = all(data['scores']['deterministic_checks'].values())
                data['status'] = 'AWAITING_SEMANTIC_REVIEW' if data['scores']['deterministic_checks_passed'] else 'FAILED'
            except Exception as error:
                data.update(status='FAILED', error_type=type(error).__name__, failure_frames=[
                    {'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                    for f in traceback.extract_tb(error.__traceback__)])
            finally:
                if client: client.close()
                data['finished_at'] = now()
                save()
            summary['cases'].append({'case_id': case['case_id'], 'repeat_id': repeat, 'path': str(path),
                'sha256': digest(path), 'status': data['status'], 'actual_mode': data.get('scores', {}).get('actual_mode')})
            write_json(args.output_dir / 'summary.json', summary)
    summary.update(status='FAILED' if any(c['status'] == 'FAILED' for c in summary['cases']) else 'AWAITING_SEMANTIC_REVIEW',
                   counts=dict(Counter(c['status'] for c in summary['cases'])), completed_at=now())
    write_json(args.output_dir / 'summary.json', summary)
    print(json.dumps({'status': summary['status'], 'counts': summary['counts'], 'output': str(args.output_dir)}))
    return int(summary['status'] == 'FAILED')


def self_test():
    value = contract()
    assert value['repeat_ids'] == [1, 2] and value['max_messages_per_case'] == 1
    case = value['cases'][0]
    ticket = {'ticket_id': 'actual', 'conversation_id': 'conversation', 'status': 'OPEN'}
    receipt = {'tool_succeeded': True, 'command_status': 'command_accepted', 'evidence_id': 'call',
        'observed_at': '2026-01-01T00:00:02Z', 'data': {'ticket': ticket}}
    run = {'updated_at': '2026-01-01T00:00:03Z', 'result': {'model_mode': 'live', 'answer_status': 'needs_human',
        'handoff_origin': 'model_tool', 'ticket': ticket, 'tool_evidence_ids': ['call']},
        'context': {'model_attempts': [{'started_at': '2026-01-01T00:00:01Z'}]}}
    data = {'model_runs': [{'run': run, 'tool_receipts': [{'tool_name': 'request_handoff', 'call_id': 'call', 'receipt_json': receipt}]}],
        'tickets_after': [ticket], 'conversation_id': 'conversation', 'conversation_after': {'proposals': []}, 'actor': {}}
    assert score(case, data)['deterministic_checks_passed']
    data['message_contract_error'] = 'model_provider_receipt_missing'
    assert not score(case, data)['deterministic_checks_passed']
    del data['message_contract_error']
    run['result']['handoff_origin'] = 'controller_fallback'
    assert not score(case, data)['deterministic_checks_passed'] and score(case, data)['service_handoff_exists']
    run['result']['handoff_origin'] = 'model_tool'
    run['context']['model_attempts'].append({'started_at': '2026-01-01T00:00:04Z'})
    assert not score(case, data)['deterministic_checks']['no_activity_after_handoff']
    data['model_runs'][0]['tool_receipts'] = []
    assert not score(case, data)['deterministic_checks']['model_chose_real_handoff']
    print('Handoff development self-test passed: fixed matrix, actual receipt, fallback separation, terminal boundary. No service calls.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--repeat-id', type=int, choices=[1, 2], help='Default runs both frozen repeats; this selects one without resampling.')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test: self_test()
    else:
        if args.output_dir is None: parser.error('--output-dir is required and must not exist')
        raise SystemExit(main(args))
