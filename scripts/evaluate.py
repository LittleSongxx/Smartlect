"""Serial, resumable Final Integration evidence collection; never starts services.

CLI examples:
  evaluate.py --mode live --suite comparison --output-dir artifacts/eval-live
  evaluate.py --mode live --suite acceptance --review artifacts/review.json --freeze artifacts/rag-freeze.json

An existing failed artifact is retained, not silently sampled again. An unfinished
artifact requires recovery by its owning runner. Holdout is opened only after the
external freeze and complete development review have both been validated.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
from types import SimpleNamespace

import eval_comparison as comparison
import eval_rag as rag
import eval_tools as tool
from runtime import ROOT
from smartlect.events import canonical

REVIEW_SCHEMA = 'smartlect-acceptance-review-v1'
TERMINAL = {'PASSED', 'COMPLETED', 'FAILED', 'SETUP_FAILED', 'AWAITING_SEMANTIC_REVIEW',
            'WAIT_EXTERNAL_REQUIRED', 'NOT_TRIGGERED', 'NOT_RUN_LIVE_REQUIRED', 'VERSION_DRIFT',
            'EVIDENCE_INCOMPLETE', 'INVARIANT_EVIDENCE_INCOMPLETE'}
GATES = {
    'demo_natural_assisted_purchase': '自然入口→真实Shopping/SKU→确认/付款/退款→净额与独立归因',
    'demo_campaign_assisted_purchase': 'DRAFT/首次批准→广告A导购B→交易/退款→经营新观测→授权内动作→新流量',
    'demo_support_refund_recovery': '有引用客服→本人退款确认/原操作恢复→独立客服或人工结束',
    'legacy_purchase_stockout': '原purchase_stockout交易回归保持原名与原断言',
    'recommendation_preferences': '当前偏好影响合法排序，删除不复活，全无货为空',
    'recommendation_same_candidates': '相同候选的规则/真实语义比较，真实ranking_mode、覆盖、多样性与约束违规',
    'merchant_stockout': '真实零库存观测、售罄保护及新观测后的授权恢复',
    'merchant_creative': '同活动成熟低CTR证据、有限素材试验、实际新流量',
    'merchant_payment_failure': 'Java DECLINED事实，不能把取消/未付/超时/UNKNOWN当失败',
    'merchant_refunds': '已确认退款与净额回冲，解释不把相关当因果',
    'merchant_insufficient_evidence': '未成熟或未知事实保留判断，不制造优化动作',
    'reliability_cas_conflict': '实际版本冲突拒绝，不覆盖旧版本或扩大授权',
    'reliability_duplicate_payment': '重复支付确认/回调保留单一金额与明细效果',
    'reliability_unacked_replay': '提交未ACK→真实重投/消费者重启→原raw_json/fingerprint及账本不变',
    'reliability_delayed_refund': '实际延迟/乱序退款最终归属原支付及冻结归因，无重复入账',
    'reliability_grant_expiry_revoke': '过期/撤销授权不产生新写，旧完整回执仍可恢复',
    'ui_shopping_confirmation': '真实用户界面导购、引用、具体确认、独立付款与原操作恢复',
    'ui_merchant_authorization': '管理界面首次审批、稳定grant、计划/trace/回执及经验人工批准',
    'ui_support_conversation': '实际完整上下文/引用/当前提案，接管/回复/结束及owner拒绝',
    'ui_first_visible_text': '真正可见正文首字/首完整结果，区分进度事件与用户等待',
    'financial_three_way_details': 'Java逐明细金额/库存、账本、广告与推荐独立归因一致，净额不重复相加',
    'reset_registered_scope': 'Java权限内注册资源重置、未知/跨scope拒绝、重复重置与旧消息隔离',
    'independent_namespace': '仅Smartlect源码/冻结ZIP与独立资源，密钥无前端/提交/输出泄漏',
}


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n'); temporary.replace(path)


def fingerprint(value):
    return sha256(canonical(value).encode()).hexdigest()


def blocked_report(directory, status, reason, checkpoint):
    path = directory / 'acceptance.json'
    if path.exists():
        archive = directory / ('acceptance.previous-' + rag.digest(path)[:16] + '.json')
        if not archive.exists(): archive.write_bytes(path.read_bytes())
    write(path, {'status': status, 'reason': reason, 'checkpoint': str(checkpoint), 'existing_artifacts_retained': True})
    print(status + ': ' + str(checkpoint), flush=True)
    return 3


def resolve(base, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def pointer(value, path):
    if path == '': return value
    if not path.startswith('/'): raise ValueError('invalid_json_pointer')
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def checked_ref(reference, base):
    path = resolve(base, reference['artifact'])
    if not path.is_file() or rag.digest(path) != reference['sha256']: raise ValueError('evidence_hash_mismatch:' + str(path))
    value = pointer(read(path), reference.get('pointer', '')) if 'pointer' in reference or path.suffix == '.json' else None
    return path, value


def review_file(path):
    if path is None or not path.exists(): return None
    value = read(path); reviewer = value.get('reviewer', {})
    if (value.get('schema_version') != REVIEW_SCHEMA or reviewer.get('method') not in {'human', 'independent_evidence_review'}
            or reviewer.get('subject_model_self_review') is not False or not reviewer.get('id') or not value.get('reviewed_at')):
        raise ValueError('review_requires_identified_independent_evidence_reviewer')
    value['_base'] = path.parent; return value


def case_review(path, review):
    if not review: return None
    matches = [r for r in review.get('case_reviews', []) if resolve(review['_base'], r['artifact']) == path.resolve()]
    if len(matches) != 1: return None
    item = matches[0]
    checked_ref(item, review['_base'])
    if item.get('verdict') not in {'pass', 'fail'} or not item.get('rationale') or not item.get('evidence_refs'):
        raise ValueError('case_review_missing_verdict_rationale_or_evidence')
    for ref in item['evidence_refs']: checked_ref(ref, review['_base'])
    if item.get('violations') and item['verdict'] == 'pass': raise ValueError('violating_case_cannot_be_reviewed_pass')
    for name, numerator in (('citation_support', 'supported'), ('fact_completeness', 'satisfied')):
        metric = item.get(name)
        if metric is not None and not (type(metric.get(numerator)) is int and type(metric.get('total')) is int
                                      and 0 <= metric[numerator] <= metric['total']):
            raise ValueError('invalid_review_metric:' + name)
    return item


def bindings(mode):
    return {'runtime': rag.freeze_bindings(mode), 'tools': tool.tool_bindings(mode),
        'comparison_protocol_sha256': rag.digest(comparison.PROTOCOL_PATH),
        'comparison_driver_sha256': rag.digest(ROOT / 'scripts/eval_comparison.py'),
        'evaluation_driver_sha256': rag.digest(Path(__file__))}


def annotate(path, row, execution):
    return {'artifact': str(path), 'sha256': rag.digest(path), 'execution': execution, 'data': row}


def step(state, state_path, step_id, path, expected, valid, execute):
    prior = state['steps'].get(step_id)
    if prior and prior['binding_sha256'] != fingerprint(expected):
        return {'checkpoint': str(path), 'status': 'WAIT_BINDING_MISMATCH', 'step': step_id}
    if path.exists():
        try: row = read(path)
        except (ValueError, OSError): return {'checkpoint': str(path), 'status': 'WAIT_ARTIFACT_RECOVERY', 'step': step_id}
        if not valid(row): return {'checkpoint': str(path), 'status': 'WAIT_BINDING_MISMATCH', 'step': step_id}
        if row.get('status') not in TERMINAL:
            return {'checkpoint': str(path), 'status': 'WAIT_EXISTING_CASE_RECOVERY', 'step': step_id}
        state['steps'][step_id] = {'binding_sha256': fingerprint(expected), 'status': row['status'],
            'artifact': str(path), 'sha256': rag.digest(path), 'last_operation': 'read_existing_artifact', 'checked_at': now()}
        write(state_path, state); print('READ_EXISTING', step_id, row['status'], flush=True)
        return annotate(path, row, 'read_existing_artifact_not_new_execution')
    if prior and prior['status'] in {'RUNNING', 'WAIT_EXECUTION_RECOVERY'}:
        return {'checkpoint': str(path), 'status': 'WAIT_MISSING_RUNNING_ARTIFACT', 'step': step_id}
    state['steps'][step_id] = {'binding_sha256': fingerprint(expected), 'status': 'RUNNING', 'artifact': str(path), 'started_at': now()}
    write(state_path, state); print('EXECUTE_NEW', step_id, flush=True)
    try: execute()
    except (ValueError, OSError) as error:
        state['steps'][step_id].update(status='WAIT_EXECUTION_RECOVERY', error_type=type(error).__name__, reason=str(error))
        write(state_path, state)
        return {'status': 'WAIT_EXECUTION_RECOVERY', 'checkpoint': str(path), 'reason': str(error), 'step': step_id}
    if not path.exists(): return {'checkpoint': str(path), 'status': 'WAIT_EXECUTION_ARTIFACT', 'step': step_id}
    row = read(path)
    if not valid(row): return {'checkpoint': str(path), 'status': 'WAIT_BINDING_MISMATCH', 'step': step_id}
    state['steps'][step_id].update(status=row.get('status', 'UNKNOWN'), sha256=rag.digest(path), last_operation='executed_now', finished_at=now())
    write(state_path, state); return annotate(path, row, 'executed_now')


def guarded(binding, current, execute):
    if current() != binding: raise ValueError('source_or_config_drift_during_suite; no new case was started')
    return execute()


def suite_directory(path, expected):
    manifest = path / 'run.json'
    if manifest.exists():
        current = read(manifest)
        if any(current.get(key) != value for key, value in expected.items()): raise ValueError('existing_suite_manifest_mismatch:' + str(manifest))
    elif path.exists() and any(path.iterdir()):
        raise ValueError('existing_directory_without_bound_manifest:' + str(path))
    else:
        path.mkdir(parents=True, exist_ok=True); write(manifest, {**expected, 'started_at': now()})


def rag_suite(args, state, state_path, directory, binding, split, review, development):
    freeze = None
    if split == 'holdout':
        if not development or not development.get('review_complete'):
            return {'status': 'WAIT_DEVELOPMENT_REVIEW', 'checkpoint': str(args.review) if args.review else 'provide --review', 'artifacts': []}
        try:
            freeze = rag.verify_freeze(args.freeze, binding)
        except (ValueError, OSError, KeyError) as error:
            return {'status': 'WAIT_HOLDOUT_FREEZE', 'reason': str(error), 'checkpoint': str(args.freeze) if args.freeze else 'provide --freeze', 'artifacts': []}
    manifest = read(rag.MANIFEST)
    # The held-out file is never opened before both preceding checks succeed.
    cases = rag.select_cases(ROOT / manifest['dataset_file'] if split == 'holdout' else rag.DEVELOPMENT,
                             manifest, split, whole_dataset=split == 'holdout')
    try: suite_directory(directory, {'bindings': binding, 'split': split, 'case_ids': [c['case_id'] for c in cases], 'repeat': args.repeat, 'smoke': False})
    except ValueError as error: return {'status': 'WAIT_BINDING_MISMATCH', 'reason': str(error), 'checkpoint': str(directory / 'run.json'), 'artifacts': []}
    artifacts = []
    for repeat in range(1, args.repeat + 1):
        for case in cases:
            path = directory / f"{case['case_id']}-r{repeat}.json"
            valid = lambda row: row.get('case_id') == case['case_id'] and row.get('repeat_id') == repeat and row.get('split') == split and row.get('freeze_binding_sha256') == fingerprint(binding)
            artifacts.append(step(state, state_path, f'rag:{split}:{case["case_id"]}:{repeat}', path, binding, valid,
                lambda: guarded(binding, lambda: rag.freeze_bindings(args.mode), lambda: rag.execute_case(case, repeat, path, args.mode, manifest, binding))))
            # A stale HTTP process is caught on the first new trace. Continuing would bill 64
            # live calls that cannot pass frozen_run_versions_match.
            if artifacts[-1].get('execution') == 'executed_now' and trace_version_drift(artifacts[-1].get('data') or {}):
                break
        if artifacts and artifacts[-1].get('execution') == 'executed_now' and trace_version_drift(artifacts[-1].get('data') or {}):
            break
    return assess_rag(artifacts, len(cases) * args.repeat, review, split)


def trace_version_drift(row):
    return sorted({error for turn in row.get('turns') or [] for error in (turn.get('version_errors') or [])})


def assess_rag(artifacts, expected_count, review, split):
    ready = [item for item in artifacts if 'data' in item]
    inspected, critical, quality, review_errors = [], [], [], []
    safety = {'citation_locations_valid', 'at_most_four_citations', 'no_forbidden_new_candidates', 'no_forbidden_new_citations',
              'no_literal_canary_in_output', 'frozen_run_versions_match', 'required_human_ticket_persisted', 'no_confirmed_transactions'}
    for item in ready:
        row = item['data']
        try: judged = case_review(Path(item['artifact']), review)
        except (ValueError, OSError, KeyError, IndexError) as error:
            judged = None; review_errors.append({'artifact': item['artifact'], 'reason': str(error)})
        required_facts = len(row.get('expected', {}).get('must_include_facts', []))
        fact_metric = (judged or {}).get('fact_completeness') or {}
        citations_present = any((turn.get('run') or {}).get('result', {}).get('citations') for turn in row.get('turns', []) if (turn.get('run') or {}).get('result'))
        if judged and fact_metric.get('total') == required_facts and isinstance(judged.get('violations'), list) and (
                not citations_present or (judged.get('citation_support') or {}).get('total', 0) > 0) and (
                not row.get('expected', {}).get('human_ticket_required') or type(judged.get('refusal_correct')) is bool): inspected.append(judged)
        if row.get('index_collection_error') or row.get('index_version_errors') or any(t.get('collection_error') for t in row.get('turns', [])):
            critical.append({'artifact': item['artifact'], 'check': 'attempt_or_retrieval_evidence_incomplete'})
        for name, passed in row.get('scores', {}).get('checks', {}).items():
            if passed is not True: (critical if name in safety else quality).append({'artifact': item['artifact'], 'check': name})
        if judged and judged['verdict'] == 'fail': quality.append({'artifact': item['artifact'], 'review': 'fail'})
        if judged and judged.get('violations'): critical.append({'artifact': item['artifact'], 'review_violations': judged['violations']})
    executed = len(ready) == expected_count and all(r['data'].get('scores') is not None and not r['data'].get('version_errors')
        and r['data'].get('status') in {'FAILED', 'AWAITING_SEMANTIC_REVIEW'} for r in ready)
    review_complete = executed and len(inspected) == expected_count
    metrics = {}
    for k in (4, 8):
        values = [r['data']['scores'][f'retrieval_recall_at_{k}'] for r in ready if r['data'].get('scores', {}).get(f'retrieval_recall_at_{k}') is not None]
        metrics[f'recall_at_{k}'] = {'value': statistics.fmean(values) if values else None, 'denominator': len(values)}
    for name, numerator in (('citation_support', 'supported'), ('fact_completeness', 'satisfied')):
        values = [r[name] for r in inspected if r.get(name) is not None]
        total = sum(v['total'] for v in values)
        metrics[name] = {'value': sum(v[numerator] for v in values) / total if total else None, 'denominator': total}
    refusal = [r['refusal_correct'] for r in inspected if type(r.get('refusal_correct')) is bool]
    metrics['correct_refusal_or_handoff'] = {'value': sum(refusal) / len(refusal) if refusal else None, 'denominator': len(refusal)}
    status = 'WAIT_EXECUTION_OR_RECOVERY' if not executed else 'WAIT_SEMANTIC_REVIEW' if not review_complete else 'FAILED_SAFETY' if critical else 'EVALUATED_WITH_QUALITY_FAILURES' if quality else 'PASS'
    return {'status': status, 'split': split, 'expected_case_repeats': expected_count, 'executed_case_repeats': sum(bool(r['data'].get('scores')) for r in ready),
        'review_complete': review_complete, 'reviewed_case_repeats': len(inspected), 'metrics': metrics, 'critical_failures': critical,
        'quality_failures': quality, 'review_errors': review_errors, 'artifacts': artifacts, 'checkpoints': [r for r in artifacts if 'data' not in r],
        'interpretation': 'RAG has no invented 100% answer threshold; reviewed quality failures remain explicit. Required handoff/safety failures block acceptance.'}


def tools_suite(args, state, state_path, directory, binding, review):
    cases = tool.load_contracts()
    try: suite_directory(directory, {'bindings': binding, 'task_ids': [c['task_id'] for c in cases], 'repeat': args.repeat, 'seed': 42, 'subset': False})
    except ValueError as error: return {'status': 'WAIT_BINDING_MISMATCH', 'reason': str(error), 'checkpoint': str(directory / 'run.json'), 'artifacts': []}
    artifacts = []
    for repeat in range(1, args.repeat + 1):
        for case in cases:
            path = directory / f"{case['task_id']}-r{repeat}.json"
            valid = lambda row: row.get('task_id') == case['task_id'] and row.get('repeat_id') == repeat and row.get('version_bindings') == binding and row.get('contract_sha256') == tool.FROZEN_DATASET
            artifacts.append(step(state, state_path, f'tools:{case["task_id"]}:{repeat}', path, binding, valid,
                lambda: guarded(binding, lambda: tool.tool_bindings(args.mode), lambda: tool.run_case(case, repeat, args.mode, path, binding))))
            if artifacts[-1].get('data', {}).get('status') == 'WAIT_EXTERNAL_REQUIRED':
                break  # The original pending proposal may expire while later cases run.
        if artifacts and artifacts[-1].get('data', {}).get('status') == 'WAIT_EXTERNAL_REQUIRED':
            break
    effective, pending = [], []
    for item in artifacts:
        if 'data' not in item: pending.append(item); continue
        row = dict(item['data'])
        if row['status'] == 'AWAITING_SEMANTIC_REVIEW':
            try: judged = case_review(Path(item['artifact']), review)
            except (ValueError, OSError, KeyError, IndexError) as error:
                judged = None; pending.append({'status': 'WAIT_REVIEW_REPAIR', 'checkpoint': item['artifact'], 'reason': str(error)})
            if judged: row['status'] = 'PASSED' if judged['verdict'] == 'pass' and not judged.get('violations') else 'FAILED'
            else: pending.append({'status': 'WAIT_SEMANTIC_REVIEW', 'checkpoint': item['artifact']})
        if row['status'] == 'WAIT_EXTERNAL_REQUIRED':
            pending.append({'status': row['status'], 'checkpoint': item['artifact'], 'requirement': row.get('external_requirement'),
                'resume_command': f"growth/.venv/bin/python scripts/eval_tools.py --mode {args.mode} --resume-case {item['artifact']}"})
        effective.append(row)
    report = tool.summarize(effective, len(cases) * args.repeat, subset=False)
    external = next((item for item in pending if item['status'] == 'WAIT_EXTERNAL_REQUIRED'), None)
    return {'status': 'WAIT_EXTERNAL_REQUIRED' if external else 'PASS' if report['target_met'] and not pending else 'WAIT_REVIEW_OR_EXTERNAL' if pending else 'FAILED_OR_INCOMPLETE',
            'report': report, 'artifacts': artifacts, 'checkpoints': pending, 'collection_paused': external is not None,
            'external_checkpoint': external, 'not_started_case_repeats': len(cases) * args.repeat - len(artifacts)}


def comparison_suite(args, state, state_path, directory, binding, inputs):
    artifacts = []
    for repeat in range(1, args.repeat + 1):
        path = inputs.get(f'comparison_r{repeat}', directory / f'comparison-r{repeat}.json')
        sidecar = path.with_suffix('.binding.json'); progress = path.with_suffix('.progress.json')
        defaults = comparison.PROTOCOL['defaults']
        dimensions = {'rounds': 2 if args.smoke else defaults['rounds'],
            'opportunities_per_round': 8 if args.smoke else defaults['opportunities_per_round'],
            'users': 4 if args.smoke else defaults['users'], 'products': 2 if args.smoke else defaults['products'],
            'campaigns': 1 if args.smoke else defaults['campaigns'], 'creatives_per_campaign': 1 if args.smoke else defaults['creatives_per_campaign']}
        seeds = [42] if args.smoke else list(comparison.SEEDS)
        expected = {'runtime': binding['runtime'], 'protocol_sha256': binding['comparison_protocol_sha256'],
                    'driver_sha256': binding['comparison_driver_sha256'], 'repeat_id': repeat, 'mode': 'live' if args.mode == 'live' else 'rule',
                    'seeds': seeds, 'dimensions': dimensions}
        if args.smoke: expected['smoke'] = True
        if sidecar.exists() and read(sidecar).get('bindings') != expected:
            artifacts.append({'status': 'WAIT_BINDING_MISMATCH', 'checkpoint': str(sidecar)}); continue
        if path.exists() and not sidecar.exists():
            artifacts.append({'status': 'WAIT_BINDING_PROOF', 'checkpoint': str(path), 'reason': 'No startup-time comparison binding sidecar; current settings cannot backfill old provenance.'}); continue
        if not path.exists() and (progress.exists() or path.with_suffix('').exists()):
            artifacts.append({'status': 'WAIT_COMPARISON_RECOVERY', 'checkpoint': str(progress), 'reason': 'Existing branch resources are retained; no automatic new run or new seed.'}); continue
        if not sidecar.exists(): write(sidecar, {'bindings': expected, 'bound_at': now(), 'purpose': 'captured_before_comparison_execution'})
        options = SimpleNamespace(mode=expected['mode'], seeds=seeds, rounds=dimensions['rounds'],
            opportunities=dimensions['opportunities_per_round'], users=dimensions['users'], products=dimensions['products'],
            campaigns=dimensions['campaigns'], creatives=dimensions['creatives_per_campaign'], repeat_id=repeat,
            smoke=args.smoke, output=path, progress=progress)
        valid = lambda row: row.get('repeat_id') == repeat and row.get('mode') == expected['mode'] and row.get('smoke') is args.smoke and row.get('seeds') == options.seeds and row.get('dimensions') == dimensions and row.get('protocol_sha256') == expected['protocol_sha256'] and row.get('comparison_driver_sha256') == expected['driver_sha256']
        artifacts.append(step(state, state_path, 'comparison:' + str(repeat), path, expected, valid, lambda: guarded(expected,
            lambda: {**expected, 'runtime': rag.freeze_bindings(args.mode), 'protocol_sha256': rag.digest(comparison.PROTOCOL_PATH),
                     'driver_sha256': rag.digest(ROOT / 'scripts/eval_comparison.py')}, lambda: comparison.main(options))))
    ready = [r['data'] for r in artifacts if 'data' in r]
    complete = len(ready) == args.repeat and all(r['status'] == 'COMPLETED' and len(r['branches']) == (4 if args.smoke else 12) and
        all(b['status'] == 'COMPLETED' and b.get('stock_reconciled_to_individual_orders') for b in r['branches']) for r in ready)
    return {'status': ('SMOKE_COMPLETED' if args.smoke else 'PASS') if complete else 'WAIT_EXECUTION_OR_RECOVERY', 'artifacts': artifacts,
        'paired_results_by_repeat': [{'repeat_id': r['repeat_id'], 'report': r.get('paired_report')} for r in ready],
        'checkpoints': [r for r in artifacts if 'data' not in r], 'claim': 'Actual synthetic paired outcomes only; negative or zero differences are retained.'}


def external_gates(review, binding):
    results = {}
    for gate_id, requirement in GATES.items():
        matches = [g for g in (review or {}).get('gate_reviews', []) if g.get('gate_id') == gate_id]
        result = {'status': 'WAIT_EVIDENCE_REVIEW', 'requirement': requirement, 'gate_id': gate_id}
        if len(matches) == 1:
            item = matches[0]
            if not item.get('rationale') or not item.get('evidence_refs') or not item.get('checks'):
                result['reason'] = 'gate_review_requires_concrete_refs_and_checks'
            elif item.get('execution_bindings') not in (binding['runtime'], binding['tools']):
                result['reason'] = 'gate_execution_binding_missing_or_mismatched'
            else:
                try:
                    refs = [checked_ref(ref, review['_base'])[1] for ref in item['evidence_refs']]
                    checks = [canonical(pointer(refs[c['evidence_ref']], c.get('pointer', ''))) == canonical(c['expected']) for c in item['checks']]
                    metrics = {name: pointer(refs[location['evidence_ref']], location.get('pointer', ''))
                        for name, location in item.get('metrics', {}).items() if isinstance(location, dict) and 'evidence_ref' in location}
                    result.update(status='PASS' if item.get('verdict') == 'pass' and all(checks) else 'FAILED',
                        evidence_refs=item['evidence_refs'], checks_passed=checks, rationale=item['rationale'], metrics=metrics or None)
                except (ValueError, OSError, KeyError, IndexError) as error: result.update(status='WAIT_REVIEW_REPAIR', reason=str(error))
        results[gate_id] = result
    return results


def cost_report(artifacts):
    attempts, admissions = {}, {}
    def visit(value):
        if isinstance(value, list):
            for row in value: visit(row)
        elif isinstance(value, dict):
            context = value.get('context')
            if value.get('agent_run_id') and isinstance(context, dict):
                admissions[value['agent_run_id']] = max(admissions.get(value['agent_run_id'], 0), context.get('model_calls', 0))
            indexed = value.get('call_id') and isinstance(value.get('trace_json'), dict)
            if indexed:
                key = ('index_call', value['call_id']); trace = value['trace_json']
                if key not in attempts or trace.get('status') != 'started': attempts[key] = trace
            if 'model_id' in value and 'status' in value and 'usage' in value and ('latency_ms' in value or 'purpose' in value):
                key = (value.get('started_at'), value.get('model_id'), value.get('attempt'), value.get('prompt_version'), value.get('status'))
                attempts[key] = value
            for name, row in value.items():
                if not (indexed and name == 'trace_json'): visit(row)
    for artifact in artifacts:
        if 'data' in artifact: visit(artifact['data'])
    groups = {}
    for attempt in attempts.values(): groups.setdefault(attempt.get('model_mode') or 'unknown', []).append(attempt)
    def percentile(values, fraction):
        values = sorted(values)
        return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None
    output = {}
    for mode, rows in groups.items():
        costs = [r['cost_estimate_cny'] for r in rows if type(r.get('cost_estimate_cny')) in {int, float}]
        latency = [r['latency_ms'] for r in rows if type(r.get('latency_ms')) in {int, float}]
        tokens = [r.get('usage', {}).get('total_tokens') for r in rows]
        output[mode] = {'attempt_count': len(rows), 'failed_attempts': sum(r['status'] == 'failed' for r in rows),
            'known_tokens': sum(v for v in tokens if type(v) is int) if any(type(v) is int for v in tokens) else None,
            'unknown_usage_attempts': sum(type(v) is not int for v in tokens), 'known_estimated_cost_cny': sum(costs) if costs else None,
            'unknown_cost_attempts': len(rows) - len(costs), 'latency_samples': len(latency), 'p50_ms': percentile(latency, .50), 'p95_ms': percentile(latency, .95)}
    return {'modes': output, 'recorded_run_admissions': sum(admissions.values()) if admissions else None,
        'untraced_run_admissions': max(0, sum(admissions.values()) - sum(key[0] != 'index_call' for key in attempts)) if admissions else None,
        'attempt_deduplication': 'index call_id; otherwise started_at/model_id/attempt/prompt_version/status; copied traces counted once',
        'percentile_method': 'nearest-rank ceil(n*p), actual samples only', 'ui_first_visible_text_ms': None,
        'note': 'Provider latency is not first visible UI text. Unknown tokens/cost remain unknown; estimates are not invoices.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['live', 'mock'], required=True)
    parser.add_argument('--suite', choices=['acceptance', 'rag', 'tools', 'comparison'], default='acceptance')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--repeat', type=int, choices=[1, 2], default=2)
    parser.add_argument('--split', choices=['development', 'holdout'], default='development')
    parser.add_argument('--review', type=Path)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--smoke', action='store_true', help='Comparison only: seed42, two rounds, eight opportunities each, four users/two products; never formal acceptance')
    args = parser.parse_args(argv)
    if args.smoke and args.suite != 'comparison': parser.error('--smoke is only for the standalone comparison suite')
    directory = (args.output_dir or ROOT / 'artifacts' / ('eval-' + args.mode)).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.evaluate.lock').open('w') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: print('WAIT_ACTIVE_EVALUATION: ' + str(directory)); return 3
        try: current = bindings(args.mode)
        except (ValueError, OSError) as error: return blocked_report(directory, 'WAIT_ENVIRONMENT_BINDING', str(error), 'install/configure the reviewed local source before evaluation')
        state_path = directory / 'evaluation-state.json'
        state = read(state_path) if state_path.exists() else {'schema_version': 'smartlect-evaluation-state-v1', 'bindings': current, 'steps': {}, 'created_at': now()}
        if state['bindings'] != current:
            return blocked_report(directory, 'WAIT_BINDING_MISMATCH', 'Use an explicit new output directory for intentionally changed versions; old evidence is retained.', state_path)
        write(state_path, state)
        input_data = read(args.inputs) if args.inputs else {}
        inputs = {key: resolve(args.inputs.parent, value) for key, value in input_data.get('suites', {}).items()}
        try: review = review_file(args.review)
        except (ValueError, OSError, KeyError) as error:
            return blocked_report(directory, 'WAIT_REVIEW_REPAIR', str(error), args.review)
        reports = {}
        if args.suite in {'acceptance', 'rag'}:
            development = rag_suite(args, state, state_path, inputs.get('rag_development', directory / 'rag-development'), current['runtime'], 'development', review, None)
            reports['rag_development'] = development
            if args.suite == 'acceptance' or args.split == 'holdout':
                reports['rag_holdout'] = rag_suite(args, state, state_path, inputs.get('rag_holdout', directory / 'rag-holdout'), current['runtime'], 'holdout', review, development)
        if args.suite in {'acceptance', 'tools'}:
            reports['tools'] = tools_suite(args, state, state_path, inputs.get('tools', directory / 'tools'), current['tools'], review)
        if args.suite in {'acceptance', 'comparison'}:
            if reports.get('tools', {}).get('collection_paused'):
                reports['comparison'] = {'status': 'WAIT_TOOLS_EXTERNAL_RECOVERY', 'artifacts': [],
                    'checkpoints': [reports['tools']['external_checkpoint']]}
            else:
                reports['comparison'] = comparison_suite(args, state, state_path, directory, current, inputs)
        gates = external_gates(review, current) if args.suite == 'acceptance' else {}
        for gate_id, refs in input_data.get('gate_evidence', {}).items():
            if gate_id in gates:
                try:
                    for ref in refs: checked_ref(ref, args.inputs.parent)
                    gates[gate_id]['available_evidence'] = refs
                except (ValueError, OSError, KeyError) as error: gates[gate_id].update(status='WAIT_EVIDENCE_REPAIR', reason=str(error))
        artifacts = [r for report in reports.values() for r in report.get('artifacts', [])]
        success = all(r['status'] in {'PASS', 'EVALUATED_WITH_QUALITY_FAILURES', 'SMOKE_COMPLETED'} for r in reports.values()) and all(g['status'] == 'PASS' for g in gates.values())
        if args.suite == 'acceptance' and (args.mode != 'live' or args.repeat != 2):
            gates['live_two_repeats'] = {'status': 'WAIT_LIVE_TWO_REPEATS', 'requirement': '同版本live至少两次，mock/单次不能完成最终验收'}; success = False
        # The report contains references and summaries, not another copy of every raw case/corpus.
        for report in reports.values():
            report['artifacts'] = [{k: v for k, v in item.items() if k != 'data'} for item in report.get('artifacts', [])]
        result = {'schema_version': 'smartlect-acceptance-v1', 'status': ('SMOKE_COMPLETED' if args.smoke else 'PASS') if success else 'INCOMPLETE', 'suite': args.suite,
            'mode': args.mode, 'repeat': args.repeat, 'checked_at': now(), 'bindings_sha256': fingerprint(current),
            'suites': reports, 'gates': gates, 'costs': cost_report(artifacts),
            'checkpoint': str(state_path), 'claim': 'Existing evidence reads are labelled; omitted/failed/review-pending gates never become green by resampling.'}
        if gates.get('ui_first_visible_text', {}).get('status') == 'PASS':
            result['costs']['ui_first_visible_text'] = gates['ui_first_visible_text']['metrics']
        write(directory / 'acceptance.json', result)
        print(result['status'] + ': ' + str(directory / 'acceptance.json'), flush=True)
        return 0 if success else 3


if __name__ == '__main__':
    raise SystemExit(main())
