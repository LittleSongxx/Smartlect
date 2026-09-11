"""Attribute a measured metric change to the design change that caused it.

A number quoted from memory rots. This reads two completed suite runs, computes the
deltas itself on the case-repeats both runs actually executed, and records them together
with the bindings each run carries, so a later claim cannot drift from the artifacts that
produced it.

    attribution.py compare RUN_A RUN_B
    attribution.py record RUN_A RUN_B --change-id ... --designed ... --root-cause ...

Comparing only the shared subset matters: a run that stopped early would otherwise look
better or worse purely because it covered different cases.
"""
import argparse
import collections
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / 'artifacts/quality-attribution-ledger.json'
CHECKS = ('answer_status_matches', 'required_human_ticket_persisted',
          'required_citation_documents_present', 'no_literal_canary_in_output',
          'citation_locations_valid', 'no_forbidden_new_citations')


def suite_dir(root):
    root = Path(root)
    root = root if root.is_absolute() else (ROOT / root)
    for candidate in (root, root / 'rag-development', root / 'rag-holdout', root / 'tools'):
        if (candidate / 'run.json').exists():
            return candidate
    raise SystemExit(f'no run.json under {root}')


def load(root):
    directory = suite_dir(root)
    run = json.loads((directory / 'run.json').read_text())
    cases = {}
    for path in sorted(directory.glob('*-r[0-9].json')):
        row = json.loads(path.read_text())
        key = f"{row.get('case_id') or row.get('task_id')}-r{row['repeat_id']}"
        cases[key] = row
    inside = directory.is_relative_to(ROOT)
    return {'path': str(directory.relative_to(ROOT) if inside else directory), 'run': run, 'cases': cases}


def measure(side, keys):
    """Metrics over one run, restricted to the given case-repeats."""
    rows = [side['cases'][k] for k in keys if 'scores' in side['cases'].get(k, {})]
    if not rows:
        return {'scored_case_repeats': 0}
    failing = collections.Counter()
    for row in rows:
        for name, ok in row['scores']['checks'].items():
            if not ok:
                failing[name] += 1
    def content_pass(row):
        checks = {name: ok for name, ok in row['scores']['checks'].items() if name != 'frozen_run_versions_match'}
        return bool(checks) and all(checks.values())
    out = {'scored_case_repeats': len(rows),
           'deterministic_passes': sum(r['scores']['deterministic_checks_passed'] for r in rows),
           'content_deterministic_passes': sum(content_pass(r) for r in rows),
           'failing_checks': {name: failing.get(name, 0) for name in CHECKS if name in rows[0]['scores']['checks']},
           'statuses': dict(collections.Counter(r.get('status') for r in rows))}
    escalation = [r['scores']['escalation'] for r in rows if isinstance(r['scores'].get('escalation'), dict)]
    if escalation:
        out['escalation_observed'] = sum(bool(e['observed']) for e in escalation)
        out['escalation_permitted_by_dataset'] = sum(bool(e['permitted']) for e in escalation)
    for k in (4, 8):
        values = [r['scores'][f'retrieval_recall_at_{k}'] for r in rows
                  if r['scores'].get(f'retrieval_recall_at_{k}') is not None]
        if values:
            out[f'recall_at_{k}'] = round(sum(values) / len(values), 4)
            out[f'recall_at_{k}_denominator'] = len(values)
    # Semantic metrics are intentionally left as the runner reported them.
    for name in ('citation_support_rate', 'answer_fact_completeness', 'correct_refusal_or_handoff'):
        reported = {r['scores'].get(name) for r in rows}
        out[name] = None if reported == {None} else 'MIXED_SEE_CASES'
    return out


def binding_delta(before, after):
    keys = sorted(set(before['run']['bindings']) | set(after['run']['bindings']))
    changed = {}
    for key in keys:
        a, b = before['run']['bindings'].get(key), after['run']['bindings'].get(key)
        if a != b:
            changed[key] = {'before': a, 'after': b} if not isinstance(a, dict) else 'differs'
    return changed


