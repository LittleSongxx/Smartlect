"""DeepSeek judge for quality-v2 support Faithfulness.

The judge model is deliberately different from the main conversation model
(qwen via dashscope) so Faithfulness is never self-graded. Since contract v3
the public Faithfulness is judge-based; the old exact-substring rule score
stays as Faithfulness_rule diagnostic. Deterministic gates (forbidden docs /
must_not_claim / forbidden_claims) remain rule-based in score_support.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re

import httpx

from quality_v2 import SUPPORT_DEV, _corpus_for, _fold, answer_text, load_jsonl
from runtime import ENV_FILE, ROOT, model_env, parse_env

DEFAULT_JUDGE_BASE = 'https://api.deepseek.com'
DEFAULT_JUDGE_MODEL = 'deepseek-flash'
SAMPLE_SEED = 20260912
JUDGE_PROMPT_VERSION = 'qv2-judge-faith-v3'
SUPPORTED_VERDICTS = ('supported', 'absent', 'contradicted', 'unsupported')
CALIBRATION_PATH = ROOT / 'evals/quality-v2/support/judge-calibration.jsonl'
CALIBRATION_PASS_THRESHOLD = 0.90
HUMAN_REVIEW_SEED = 20260913
HUMAN_REVIEW_SIZE = 20


class JudgeUnavailable(RuntimeError):
    pass


def judge_config():
    return {**parse_env(ENV_FILE), **model_env()}


def _chat(config, messages, *, max_tokens=6000):
    base = (config.get('SMARTLECT_JUDGE_BASE_URL') or DEFAULT_JUDGE_BASE).rstrip('/')
    key = config.get('SMARTLECT_JUDGE_API_KEY')
    if not base or not key:
        raise JudgeUnavailable('judge_needs_judge_model_env')
    body = {'model': config.get('SMARTLECT_JUDGE_MODEL') or DEFAULT_JUDGE_MODEL,
            'messages': messages, 'temperature': 0, 'max_tokens': max_tokens,
            'response_format': {'type': 'json_object'}}
    with httpx.Client(timeout=90, trust_env=False) as client:
        response = client.post(base + '/chat/completions', json=body,
                               headers={'Authorization': 'Bearer ' + key})
    if response.status_code != 200:
        raise JudgeUnavailable('judge_http_' + str(response.status_code))
    payload = response.json()
    content = (payload.get('choices') or [{}])[0].get('message', {}).get('content')
    if not isinstance(content, str) or not content.strip():
        raise JudgeUnavailable('judge_empty_content')
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', content, re.S)
        if not match:
            raise JudgeUnavailable('judge_response_not_json')
        return json.loads(match.group(0))


def judge_messages(case, result):
    corpus = _corpus_for(case)
    citations = '\n\n'.join(f"[{row.get('doc_id')}@v{row.get('version')}] {row.get('content')}"
                            for row in result.get('citations') or []) or '（无引用）'
    questions = [{'claim_id': c.get('id') or c.get('text', '')[:12], 'text': c.get('text')}
                 for c in case.get('checkable_claims') or []]
    payload = {
        'question': ' '.join(case.get('user_turns') or []),
        'visible_documents': corpus,
        'agent_answer': answer_text(result),
        'citations': citations,
        'claims_to_verify': questions,
    }
    return [
        {'role': 'system', 'content':
            '你是客服质量评测裁判，只依据 visible_documents 判断 agent_answer。\n'
            '对每条 claims_to_verify 判定：supported=答案明确表达了该事实且与资料一致（改述也算，语义相同即可）；'
            'absent=答案完全没有提到；contradicted=答案说了相反内容；unsupported=答案提到了但资料不支持该说法。\n'
            '每条判定必须附 quote：supported/contradicted/unsupported 给出答案中支撑判定的原句片段；absent 给空串。'
            '找不到可引用的原句时不得判 supported。\n'
            '只输出 JSON：{"claims":[{"claim_id":..,"verdict":"supported|absent|contradicted|unsupported","quote":".."}],'
            '"summary":"一句话"}'},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]


def judge_case(case, result, config):
    verdict = _chat(config, judge_messages(case, result))
    judged = {}
    quotes = {}
    for item in verdict.get('claims') or []:
        claim_id, verdict_text = item.get('claim_id'), item.get('verdict')
        quote = str(item.get('quote') or '')
        if verdict_text == 'supported' and quote and _fold(quote[:24]) not in _fold(answer_text(result)):
            verdict_text = 'unsupported'  # a "supported" without a real answer quote does not count
        if verdict_text in SUPPORTED_VERDICTS:
            judged[claim_id] = verdict_text
            quotes[claim_id] = quote
    total = len(case.get('checkable_claims') or [])
    if total and len(judged) != total:
        raise JudgeUnavailable('judge_missing_verdicts:%d/%d' % (len(judged), total))
    supported = sum(1 for value in judged.values() if value == 'supported')
    return {'supported': supported, 'total': total, 'verdicts': judged, 'quotes': quotes,
            'summary': str(verdict.get('summary') or '')[:160]}


def apply_judge_faithfulness(scores, pairs, config, *, errors=None):
    """Fill the public Faithfulness field from judge verdicts.

    pairs entries are (case, result) or (case, result, score_row); the
    three-tuple form targets an exact trial row instead of a case_id lookup,
    so k trials of one case never overwrite each other.

    Faithfulness counts essential claims only (the propositions the question
    directly requires); peripheral doc-related-but-unasked claims become the
    Peripheral_coverage diagnostic. Cases whose judge call fails keep
    Faithfulness null (missing denominator), never a borrowed rule value."""
    by_id = {score['case_id']: score for score in scores}
    for item in pairs:
        case, result = item[0], item[1]
        score = item[2] if len(item) > 2 else by_id[case['case_id']]
        try:
            verdict = judge_case(case, result, config)
        except (JudgeUnavailable, json.JSONDecodeError, KeyError) as error:
            (errors if errors is not None else []).append({'case_id': case['case_id'],
                                                           'reason': str(error)})
            continue
        claims = case.get('checkable_claims') or []
        essential = [c for c in claims if c.get('scope', 'essential') == 'essential']
        peripheral = [c for c in claims if c.get('scope') == 'peripheral']
        verdicts = verdict['verdicts']
        key_of = lambda c: c.get('id') or c.get('text', '')[:12]
        if essential:
            score['Faithfulness'] = sum(1 for c in essential
                                        if verdicts.get(key_of(c)) == 'supported') / len(essential)
        else:
            score['Faithfulness'] = None
        if peripheral:
            score['Peripheral_coverage'] = sum(1 for c in peripheral
                                               if verdicts.get(key_of(c)) == 'supported') / len(peripheral)
        else:
            score['Peripheral_coverage'] = None
        score['judge_verdicts'] = verdict['verdicts']
        score['judge_quotes'] = verdict['quotes']
        score['judge_summary'] = verdict['summary']
    return scores


ANSWER_SIDE_PROMPT_VERSION = 'qv2-judge-answer-side-v1'


def judge_answer_side(case, result, config):
    """RAGAS-aligned answer-side check: decompose the answer's own factual
    statements and verify each against the visible documents/citations."""
    corpus = _corpus_for(case)
    citations = '\n\n'.join(f"[{row.get('doc_id')}@v{row.get('version')}] {row.get('content')}"
                            for row in result.get('citations') or []) or '（无引用）'
    payload = {'question': ' '.join(case.get('user_turns') or []),
               'visible_documents': corpus,
               'citations': citations,
               'agent_answer': answer_text(result)}
    messages = [
        {'role': 'system', 'content':
            '你是客服质量评测裁判。把 agent_answer 分解为它自己做出的全部可验证事实/政策断言'
            '（不含问候、建议句和问题句），对每一条判断 visible_documents 是否支撑：'
            'supported=资料明确支撑（改述算）；unsupported=资料没有该说法或相反。'
            '每条附 answer_quote（答案原句片段）。只输出 JSON：'
            '{"statements":[{"statement":..,"verdict":"supported|unsupported","answer_quote":..}],"summary":"一句话"}'},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]
    verdict = _chat(config, messages)
    statements = [item for item in verdict.get('statements') or []
                  if item.get('verdict') in ('supported', 'unsupported') and item.get('answer_quote')]
    if not statements:
        return None  # no checkable assertions (greeting/clarification only)
    supported = sum(1 for item in statements if item['verdict'] == 'supported')
    return {'supported': supported, 'total': len(statements), 'statements': statements,
            'summary': str(verdict.get('summary') or '')[:160]}


def apply_judge_answer_side(scores, pairs, config, *, errors=None):
    by_id = {score['case_id']: score for score in scores}
    for item in pairs:
        case, result = item[0], item[1]
        score = item[2] if len(item) > 2 else by_id[case['case_id']]
        try:
            verdict = judge_answer_side(case, result, config)
        except (JudgeUnavailable, json.JSONDecodeError, KeyError) as error:
            (errors if errors is not None else []).append({'case_id': case['case_id'],
                                                           'reason': str(error)})
            continue
        if verdict is None:
            score['Faithfulness_answer_side'] = None
            score['answer_side_statements'] = 0
        else:
            score['Faithfulness_answer_side'] = verdict['supported'] / verdict['total']
            score['answer_side_statements'] = verdict['total']
            score['answer_side_summary'] = verdict['summary']
    return scores


def cohens_kappa(labels_a, labels_b):
    """Cohen's kappa for two raters over the same items (None on empty input)."""
    if len(labels_a) != len(labels_b) or not labels_a:
        return None
    categories = sorted(set(labels_a) | set(labels_b))
    n = len(labels_a)
    observed = sum(1 for x, y in zip(labels_a, labels_b) if x == y) / n
    count_a, count_b = {}, {}
    for value in labels_a:
        count_a[value] = count_a.get(value, 0) + 1
    for value in labels_b:
        count_b[value] = count_b.get(value, 0) + 1
    expected = sum(count_a.get(c, 0) * count_b.get(c, 0) for c in categories) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def load_calibration_pairs(path=CALIBRATION_PATH):
    pairs = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    for pair in pairs:
        corpus = _corpus_for({'visible_doc_ids': pair['visible_doc_ids']})
        if _fold(pair['claim']['text']) not in _fold(corpus):
            raise ValueError('calibration_claim_not_in_corpus:' + pair['pair_id'])
        if pair['expect_verdict'] not in SUPPORTED_VERDICTS:
            raise ValueError('calibration_bad_expect:' + pair['pair_id'])
    return pairs


