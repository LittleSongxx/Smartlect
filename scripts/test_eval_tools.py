"""Pure local checks; no services, model network, DB or WSL control."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import eval_tools as runner
from smartlect.provider import ProviderError
from tool_fault_fixture import InjectedProvider


class ToolRunnerTests(unittest.TestCase):
    def test_frozen_twenty_contracts_have_handlers_and_explicit_nonresult_groups(self):
        tasks = runner.load_contracts()
        self.assertEqual(len(tasks), 20)
        self.assertEqual(sum(t['agent_required'] for t in tasks), 8)
        self.assertEqual(sum(t['kind'] == 'service_reliability' for t in tasks), 11)
        self.assertTrue(all(callable(getattr(runner, 'task_' + t['task_id'].split('-')[1])) for t in tasks))
        self.assertEqual(json.loads(runner.MANIFEST.read_text())['execution_status'], 'not_run')

    def test_only_predeclared_turn_and_authoritative_runtime_values_enter_prompt(self):
        task = {'turn_templates': ['请核对商品{product_id}，先不购买。'], 'expected': {'success': 'SECRET_EXPECTED_LABEL'}}
        rendered = runner.prompt(task, 0, product_id='actual-java-id')
        self.assertEqual(rendered, '请核对商品actual-java-id，先不购买。')
        self.assertNotIn('SECRET_EXPECTED_LABEL', rendered)

    def test_confirmation_audit_requires_same_owner_original_version_and_explicit_positive_decision(self):
        proposal = {'owner_actor_id': 'owner', 'proposal_id': 'proposal', 'decision_version': 3, 'action_type': 'refund'}
        entry = {'actor_id': 'owner', 'path': 'proposals/proposal/confirm', 'request': {'proposal_version': 3, 'approved': True}}
        self.assertTrue(runner.proposal_authorized(proposal, [entry]))
        for modified in ({**entry, 'actor_id': 'other'}, {**entry, 'request': {'proposal_version': 2, 'approved': True}},
                         {**entry, 'request': {'proposal_version': 3, 'approved': False}}):
            self.assertFalse(runner.proposal_authorized(proposal, [modified]))

    def test_unrun_and_semantic_pending_never_pass_and_unmeasured_invariants_stay_null(self):
        names = json.loads(runner.MANIFEST.read_text())['strong_invariants']
        row = {'task_kind': 'agent_multistep', 'status': 'AWAITING_SEMANTIC_REVIEW',
            'expected': {'strong_invariants': names}, 'invariants': {name: {'violations': None, 'checks': []} for name in names}}
        summary = runner.summarize([row], 20, subset=False)
        self.assertEqual(summary['formal_success_rate'], 0)
        self.assertFalse(summary['target_met']); self.assertEqual(summary['semantic_pending'], 1)
        self.assertTrue(all(r['violations'] is None for r in summary['strong_invariants'].values()))
        self.assertIsNone(runner.summarize([row], 1, subset=True)['formal_success_rate'])

    def test_mock_mode_does_not_instantiate_client_or_fake_agent_work(self):
        task = runner.load_contracts()[0]
        with TemporaryDirectory() as temp, patch.object(runner, 'ToolClient') as client:
            result = runner.run_case(task, 1, 'mock', Path(temp) / 'case.json', {})
            self.assertEqual(result['status'], 'NOT_RUN_LIVE_REQUIRED'); client.assert_not_called()

    def test_stock_effect_check_uses_the_selected_proposal_sku_not_the_first_catalogue_entry(self):
        client = object.__new__(runner.ToolClient)
        first = {'productId': 'product', 'propertyValueIds': 'first', 'propertyValueIdHash': 'hash-first'}
        selected = {'productId': 'product', 'propertyValueIds': 'selected', 'propertyValueIdHash': 'hash-selected'}
        client.catalog = {'skus': [first, selected]}
        proposal = {'parameters': {'orderList': [{'productId': 'product', 'propertyValueIds': 'selected', 'buyCount': 1}]}}
        client.stock = Mock(side_effect=[5, 4]); client.confirm = Mock(return_value={'status': 'SUCCEEDED'})
        client.invariant = lambda name, value, label: self.assertTrue(value)
        client.confirm_once_checked(proposal)
        self.assertEqual([call.args[0] for call in client.stock.call_args_list], [selected, selected])

    def test_resume_summary_counts_the_original_case_once_and_preserves_its_archive(self):
        names = json.loads(runner.MANIFEST.read_text())['strong_invariants']
        case = {'task_kind': 'service_reliability', 'status': 'PASSED', 'expected': {'strong_invariants': names},
                'invariants': {name: {'violations': 0, 'checks': []} for name in names}}
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'run.json').write_text(json.dumps({'task_ids': ['tool-008'], 'repeat': 1, 'subset': True}))
            (root / 'tool-008-r1.json').write_text(json.dumps(case))
            archive = root / 'tool-008-r1.before-resume-old.json'; archive.write_text(json.dumps({**case, 'status': 'WAIT_EXTERNAL_REQUIRED'}))
            runner.refresh_summary(root)
            summary = json.loads((root / 'summary.json').read_text())
            self.assertEqual(summary['recorded_case_repeats'], 1); self.assertEqual(summary['passed'], 1)
            self.assertEqual(json.loads(archive.read_text())['status'], 'WAIT_EXTERNAL_REQUIRED')


class InjectedTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_attempts_are_bounded_and_never_reported_as_real_model_calls(self):
        config = {'SMARTLECT_MODEL_ID': 'qwen3.7-plus', 'SMARTLECT_MODEL_API_KEY': 'synthetic-fixture-only',
                  'SMARTLECT_MODEL_BASE_URL': 'https://dashscope.aliyuncs.com/compatible-mode/v1'}
        provider = InjectedProvider(config, 'timeout'); traces = []; admitted = []
        with self.assertRaisesRegex(ProviderError, 'model_timeout'):
            await provider.chat([{'role': 'user', 'content': 'synthetic fault test'}],
                                before_attempt=lambda: admitted.append(True), on_trace=traces.append)
        self.assertEqual(len(admitted), 2); self.assertEqual(len(traces), 2)
        self.assertTrue(all(t['model_mode'] == 'injected_transport' and t['real_model_called'] is False
                            and t['status'] == 'failed' for t in traces))

    async def test_invalid_json_fixture_returns_explicitly_synthetic_malformed_content(self):
        config = {'SMARTLECT_MODEL_ID': 'qwen3.7-plus', 'SMARTLECT_MODEL_API_KEY': 'synthetic-fixture-only',
                  'SMARTLECT_MODEL_BASE_URL': 'https://dashscope.aliyuncs.com/compatible-mode/v1'}
        traces = []
        result = await InjectedProvider(config, 'invalid_json').chat([{'role': 'user', 'content': 'synthetic'}], on_trace=traces.append)
        with self.assertRaises(ValueError): json.loads(result['message']['content'])
        self.assertEqual(len(traces), 1)
        self.assertIs(traces[0]['real_model_called'], False)


if __name__ == '__main__':
    unittest.main()