def compare(before, after):
    shared = sorted(set(before['cases']) & set(after['cases']))
    only_before = sorted(set(before['cases']) - set(after['cases']))
    only_after = sorted(set(after['cases']) - set(before['cases']))
    a, b = measure(before, shared), measure(after, shared)
    moved = {'fixed': [], 'broken': []}
    content_moved = {'fixed': [], 'broken': []}
    def content_pass(row):
        checks = {name: ok for name, ok in row.get('scores', {}).get('checks', {}).items()
                  if name != 'frozen_run_versions_match'}
        return bool(checks) and all(checks.values())
    for key in shared:
        was = before['cases'][key].get('scores', {}).get('deterministic_checks_passed')
        now = after['cases'][key].get('scores', {}).get('deterministic_checks_passed')
        if was is False and now is True:
            moved['fixed'].append(key)
        elif was is True and now is False:
            moved['broken'].append(key)
        was_c, now_c = content_pass(before['cases'][key]), content_pass(after['cases'][key])
        if (not was_c) and now_c:
            content_moved['fixed'].append(key)
        elif was_c and (not now_c):
            content_moved['broken'].append(key)
    return {
        'compared_on': 'case_repeats executed by both runs',
        'shared_case_repeats': len(shared),
        'only_in_before': only_before, 'only_in_after': only_after,
        'before': {'artifact': before['path'], 'metrics': a},
        'after': {'artifact': after['path'], 'metrics': b},
        'delta': {'deterministic_passes': b.get('deterministic_passes', 0) - a.get('deterministic_passes', 0),
                  'content_deterministic_passes': b.get('content_deterministic_passes', 0) - a.get('content_deterministic_passes', 0),
                  **{f'recall_at_{k}': round(b[f'recall_at_{k}'] - a[f'recall_at_{k}'], 4)
                     for k in (4, 8) if f'recall_at_{k}' in a and f'recall_at_{k}' in b},
                  'failing_checks': {name: b['failing_checks'].get(name, 0) - a['failing_checks'].get(name, 0)
                                     for name in a.get('failing_checks', {})}},
        'case_level_movement': moved,
        'content_case_level_movement': content_moved,
        'binding_changes': binding_delta(before, after),
    }


def head():
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['compare', 'record'])
    parser.add_argument('before')
    parser.add_argument('after')
    parser.add_argument('--change-id', help='Short stable id, e.g. handoff-as-declared-status')
    parser.add_argument('--designed', help='What was actually built')
    parser.add_argument('--root-cause', help='The shared cause it addressed, not the symptom')
    parser.add_argument('--caveat', action='append', default=[], help='Repeatable; what this does not show')
    args = parser.parse_args(argv)

    result = compare(load(args.before), load(args.after))
    if args.command == 'compare':
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    for required in ('change_id', 'designed', 'root_cause'):
        if not getattr(args, required):
            parser.error(f'--{required.replace("_", "-")} is required to record an entry')
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else {
        'artifact_kind': 'design_to_metric_attribution_not_a_release_claim',
        'reading_note': 'Every number here was computed from the two named suite artifacts by '
                        'scripts/attribution.py, never typed in. Semantic metrics stay null until an '
                        'independent review is recorded, so a deterministic gain is not answer quality. '
                        'Changes measured some other way are not in entries and must carry their own '
                        'artifact stating the method: the retrieval rerank stage is in '
                        'artifacts/retrieval-rerank-attribution-v1.json, measured in-process against the '
                        'base fixture corpus rather than by comparing two suite runs.',
        'entries': []}
    ledger['entries'].append({'change_id': args.change_id, 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'git_head': head(), 'designed': args.designed, 'root_cause': args.root_cause,
        'caveats': args.caveat, 'measurement': result})
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n')
    shown = LEDGER.relative_to(ROOT) if LEDGER.is_relative_to(ROOT) else LEDGER
    print(f"recorded {args.change_id}: deterministic_passes {result['delta']['deterministic_passes']:+d} "
          f"on {result['shared_case_repeats']} shared case_repeats -> {shown}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