def _calibration_pseudo_case(pair):
    return {'case_id': pair['pair_id'], 'user_turns': pair['user_turns'],
            'visible_doc_ids': pair['visible_doc_ids'], 'checkable_claims': [pair['claim']]}


def run_calibration(output_dir, *, pro_model='deepseek-v4-pro'):
    """Judge calibration: known-verdict pairs through both judges.

    Reports per-model agreement with the constructed gold, Cohen's kappa
    between the two judges, and a human-review list of every disagreement.
    Gold is binary (supported vs not) because only 'supported' earns public
    Faithfulness credit; the 4-way verdicts stay as diagnostics."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_config = judge_config()
    pro_config = {**base_config, 'SMARTLECT_JUDGE_MODEL': pro_model}
    pairs = load_calibration_pairs()
    rows, errors = [], []
    for pair in pairs:
        case = _calibration_pseudo_case(pair)
        result = {'answer': pair['agent_answer'], 'citations': []}
        entry = {'pair_id': pair['pair_id'], 'category': pair['category'],
                 'expect_verdict': pair['expect_verdict'],
                 'claim': pair['claim']['text'], 'agent_answer': pair['agent_answer']}
        for name, config in (('flash', base_config), ('pro', pro_config)):
            try:
                verdict = judge_case(case, result, config)
                claim_key = pair['claim'].get('id') or pair['claim']['text'][:12]
                entry[name + '_verdict'] = verdict['verdicts'].get(claim_key)
                entry[name + '_quote'] = verdict['quotes'].get(claim_key, '')
            except (JudgeUnavailable, json.JSONDecodeError, KeyError) as error:
                entry[name + '_verdict'] = None
                entry[name + '_quote'] = ''
                errors.append({'pair_id': pair['pair_id'], 'judge': name, 'reason': str(error)})
        rows.append(entry)

    judged = [r for r in rows if r['flash_verdict'] and r['pro_verdict']]
    gold = [r['expect_verdict'] for r in judged]
    credit_gold = [v == 'supported' for v in gold]

    def _agreement(key):
        hits = [r[key] for r in judged]
        credit = [v == 'supported' for v in hits]
        return sum(1 for a, b in zip(credit, credit_gold) if a == b) / len(judged) if judged else None

    flash_agreement, pro_agreement = _agreement('flash_verdict'), _agreement('pro_verdict')
    flash_labels = [r['flash_verdict'] for r in judged]
    pro_labels = [r['pro_verdict'] for r in judged]
    cross_agreement = (sum(1 for a, b in zip(flash_labels, pro_labels) if a == b) / len(judged)
                       if judged else None)
    by_category = {}
    for category in sorted({r['category'] for r in judged}):
        subset = [r for r in judged if r['category'] == category]
        by_category[category] = {
            'n': len(subset),
            'flash_agreement': sum(1 for r in subset
                                   if (r['flash_verdict'] == 'supported') == (r['expect_verdict'] == 'supported')) / len(subset)}

    disagreements = [r for r in judged
                     if (r['flash_verdict'] == 'supported') != (r['expect_verdict'] == 'supported')
                     or (r['pro_verdict'] == 'supported') != (r['expect_verdict'] == 'supported')
                     or r['flash_verdict'] != r['pro_verdict']]
    report = {
        'schema_version': 'quality-v2-judge-calibration-v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'n_pairs': len(pairs), 'n_judged': len(judged), 'errors': errors,
        'judge_flash_model': base_config.get('SMARTLECT_JUDGE_MODEL') or DEFAULT_JUDGE_MODEL,
        'judge_pro_model': pro_model,
        'judge_prompt_version': JUDGE_PROMPT_VERSION,
        'flash_agreement_with_gold': flash_agreement,
        'pro_agreement_with_gold': pro_agreement,
        'flash_pro_agreement': cross_agreement,
        'cohens_kappa_binary': cohens_kappa(['supported' if v == 'supported' else 'not'
                                             for v in flash_labels],
                                            ['supported' if v == 'supported' else 'not'
                                             for v in pro_labels]),
        'cohens_kappa_4way': cohens_kappa(flash_labels, pro_labels),
        'flash_agreement_by_category': by_category,
        'flash_passes_90': flash_agreement is not None and flash_agreement >= CALIBRATION_PASS_THRESHOLD,
        'disagreement_count': len(disagreements),
    }
    (output_dir / 'calibration-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    lines = ['# Judge 校准分歧人工复核清单', '',
             '- run: %s' % output_dir,
             '- gold 判定由构造方式决定（直引/忠实改述=supported；否定翻转/编造=非 supported；跑题/半说=absent/unsupported）',
             '- 复核列请人工填写：判定是否同意 flash/pro 的判定，并注明理由', '',
             '| pair | 类别 | 金标 | flash | pro | flash quote | claim | 答案摘录 | 人工结论 |', '|---|---|---|---|---|---|---|---|---|']
    for r in disagreements:
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s |  |' % (
            r['pair_id'], r['category'], r['expect_verdict'], r['flash_verdict'], r['pro_verdict'],
            (r['flash_quote'] or '')[:40].replace('|', '/'), r['claim'][:36].replace('|', '/'),
            r['agent_answer'][:48].replace('|', '/').replace('\n', ' ')))
    (output_dir / 'calibration-disagreements.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({k: report[k] for k in (
        'n_pairs', 'n_judged', 'flash_agreement_with_gold', 'pro_agreement_with_gold',
        'flash_pro_agreement', 'cohens_kappa_binary', 'flash_passes_90', 'disagreement_count')},
        ensure_ascii=False, indent=2))
    if errors:
        print('judge_errors:', json.dumps(errors, ensure_ascii=False))
    return report


def write_human_review(run_dir, targets):
    """Sample judged claims from a completed run into a human-review checklist.

    Every official run auto-samples HUMAN_REVIEW_SIZE judged claims (with the
    judge quote) so Faithfulness keeps a standing human audit trail."""
    pool = []
    for target in targets:
        case, row = target['case'], target['row']
        verdicts, quotes = row.get('judge_verdicts') or {}, row.get('judge_quotes') or {}
        for claim in case.get('checkable_claims') or []:
            key = claim.get('id') or claim['text'][:12]
            if key in verdicts:
                pool.append({'case_id': case['case_id'], 'trial': row.get('trial'),
                             'claim_id': key, 'claim_text': claim['text'], 'scope': claim.get('scope'),
                             'verdict': verdicts[key], 'quote': quotes.get(key, '')})
    if not pool:
        return None
    rng = random.Random(HUMAN_REVIEW_SEED)
    sampled = rng.sample(pool, min(HUMAN_REVIEW_SIZE, len(pool)))
    out = Path(run_dir) / 'judge'
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'human-review.jsonl', 'w', encoding='utf-8') as handle:
        for item in sampled:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
    lines = ['# Judge 判定人审清单（自动抽样 %d 条）' % len(sampled), '',
             '- seed: %d（同池复现同抽样）' % HUMAN_REVIEW_SEED,
             '- 复核列请人工填写：agree / disagree + 理由', '',
             '| # | case | trial | claim (scope) | verdict | quote | 人工结论 |', '|---|---|---|---|---|---|---|']
    for index, item in enumerate(sampled, 1):
        lines.append('| %d | %s | %s | %s (%s) | %s | %s |  |' % (
            index, item['case_id'], item['trial'] or '-', item['claim_text'][:40].replace('|', '/'),
            item['scope'], item['verdict'], (item['quote'] or '')[:40].replace('|', '/')))
    (out / 'human-review.md').write_text('\n'.join(lines) + '\n')
    return len(sampled)


def _load_result(run_dir, case_id):
    path = Path(run_dir) / 'support' / (case_id + '.json')
    if not path.exists():
        return None
    evidence = json.loads(path.read_text())
    observation = evidence.get('observation')
    if observation is None:  # older evidence layout
        runs = evidence.get('model_runs') or []
        result = (runs[-1].get('run') or {}).get('result') if runs else None
        if result is None:
            return None
        return {'result': result, 'scores': evidence.get('scores')}
    return {**observation, 'scores': evidence.get('scores')}


def run_llm_judge(run_dir, lines, *, sample=None):
    """CLI spot-check report over a completed run directory (judge/judge-report.json)."""
    run_dir = Path(run_dir)
    if 'support' not in lines:
        print(json.dumps({'judge': 'skipped', 'lines': list(lines)}, ensure_ascii=False))
        return
    config = judge_config()
    cases = {row['case_id']: row for row in load_jsonl(SUPPORT_DEV)}
    pool = sorted((row for row in cases.values() if row.get('checkable_claims')),
                  key=lambda row: row['case_id'])
    if sample is not None:
        rng = random.Random(SAMPLE_SEED)
        pool = rng.sample(pool, min(sample, len(pool))) if pool else []
    report = {'schema_version': 'quality-v2-judge-v2', 'run_dir': str(run_dir),
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'judge_model': config.get('SMARTLECT_JUDGE_MODEL') or DEFAULT_JUDGE_MODEL,
              'judge_prompt_version': JUDGE_PROMPT_VERSION,
              'judge_differs_from_main_model': True,
              'sample_seed': SAMPLE_SEED if sample is not None else None,
              'cases': [], 'errors': []}
    for case in pool:
        loaded = _load_result(run_dir, case['case_id'])
        if loaded is None:
            report['errors'].append({'case_id': case['case_id'], 'reason': 'evidence_missing'})
            continue
        try:
            verdict = judge_case(case, loaded['result'], config)
        except (JudgeUnavailable, json.JSONDecodeError, KeyError) as error:
            report['errors'].append({'case_id': case['case_id'], 'reason': str(error)})
            continue
        rule = (loaded.get('scores') or {})
        report['cases'].append({
            'case_id': case['case_id'],
            'judge_faithfulness': verdict['supported'] / verdict['total'] if verdict['total'] else None,
            'judge_verdicts': verdict['verdicts'],
            'judge_summary': verdict['summary'],
            'rule_faithfulness': rule.get('Faithfulness_rule', rule.get('Faithfulness')),
        })
    values = [entry['judge_faithfulness'] for entry in report['cases']
              if entry['judge_faithfulness'] is not None]
    report['judge_faithfulness_sample'] = sum(values) / len(values) if values else None
    out = run_dir / 'judge'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'judge-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('schema_version', 'judge_model',
                                             'judge_faithfulness_sample', 'errors')},
                     ensure_ascii=False, indent=2))
