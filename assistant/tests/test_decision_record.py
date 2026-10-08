import importlib
import os
import unittest
from unittest.mock import patch

from smartlect.decision_record import (SHOPPING_MODEL_LIMIT,
                                       attach_shopping_audit, shopping_decision)
from smartlect.agents.shopping.policy import CLOSE_REASONS


class DecisionRecordTests(unittest.TestCase):
    def test_shopping_audit_does_not_change_control_fields(self):
        result = {
            'answer': '七天无理由。', 'answer_status': 'answered',
            'request_kind': 'inquire_fact', 'handoff_requested': False,
            'grounding': 'store_policy', 'evidence_kind': 'supported',
            'compiled': {'answer_status': 'answered', 'open_ticket': False},
            'citations': [{'chunk_id': 'c1', 'content': '退货说明'}],
            'proposal': None, 'ticket': None, 'model_mode': 'live',
        }
        context = {
            'prompt_version': 'shopping-react-v23', 'schema_version': 'shopping-answer-v5',
            'skill_versions': {'support_policy': '1.5.0'}, 'accepted_tools': ['search_knowledge'],
            'model_calls': 2, 'tool_calls': 1, 'retrieval_calls': 1, 'answer_repairs': 0,
            'final_output_channel': 'finish_answer',
        }
        attach_shopping_audit(result, context)
        self.assertEqual(result['answer'], '七天无理由。')
        self.assertEqual(result['answer_status'], 'answered')
        self.assertEqual(result['citations'][0]['chunk_id'], 'c1')
        self.assertIsNone(result['ticket'])
        self.assertIsNone(result['proposal'])
        self.assertEqual(result['audit']['plane'], 'shopping')
        self.assertIs(result['decision'], result['audit'])
        self.assertIs(result['checks'], result['audit_checks'])
        self.assertEqual(result['decision']['plane'], 'shopping')
        self.assertEqual(result['decision']['citation_chunk_ids'], ['c1'])
        self.assertEqual(result['audit']['budget']['model_attempts_limit'], SHOPPING_MODEL_LIMIT)
        self.assertEqual(result['decision']['accepted_tools'], ['search_knowledge'])
        self.assertIs(result['decision']['compiled_open_ticket'], False)
        statuses = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(statuses['compiled_decision_present'], 'passed')
        self.assertEqual(statuses['policy_grounding_has_this_turn_citation'], 'passed')
        self.assertEqual(statuses['proposal_is_not_execution'], 'not_applicable')
        self.assertEqual(statuses['budget_within_limits'], 'passed')

    def test_shopping_recovered_proposal_skips_compiler_check(self):
        result = {
            'answer': '已恢复保存的交易提案，请核对后确认。', 'answer_status': 'answered',
            'citations': [], 'proposal': {'proposal_id': 'p1'}, 'closeout': 'recovered_proposal',
            'model_mode': 'live',
        }
        attach_shopping_audit(result, {'skill_versions': {'order_service': '1.1.0'}})
        self.assertEqual(result['answer_status'], 'answered')
        self.assertEqual(result['proposal']['proposal_id'], 'p1')
        statuses = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(statuses['compiled_decision_present'], 'not_applicable')
        self.assertEqual(statuses['proposal_is_not_execution'], 'passed')

    def test_needs_human_without_ticket_fails_check_only(self):
        result = {'answer_status': 'needs_human', 'citations': [], 'request_kind': 'request_handoff'}
        attach_shopping_audit(result, {})
        self.assertEqual(result['answer_status'], 'needs_human')
        self.assertNotIn('ticket', result)
        statuses = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(statuses['needs_human_has_ticket'], 'failed')

    def test_shopping_model_limit_follows_env(self):
        # 单一事实源：决策记录的预算上限来自 agents.shopping.policy，
        # 环境变量只在那一个模块读取（reload 链 policy → decision_record）。
        self.assertEqual(SHOPPING_MODEL_LIMIT, max(1, int(os.environ.get('SMARTLECT_MODEL_CALL_LIMIT') or 6)))
        with patch.dict(os.environ, {'SMARTLECT_MODEL_CALL_LIMIT': '9'}):
            import smartlect.agents.shopping.policy as policy_module
            import smartlect.decision_record as module
            importlib.reload(policy_module)
            reloaded = importlib.reload(module)
            self.assertEqual(reloaded.SHOPPING_MODEL_LIMIT, 9)
        importlib.reload(policy_module)
        importlib.reload(module)

    def test_close_reason_mapping_covers_all_terminal_paths(self):
        """终止原因归一（组件 5）：每条收口路径都必须落到已知枚举值。"""
        base_result = {'answer': 'ok', 'answer_status': 'answered', 'citations': [], 'proposal': None}
        cases = [
            # (result 覆盖, context 覆盖, 期望 close_reason)
            ({}, {}, 'completed'),
            ({'closeout': 'observed_catalog_template'}, {}, 'completed'),
            ({'closeout': 'rollback_substitution_template'}, {}, 'completed'),
            ({'closeout': 'salvaged_observed_facts'}, {}, 'completed'),
            ({'closeout': 'handoff_tool'}, {}, 'handoff'),
            ({'closeout': 'recovered_proposal'}, {}, 'recovered_proposal'),
            ({'closeout': 'recovered_ticket'}, {}, 'recovered_ticket'),
            ({'safety_override': 'citation_no_longer_visible'}, {}, 'guard_violation'),
            ({}, {'fallback_reason': 'answer_contract_failed'}, 'repair_exhausted'),
            ({}, {'fallback_reason': 'tool_call_limit'}, 'budget_exceeded'),
            ({}, {'fallback_reason': 'context_limit'}, 'budget_exceeded'),
            ({}, {'fallback_reason': 'model_call_or_time_limit'}, 'budget_exceeded'),
            ({}, {'fallback_reason': 'retrieval_rewrite_limit'}, 'budget_exceeded'),
            ({}, {'fallback_reason': 'turn_token_budget'}, 'budget_exceeded'),
            ({}, {'fallback_reason': ''}, 'deadline'),
            ({}, {'fallback_reason': 'TimeoutError'}, 'deadline'),
            ({}, {'fallback_reason': 'model_timeout'}, 'provider_fault'),
            ({}, {'fallback_reason': 'model_transport_error'}, 'provider_fault'),
            ({}, {'fallback_reason': 'explicit_mock'}, 'provider_fault'),
            ({}, {'fallback_reason': 'mystery_failure'}, 'degraded'),
            ({'closeout': 'empty_evidence'}, {}, 'retrieval_empty'),
            ({'closeout': 'provider_fault'}, {}, 'provider_fault'),
            # 显式覆盖优先于一切派生
            ({}, {'close_reason': 'completed'}, 'completed'),
        ]
        for result_over, context_over, expected in cases:
            with self.subTest(result_over=result_over, context_over=context_over):
                result = dict(base_result)
                result.update(result_over)
                context = dict(context_over)
                decision = shopping_decision(result, context)
                self.assertIn(decision['close_reason'], CLOSE_REASONS)
                self.assertEqual(decision['close_reason'], expected)

    def test_close_reason_check_reports_unknown_only_for_unmapped(self):
        result = {'answer_status': 'answered', 'citations': []}
        attach_shopping_audit(result, {})
        statuses = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(statuses['close_reason_known'], 'passed')
        # 显式未知值：原样保留（不静默重映射），check 失败暴露未登记原因
        result2 = {'answer_status': 'answered', 'citations': []}
        attach_shopping_audit(result2, {'close_reason': 'not_a_reason'})
        self.assertEqual(result2['decision']['close_reason'], 'not_a_reason')
        statuses2 = {item['id']: item['status'] for item in result2['checks']}
        self.assertEqual(statuses2['close_reason_known'], 'failed')

    def test_dispatch_summary_aggregates_sub_attempts_and_unverified(self):
        """派发审计（组件 6）：sub-* 前缀的子智能体调用聚合 token/成本，无派发时字段为 None。"""
        context = {
            'dispatch_summary': {'task_count': 2, 'unverified_count': 1,
                                 'routing': [{'task': '查A', 'status': 'succeeded'}]},
            'model_attempts': [
                {'prompt_version': 'shopping-react-v28', 'usage': {'total_tokens': 500},
                 'cost_estimate_cny': 0.01},
                {'prompt_version': 'sub-retrieval-scout-v1', 'usage': {'total_tokens': 300},
                 'cost_estimate_cny': 0.005},
                {'prompt_version': 'sub-comparator-v1', 'usage': {'total_tokens': 200},
                 'cost_estimate_cny': 0.002}],
        }
        decision = shopping_decision({'answer_status': 'answered', 'citations': []}, context)
        self.assertEqual(decision['dispatch']['task_count'], 2)
        self.assertEqual(decision['dispatch']['unverified_count'], 1)
        self.assertEqual(decision['dispatch']['model_attempts'], 2)
        self.assertEqual(decision['dispatch']['total_tokens'], 500)
        self.assertEqual(decision['dispatch']['cost_estimate_cny'], 0.007)
        # 无派发：不产空摘要
        plain = shopping_decision({'answer_status': 'answered', 'citations': []}, {})
        self.assertIsNone(plain['dispatch'])
