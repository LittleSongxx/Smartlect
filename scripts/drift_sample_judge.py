"""生产漂移采样评审（组件 13b）：离线抽样近 N 天完成 run，judge 评"答案-引用一致性"。

定位与边界（诚实声明）：
- 这是离线诊断脚本，不接入线上请求路径；采样自 agent_run（answer + citations）。
- 没有 ground truth claims（那只有评测集有），judge 只评 faithfulness 式的
  「答案关键论断是否被随附引用文本支持」——它是漂移信号（同一口径的 7 天
  滚动趋势），不是准确率，更不能替代官方评测。
- judge 网关与 judge_quality_v2 同一套（SMARTLECT_JUDGE_* 环境变量，
  与被测模型不同家族）。

用法（在 scripts/ 目录）：
  ../assistant/.venv/bin/python -m drift_sample_judge --days 7 --sample 50 --output ../eval/verification/drift-<date>/
输出：report.json（逐 run 判定 + 汇总）+ 7 天滚动均值。
"""
import argparse
import asyncio
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from runtime import parse_env  # noqa: E402

JUDGE_PROMPT = """你是电商客服答案的引用一致性评审。给你一条助手答案与它随附的引用文本。
逐条判断答案中关于本店政策/规则/商品事实的关键论断是否被引用文本支持。
只输出 JSON：{"supported_claims": <被支持的关键论断数>, "total_claims": <关键论断总数>,
"unsupported_quote": "<第一条不被支持的论断原文，没有则空串>", "verdict": "supported|partial|unsupported"}。
寒暄、追问、转交说明不算关键论断。不确定按不支持计。"""


def load_runs(connect, *, days, sample, scope=None):
    """近 N 天 COMPLETED run 的 answer + citations（从 result_json 提取，不解 context 大字段）。"""
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("""SELECT r.agent_run_id, r.created_at, c.execution_scope_id,
            JSON_UNQUOTE(JSON_EXTRACT(r.result_json, '$.answer')) AS answer,
            JSON_EXTRACT(r.result_json, '$.citations') AS citations
            FROM agent_run r JOIN conversation c ON c.conversation_id=r.conversation_id
            WHERE r.state='COMPLETED' AND r.result_json IS NOT NULL
            AND r.created_at>=UTC_TIMESTAMP(6)-INTERVAL %s DAY
            """ + ("AND c.execution_scope_id=%s" if scope else "") + " ORDER BY r.created_at DESC",
            ((days, scope) if scope else (days,)))
        rows = cursor.fetchall()
    random.Random(20261007).shuffle(rows)
    return rows[:sample]


async def judge_run(http, base_url, headers, row):
    citations = row['citations'] if isinstance(row['citations'], list) else []
    evidence = '\n'.join(f"[{i + 1}] {item.get('content', '')[:800]}"
                         for i, item in enumerate(citations) if isinstance(item, dict))
    payload = {'model': os.environ.get('SMARTLECT_JUDGE_MODEL', 'deepseek-flash'),
               'temperature': 0, 'response_format': {'type': 'json_object'},
               'messages': [{'role': 'system', 'content': JUDGE_PROMPT},
                            {'role': 'user', 'content': '答案：' + (row['answer'] or '')[:2000]
                             + '\n引用文本：\n' + (evidence or '（无引用）')}]}
    try:
        response = await http.post(base_url.rstrip('/') + '/chat/completions', headers=headers, json=payload)
        response.raise_for_status()
        verdict = json.loads(response.json()['choices'][0]['message']['content'])
    except Exception as error:  # judge 失败降级为 unknown，不伪装成通过
        verdict = {'verdict': 'unknown', 'error': type(error).__name__}
    return {'agent_run_id': row['agent_run_id'], 'created_at': str(row['created_at']),
            'n_citations': len(citations), **verdict}


async def main(days, sample, output, scope=None):
    import httpx
    from smartlect.db import connect_from_env

    env = parse_env(ROOT / 'run' / 'runtime.env') if (ROOT / 'run' / 'runtime.env').exists() else {}
    os.environ.setdefault('SMARTLECT_JUDGE_API_KEY', env.get('SMARTLECT_JUDGE_API_KEY', ''))
    base_url = os.environ.get('SMARTLECT_JUDGE_BASE_URL', env.get('SMARTLECT_JUDGE_BASE_URL',
                                                                  'https://api.deepseek.com'))
    api_key = os.environ.get('SMARTLECT_JUDGE_API_KEY', '')
    if not api_key:
        raise SystemExit('missing SMARTLECT_JUDGE_API_KEY (run/runtime.env 或环境变量)')

    rows = load_runs(connect_from_env(), days=days, sample=sample, scope=scope)
    if not rows:
        raise SystemExit('no_completed_runs_in_window')
    headers = {'Authorization': 'Bearer ' + api_key}
    async with httpx.AsyncClient(timeout=60) as http:
        judged = [await judge_run(http, base_url, headers, row) for row in rows]

    by_day = defaultdict(list)
    for item in judged:
        by_day[str(item['created_at'])[:10]].append(item['verdict'])
    rolling = {day: {'n': len(vs),
                     'supported_rate': sum(1 for v in vs if v == 'supported') / len(vs)}
               for day, vs in sorted(by_day.items())}
    report = {'schema_version': 'drift-sample-judge-v1', 'days': days, 'sampled': len(judged),
              'note': '无 ground truth 的 faithfulness 式采样评审：漂移信号，不是准确率；'
                      '不替代官方评测（quality-v2）。',
              'verdicts': judged, 'rolling_by_day': rolling,
              'generated_at': datetime.now(timezone.utc).isoformat()}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'drift-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'sampled': len(judged), 'rolling_by_day': rolling}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生产漂移采样评审（离线）')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--sample', type=int, default=50)
    parser.add_argument('--scope', default=None, help='可选 execution_scope_id 过滤')
    parser.add_argument('--output', required=True, help='新目录（按惯例放 eval/verification/drift-<date>/）')
    args = parser.parse_args()
    asyncio.run(main(args.days, args.sample, args.output, args.scope))
