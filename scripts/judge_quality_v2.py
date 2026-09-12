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
    for item in verdict.get('claims') or []:
        claim_id, verdict_text = item.get('claim_id'), item.get('verdict')
        quote = str(item.get('quote') or '')
        if verdict_text == 'supported' and quote and _fold(quote[:24]) not in _fold(answer_text(result)):
            verdict_text = 'unsupported'  # a "supported" without a real answer quote does not count
        if verdict_text in SUPPORTED_VERDICTS:
            judged[claim_id] = verdict_text
    total = len(case.get('checkable_claims') or [])
    if total and len(judged) != total:
        raise JudgeUnavailable('judge_missing_verdicts:%d/%d' % (len(judged), total))
    supported = sum(1 for value in judged.values() if value == 'supported')
    return {'supported': supported, 'total': total, 'verdicts': judged,
            'summary': str(verdict.get('summary') or '')[:160]}


def apply_judge_faithfulness(scores, pairs, config, *, errors=None):
    """Fill the public Faithfulness field from judge verdicts.

    Faithfulness counts essential claims only (the propositions the question
    directly requires); peripheral doc-related-but-unasked claims become the
    Peripheral_coverage diagnostic. Cases whose judge call fails keep
    Faithfulness null (missing denominator), never a borrowed rule value."""
    by_id = {score['case_id']: score for score in scores}
    for case, result in pairs:
        try:
            verdict = judge_case(case, result, config)
        except (JudgeUnavailable, json.JSONDecodeError, KeyError) as error:
            (errors if errors is not None else []).append({'case_id': case['case_id'],
                                                           'reason': str(error)})
            continue
        score = by_id[case['case_id']]
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
    for case, result in pairs:
        try:
            verdict = judge_answer_side(case, result, config)
        except (JudgeUnavailable, json.JSONDecodeError, KeyError) as error:
            (errors if errors is not None else []).append({'case_id': case['case_id'],
                                                           'reason': str(error)})
            continue
        score = by_id[case['case_id']]
        if verdict is None:
            score['Faithfulness_answer_side'] = None
            score['answer_side_statements'] = 0
        else:
            score['Faithfulness_answer_side'] = verdict['supported'] / verdict['total']
            score['answer_side_statements'] = verdict['total']
            score['answer_side_summary'] = verdict['summary']
    return scores


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
