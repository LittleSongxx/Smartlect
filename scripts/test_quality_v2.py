"""Contract tests for quality-v2 scoring. No live stack, no holdout load."""
import json
import tempfile
import unittest
from pathlib import Path

from eval_quality_v2 import business_closeout_after_budget
import quality_v2
from quality_v2 import (ADS_PLAYBOOKS, CONTRACT_JSON, SHOPPING_CATALOG, SHOPPING_DEV, SUPPORT_DEV,
                        AnnotationError, ads_grant_envelope, aggregate_line, append_rerun_ledger,
                        campaign_rates, catalog_index, catalog_overlay_plan, last_real_search,
                        live_support_cases, load_json, load_jsonl, refuse_holdout, remap_observation,
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
        self.assertEqual(score['Pass@1'], 1)

    def test_over_budget_item_fails_pass(self):
        case = self.cases['shop-d-01']
        items = [self.skus['kb-lite:black'], self.skus['kb-pro:black']]
        score = score_shopping(case, {'selected_sku_keys': [row['sku_key'] for row in items],
                                      'products': items, 'retrieve_diagnostics': {'popular_used': False}})
        self.assertEqual(score['Pass@1'], 0)
        self.assertEqual(score['Precision@4'], 0.25)

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
                'verdicts': {'a': 'supported', 'b': 'absent'}, 'summary': ''}
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
        self.assertIsNone(scored['CTR'])
        self.assertIsNone(scored['CVR'])
        self.assertEqual(scored['unknown_payments'], 1)

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
        self.assertEqual(len(shopping), 39)
        self.assertEqual(len(support), 32)
        self.assertEqual(len(ads), 5)
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
        verdicts = [{'supported': 1, 'total': 1, 'verdicts': {'a': 'supported'}, 'summary': ''},
                    {'supported': 0, 'total': 1, 'verdicts': {'a': 'absent'}, 'summary': ''}]
        with patch.object(jq, 'judge_case', side_effect=verdicts):
            jq.apply_judge_faithfulness([row1, row2],
                                        [(case, {'answer': 'a'}, row1), (case, {'answer': 'b'}, row2)],
                                        {})
        self.assertEqual(row1['Faithfulness'], 1.0)
        self.assertEqual(row2['Faithfulness'], 0.0)  # same case_id, different trial rows


if __name__ == '__main__':
    unittest.main()
