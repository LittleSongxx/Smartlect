"""Synthetic checks for the attribution tool. Never reads repository suite artifacts."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import attribution


def case(case_id, repeat, *, passed, checks=None, recall=None, observed=False, permitted=False):
    checks = checks or {'answer_status_matches': passed, 'required_human_ticket_persisted': passed,
                        'required_citation_documents_present': True, 'no_literal_canary_in_output': True}
    scores = {'deterministic_checks_passed': passed, 'checks': checks,
              'escalation': {'observed': observed, 'permitted': permitted},
              'citation_support_rate': None, 'answer_fact_completeness': None,
              'correct_refusal_or_handoff': None}
    if recall is not None:
        scores['retrieval_recall_at_4'] = recall
        scores['retrieval_recall_at_8'] = recall
    return {'case_id': case_id, 'repeat_id': repeat, 'status':
            'AWAITING_SEMANTIC_REVIEW' if passed else 'FAILED', 'scores': scores}


def write_run(root, name, rows, bindings):
    directory = Path(root) / name
    directory.mkdir(parents=True)
    (directory / 'run.json').write_text(json.dumps({'bindings': bindings, 'split': 'development', 'repeat': 2}))
    for row in rows:
        (directory / f"{row['case_id']}-r{row['repeat_id']}.json").write_text(json.dumps(row))
    return directory


class AttributionTests(unittest.TestCase):
    def build(self, temp):
        before = write_run(temp, 'before', [
            case('a', 1, passed=False, recall=0.5), case('b', 1, passed=True, recall=1.0),
            case('c', 1, passed=True, recall=1.0)], {'prompt_version': 'v1', 'model': {'model_id': 'm'}})
        after = write_run(temp, 'after', [
            case('a', 1, passed=True, recall=1.0), case('b', 1, passed=False, recall=1.0),
            case('d', 1, passed=True, recall=1.0)], {'prompt_version': 'v2', 'model': {'model_id': 'm'}})
        return before, after

    def test_only_case_repeats_both_runs_executed_are_compared(self):
        # A run that stopped early would otherwise look better or worse for covering less.
        with TemporaryDirectory() as temp:
            before, after = self.build(temp)
            result = attribution.compare(attribution.load(before), attribution.load(after))
            self.assertEqual(result['shared_case_repeats'], 2)
            self.assertEqual(result['only_in_before'], ['c-r1'])
            self.assertEqual(result['only_in_after'], ['d-r1'])
            # a fixed, b broken, c and d excluded: net zero rather than a false +1.
            self.assertEqual(result['delta']['deterministic_passes'], 0)
            self.assertEqual(result['delta']['content_deterministic_passes'], 0)
            self.assertEqual(result['case_level_movement'], {'fixed': ['a-r1'], 'broken': ['b-r1']})
            self.assertEqual(result['content_case_level_movement'], {'fixed': ['a-r1'], 'broken': ['b-r1']})

    def test_recall_and_failing_checks_are_computed_not_copied(self):
        with TemporaryDirectory() as temp:
            before, after = self.build(temp)
            result = attribution.compare(attribution.load(before), attribution.load(after))
            self.assertEqual(result['before']['metrics']['recall_at_4'], 0.75)
            self.assertEqual(result['after']['metrics']['recall_at_4'], 1.0)
            self.assertEqual(result['delta']['recall_at_4'], 0.25)
            self.assertEqual(result['delta']['failing_checks']['answer_status_matches'], 0)

    def test_binding_changes_are_surfaced_so_a_claim_names_what_moved(self):
        with TemporaryDirectory() as temp:
            before, after = self.build(temp)
            result = attribution.compare(attribution.load(before), attribution.load(after))
            self.assertEqual(result['binding_changes']['prompt_version'], {'before': 'v1', 'after': 'v2'})
            self.assertNotIn('model', result['binding_changes'])

    def test_semantic_metrics_stay_null_and_are_never_inferred(self):
        with TemporaryDirectory() as temp:
            before, after = self.build(temp)
            result = attribution.compare(attribution.load(before), attribution.load(after))
            for side in ('before', 'after'):
                self.assertIsNone(result[side]['metrics']['citation_support_rate'])
                self.assertIsNone(result[side]['metrics']['answer_fact_completeness'])

    def test_content_passes_ignore_stale_process_bind_failures(self):
        with TemporaryDirectory() as temp:
            checks = {'answer_status_matches': True, 'required_human_ticket_persisted': True,
                      'required_citation_documents_present': True, 'no_literal_canary_in_output': True,
                      'frozen_run_versions_match': False}
            before = write_run(temp, 'before', [case('a', 1, passed=True)], {'prompt_version': 'v1'})
            after_row = case('a', 1, passed=False, checks=checks)
            after_row['scores']['checks'] = checks
            after_row['scores']['deterministic_checks_passed'] = False
            after = write_run(temp, 'after', [after_row], {'prompt_version': 'v1'})
            result = attribution.compare(attribution.load(before), attribution.load(after))
            self.assertEqual(result['delta']['deterministic_passes'], -1)
            self.assertEqual(result['delta']['content_deterministic_passes'], 0)
            self.assertEqual(result['content_case_level_movement'], {'fixed': [], 'broken': []})
            self.assertEqual(result['case_level_movement'], {'fixed': [], 'broken': ['a-r1']})

    def test_recording_requires_a_named_root_cause(self):
        with TemporaryDirectory() as temp:
            before, after = self.build(temp)
            for argv in ([str(before), str(after), '--change-id', 'x', '--designed', 'y'],
                         [str(before), str(after), '--change-id', 'x', '--root-cause', 'z']):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    attribution.main(['record', *argv])

    def test_ledger_appends_and_keeps_prior_entries(self):
        with TemporaryDirectory() as temp:
            before, after = self.build(temp)
            ledger = Path(temp) / 'ledger.json'
            original = attribution.LEDGER
            attribution.LEDGER = ledger
            try:
                for name in ('first', 'second'):
                    attribution.main(['record', str(before), str(after), '--change-id', name,
                                      '--designed', 'd', '--root-cause', 'r', '--caveat', 'c'])
                entries = json.loads(ledger.read_text())['entries']
            finally:
                attribution.LEDGER = original
            self.assertEqual([e['change_id'] for e in entries], ['first', 'second'])
            self.assertEqual(entries[0]['caveats'], ['c'])
            self.assertEqual(entries[0]['measurement']['shared_case_repeats'], 2)


if __name__ == '__main__':
    unittest.main()
