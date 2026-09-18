import importlib
import os
import unittest
from unittest.mock import patch

from smartlect.decision_record import SHOPPING_MODEL_LIMIT, attach_merchant_audit, attach_shopping_audit


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

    def test_merchant_audit_records_no_replan_invariant(self):
        result = {
            'plan': {'plan_id': 'plan1', 'status': 'WAIT_OBSERVATION', 'spec': {'evidence_ids': ['ev1']}},
            'model_mode': 'not_called', 'wait_reason': 'no_new_observation', 'model_calls': 0,
        }
        attach_merchant_audit(result, {
            'prompt_version': 'merchant-plan-v19', 'observation_watermark': 'w1',
            'skill_versions': {'campaign_plan': '1.11.0'},
        })
        self.assertEqual(result['wait_reason'], 'no_new_observation')
        self.assertFalse(result['decision']['replanned'])
        statuses = {item['id']: item['status'] for item in result['checks']}
        self.assertEqual(statuses['model_has_no_tools'], 'passed')
        self.assertEqual(statuses['no_replan_on_same_watermark'], 'passed')
        self.assertEqual(statuses['evidence_bound_or_waiting'], 'passed')

    def test_shopping_model_limit_follows_env(self):
        self.assertEqual(SHOPPING_MODEL_LIMIT, max(1, int(os.environ.get('SMARTLECT_MODEL_CALL_LIMIT') or 6)))
        with patch.dict(os.environ, {'SMARTLECT_MODEL_CALL_LIMIT': '9'}):
            import smartlect.decision_record as module
            reloaded = importlib.reload(module)
            self.assertEqual(reloaded.SHOPPING_MODEL_LIMIT, 9)
        importlib.reload(module)
