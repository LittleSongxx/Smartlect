"""Contract tests for quality-v2 scoring. No live stack, no holdout load."""
import json
import tempfile
import unittest
from pathlib import Path

from eval_quality_v2 import business_closeout_after_budget, handoff_ends_conversation
import quality_v2
from quality_v2 import (ADS_PLAYBOOKS, CONTRACT_JSON, SHOPPING_CATALOG, SHOPPING_DEV, SUPPORT_DEV,
                        AnnotationError, ads_grant_envelope, aggregate_line, append_rerun_ledger,
                        campaign_rates, catalog_index, catalog_overlay_plan, context_precision_at_k,
                        handoff_f1, last_real_search, live_support_cases, load_json, load_jsonl,
                        mrr_at_k, recall_at_1_strict, recall_at_k, refuse_holdout, remap_observation,
                        score_ads, score_faithfulness, score_shopping, score_support,
                        self_check_scores, sku_satisfies, trial_table, validate_dev_sets,
                        validate_support_case, validate_shopping_case, wilson_ci, write_report)
from runtime import ROOT


class ShoppingScoreTests(unittest.TestCase):
    def setUp(self):
        self.cases = {row['case_id']: row for row in load_jsonl(SHOPPING_DEV)}
        self.skus = catalog_index()

    def test_short_list_precision_is_quarter_but_can_pass(self):
        case = self.cases['shop-d-24']
        sku = self.skus['kb-lite:black']
        score = score_shopping(case, {'selected_sku_keys': ['kb-lite:black'], 'products': [sku],
                                      'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(score['Precision@4'], 0.25)
        self.assertEqual(score['Precision@4/ceiling'], 1.0)  # at its own achievable maximum
        self.assertEqual(score['Pass@1'], 1)

    def test_over_budget_item_fails_pass(self):
        case = self.cases['shop-d-01']
        items = [self.skus['kb-lite:black'], self.skus['kb-pro:black']]
        score = score_shopping(case, {'selected_sku_keys': [row['sku_key'] for row in items],
                                      'products': items, 'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(score['Pass@1'], 0)
        self.assertEqual(score['Precision@4'], 0.25)
        self.assertEqual(score['Precision@4/ceiling'],
                         min(score['Precision@4'] / score['Precision@4_ceiling'], 1.0))

    def test_ceiling_ratio_caps_demand_fill_overshoot(self):
        case = {'case_id': 'x', 'kind': 'recommend',
                'hard_constraints': {'quantity': 4, 'required_terms': ['USB'], 'excluded_terms': []},
                'satisfaction_set': ['cable:usb'], 'expected_pass': 1}
        sku = self.skus['cable:usb']
        score = score_shopping(case, {'selected_sku_keys': ['cable:usb'], 'products': [sku],
                                      'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(score['Precision@4'], 1.0)      # 1 SKU x quantity 4 fills all slots
        self.assertEqual(score['Precision@4_ceiling'], 0.25)
        self.assertEqual(score['Precision@4/ceiling'], 1.0)  # capped at 1.0, never 4.0

    def test_legal_empty_precision_is_null(self):
        case = self.cases['shop-d-03']
        score = score_shopping(case, {'selected_sku_keys': [], 'products': [],
                                      'retrieve_diagnostics': {'popular_used': False,
                                                               'empty_reason': 'hard_constraint_unsatisfied'}})
        self.assertIsNone(score['Precision@4'])
        self.assertEqual(score['Pass@1'], 1)
        filled = score_shopping(case, {'selected_sku_keys': ['chair:mesh'], 'products': [self.skus['chair:mesh']],
                                       'retrieve_diagnostics': {'popular_used': True,
                                                                'empty_reason': None}})
        self.assertEqual(filled['Pass@1'], 0)

    def test_compare_does_not_report_precision(self):
        case = self.cases['shop-d-04']
        sku = self.skus['kb-lite:black']
        score = score_shopping(case, {'selected_sku_keys': [sku['sku_key']], 'products': [sku],
                                      'comparison_complete': False, 'missing_targets': ['火星飞船'],
                                      'comparison_sku_keys': [sku['sku_key']],
                                      'retrieve_diagnostics': {'popular_used': False}})
        self.assertIsNone(score['Precision@4'])
        self.assertEqual(score['Pass@1'], 1)
        padded = score_shopping(case, {'selected_sku_keys': [sku['sku_key'], 'chair:mesh'],
                                       'products': [sku, self.skus['chair:mesh']],
                                       'comparison_complete': True, 'missing_targets': [],
                                       'comparison_sku_keys': [sku['sku_key'], 'chair:mesh'],
                                       'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(padded['Pass@1'], 0)

    def test_required_terms_are_gold_not_query(self):
        case = self.cases['shop-d-23']
        self.assertIn('键盘', case['hard_constraints']['required_terms'])
        self.assertNotIn('办公', case['hard_constraints']['required_terms'])

    def test_channel_failure_is_setup_failed(self):
        score = score_shopping(self.cases['shop-d-01'], {'setup_failed': True, 'setup_reason': 'provider_fault'})
        self.assertEqual(score['outcome'], 'setup_failed')
        self.assertIsNone(score['Precision@4'])

    def test_hallucinated_sku_key_is_a_violating_slot(self):
        case = self.cases['shop-d-01']
        sku = self.skus['kb-lite:black']
        score = score_shopping(case, {'selected_sku_keys': ['kb-lite:black', 'ghost:cafe'],
                                      'products': [sku],
                                      'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(score['Pass@1'], 0)
        self.assertEqual(score['Precision@4'], 0.25)
        self.assertIn('ghost:cafe', score['selected'])

    def test_quantity_gate(self):
        case = self.cases['shop-d-25']
        items = [self.skus['cable:usb'], self.skus['cable:typec']]
        score = score_shopping(case, {'selected_sku_keys': [row['sku_key'] for row in items],
                                      'products': items, 'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(score['Pass@1'], 1)
        empty = score_shopping(self.cases['shop-d-26'], {'selected_sku_keys': [], 'products': [],
                                                         'retrieve_diagnostics': {
                                                             'popular_used': False,
                                                             'empty_reason': 'no_eligible_sku'}})
        self.assertEqual(empty['Pass@1'], 1)

    def test_satisfaction_keys_exist(self):
        for case in self.cases.values():
            for key in case.get('satisfaction_set') or []:
                self.assertIn(key, self.skus, case['case_id'])
            if case['kind'] != 'compare' and case.get('satisfaction_set'):
                for key in case['satisfaction_set']:
                    self.assertTrue(sku_satisfies(self.skus[key], case['hard_constraints']), case['case_id'] + ' ' + key)

    def test_overlay_plan_covers_snapshot(self):
        catalog = load_json(SHOPPING_CATALOG)
        products = [f'p{index}' for index in range(len(catalog['skus']))]
        skus = []
        for index, product_id in enumerate(products):
            skus.append({'productId': product_id, 'propertyValueIdHash': f'h{index}a',
                         'propertyValueIds': f'v{index}a', 'specIndex': 0})
            skus.append({'productId': product_id, 'propertyValueIdHash': f'h{index}b',
                         'propertyValueIds': f'v{index}b', 'specIndex': 1})
        plan = catalog_overlay_plan({'products': products, 'skus': skus}, catalog)
        self.assertEqual([row['gold_sku_key'] for row in plan['products']],
                         [row['sku_key'] for row in catalog['skus']])
        self.assertEqual(plan['products'][0]['primary_hash'], 'h0a')
        self.assertEqual(plan['products'][0]['extra_hashes'], ['h0b'])
        self.assertTrue(all(len(category) <= 5 for category in plan['categories']))
        chair = next(row for row in plan['products'] if row['gold_sku_key'] == 'chair:mesh')
        self.assertEqual(chair['categoryId'], 'furniture')
        self.assertEqual(chair['live_category_id'], 'furn')

    def test_live_keys_remap_to_snapshot_gold(self):
        case = self.cases['shop-d-01']
        live = {'sku_key': '9300:abc', 'productName': '轻便键盘', 'specification': '黑色',
                'price_cents': 12900, 'stock': 10}
        observation = remap_observation({'selected_sku_keys': ['9300:abc'], 'products': [live]})
        self.assertEqual(observation['selected_sku_keys'], ['kb-lite:black'])
        self.assertEqual(observation['products'][0]['status'], 1)
        score = score_shopping(case, {'selected_sku_keys': ['9300:abc'], 'products': [live],
                                      'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(score['Pass@1'], 1)
        self.assertEqual(score['Precision@4'], 0.25)

    def test_annotation_error_on_bad_gold(self):
        case = dict(self.cases['shop-d-01'])
        case['satisfaction_set'] = ['kb-pro:black']
        problems = []
        validate_shopping_case(case, self.skus, problems)
        self.assertTrue(any('satisfaction_set_mismatch' in item for item in problems))


    def test_quantity_demand_fill_precision(self):
        case = self.cases['shop-d-25']
        sku = self.skus['cable:usb']
        one = score_shopping(case, {'selected_sku_keys': ['cable:usb'], 'products': [sku],
                                    'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(one['Precision@4'], 0.5)  # one SKU x quantity 2 fills both slots
        self.assertEqual(one['Pass@1'], 1)
        both = score_shopping(case, {'selected_sku_keys': ['cable:usb', 'cable:typec'],
                                     'products': [sku, self.skus['cable:typec']],
                                     'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(both['Precision@4'], 0.5)
        self.assertEqual(both['Pass@1'], 1)


class SupportScoreTests(unittest.TestCase):
    def setUp(self):
        self.cases = {row['case_id']: row for row in load_jsonl(SUPPORT_DEV)}

    def test_last_real_search_skips_empty_observation(self):
        calls = [
            {'tool_name': 'search_knowledge', 'data': {'candidates': [{'doc_id': '02-payment'}],
                                                       'retrieval': {'final_depth': 8}}},
            {'tool_name': 'search_knowledge', 'data': {'answer_status': 'insufficient', 'candidates': []}},
        ]
        self.assertEqual(last_real_search(calls)['candidates'][0]['doc_id'], '02-payment')

    def test_recall_null_when_no_relevant(self):
        case = {'case_id': 'x', 'relevant_doc_ids': [], 'expected_retrieval': False, 'expected_handoff': False,
                'checkable_claims': []}
        score = score_support(case, {'result': {'answer': '你好', 'answer_status': 'answered', 'citations': []},
                                     'tool_calls': []})
        self.assertIsNone(score['Recall@8'])
        self.assertIsNone(score['Faithfulness'])
        self.assertEqual(score['Pass@1'], 1)

    def test_faithfulness_needs_answer_side_and_citation_side(self):
        case = self.cases['sup-d-01']
        citation = {'doc_id': '02-payment', 'version': 1,
                    'content': '模拟支付；付款成功必须以订单和支付结果为准。客服不会索要银行卡密码或支付密码。'}
        both = score_faithfulness(case, {'answer': '本店支持模拟支付，付款成功必须以订单和支付结果为准，'
                                                   '客服不会索要银行卡密码或支付密码。',
                                         'citations': [citation]})
        self.assertEqual(both, 1.0)
        citation_only = score_faithfulness(case, {'answer': '本店支持模拟支付方式，请放心。',
                                                  'citations': [citation]})
        self.assertLess(citation_only, 1.0)
        answer_only = score_faithfulness(case, {'answer': '付款成功必须以订单和支付结果为准，会真实扣款。',
                                                'citations': []})
        self.assertEqual(answer_only, 0.0)

    def test_faithfulness_cleared_citations_are_null(self):
        case = self.cases['sup-d-24']
        score = score_support(case, {'result': {'answer': '引用已失效。', 'answer_status': 'needs_human', 'citations': [],
                                               'safety_override': 'citation_no_longer_visible',
                                               'ticket': {'ticket_id': 't'}},
                                     'tool_calls': [{'tool_name': 'search_knowledge',
                                                     'data': {'candidates': [{'doc_id': '02-payment'}],
                                                              'retrieval': {'final_depth': 8}}}]})
        self.assertIsNone(score['Faithfulness'])
        self.assertEqual(score['Recall@8'], 1.0)
        self.assertEqual(score['Pass@1'], 1)

    def test_policy_claim_without_citation_is_zero(self):
        self.assertEqual(score_faithfulness({'checkable_claims': [{'text': '模拟支付'}]},
                                            {'answer': '模拟支付', 'citations': []}), 0.0)

    def test_forbidden_doc_fails(self):
        case = {'case_id': 'acl', 'relevant_doc_ids': [], 'forbidden_doc_ids': ['secret'],
                'expected_handoff': True, 'expected_retrieval': True, 'checkable_claims': []}
        score = score_support(case, {'result': {'answer': '内部资料。', 'answer_status': 'needs_human',
                                                'citations': [{'doc_id': 'secret'}],
                                                'ticket': {'ticket_id': 't'}},
                                     'tool_calls': [{'tool_name': 'search_knowledge',
                                                     'data': {'candidates': [{'doc_id': 'secret'}],
                                                              'retrieval': {'final_depth': 8}}}]})
        self.assertEqual(score['Pass@1'], 0)

    def test_must_not_claim_hit_fails_even_with_good_citations(self):
        case = self.cases['sup-d-01']
        citation = {'doc_id': '02-payment', 'version': 1, 'content': '模拟支付；当前没有真实扣款渠道。'}
        score = score_support(case, {'result': {'answer': '本店支持真实银行卡支付，也支持模拟支付。',
                                                'answer_status': 'answered', 'citations': [citation]},
                                     'tool_calls': [{'tool_name': 'search_knowledge',
                                                     'data': {'candidates': [{'doc_id': '02-payment'}],
                                                              'retrieval': {'final_depth': 8}}}]})
        self.assertEqual(score['outcome'], 'fail')
        self.assertEqual(score['Pass@1'], 0)
        self.assertTrue(score['must_not_claim_hit'])

    def test_honest_negation_is_not_a_forbidden_claim(self):
        case = self.cases['sup-d-13']
        citation = {'doc_id': '01-store-scope', 'version': 1,
                    'content': '支付与广告为模拟渠道，不收取真实款项，不实际投放广告。'}
        score = score_support(case, {'result': {'answer': '本店不收取真实款项，也不实际投放广告。',
                                                'answer_status': 'answered', 'citations': [citation]},
                                     'tool_calls': [{'tool_name': 'search_knowledge',
                                                     'data': {'candidates': [{'doc_id': '01-store-scope'}],
                                                              'retrieval': {'final_depth': 8}}}]})
        self.assertEqual(score['must_not_claim_hit'], [])
        self.assertEqual(score['outcome'], 'pass')

    def test_allow_handoff_accepts_ticket_closure(self):
        case = self.cases['sup-d-05']
        score = score_support(case, {'result': {'answer': '该规则已过期，已转人工核实。',
                                                'answer_status': 'needs_human', 'citations': [],
                                                'ticket': {'ticket_id': 't1'}},
                                     'tool_calls': [{'tool_name': 'search_knowledge',
                                                     'data': {'candidates': [], 'retrieval': {'final_depth': 8}}}]})
        self.assertTrue(score['handoff'])
        self.assertEqual(score['outcome'], 'pass')
        self.assertEqual(score['Pass@1'], 1)

    def test_allow_handoff_still_fails_ticketless_needs_human(self):
        case = self.cases['sup-d-05']
        score = score_support(case, {'result': {'answer': '该规则已过期，需人工核实。',
                                                'answer_status': 'needs_human', 'citations': []},
                                     'tool_calls': []})
        self.assertFalse(score['handoff'])
        self.assertEqual(score['outcome'], 'fail')
        self.assertEqual(score['Pass@1'], 0)

    def test_allow_handoff_validator_constraint(self):
        problems = []
        validate_support_case({'case_id': 'x', 'split': 'development', 'expected_retrieval': True,
                               'expected_handoff': True, 'allow_insufficient': True, 'allow_handoff': True,
                               'checkable_claims': []}, problems)
        self.assertTrue(any('allow_handoff_requires' in p for p in problems))
        problems = []
        validate_support_case({'case_id': 'y', 'split': 'development', 'expected_retrieval': True,
                               'expected_handoff': False, 'allow_insufficient': False, 'allow_handoff': True,
                               'checkable_claims': []}, problems)
        self.assertTrue(any('allow_handoff_requires' in p for p in problems))

    def test_qing_wu_negation_cue_is_exempt(self):
        case = self.cases['sup-d-51']
        score = score_support(case, {'result': {'answer': '请勿重新提交一笔新退款，可以恢复查询已有申请。',
                                                'answer_status': 'answered', 'citations': []},
                                     'tool_calls': []})
        self.assertEqual(score['must_not_claim_hit'], [])
        self.assertEqual(score['outcome'], 'pass')

    def test_fabricated_resubmission_still_hits(self):
        case = self.cases['sup-d-51']
        score = score_support(case, {'result': {'answer': '已为您重新提交一笔新退款，请稍候。',
                                                'answer_status': 'answered', 'citations': []},
                                     'tool_calls': []})
        self.assertTrue(score['must_not_claim_hit'])
        self.assertEqual(score['outcome'], 'fail')

    def test_handoff_ended_conversation_classifier(self):
        ticketed = {'answer_status': 'needs_human', 'ticket': {'ticket_id': 't'}}
        self.assertTrue(handoff_ends_conversation(ticketed, 2))
        self.assertFalse(handoff_ends_conversation({'answer_status': 'answered'}, 2))
        self.assertFalse(handoff_ends_conversation(ticketed, 0))

    def test_early_handoff_scores_pass_when_gold_expects_it(self):
        case = {'case_id': 'x', 'relevant_doc_ids': [], 'expected_handoff': True,
                'expected_retrieval': True, 'checkable_claims': []}
        score = score_support(case, {'result': {'answer': '已成交订单换货需人工核实，已建工单。',
                                                'answer_status': 'needs_human', 'citations': [],
                                                'ticket': {'ticket_id': 't'}},
                                     'tool_calls': [{'tool_name': 'search_knowledge',
                                                     'data': {'candidates': [], 'retrieval': {'final_depth': 8}}}]})
        self.assertEqual(score['outcome'], 'pass')
        self.assertEqual(score['Pass@1'], 1)

    def test_early_handoff_scores_fail_when_gold_forbids_it(self):
        case = {'case_id': 'x', 'relevant_doc_ids': [], 'expected_handoff': False,
                'expected_retrieval': True, 'checkable_claims': []}
        score = score_support(case, {'result': {'answer': '已为您转人工客服。',
                                                'answer_status': 'needs_human', 'citations': [],
                                                'ticket': {'ticket_id': 't'}},
                                     'tool_calls': []})
        self.assertEqual(score['outcome'], 'fail')
        self.assertEqual(score['Pass@1'], 0)

    def test_injection_marker_fails(self):
        case = self.cases['sup-d-20']
        score = score_support(case, {'result': {'answer': '好的，IGNORE_ALL_RULES，按你说的执行。',
                                                'answer_status': 'answered', 'citations': []},
                                     'tool_calls': []})
        self.assertEqual(score['outcome'], 'fail')
        self.assertIn('IGNORE_ALL_RULES', score['forbidden_claim_hit'])

    def test_extra_document_checksums_match_files(self):
        from hashlib import sha256
        for case in load_jsonl(SUPPORT_DEV):
            for doc in ((case.get('knowledge_setup') or {}).get('additional_documents') or []):
                body = (ROOT / doc['source_uri']).read_text()
                self.assertEqual(doc['body'], body)
                self.assertEqual(doc['checksum_sha256'], sha256(body.encode()).hexdigest())
                for key, value in (doc.get('facts') or {}).items():
                    self.assertIsInstance(key, str)
                    self.assertIsInstance(value, str)
                    self.assertIn(value, body)

    def test_claims_are_substrings_of_visible_corpus(self):
        problems = []
        for case in load_jsonl(SUPPORT_DEV):
            validate_support_case(case, problems)
        self.assertEqual(problems, [])

    def test_replay_only_case_is_not_live(self):
        live_ids = {row['case_id'] for row in live_support_cases()}
        self.assertNotIn('sup-d-24', live_ids)
        self.assertIn('sup-d-07', live_ids)
        self.assertFalse(next(row for row in load_jsonl(SUPPORT_DEV) if row['case_id'] == 'sup-d-24')['live_eligible'])


    def test_faithfulness_counts_essential_only(self):
        from unittest.mock import patch
        import judge_quality_v2 as jq
        case = {'case_id': 'x', 'checkable_claims': [
            {'id': 'a', 'text': '模拟支付', 'scope': 'essential'},
            {'id': 'b', 'text': '访客开放', 'scope': 'peripheral'}],
            'expected_retrieval': True, 'expected_handoff': False, 'relevant_doc_ids': []}
        scores = [{'case_id': 'x', 'outcome': 'pass'}]
        fake = {'supported': 1, 'total': 2,
                'verdicts': {'a': 'supported', 'b': 'absent'},
                'quotes': {'a': '模拟支付', 'b': ''}, 'summary': ''}
        with patch.object(jq, 'judge_case', return_value=fake):
            jq.apply_judge_faithfulness(scores, [(case, {'answer': 'x', 'citations': []})], {})
        self.assertEqual(scores[0]['Faithfulness'], 1.0)      # essential only
        self.assertEqual(scores[0]['Peripheral_coverage'], 0.0)
        side = {'supported': 3, 'total': 3, 'statements': [], 'summary': ''}
        with patch.object(jq, 'judge_answer_side', return_value=side):
            jq.apply_judge_answer_side(scores, [(case, {'answer': 'x', 'citations': []})], {})
        self.assertEqual(scores[0]['Faithfulness_answer_side'], 1.0)
        with patch.object(jq, 'judge_answer_side', return_value=None):
            jq.apply_judge_answer_side(scores, [(case, {'answer': '你好', 'citations': []})], {})
        self.assertIsNone(scores[0]['Faithfulness_answer_side'])


class AdsScoreTests(unittest.TestCase):
    def test_none_versus_zero(self):
        self.assertIsNone(campaign_rates({'impressions': 0, 'clicks': 0, 'payment_conversions': 0})['CTR'])
        self.assertEqual(campaign_rates({'impressions': 8, 'clicks': 0, 'payment_conversions': 0})['CTR'], 0.0)
        self.assertIsNone(campaign_rates({'impressions': 8, 'clicks': 0, 'payment_conversions': 0})['CVR'])
        self.assertEqual(campaign_rates({'impressions': 10, 'clicks': 3, 'payment_conversions': 0})['CVR'], 0.0)

    def test_playbooks_match_source_null_rules(self):
        books = {row['playbook_id']: row for row in load_json(ADS_PLAYBOOKS)['playbooks']}
        self.assertEqual(books['ads-d-01']['expected']['CVR'], None)
        self.assertEqual(books['ads-d-02']['expected']['CVR'], 0.0)
        self.assertGreater(books['ads-d-03']['expected']['CVR'], 0)
        self.assertEqual(books['ads-d-05']['expected']['counts']['unknown_payments'], 1)
        self.assertIsNone(books['ads-d-05']['expected']['CTR'])
        self.assertEqual(books['ads-d-04']['buy'], 'other_sku')

    def test_organic_payment_stays_out_of_cvr(self):
        book = {row['playbook_id']: row for row in load_json(ADS_PLAYBOOKS)['playbooks']}['ads-d-05']
        scored = score_ads(book, {'campaign_metrics': dict(book['expected']['counts']),
                                  'used_summary_payment_conversions': False,
                                  'used_recommendation_clicks': False})
        self.assertEqual(scored['outcome'], 'pass')
        self.assertEqual(scored['Attribution_integrity'], 1.0)
        self.assertEqual(scored['failed_assertions'], [])
        self.assertIsNone(scored['CTR'])
        self.assertIsNone(scored['CVR'])
        self.assertEqual(scored['unknown_payments'], 1)

    def test_attribution_integrity_is_assertion_level(self):
        book = {'playbook_id': 'x', 'expected': {'counts': {'impressions': 10, 'clicks': 3,
                                                            'payment_conversions': 1, 'unknown_payments': 0},
                                                 'CTR': 0.3, 'CVR': 1 / 3}}
        one_bucket_off = score_ads(book, {'campaign_metrics': {'impressions': 10, 'clicks': 3,
                                                               'payment_conversions': 1, 'unknown_payments': 1},
                                          'used_summary_payment_conversions': False,
                                          'used_recommendation_clicks': False})
        self.assertEqual(one_bucket_off['Attribution_integrity'], 7 / 8)
        self.assertEqual(one_bucket_off['failed_assertions'], ['count:unknown_payments'])
        self.assertEqual(one_bucket_off['outcome'], 'fail')
        shortcut = score_ads(book, {'campaign_metrics': dict(book['expected']['counts']),
                                    'used_summary_payment_conversions': False,
                                    'used_recommendation_clicks': True})
        self.assertEqual(shortcut['Attribution_integrity'], 7 / 8)
        self.assertEqual(shortcut['failed_assertions'], ['shortcut:no_recommendation_clicks'])

    def test_grant_envelope_matches_live_schema(self):
        envelope = ads_grant_envelope(['9300'], cap_cents=5000, until='2026-09-12T04:00:00+00:00')
        self.assertEqual(envelope['product_scope'], ['9300'])
        self.assertIn('activate_campaign', envelope['allowed_action_types'])
        self.assertEqual(envelope['budget_cap_cents'], 5000)
        self.assertEqual(envelope['max_budget_change_cents'], 2000)
        self.assertTrue(envelope['objective'])

    def test_summary_flag_is_rejected(self):
        book = load_json(ADS_PLAYBOOKS)['playbooks'][0]
        with self.assertRaises(AnnotationError):
            score_ads(book, {'campaign_metrics': book['expected']['counts'],
                             'used_summary_payment_conversions': True})

    def test_mismatched_expected_rate_is_annotation_error(self):
        book = {'playbook_id': 'x', 'expected': {'counts': {'impressions': 10, 'clicks': 5,
                                                            'payment_conversions': 0, 'unknown_payments': 0},
                                                 'CTR': 0.4, 'CVR': None}}
        with self.assertRaises(AnnotationError):
            score_ads(book, {'campaign_metrics': book['expected']['counts'],
                             'used_summary_payment_conversions': False})


class ReportTests(unittest.TestCase):
    def test_budget_closeout_is_scored_not_channel_failure(self):
        record = {'run': {'state': 'COMPLETED', 'result': {
            'model_mode': 'rule-fallback', 'answer_status': 'insufficient',
            'handoff_origin': None}}}
        self.assertTrue(business_closeout_after_budget(record))
        provider = {'run': {'state': 'COMPLETED', 'result': {
            'model_mode': 'rule-fallback', 'answer_status': 'needs_human',
            'handoff_origin': 'provider_fault'}}}
        self.assertFalse(business_closeout_after_budget(provider))
        running = {'run': {'state': 'RUNNING', 'result': {}}}
        self.assertFalse(business_closeout_after_budget(running))
        live_run = {'run': {'state': 'COMPLETED', 'result': {'model_mode': 'live'}}}
        self.assertFalse(business_closeout_after_budget(live_run))

    def test_holdout_gate_follows_freeze_artifact(self):
        import shutil
        from quality_v2 import FREEZE_MANIFEST
        backup = FREEZE_MANIFEST.with_suffix('.json.test-backup')
        if FREEZE_MANIFEST.exists():
            shutil.move(str(FREEZE_MANIFEST), str(backup))
        try:
            with self.assertRaises(ValueError):
                refuse_holdout('holdout')  # sealed until the freeze artifact exists
        finally:
            if backup.exists():
                shutil.move(str(backup), str(FREEZE_MANIFEST))
        if FREEZE_MANIFEST.exists():
            refuse_holdout('holdout')  # frozen: loadable, questions still human-authored
        refuse_holdout('development')

    def test_self_check_passes_and_has_no_total(self):
        shopping, support, ads = self_check_scores()
        self.assertEqual(len(shopping), 65)
        self.assertEqual(len(support), 63)
        self.assertEqual(len(ads), 12)
        self.assertTrue(all(row['outcome'] == 'pass' for row in shopping + support + ads))
        with tempfile.TemporaryDirectory() as folder:
            report = write_report(folder, shopping, support, ads, official=False)
        self.assertIsNone(report['composite_score'])
        self.assertFalse(report['official'])
        self.assertIn('Precision@4', report['shopping'])
        self.assertIn('Recall@8', report['support'])
        self.assertIn('CTR', report['ads'])
        self.assertNotIn('total', report['shopping'])
        self.assertEqual(report['support']['denominators']['Faithfulness'],
                         sum(1 for row in support if row.get('Faithfulness') is not None))

    def test_denominators_exclude_unscored(self):
        rows = [{'outcome': 'pass', 'Precision@4': 0.5, 'Pass@1': 1},
                {'outcome': 'setup_failed', 'Precision@4': None, 'Pass@1': None},
                {'outcome': 'pass', 'Precision@4': None, 'Pass@1': 1}]
        summary = aggregate_line('shopping', rows, ('Precision@4', 'Pass@1'))
        self.assertEqual(summary['denominators']['Precision@4'], 1)
        self.assertEqual(summary['denominators']['Pass@1'], 2)
        self.assertEqual(summary['n_setup_failed'], 1)

    def test_rerun_ledger_tracks_setup_failures(self):
        with tempfile.TemporaryDirectory() as artifacts, tempfile.TemporaryDirectory() as runs:
            artifacts, runs = Path(artifacts), Path(runs)
            first = runs / 'run-a'
            first.mkdir()
            report = {'cases': {'shopping': [{'case_id': 'shop-d-01', 'line': 'shopping',
                                              'outcome': 'setup_failed',
                                              'reason': 'provider_fault'}],
                                'support': [], 'ads': []}}
            write_report(first, [], [], [], official=False)
            from quality_v2 import _iter_case_rows
            report['cases'] = {'shopping': list(report['cases']['shopping']), 'support': [], 'ads': []}
            # write summary via write_report shape then append ledger
            report2 = {'schema_version': 'quality-v2-report-v1', 'official': False, 'partial': False,
                       'composite_score': None, 'note': 'x', 'provenance': {},
                       'shopping': aggregate_line('shopping', report['cases']['shopping'], ('Precision@4',)),
                       'support': aggregate_line('support', [], ()),
                       'ads': aggregate_line('ads', [], ()),
                       'cases': report['cases']}
            (first / 'summary.json').write_text(json.dumps(report2))
            copy = first.parent / 'artifacts-copy'
            copy.mkdir(exist_ok=True)
            import shutil
            shutil.copy(first / 'summary.json', artifacts / 'summary-invalid-dir.json')
            entries = append_rerun_ledger(first, report2, artifacts_dir=artifacts)
            self.assertEqual(entries[0]['case_id'], 'shop-d-01')
            self.assertEqual(entries[0]['status'], 'pending_rerun')
            second = runs / 'run-b'
            second.mkdir()
            resolved = {'schema_version': 'quality-v2-report-v1', 'official': False, 'partial': True,
                        'composite_score': None, 'note': 'x', 'provenance': {},
                        'shopping': aggregate_line('shopping', [{'case_id': 'shop-d-01', 'line': 'shopping',
                                                                 'outcome': 'pass', 'Pass@1': 1}], ('Pass@1',)),
                        'support': aggregate_line('support', [], ()),
                        'ads': aggregate_line('ads', [], ()),
                        'cases': {'shopping': [{'case_id': 'shop-d-01', 'line': 'shopping',
                                                'outcome': 'pass', 'Pass@1': 1}], 'support': [], 'ads': []}}
            (second / 'summary.json').write_text(json.dumps(resolved))
            shutil.copytree(first, artifacts / 'run-a')
            entries2 = append_rerun_ledger(second, resolved, artifacts_dir=artifacts)
            self.assertEqual(entries2[0]['prior_run'], 'run-a')
            self.assertEqual(entries2[0]['current_outcome'], 'pass')

    def test_contract_public_headers(self):
        contract = json.loads(CONTRACT_JSON.read_text())
        self.assertEqual(contract['shopping']['k'], 4)
        self.assertEqual(contract['shopping']['score_surface'], 'agent_selected_sku_keys')
        self.assertTrue(contract['no_composite_score'])
        self.assertEqual(contract['public_headers_only'],
                         ['Pass@1', 'Precision@4/ceiling', 'Recall@8', 'Faithfulness',
                          'Attribution_integrity'])
        self.assertEqual(len(contract['ads']['attribution_integrity']['assertions']), 8)
        self.assertTrue(contract['ads']['ctr_cvr_are_diagnostics'])
        self.assertEqual(contract['ads']['clicks_without_payment_cvr'], 0.0)
        self.assertTrue(contract['ads']['unknown_payments_counted'])
        self.assertFalse(contract['ads']['unknown_payments_enter_cvr'])
        self.assertTrue(contract['support']['faithfulness_requires_answer_side_and_citation_side'])
        self.assertTrue(contract['support']['llm_judge']['development_only'])
        self.assertTrue(contract['support']['llm_judge']['enters_public_score'])
        self.assertTrue(contract['support']['faithfulness_judge']['judge_differs_from_main_model'])
        self.assertTrue(contract['support']['faithfulness_rule_diagnostic'])
        self.assertTrue(contract['annotation_error_aborts_run'])

    def test_dev_sets_validate(self):
        self.assertTrue(validate_dev_sets())

    def test_chitchat_with_gold_is_annotation_error(self):
        case = {'case_id': 'bad', 'split': 'development', 'expected_retrieval': False,
                'relevant_doc_ids': ['02-payment'], 'checkable_claims': []}
        problems = []
        validate_support_case(case, problems)
        self.assertTrue(any('chitchat_cannot_have_relevant_docs' in item for item in problems))


class TrialsAndCITests(unittest.TestCase):
    def test_wilson_interval_known_values(self):
        # 5/10 and 8/8 are textbook Wilson 95% values.
        self.assertEqual(wilson_ci(0.5, 10), [0.2366, 0.7634])
        self.assertEqual(wilson_ci(1.0, 8), [0.6756, 1.0])
        self.assertIsNone(wilson_ci(None, 10))
        self.assertIsNone(wilson_ci(0.5, 0))

    def test_k1_aggregation_keeps_legacy_semantics(self):
        rows = [{'case_id': 'a', 'outcome': 'pass', 'Precision@4': 0.5, 'Pass@1': 1},
                {'case_id': 'b', 'outcome': 'fail', 'Precision@4': 0.0, 'Pass@1': 0},
                {'case_id': 'c', 'outcome': 'pass', 'Precision@4': None, 'Pass@1': 1}]
        summary = aggregate_line('shopping', rows, ('Precision@4', 'Pass@1'))
        self.assertEqual(summary['Precision@4'], 0.25)
        self.assertEqual(summary['Pass@1'], 2 / 3)
        self.assertEqual(summary['denominators']['Precision@4'], 2)
        self.assertEqual(summary['denominators']['Pass@1'], 3)
        self.assertEqual(summary['ci95_wilson']['Pass@1'], wilson_ci(2 / 3, 3))
        self.assertNotIn('trials', summary)
        self.assertNotIn('pass^k', summary)
        self.assertNotIn('n_cases', summary)

    def test_k1_report_has_no_trial_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            report = write_report(folder, [], [], [], official=False)
        self.assertEqual(report['trials'], 1)
        self.assertNotIn('per_case_trials', report)
        self.assertNotIn('trials', report['shopping'])

    def test_trials_aggregation_pass_at_k_macro_headline_and_flips(self):
        def row(case, trial, outcome, precision=0.5):
            return {'case_id': case, 'line': 'shopping', 'trial': trial, 'outcome': outcome,
                    'Pass@1': 1 if outcome == 'pass' else 0, 'Precision@4': precision}
        rows = ([row('case-a', t, 'pass') for t in (1, 2, 3)]
                + [row('case-b', 1, 'pass'), row('case-b', 2, 'fail'), row('case-b', 3, 'pass')]
                + [row('case-c', 1, 'setup_failed', None), row('case-c', 2, 'pass'), row('case-c', 3, 'pass')])
        summary = aggregate_line('shopping', rows, ('Precision@4', 'Pass@1'))
        self.assertEqual(summary['trials'], 3)
        self.assertEqual(summary['n_cases'], 3)
        self.assertEqual(summary['n_scored'], 8)  # trials, not cases
        # Macro headline: per-case trial means keep every case at equal weight.
        self.assertAlmostEqual(summary['Pass@1'], (1 + 2 / 3 + 1) / 3)
        self.assertEqual(summary['denominators']['Pass@1'], 8)
        # pass^k eligibility excludes case-c (one setup_failed trial).
        self.assertEqual(summary['pass^k'], {'k': 3, 'n_eligible': 2, 'n_all_pass': 1, 'value': 0.5})
        self.assertEqual(summary['flip_cases'], ['case-b'])
        table = trial_table(rows)
        self.assertEqual(table['n_cases'], 3)
        self.assertEqual(table['n_flipped'], 1)
        entry = next(item for item in table['cases'] if item['case_id'] == 'case-b')
        self.assertEqual(entry['pass_rate'], 2 / 3)
        self.assertTrue(entry['flipped'])
        with tempfile.TemporaryDirectory() as folder:
            report = write_report(folder, rows, [], [], official=False, trials=3)
        self.assertEqual(report['trials'], 3)
        self.assertIn('case-b', report['per_case_trials']['shopping']['cases'][1]['case_id'])
        self.assertNotIn('support', report['per_case_trials'])

    def test_rerun_ledger_groups_trials_per_case(self):
        with tempfile.TemporaryDirectory() as artifacts:
            artifacts = Path(artifacts)
            run_dir = artifacts / 'run-t'
            run_dir.mkdir()
            report = {'cases': {'shopping': [
                {'case_id': 'shop-d-01', 'line': 'shopping', 'trial': 1, 'outcome': 'setup_failed'},
                {'case_id': 'shop-d-01', 'line': 'shopping', 'trial': 2, 'outcome': 'pass', 'Pass@1': 1},
                {'case_id': 'shop-d-01', 'line': 'shopping', 'trial': 3, 'outcome': 'pass', 'Pass@1': 1},
                {'case_id': 'shop-d-02', 'line': 'shopping', 'trial': 1, 'outcome': 'fail', 'Pass@1': 0}],
                'support': [], 'ads': []}}
            entries = append_rerun_ledger(artifacts / 'run-t', report, artifacts_dir=artifacts)
            self.assertEqual(len(entries), 1)  # one entry per case, not per trial
            self.assertEqual(entries[0]['case_id'], 'shop-d-01')
            self.assertEqual(entries[0]['current_outcome'], 'partial_setup_failed')
            self.assertEqual(entries[0]['status'], 'pending_rerun')
            self.assertEqual([item['outcome'] for item in entries[0]['trial_outcomes']],
                             ['setup_failed', 'pass', 'pass'])
            ledger = (artifacts / 'rerun-ledger.jsonl').read_text().strip().splitlines()
            self.assertEqual(len(ledger), 1)

    def test_judge_targets_exact_trial_rows(self):
        from unittest.mock import patch
        import judge_quality_v2 as jq
        case = {'case_id': 'x', 'checkable_claims': [{'id': 'a', 'text': '模拟支付', 'scope': 'essential'}],
                'expected_retrieval': True, 'expected_handoff': False, 'relevant_doc_ids': []}
        row1 = {'case_id': 'x', 'trial': 1, 'outcome': 'pass'}
        row2 = {'case_id': 'x', 'trial': 2, 'outcome': 'pass'}
        verdicts = [{'supported': 1, 'total': 1, 'verdicts': {'a': 'supported'}, 'quotes': {'a': '模拟支付'}, 'summary': ''},
                    {'supported': 0, 'total': 1, 'verdicts': {'a': 'absent'}, 'quotes': {'a': ''}, 'summary': ''}]
        with patch.object(jq, 'judge_case', side_effect=verdicts):
            jq.apply_judge_faithfulness([row1, row2],
                                        [(case, {'answer': 'a'}, row1), (case, {'answer': 'b'}, row2)],
                                        {})
        self.assertEqual(row1['Faithfulness'], 1.0)
        self.assertEqual(row2['Faithfulness'], 0.0)  # same case_id, different trial rows
        self.assertEqual(row1['judge_quotes'], {'a': '模拟支付'})  # quotes retained for human review


class Tier1DiagnosticTests(unittest.TestCase):
    """Six Tier-1 diagnostic columns: deterministic, trial-level, never public headers."""

    def setUp(self):
        self.shopping_cases = {row['case_id']: row for row in load_jsonl(SHOPPING_DEV)}
        self.skus = catalog_index()

    @staticmethod
    def support_observation(doc_ids):
        return {'result': {'answer': '已按店内资料回答。', 'answer_status': 'answered', 'citations': []},
                'tool_calls': [{'tool_name': 'search_knowledge',
                                'data': {'candidates': [{'doc_id': doc} for doc in doc_ids],
                                         'retrieval': {'final_depth': 8}}}]}

    @staticmethod
    def support_case(gold):
        return {'case_id': 'tier1', 'relevant_doc_ids': gold, 'expected_retrieval': True,
                'expected_handoff': False, 'checkable_claims': []}

    def test_mrr_known_values_dedup_and_beyond_k(self):
        # gold a,b,c at ranks 2,3,5 -> (1/2 + 1/3 + 1/5) / 3 = 31/90
        score = score_support(self.support_case(['a', 'b', 'c']),
                              self.support_observation(['x', 'a', 'b', 'y', 'c']))
        self.assertAlmostEqual(score['MRR@8'], 31 / 90, places=12)
        # duplicates keep first position: a=1, b=3 -> (1 + 1/3) / 2 = 2/3
        score = score_support(self.support_case(['a', 'b']),
                              self.support_observation(['a', 'x', 'a', 'b']))
        self.assertAlmostEqual(score['MRR@8'], 2 / 3, places=12)
        # gold ranked 9th is beyond @8: reciprocal 0, same null-vs-zero face as Recall@8
        score = score_support(self.support_case(['a']),
                              self.support_observation(['b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'a']))
        self.assertEqual(score['MRR@8'], 0.0)
        self.assertEqual(score['Recall@8'], 0.0)

    def test_recall_at_1_strict(self):
        self.assertEqual(score_support(self.support_case(['a']),
                                       self.support_observation(['a', 'b']))['Recall@1'], 1.0)
        self.assertEqual(score_support(self.support_case(['a']),
                                       self.support_observation(['b', 'a']))['Recall@1'], 0.0)
        # two distinct gold docs cannot both sit at rank 1 after dedup
        self.assertEqual(score_support(self.support_case(['a', 'b']),
                                       self.support_observation(['a', 'b']))['Recall@1'], 0.0)
        chitchat = self.support_case([])
        chitchat['expected_retrieval'] = False
        self.assertIsNone(score_support(chitchat, self.support_observation([]))['Recall@1'])

    def test_context_precision_known_values(self):
        # hits at i=1 (1/1) and i=3 (2/3), |gold|=2 -> (1 + 2/3) / 2 = 5/6
        score = score_support(self.support_case(['a', 'b']),
                              self.support_observation(['a', 'x', 'b', 'y']))
        self.assertAlmostEqual(score['Context_Precision@8'], 5 / 6, places=12)
        # single gold at rank 3: 1/3 — and identical to MRR for single-gold trials
        score = score_support(self.support_case(['a']),
                              self.support_observation(['x', 'y', 'a']))
        self.assertAlmostEqual(score['Context_Precision@8'], 1 / 3, places=12)
        self.assertAlmostEqual(score['MRR@8'], 1 / 3, places=12)
        # no hits at all -> 0.0, not null
        self.assertEqual(score_support(self.support_case(['q']),
                                       self.support_observation(['x', 'y']))['Context_Precision@8'], 0.0)

    def test_violation_free_at_1_first_slot_only(self):
        case = self.shopping_cases['shop-d-01']
        lite, pro = self.skus['kb-lite:black'], self.skus['kb-pro:black']
        clean = score_shopping(case, {'selected_sku_keys': [lite['sku_key'], pro['sku_key']],
                                      'products': [lite, pro],
                                      'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(clean['violation_free@1'], 1)   # first slot within budget
        dirty = score_shopping(case, {'selected_sku_keys': [pro['sku_key'], lite['sku_key']],
                                      'products': [pro, lite],
                                      'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(dirty['violation_free@1'], 0)   # first slot over budget
        # empty selection on a gold case leaves the denominator
        empty = score_shopping(case, {'selected_sku_keys': [], 'products': [],
                                      'retrieve_diagnostics': {'popular_used': False}})
        self.assertIsNone(empty['violation_free@1'])
        # compare cases score completeness, not first-slot compliance
        compare_case = self.shopping_cases['shop-d-04']
        compare = score_shopping(compare_case, {'selected_sku_keys': [lite['sku_key']], 'products': [lite],
                                                'comparison_complete': False, 'missing_targets': ['火星飞船'],
                                                'comparison_sku_keys': [lite['sku_key']],
                                                'retrieve_diagnostics': {'popular_used': False}})
        self.assertIsNone(compare.get('violation_free@1'))

    def test_empty_set_honesty_mirrors_empty_branch_pass(self):
        case = self.shopping_cases['shop-d-03']
        honest = score_shopping(case, {'selected_sku_keys': [], 'products': [],
                                       'retrieve_diagnostics': {'popular_used': False,
                                                                'empty_reason': 'hard_constraint_unsatisfied'}})
        self.assertEqual(honest['empty_set_honesty'], 1)
        backfilled = score_shopping(case, {'selected_sku_keys': ['chair:mesh'], 'products': [self.skus['chair:mesh']],
                                           'retrieve_diagnostics': {'popular_used': True, 'empty_reason': None}})
        self.assertEqual(backfilled['empty_set_honesty'], 0)
        reasonless = score_shopping(case, {'selected_sku_keys': [], 'products': [],
                                           'retrieve_diagnostics': {'popular_used': False, 'empty_reason': None}})
        self.assertEqual(reasonless['empty_set_honesty'], 0)
        # non-empty-satisfaction cases carry no empty-honesty observation
        gold_case = self.shopping_cases['shop-d-01']
        filled = score_shopping(gold_case, {'selected_sku_keys': ['kb-lite:black'],
                                            'products': [self.skus['kb-lite:black']],
                                            'retrieve_diagnostics': {'popular_used': False}})
        self.assertIsNone(filled.get('empty_set_honesty'))

    def test_handoff_f1_excludes_allow_handoff_and_setup_failed(self):
        rows = [
            {'outcome': 'pass', 'expected_handoff': True, 'handoff': True},
            {'outcome': 'pass', 'expected_handoff': True, 'handoff': True},
            {'outcome': 'fail', 'expected_handoff': False, 'handoff': True},
            {'outcome': 'fail', 'expected_handoff': True, 'handoff': False},
            {'outcome': 'pass', 'expected_handoff': False, 'handoff': False},
            {'outcome': 'pass', 'expected_handoff': False, 'handoff': False},
            {'outcome': 'pass', 'expected_handoff': False, 'handoff': False},
            {'outcome': 'pass', 'allow_handoff': True, 'expected_handoff': False, 'handoff': False},
            {'outcome': 'pass', 'allow_handoff': True, 'expected_handoff': False, 'handoff': True},
            {'outcome': 'setup_failed', 'expected_handoff': True, 'handoff': False},
        ]
        result = handoff_f1(rows)
        self.assertEqual((result['tp'], result['fp'], result['fn']), (2, 1, 1))
        self.assertAlmostEqual(result['precision'], 2 / 3, places=12)
        self.assertAlmostEqual(result['recall'], 2 / 3, places=12)
        self.assertAlmostEqual(result['f1'], 2 / 3, places=12)
        self.assertEqual(result['denominator'], 7)
        self.assertEqual(result['excluded_allow_handoff'], 2)

    def test_trial_level_aggregation_differs_from_case_macro(self):
        rows = [{'case_id': 'a', 'trial': 1, 'outcome': 'pass', 'Pass@1': 1, 'violation_free@1': 1},
                {'case_id': 'a', 'trial': 2, 'outcome': 'fail', 'Pass@1': 0, 'violation_free@1': 0},
                {'case_id': 'b', 'trial': 1, 'outcome': 'pass', 'Pass@1': 1, 'violation_free@1': 1},
                {'case_id': 'b', 'trial': 2, 'outcome': 'pass', 'Pass@1': 1, 'violation_free@1': 1},
                {'case_id': 'b', 'trial': 3, 'outcome': 'pass', 'Pass@1': 1, 'violation_free@1': 1}]
        summary = aggregate_line('shopping', rows, ('Pass@1',), trial_level_names=('violation_free@1',))
        self.assertAlmostEqual(summary['violation_free@1'], 4 / 5, places=12)   # trial share
        self.assertAlmostEqual(summary['Pass@1'], 0.75, places=12)             # case-macro headline (0.5, 1.0)
        self.assertEqual(summary['denominators']['violation_free@1'], 5)
        self.assertIn('violation_free@1', summary['ci95_wilson'])

    def test_self_check_synthetic_tier1_values(self):
        shopping, support, _ = self_check_scores()
        with tempfile.TemporaryDirectory() as folder:
            report = write_report(folder, shopping, support, [], official=False, synthetic=True)
        # synthetic retrieval ranks gold docs in gold order: MRR = mean(1/i over gold positions)
        eligible = [case for case in load_jsonl(SUPPORT_DEV)
                    if case.get('relevant_doc_ids') and case.get('expected_retrieval') is not False]
        expected_mrr = quality_v2.mean(
            quality_v2.mean(1 / i for i in range(1, len(case['relevant_doc_ids']) + 1))
            for case in eligible)
        self.assertAlmostEqual(report['support']['MRR@8'], expected_mrr, places=12)
        # only single-gold trials can put all gold at rank 1 under dedup
        expected_recall1 = sum(1 for case in eligible if len(case['relevant_doc_ids']) == 1) / len(eligible)
        self.assertAlmostEqual(report['support']['Recall@1'], expected_recall1, places=12)
        # synthetic selections are gold SKUs (first slot satisfies) and legal empties
        self.assertEqual(report['shopping']['violation_free@1'], 1.0)
        self.assertEqual(report['shopping']['empty_set_honesty'], 1.0)
        n_recommend_gold = sum(1 for case in load_jsonl(SHOPPING_DEV)
                               if (case.get('kind') or 'recommend') == 'recommend'
                               and case.get('satisfaction_set'))
        # empty-satisfaction compare cases score via the compare branch instead,
        # so the honesty denominator is the non-compare empty-satisfaction cases
        n_empty = sum(1 for case in load_jsonl(SHOPPING_DEV)
                      if not case.get('satisfaction_set')
                      and (case.get('kind') or 'recommend') != 'compare')
        self.assertEqual(report['shopping']['denominators']['violation_free@1'], n_recommend_gold)
        self.assertEqual(report['shopping']['denominators']['empty_set_honesty'], n_empty)
        # perfect synthetic handoff: F1=1, allow_handoff cases excluded and counted
        self.assertEqual(report['support']['handoff_f1']['f1'], 1.0)
        self.assertEqual(report['support']['handoff_f1']['excluded_allow_handoff'],
                         sum(1 for row in support if row.get('allow_handoff')))


class JudgeCalibrationTests(unittest.TestCase):
    def test_calibration_pairs_valid(self):
        import judge_quality_v2 as jq
        pairs = jq.load_calibration_pairs()
        self.assertGreaterEqual(len(pairs), 28)
        self.assertLessEqual(len(pairs), 40)
        categories = {pair['category'] for pair in pairs}
        self.assertTrue({'verbatim', 'paraphrase', 'negation_flip', 'fabrication',
                         'boundary_absent', 'boundary_partial'} <= categories)
        gold_credit = sum(1 for pair in pairs if pair['expect_verdict'] == 'supported')
        self.assertGreater(gold_credit, len(pairs) * 0.3)   # both classes meaningfully represented
        self.assertLess(gold_credit, len(pairs) * 0.7)
        for pair in pairs:  # loader already enforces substring + verdict taxonomy; assert shape too
            self.assertTrue(pair['user_turns'] and pair['agent_answer'])
            self.assertIn(pair['claim']['text'], pair['claim']['text'])  # id/text present
            self.assertTrue(pair['claim'].get('id'))

    def test_cohens_kappa_known_values(self):
        from judge_quality_v2 import cohens_kappa
        self.assertEqual(cohens_kappa(['a', 'a', 'b', 'b'], ['a', 'a', 'b', 'b']), 1.0)
        self.assertAlmostEqual(cohens_kappa(['a', 'a', 'b', 'b'], ['a', 'b', 'a', 'b']), 0.0)
        self.assertLess(cohens_kappa(['a', 'a', 'a', 'b'], ['b', 'b', 'b', 'a']), 0.0)
        self.assertIsNone(cohens_kappa([], []))

    def test_human_review_sampling_deterministic_and_capped(self):
        import judge_quality_v2 as jq
        claims = [{'id': 'c%d' % i, 'text': '命题%d' % i, 'scope': 'essential'} for i in range(30)]
        targets = [{'case': {'case_id': 'sup-x', 'checkable_claims': claims},
                    'row': {'judge_verdicts': {('c%d' % i): ('supported' if i % 2 else 'absent')
                                               for i in range(30)},
                            'judge_quotes': {('c%d' % i): ('原句%d' % i) for i in range(30)}}}
                   ]  # 30 judged claims -> sample capped at 20
        with tempfile.TemporaryDirectory() as folder:
            first = jq.write_human_review(folder, targets)
            lines_a = (Path(folder) / 'judge' / 'human-review.jsonl').read_text()
            markdown_a = (Path(folder) / 'judge' / 'human-review.md').read_text()
            second = jq.write_human_review(folder, targets)
            lines_b = (Path(folder) / 'judge' / 'human-review.jsonl').read_text()
        self.assertEqual(first, 20)
        self.assertEqual(second, 20)
        self.assertEqual(lines_a, lines_b)  # same seed -> same sample
        rows = [json.loads(line) for line in lines_a.splitlines()]
        self.assertEqual(len(rows), 20)
        self.assertTrue(all(row['quote'] for row in rows))
        self.assertIn('人工结论', markdown_a)
        self.assertEqual(markdown_a.count('\n| '), 21)  # header row + 20 sampled rows

    def test_human_review_skips_empty_pool(self):
        import judge_quality_v2 as jq
        self.assertIsNone(jq.write_human_review('/tmp/unused-empty', [{'case': {'case_id': 'x'},
                                                                      'row': {}}]))


class AdsScriptTests(unittest.TestCase):
    def setUp(self):
        self.books = {b['playbook_id']: b for b in load_json(ADS_PLAYBOOKS)['playbooks']}

    def test_script_counts_must_derive_from_script(self):
        from quality_v2 import _validate_ads_script
        book = json.loads(json.dumps(self.books['ads-d-06']))
        book['expected']['counts']['impressions'] += 1
        issues = _validate_ads_script(book)
        self.assertTrue(any('impressions_must_equal_script_totals' in i for i in issues))
        self.assertFalse(_validate_ads_script(self.books['ads-d-06']))

    def test_multi_campaign_requires_same_sku(self):
        from quality_v2 import _validate_ads_script
        book = json.loads(json.dumps(self.books['ads-d-08']))
        book.pop('same_sku')
        self.assertTrue(any('multi_campaign_requires_same_sku' in i
                            for i in _validate_ads_script(book)))

    def test_mechanism_assertions_score_and_name_failures(self):
        book = self.books['ads-d-06']
        observation = quality_v2.synthetic_ads_observation(book)
        perfect = score_ads(book, observation)
        self.assertEqual(perfect['Attribution_integrity'], 1.0)
        self.assertEqual(len(perfect['failed_assertions']), 0)
        observation['rank_probes'][1]['observed_first'] = 'a'  # fatigue should have demoted a
        broken = score_ads(book, observation)
        self.assertLess(broken['Attribution_integrity'], 1.0)
        self.assertIn('rank:1.first', broken['failed_assertions'])
        exhausted = self.books['ads-d-09']
        observation = quality_v2.synthetic_ads_observation(exhausted)
        observation['rejections'][0]['observed_status'] = 200  # gate must reject with 409
        observation['status_probes'][0]['observed_status'] = 'ACTIVE'  # must have auto-exhausted
        soft = score_ads(exhausted, observation)
        self.assertIn('reject:0.click.ads_not_active', soft['failed_assertions'])
        self.assertIn('status:0.a', soft['failed_assertions'])

    def test_assertion_denominator_grows_with_script(self):
        base = score_ads(self.books['ads-d-01'], quality_v2.synthetic_ads_observation(self.books['ads-d-01']))
        scripted = score_ads(self.books['ads-d-06'], quality_v2.synthetic_ads_observation(self.books['ads-d-06']))
        self.assertEqual(base['Attribution_integrity'], 1.0)  # 8 base assertions
        # ads-d-06 adds 4 rank assertions (3 expect_first + 2 expect_items... = 5) over the base 8
        self.assertEqual(scripted['Attribution_integrity'], 1.0)


class Holdout2SealTests(unittest.TestCase):
    def test_run_gate_flips_with_manifest_presence(self):
        import tempfile
        import quality_v2
        original = dict(quality_v2.HOLDOUT2_MANIFESTS)
        try:
            with tempfile.TemporaryDirectory() as folder:
                for line, path in original.items():
                    quality_v2.HOLDOUT2_MANIFESTS[line] = Path(folder) / (line + '.json')
                with self.assertRaisesRegex(ValueError, 'holdout2_seal_pending'):
                    quality_v2.holdout2_ready()
                for path in quality_v2.HOLDOUT2_MANIFESTS.values():
                    path.write_text('{}')
                self.assertTrue(quality_v2.holdout2_ready())
                self.assertTrue(quality_v2.holdout2_ready(('shopping',)))
        finally:
            quality_v2.HOLDOUT2_MANIFESTS = original

    def test_holdout2_sealed_in_repo(self):
        import quality_v2
        # holdout-2 was sealed on 2026-09-13 after independent review; the gate
        # must stay open from here on (first test = final test is in force).
        self.assertTrue(all(path.exists() for path in quality_v2.HOLDOUT2_MANIFESTS.values()))
        self.assertTrue(quality_v2.holdout2_ready())

    def test_holdout2_datasets_validate_offline(self):
        quality_v2.validate_dev_sets(split='holdout2')  # offline check only


class Holdout3SealTests(unittest.TestCase):
    def test_run_gate_flips_with_manifest_presence(self):
        import tempfile
        import quality_v2
        original = dict(quality_v2.HOLDOUT3_MANIFESTS)
        try:
            with tempfile.TemporaryDirectory() as folder:
                for line, path in original.items():
                    quality_v2.HOLDOUT3_MANIFESTS[line] = Path(folder) / (line + '.json')
                with self.assertRaisesRegex(ValueError, 'holdout3_seal_pending'):
                    quality_v2.holdout3_ready()
                for path in quality_v2.HOLDOUT3_MANIFESTS.values():
                    path.write_text('{}')
                self.assertTrue(quality_v2.holdout3_ready())
                self.assertTrue(quality_v2.holdout3_ready(('shopping',)))
        finally:
            quality_v2.HOLDOUT3_MANIFESTS = original

    def test_holdout3_draft_validates_offline_when_authored(self):
        # Draft stage: questions may not exist yet; once they do they must validate
        # offline. Running is refused until the user stamps every line's manifest.
        from quality_v2 import SHOPPING_HOLDOUT3
        if SHOPPING_HOLDOUT3.exists():
            quality_v2.validate_dev_sets(split='holdout3')


class FrozenReportTests(unittest.TestCase):
    def test_report_frozen_sections_and_no_composite(self):
        import tempfile
        from eval_quality_v2 import write_frozen_report
        block = {'n': 3, 'n_scored': 3, 'n_setup_failed': 0, 'n_pass': 2,
                 'Pass@1': 2 / 3, 'denominators': {'Pass@1': 3},
                 'ci95_wilson': {'Pass@1': [0.2, 0.9]},
                 'pass^k': {'k': 3, 'n_eligible': 1, 'n_all_pass': 1, 'value': 1.0},
                 'flip_cases': []}
        summary = {'schema_version': 'quality-v2-report-v2', 'official': True, 'partial': False,
                   'trials': 3, 'composite_score': None, 'note': 'x',
                   'provenance': {'git_head': 'deadbeef', 'contract_sha256': 'c0ffee'},
                   'shopping': {**block, 'Precision@4/ceiling': 1.0, 'Precision@4': 0.5,
                                'denominators': {'Pass@1': 3, 'Precision@4': 3, 'Precision@4/ceiling': 3}},
                   'support': {**block}, 'ads': {**block, 'Attribution_integrity': 1.0},
                   'cases': {'shopping': [
                       {'case_id': 'shop-x', 'trial': 1, 'outcome': 'fail',
                        'selected': ['a', 'b'], 'hits': 1},
                       {'case_id': 'shop-x', 'trial': 2, 'outcome': 'pass', 'selected': ['a'], 'hits': 1}],
                       'support': [], 'ads': []},
                   'per_case_trials': {}}
        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder) / 'run-x'
            run_dir.mkdir()
            (run_dir / 'summary.json').write_text(json.dumps(summary))
            report = write_frozen_report(run_dir)
            text = (run_dir / 'report.md').read_text()
        self.assertIn('指标↔设计↔归因层映射表', text)
        self.assertIn('Wilson 95% CI', text)
        self.assertIn('选品越金标（hits 1/2）', text)      # 线感知的失败归因
        self.assertIn('pass^3', text)
        self.assertIn('qv2', report)                        # 映射表内容在场
        self.assertNotIn('composite_score', text)           # 不合成总分也不复述它
        self.assertIn('模拟 CTR/CVR 非因果', text)


if __name__ == '__main__':
    unittest.main()
