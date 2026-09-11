"""Local evidence/orchestration checks: no runtime config, DB, model or subprocess."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import evaluate as driver


class EvaluationTests(unittest.TestCase):
    def test_matching_failed_artifact_is_read_without_rerun_or_deletion(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'case.json'
            driver.write(path, {'status': 'FAILED', 'binding': 'same'})
            execute = Mock(); state = {'steps': {}}
            result = driver.step(state, root / 'state.json', 'case', path, {'binding': 'same'}, lambda r: r['binding'] == 'same', execute)
            execute.assert_not_called(); self.assertEqual(result['data']['status'], 'FAILED')
            self.assertEqual(result['execution'], 'read_existing_artifact_not_new_execution')
            self.assertEqual(driver.read(path)['status'], 'FAILED')

    def test_partial_or_mismatched_artifacts_never_allocate_another_case(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'case.json'; execute = Mock()
            driver.write(path, {'status': 'RUNNING'})
            result = driver.step({'steps': {}}, root / 'state.json', 'case', path, {}, lambda r: True, execute)
            self.assertEqual(result['status'], 'WAIT_EXISTING_CASE_RECOVERY')
            result = driver.step({'steps': {}}, root / 'state.json', 'case', path, {}, lambda r: False, execute)
            self.assertEqual(result['status'], 'WAIT_BINDING_MISMATCH'); execute.assert_not_called()

    def test_holdout_reader_is_unreachable_without_review_and_external_freeze(self):
        args = SimpleNamespace(review=None, freeze=None, mode='live', repeat=2)
        with patch.object(driver.rag, 'select_cases') as selector:
            result = driver.rag_suite(args, {}, Path('unused'), Path('unused'), {}, 'holdout', None, None)
            self.assertEqual(result['status'], 'WAIT_DEVELOPMENT_REVIEW')
            result = driver.rag_suite(args, {}, Path('unused'), Path('unused'), {}, 'holdout', {}, {'review_complete': True})
            self.assertEqual(result['status'], 'WAIT_HOLDOUT_FREEZE'); selector.assert_not_called()

    def test_comparison_partial_progress_is_a_checkpoint_not_a_new_sample(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); driver.write(root / 'comparison-r1.progress.json', {'status': 'RUNNING'})
            args = SimpleNamespace(repeat=1, mode='live', smoke=False)
            binding = {'runtime': {}, 'comparison_protocol_sha256': 'protocol', 'comparison_driver_sha256': 'driver'}
            with patch.object(driver.comparison, 'main') as execute:
                report = driver.comparison_suite(args, {'steps': {}}, root / 'state.json', root, binding, {})
                execute.assert_not_called(); self.assertEqual(report['checkpoints'][0]['status'], 'WAIT_COMPARISON_RECOVERY')

    def test_tools_pause_at_external_checkpoint_and_resume_only_unstarted_cases(self):
        cases = driver.tool.load_contracts()
        names = driver.read(driver.tool.MANIFEST)['strong_invariants']
        called = []
        def execute(case, repeat, mode, path, binding):
            called.append((case['task_id'], repeat))
            waiting = case['task_id'] in {'tool-008', 'tool-013'}
            row = {'task_id': case['task_id'], 'task_kind': case['kind'], 'repeat_id': repeat,
                'version_bindings': binding, 'contract_sha256': driver.tool.FROZEN_DATASET,
                'status': 'WAIT_EXTERNAL_REQUIRED' if waiting else 'PASSED', 'expected': case['expected'],
                'external_requirement': 'root-controlled fixture',
                'invariants': {name: {'violations': None if waiting else 0, 'checks': []} for name in names}}
            driver.write(path, row); return row
        with TemporaryDirectory() as temp, patch.object(driver.tool, 'tool_bindings', return_value={}), patch.object(driver.tool, 'run_case', side_effect=execute):
            root = Path(temp); directory = root / 'tools'; state = {'steps': {}}
            args = SimpleNamespace(repeat=2, mode='live')
            report = driver.tools_suite(args, state, root / 'state.json', directory, {}, None)
            self.assertEqual(called, [(c['task_id'], 1) for c in cases[:8]])
            self.assertTrue(report['collection_paused']); self.assertEqual(report['status'], 'WAIT_EXTERNAL_REQUIRED')
            self.assertEqual(report['report']['expected_case_repeats'], 40)
            self.assertEqual(report['not_started_case_repeats'], 32)
            self.assertFalse(report['report']['target_met'])
            self.assertFalse((directory / 'tool-009-r1.json').exists())
            self.assertFalse((directory / 'tool-001-r2.json').exists())
            driver.tools_suite(args, state, root / 'state.json', directory, {}, None)
            self.assertEqual(len(called), 8, 'Waiting original checkpoint must not be recreated')
            checkpoint = directory / 'tool-008-r1.json'; resumed = driver.read(checkpoint)
            resumed['status'] = 'PASSED'
            for value in resumed['invariants'].values(): value['violations'] = 0
            driver.write(checkpoint, resumed)
            report = driver.tools_suite(args, state, root / 'state.json', directory, {}, None)
            self.assertEqual(called, [(c['task_id'], 1) for c in cases[:13]])
            self.assertEqual(report['external_checkpoint']['checkpoint'], str(directory / 'tool-013-r1.json'))
            self.assertEqual(report['report']['expected_case_repeats'], 40)
            self.assertFalse((directory / 'tool-014-r1.json').exists())

    def test_comparison_smoke_writes_binding_first_and_second_call_only_reads(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); args = SimpleNamespace(repeat=1, mode='mock', smoke=True)
            binding = {'runtime': {}, 'comparison_protocol_sha256': driver.rag.digest(driver.comparison.PROTOCOL_PATH),
                       'comparison_driver_sha256': driver.rag.digest(driver.ROOT / 'scripts/eval_comparison.py')}
            def execute(options):
                self.assertTrue(options.output.with_suffix('.binding.json').exists())
                self.assertEqual((options.mode, options.seeds, options.rounds, options.opportunities), ('rule', [42], 2, 8))
                self.assertEqual(driver.read(options.output.with_suffix('.binding.json'))['bindings']['dimensions']['rounds'], 2)
                driver.write(options.output, {'status': 'COMPLETED', 'repeat_id': 1, 'mode': 'rule', 'smoke': True,
                    'seeds': [42], 'protocol_sha256': binding['comparison_protocol_sha256'], 'comparison_driver_sha256': binding['comparison_driver_sha256'],
                    'dimensions': {'rounds': 2, 'opportunities_per_round': 8, 'users': 4, 'products': 2, 'campaigns': 1, 'creatives_per_campaign': 1},
                    'branches': [{'status': 'COMPLETED', 'stock_reconciled_to_individual_orders': True} for _ in range(4)]})
            state = {'steps': {}}
            with patch.object(driver.rag, 'freeze_bindings', return_value={}), patch.object(driver.comparison, 'main', side_effect=execute) as call:
                self.assertEqual(driver.comparison_suite(args, state, root / 'state.json', root, binding, {})['status'], 'SMOKE_COMPLETED')
                self.assertEqual(driver.comparison_suite(args, state, root / 'state.json', root, binding, {})['status'], 'SMOKE_COMPLETED')
                self.assertEqual(call.call_count, 1)
                old_path = root / 'comparison-r1.json'; old = driver.read(old_path); old['dimensions']['rounds'] = 1
                driver.write(old_path, old)
                old_binding_path = old_path.with_suffix('.binding.json'); old_binding = driver.read(old_binding_path)
                old_binding['bindings']['dimensions']['rounds'] = 1; driver.write(old_binding_path, old_binding)
                retained = old_path.read_bytes()
                report = driver.comparison_suite(args, state, root / 'state.json', root, binding, {})
                self.assertEqual(report['checkpoints'][0]['status'], 'WAIT_BINDING_MISMATCH')
                self.assertEqual(old_path.read_bytes(), retained); self.assertEqual(call.call_count, 1)

    def test_new_rag_trace_version_drift_stops_further_cases(self):
        cases = [{'case_id': 'one'}, {'case_id': 'two'}]
        called = []
        def execute_case(case, repeat, path, mode, manifest, binding):
            called.append(case['case_id'])
            driver.write(path, {'case_id': case['case_id'], 'repeat_id': repeat, 'split': 'development',
                'freeze_binding_sha256': driver.fingerprint(binding), 'status': 'FAILED',
                'scores': {'checks': {'frozen_run_versions_match': False}},
                'turns': [{'version_errors': ['prompt_version_drift_or_missing']}]})
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'manifest.json').write_text(json.dumps({'dataset_file': 'unused'}))
            args = SimpleNamespace(repeat=2, mode='live', freeze=None, review=None)
            with patch.object(driver.rag, 'MANIFEST', root / 'manifest.json'), \
                 patch.object(driver.rag, 'select_cases', return_value=cases), \
                 patch.object(driver.rag, 'freeze_bindings', return_value={'prompt': 'bound'}), \
                 patch.object(driver.rag, 'execute_case', side_effect=execute_case):
                report = driver.rag_suite(args, {'steps': {}}, root / 'state.json', root / 'suite', {'prompt': 'bound'},
                                          'development', None, None)
            self.assertEqual(called, ['one'])
            self.assertFalse((root / 'suite' / 'two-r1.json').exists())
            self.assertEqual(report['executed_case_repeats'], 1)
            self.assertEqual(report['status'], 'WAIT_EXECUTION_OR_RECOVERY')

    def test_required_human_failure_is_safety_failure_even_with_semantic_review(self):
        row = {'status': 'FAILED', 'expected': {'must_include_facts': ['a'], 'human_ticket_required': True},
               'scores': {'checks': {'required_human_ticket_persisted': False}}, 'turns': []}
        review = {'verdict': 'pass', 'rationale': 'synthetic', 'violations': [], 'fact_completeness': {'satisfied': 1, 'total': 1}, 'refusal_correct': True}
        with patch.object(driver, 'case_review', return_value=review):
            result = driver.assess_rag([{'artifact': 'synthetic.json', 'data': row}], 1, {}, 'development')
        self.assertEqual(result['status'], 'FAILED_SAFETY'); self.assertEqual(len(result['critical_failures']), 1)

    def test_review_hash_pointer_and_typed_check_cannot_turn_missing_measurement_into_zero(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'raw.json'; driver.write(path, {'missing': False})
            ref = {'artifact': 'raw.json', 'sha256': driver.rag.digest(path)}
            review = {'_base': root, 'gate_reviews': [{'gate_id': 'ui_first_visible_text', 'verdict': 'pass',
                'rationale': 'synthetic typed check', 'execution_bindings': {}, 'evidence_refs': [ref],
                'checks': [{'evidence_ref': 0, 'pointer': '/missing', 'expected': 0}]}]}
            result = driver.external_gates(review, {'runtime': {}, 'tools': {}})
            self.assertEqual(result['ui_first_visible_text']['status'], 'FAILED')
            self.assertEqual(result['merchant_refunds']['status'], 'WAIT_EVIDENCE_REVIEW')
            driver.write(path, {'missing': 0})
            with self.assertRaisesRegex(ValueError, 'hash_mismatch'): driver.checked_ref(ref, root)

    def test_copied_attempts_count_once_unknown_cost_and_usage_remain_null(self):
        trace = {'model_id': 'synthetic', 'model_mode': 'mock', 'started_at': '2026-09-09T00:00:00Z', 'attempt': 1,
                 'prompt_version': 'p1', 'status': 'failed', 'usage': {'total_tokens': None}, 'latency_ms': 20, 'cost_estimate_cny': None}
        report = driver.cost_report([{'data': {'model_attempts': [trace]}}, {'data': {'trace': deepcopy(trace)}}])
        self.assertEqual(report['modes']['mock']['attempt_count'], 1)
        self.assertIsNone(report['modes']['mock']['known_tokens']); self.assertIsNone(report['modes']['mock']['known_estimated_cost_cny'])
        self.assertIsNone(report['ui_first_visible_text_ms'])

    def test_unfinished_index_attempts_keep_distinct_durable_call_ids(self):
        trace = {'model_id': 'synthetic-index', 'model_mode': 'live', 'status': 'started', 'usage': {}, 'latency_ms': None}
        first = {'call_id': 'index-one', 'trace_json': trace}; second = {'call_id': 'index-two', 'trace_json': trace}
        report = driver.cost_report([{'data': [first, second, deepcopy(first)]}])
        self.assertEqual(report['modes']['live']['attempt_count'], 2)
        self.assertEqual(report['modes']['live']['unknown_cost_attempts'], 2)


if __name__ == '__main__':
    unittest.main()
