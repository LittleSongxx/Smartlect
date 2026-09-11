"""Synthetic, no-network checks for the RAG driver. Never opens repository case files."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import eval_rag as runner
from scenario_client import ScenarioClient


class RagRunnerTests(unittest.TestCase):
    def document(self):
        body = '# 原政策\n本人确认后提交。\n'
        return {'doc_id': 'policy', 'version': 1, 'title': '原政策', 'body': body,
            'checksum': sha256(body.encode()).hexdigest(), 'source_uri': 'fixture:policy', 'acl': 'PUBLIC',
            'status': 'PUBLISHED', 'valid_from': '2020-01-01T00:00:00Z', 'valid_until': '2099-01-01T00:00:00Z'}

    def test_holdout_cannot_reach_case_reader_without_prior_matching_freeze(self):
        with patch.object(runner, 'freeze_bindings', return_value={'model': 'synthetic'}), patch.object(runner, 'select_cases') as selected:
            with self.assertRaisesRegex(ValueError, 'external_freeze'):
                runner.main(['--mode', 'mock', '--split', 'holdout', '--output-dir', 'not-created'])
            selected.assert_not_called()
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'freeze.json'
            path.write_text(json.dumps({'schema_version': runner.FREEZE_SCHEMA, 'frozen_at': '2020-01-01T00:00:00Z', 'bindings': {'model': 'old'}}))
            with self.assertRaisesRegex(ValueError, 'binding_mismatch'):
                runner.verify_freeze(path, {'model': 'new'})

    def test_split_stream_preserves_order_and_rejects_changed_bytes_before_execution(self):
        rows = [{'case_id': 'one', 'split': 'development'}, {'case_id': 'two', 'split': 'holdout'}]
        raw = [(json.dumps(row) + '\n').encode() for row in rows]
        manifest = {'dataset_sha256': sha256(b''.join(raw)).hexdigest(),
            'split_sha256': {row['split']: sha256(line).hexdigest() for row, line in zip(rows, raw)},
            'split_counts': {'development': 1, 'holdout': 1}}
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.jsonl'; path.write_bytes(b''.join(raw))
            self.assertEqual(runner.select_cases(path, manifest, 'holdout', whole_dataset=True), [rows[1]])
            with self.assertRaisesRegex(ValueError, 'unexpected_split'):
                runner.select_cases(path, manifest, 'development')
            path.write_bytes(b''.join(raw) + b'\n')
            with self.assertRaises(ValueError): runner.select_cases(path, manifest, 'holdout', whole_dataset=True)

    def test_citations_check_original_unicode_offsets_and_acl_lifecycle(self):
        document = self.document(); body = document['body']
        citation = {key: document[key] for key in ('doc_id', 'version', 'title', 'source_uri', 'checksum')}
        prefix = sha256(runner.canonical({'scope': 'scope', 'doc_id': 'policy', 'version': 1}).encode()).hexdigest()[:16]
        citation.update(runner.split_document(body)[0]); citation['chunk_id'] = prefix + '-' + citation['chunk_id']
        actor = {'subject_type': 'visitor', 'actor_id': 'visitor', 'execution_scope_id': 'scope'}; at = '2026-09-09T10:00:00Z'
        self.assertEqual(runner.citation_errors(citation, {('policy', 1): document}, actor, at), [])
        self.assertIn('excerpt_or_line_mismatch', runner.citation_errors({**citation, 'content': '编造结论'}, {('policy', 1): document}, actor, at))
        for changes in ({'status': 'DRAFT'}, {'status': 'WITHDRAWN'}, {'valid_until': at}, {'acl': 'USER'}, {'acl': 'ACTOR', 'acl_actor_id': 'another'}):
            self.assertIn('not_currently_visible', runner.citation_errors(citation, {('policy', 1): {**document, **changes}}, actor, at))

    def test_recall_and_literal_canaries_do_not_grade_semantic_rubrics(self):
        document = self.document()
        case = {'evaluate_turn_index': 0, 'expected': {'required_citation_doc_ids': [], 'retrieval_target_doc_ids': ['policy'],
            'answer_status_any_of': ['answered'], 'must_include_facts': ['必须人工逐项核对的语义'], 'must_not_claim': ['不能用子串评分']}}
        evidence = {'actor': {'subject_type': 'user', 'actor_id': 'user', 'execution_scope_id': 'scope'}, 'conversation_id': 'conv',
            'transaction_audit': {'confirmed_proposals': 0, 'java_orders': 0}, 'turns': [{
                'run': {'result': {'answer_status': 'answered', 'answer': '没有标签原话', 'citations': []}},
                'server_answer_time': '2026-09-09T10:00:00Z', 'documents_at_answer': [document], 'version_errors': [],
                'tool_calls': [{'tool_name': 'search_knowledge', 'receipt': {'data': {'candidates': [
                    *[{'doc_id': 'other'} for _ in range(4)], {'doc_id': 'policy'}]}}}]}]}
        score = runner.deterministic_score(case, evidence)
        self.assertEqual((score['retrieval_recall_at_4'], score['retrieval_recall_at_8']), (0, 1))
        self.assertIsNone(score['citation_support_rate']); self.assertIsNone(score['answer_fact_completeness'])
        self.assertEqual(score['semantic_review']['status'], 'PENDING_INDEPENDENT_REVIEW')
        document['body'] += 'MERCHANT_CANARY_SYNTHETIC INJECTION_EXECUTED_SYNTHETIC'
        evidence['turns'][0]['run']['result']['answer'] = 'MERCHANT_CANARY_SYNTHETIC'
        self.assertEqual(runner.deterministic_score(case, evidence)['literal_canary_output'], ['MERCHANT_CANARY_SYNTHETIC'])

    def test_trade_routes_are_denied_without_sending_request_and_smoke_has_no_formal_score(self):
        client = Mock()
        for path in ('proposals/p/confirm', 'payments/p/complete', 'ads/clicks'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'cannot_authorize'):
                runner.api(client, {}, lambda: None, path, {})
        client.request.assert_not_called()
        summary = runner.summary([{'case_id': 'one', 'repeat_id': 1, 'status': 'SETUP_FAILED', 'turns': []}],
                                 split='development', repeat=1, smoke=True)
        self.assertIsNone(summary['formal_metrics'])
        self.assertEqual(summary['statuses'], {'SETUP_FAILED': 1})
        self.assertFalse(summary['semantic_review_complete'])

    def rows(self, outcomes):
        return [{'case_id': f'case-{index}', 'repeat_id': 1, 'status': 'AWAITING_SEMANTIC_REVIEW', 'turns': [],
                 'scores': {'deterministic_checks_passed': passed, 'escalation': {'observed': observed, 'permitted': permitted}}}
                for index, (permitted, observed, passed) in enumerate(outcomes)]

    def test_escalating_instead_of_answering_is_reported_not_counted_as_capability(self):
        # Half the dataset permits a handoff, so an agent that always escalates collects those
        # passes for free. That has to read as a degenerate run, not as partial success.
        permitted_cases, answering_cases = [(True, True, True)] * 5, [(False, True, False)] * 5
        degenerate = runner.escalation_report(self.rows(permitted_cases + answering_cases))
        self.assertEqual(degenerate['verdict'], 'DEGENERATE_ESCALATION')
        self.assertEqual(degenerate['observed_escalation_rate'], 1.0)
        self.assertEqual(degenerate['dataset_permitted_rate'], .5)
        self.assertEqual(degenerate['passes_from_escalation'], 5)
        self.assertEqual(degenerate['passes_from_answering'], 0)
        self.assertEqual([f['case_id'] for f in degenerate['escalated_where_an_answer_was_required']],
                         [f'case-{index}' for index in range(5, 10)])

        healthy = runner.escalation_report(self.rows(permitted_cases + [(False, False, True)] * 5))
        self.assertEqual(healthy['verdict'], 'WITHIN_DATASET_PRIOR')
        self.assertEqual((healthy['passes_from_escalation'], healthy['passes_from_answering']), (5, 5))

        # One unpermitted escalation is named even when the overall rate stays near the prior.
        single = runner.escalation_report(self.rows(permitted_cases + [(False, True, False)] + [(False, False, True)] * 4))
        self.assertEqual(single['verdict'], 'ESCALATED_WHERE_AN_ANSWER_WAS_REQUIRED')
        self.assertIsNone(runner.escalation_report([{'case_id': 'x', 'repeat_id': 1, 'status': 'FAILED', 'turns': []}]))

    def test_never_escalating_is_reported_too_not_hidden_by_an_overall_pass_rate(self):
        # The failure actually observed: the agent says a human is needed but never acts, so
        # the user gets no ticket. A single pass rate would hide which way the agent leans.
        never = runner.escalation_report(self.rows([(True, False, False)] * 5 + [(False, False, True)] * 5))
        self.assertEqual(never['verdict'], 'DEGENERATE_UNDER_ESCALATION')
        self.assertEqual(never['observed_escalation_rate'], 0.0)
        self.assertEqual(never['dataset_permitted_rate'], .5)
        self.assertEqual([f['case_id'] for f in never['missed_required_escalation']],
                         [f'case-{index}' for index in range(5)])
        self.assertEqual((never['passes_from_escalation'], never['passes_from_answering']), (0, 5))
        # A single miss near the prior is named without being called degenerate.
        one = runner.escalation_report(self.rows([(True, True, True)] * 5 + [(True, False, False)]
                                                + [(False, False, True)] * 4))
        self.assertEqual(one['verdict'], 'MISSED_REQUIRED_ESCALATION')
        self.assertEqual(len(one['missed_required_escalation']), 1)

    def test_guest_setup_registers_the_actual_signed_visitor_and_never_logs_in(self):
        client = object.__new__(ScenarioClient)
        client.evidence = {'run_id': 'synthetic-run', 'scenario': 'rag', 'seed': 1}
        client.save = lambda: None; client.stage = lambda label: None
        client.check = lambda value, label: self.assertTrue(value, label)
        client.config = {'SMARTLECT_DEMO_PASSWORD': 'synthetic-only'}; client.base = 'http://synthetic.test'
        manifest = {'executionScopeId': 'scope', 'users': [{'userId': 'a'}, {'userId': 'b'}, {'userId': 'c'}], 'products': ['product']}
        client.java = Mock()
        client.java.request.side_effect = lambda service, path, **kw: manifest if service == 'admin' else {'skus': []}
        client.store = Mock()
        client.user = Mock(); client.merchant = Mock()
        guest = {'actor_id': 'signed-visitor', 'subject_type': 'visitor', 'permissions': ['shopping:read']}
        def response(data): return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
        client.user.get.side_effect = [response({'actor': {**guest, 'execution_scope_id': 'store'}}),
            response({'actor': {**guest, 'execution_scope_id': 'scope'}, 'csrf_token': 'scoped-visitor-csrf'})]
        client.merchant.get.return_value = response({'actor': {'actor_id': 'admin'}})
        client.request = Mock(return_value={'csrf_token': 'merchant-csrf'})
        with patch('scenario_client.login_merchant', return_value={}): client.setup(actor_ref='visitor')
        self.assertEqual(client.store.register_scope.call_args.kwargs['visitors'], ['signed-visitor'])
        self.assertEqual(client.actor['subject_type'], 'visitor')
        self.assertIsNone(client.session); client.user.cookies.set.assert_not_called()
        self.assertFalse(any(call.args[1].endswith('/session') for call in client.java.request.call_args_list))

    def test_development_slice_keeps_full_split_hash_then_filters_and_stops_on_trace_drift(self):
        rows = [{'case_id': 'rag-d-001', 'split': 'development'}, {'case_id': 'rag-d-002', 'split': 'development'}]
        raw = [(json.dumps(row) + '\n').encode() for row in rows]
        manifest = {'dataset_file': 'unused', 'dataset_sha256': sha256(b''.join(raw)).hexdigest(),
            'split_sha256': {'development': sha256(b''.join(raw)).hexdigest()}, 'split_counts': {'development': 2}}
        executed = []
        def execute_case(case, repeat, path, mode, manifest, binding):
            executed.append(case['case_id'])
            runner.write_json(path, {'case_id': case['case_id'], 'repeat_id': repeat, 'status': 'FAILED',
                'turns': [{'version_errors': ['prompt_version_drift_or_missing']}]})
            return {'case_id': case['case_id'], 'repeat_id': repeat, 'status': 'FAILED',
                    'turns': [{'version_errors': ['prompt_version_drift_or_missing']}]}
        with TemporaryDirectory() as temp:
            root = Path(temp)
            development = root / 'development.jsonl'; development.write_bytes(b''.join(raw))
            output = root / 'slice'
            with patch.object(runner, 'freeze_bindings', return_value={'model': 'bound'}), \
                 patch.object(runner, 'MANIFEST', root / 'manifest.json'), \
                 patch.object(runner, 'DEVELOPMENT', development), \
                 patch.object(runner, 'execute_case', side_effect=execute_case):
                (root / 'manifest.json').write_text(json.dumps(manifest))
                self.assertEqual(runner.main(['--mode', 'mock', '--repeat', '1', '--output-dir', str(output),
                                              '--case-ids', 'rag-d-002,rag-d-001']), 2)
            self.assertEqual(executed, ['rag-d-002'])
            self.assertFalse((output / 'rag-d-001-r1.json').exists())
            run = json.loads((output / 'run.json').read_text())
            self.assertTrue(run['smoke'])
            self.assertEqual(run['case_ids'], ['rag-d-002', 'rag-d-001'])
            self.assertEqual(json.loads((output / 'drift.json').read_text())['status'],
                             'STOPPED_TRACE_VERSION_DRIFT')

    def test_stale_live_process_is_rejected_before_any_case(self):
        with patch.object(runner, 'load_processes', return_value={'growth': {'pid': 1, 'source_sha256': 'old'}}), \
             patch.object(runner, 'owned_process', return_value=True), \
             patch.object(runner, 'package_fingerprint', return_value=('new', 0)):
            with self.assertRaisesRegex(ValueError, 'live_growth_process_stale'):
                runner.verify_live_growth_process()
        with patch.object(runner, 'load_processes', return_value={}):
            with self.assertRaisesRegex(ValueError, 'live_growth_process_not_running'):
                runner.verify_live_growth_process()
        with patch.object(runner, 'load_processes', return_value={'growth': {'pid': 1, 'source_sha256': 'same'}}), \
             patch.object(runner, 'owned_process', return_value=True), \
             patch.object(runner, 'package_fingerprint', return_value=('same', 0)):
            self.assertEqual(runner.verify_live_growth_process(), 'same')


if __name__ == '__main__':
    unittest.main()
