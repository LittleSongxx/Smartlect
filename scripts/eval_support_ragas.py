#!/usr/bin/env python3
"""support-ragas：客服线 RAGAS 评测 runner（quality-v2 客服线的继任）。

流程：
  collect —— 需要活栈：每题独立场景，整库 47 篇灌入知识库（含干扰文档），
             单轮提问，采集终答 + 最后一次真实检索的候选 doc_id 序。
  score   —— 需要 judge/embedding 密钥：contexts 按 doc_id 映射回语料全文，
             RAGAS 经典四件套（faithfulness / answer_relevancy /
             context_precision / context_recall）。
  moe     —— score 跑两遍，量四指标的运行间漂移带（读数带判读的前置）。

数据面：evals/support-ragas/{corpus/*.md, questions.jsonl}。
环境：复用 run/model.env 的 SMARTLECT_EMBEDDING_* 与 SMARTLECT_JUDGE_*。
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import ENV_FILE, ROOT, model_env, parse_env  # noqa: E402

CORPUS_DIR = ROOT / 'evals/support-ragas/corpus'
QUESTIONS = ROOT / 'evals/support-ragas/questions.jsonl'
ARTIFACT = ROOT / 'artifacts/support-ragas'
RAGAS_REQUIREMENTS = ROOT / 'evals/support-ragas/requirements.txt'


def now():
    return datetime.now(timezone.utc).isoformat()


def corpus():
    return {path.stem: path.read_text() for path in sorted(CORPUS_DIR.glob('*.md'))}


def questions():
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    return rows


def growth_up():
    try:
        import httpx
        port = parse_env(ENV_FILE)['SMARTLECT_GROWTH_PORT']
        with httpx.Client(timeout=2, trust_env=False) as client:
            return client.get('http://127.0.0.1:' + port + '/health').status_code == 200
    except Exception:
        return False


def load_corpus_documents(docs):
    """语料 → setup_knowledge 的 additional_documents 载荷（与旧客服线同格式）。"""
    payload = []
    for doc_id, body in sorted(docs.items()):
        payload.append({
            'doc_id': doc_id, 'version': 1,
            'title': body.splitlines()[0].lstrip('# '),
            'source_uri': 'evals/support-ragas/corpus/' + doc_id + '.md',
            'body': body, 'acl': 'PUBLIC', 'lifecycle': 'publish_before_question',
            'checksum_sha256': sha256(body.encode()).hexdigest()})
    return payload


def last_search_candidates(observation):
    """最后一次真实 search_knowledge 的去重候选 doc_id 序（与旧 Recall 同判别）。"""
    from quality_v2 import last_real_search
    search = last_real_search(observation.get('tool_calls') or [])
    ranked = []
    for row in (search or {}).get('candidates') or []:
        doc_id = row.get('doc_id') if isinstance(row, dict) else row
        if doc_id and doc_id not in ranked:
            ranked.append(doc_id)
    return ranked


def cmd_collect(args):
    if not growth_up():
        raise SystemExit('growth_not_healthy; start the isolated stack first (scripts/dev.sh up)')
    from eval_support import setup_knowledge
    from scenario_client import ScenarioClient
    docs = corpus()
    rag_case = {'knowledge_setup': {'additional_documents': load_corpus_documents(docs)}}
    empty_manifest = {'base_corpus': {'documents': []}}
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    rows = questions()
    if args.case:
        wanted = {item.strip() for chunk in args.case for item in chunk.split(',')}
        rows = [row for row in rows if row['id'] in wanted]
    evidence_root = {'schema_version': 'support-ragas-collect-v1',
                     'collected_at': now(), 'question_count': len(rows),
                     'corpus_sha256': {doc_id: sha256(body.encode()).hexdigest()
                                       for doc_id, body in sorted(docs.items())}}
    (output / 'collect-meta.json').write_text(json.dumps(evidence_root, ensure_ascii=False, indent=2))
    for index, row in enumerate(rows, start=1):
        path = output / (row['id'] + '.json')
        evidence = {'id': row['id'], 'layer': row['layer'], 'status': 'SETUP_RUNNING',
                    'run_id': 'sr-' + uuid.uuid4().hex, 'question': row['question'],
                    'reference_answer': row['reference_answer'], 'gold_docs': row['gold_docs']}
        save = lambda: path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
        save()
        client = None
        try:
            client = ScenarioClient(evidence, save, requested_mode='live')
            client.setup(actor_ref='user_a')
            setup_knowledge(client, evidence, save, empty_manifest, rag_case)
            conversation = client.conversation()
            reply = client.message(conversation, row['question'], label=row['question'][:40])
            evidence['answer'] = str((reply or {}).get('answer') or '')
            evidence['answer_status'] = (reply or {}).get('answer_status')
            from eval_quality_v2 import collect_tools
            run_id = client.evidence['model_runs'][-1]['agent_run_id']
            evidence['retrieved_doc_ids'] = last_search_candidates(
                {'tool_calls': collect_tools(client, run_id)}) or None
            evidence['status'] = 'COLLECTED'
        except Exception as error:
            evidence['status'] = 'FAILED'
            evidence['error'] = type(error).__name__
            evidence['error_text'] = str(error)[:500]
        finally:
            if client is not None:
                client.close()
            evidence['finished_at'] = now()
            save()
        print('%d/%d %s %s' % (index, len(rows), row['id'], evidence['status']))
    return output


def build_dataset(input_dir):
    docs = corpus()
    samples = {'question': [], 'answer': [], 'contexts': [], 'reference': [], 'ground_truth': [], 'id': []}
    skipped = []
    for path in sorted(input_dir.glob('*.json')):
        if path.name == 'collect-meta.json':
            continue
        row = json.loads(path.read_text())
        if not isinstance(row, dict) or 'question' not in row:
            continue  # scores.json 等判分产物不是题目证据
        if row.get('status') != 'COLLECTED':
            skipped.append((row.get('id'), row.get('status')))
            continue
        contexts = [docs[doc_id] for doc_id in (row.get('retrieved_doc_ids') or []) if doc_id in docs]
        samples['question'].append(row['question'])
        samples['answer'].append(row['answer'])
        samples['contexts'].append(contexts)
        samples['reference'].append(row['reference_answer'])
        samples['ground_truth'].append(row['reference_answer'])
        samples['id'].append(row['id'])
    return samples, skipped


def ragas_clients():
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    env = model_env()
    if not env.get('SMARTLECT_JUDGE_API_KEY') or not env.get('SMARTLECT_EMBEDDING_API_KEY'):
        raise SystemExit('missing judge/embedding keys in run/model.env')
    judge = LangchainLLMWrapper(ChatOpenAI(
        model=env['SMARTLECT_JUDGE_MODEL'], api_key=env['SMARTLECT_JUDGE_API_KEY'],
        base_url=env['SMARTLECT_JUDGE_BASE_URL'], temperature=0))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
        model=env['SMARTLECT_EMBEDDING_MODEL'], api_key=env['SMARTLECT_EMBEDDING_API_KEY'],
        base_url=env['SMARTLECT_EMBEDDING_BASE_URL'],
        dimensions=int(env.get('SMARTLECT_EMBEDDING_DIMENSIONS') or 1024),
        check_embedding_ctx_length=False))
    return judge, embeddings


def score_once(samples, output_dir, tag):
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (answer_relevancy, context_precision, context_recall, faithfulness)
    judge, embeddings = ragas_clients()
    dataset = Dataset.from_dict({k: v for k, v in samples.items() if k != 'id'})
    report = evaluate(dataset, metrics=[faithfulness, answer_relevancy,
                                        context_precision, context_recall],
                      llm=judge, embeddings=embeddings, show_progress=True)
    frame = report.to_pandas()
    frame.insert(0, 'id', samples['id'])
    frame.to_csv(output_dir / ('ragas-%s.csv' % tag), index=False)
    metrics = {}
    for name in ('faithfulness', 'answer_relevancy', 'context_precision', 'context_recall'):
        column = frame[name].dropna() if name in frame else None
        metrics[name] = float(column.mean()) if column is not None and len(column) else None
    summary = {'tag': tag, 'scored_at': now(), 'n': len(samples['id']), 'metrics': metrics}
    return summary


def write_markdown(summaries, output_dir):
    env = model_env()
    lines = ['# support-ragas 评测报告', '',
             'RAGAS 四件套（judge=%s，embedding=%s，与主对话模型异源）。' % (
                 env['SMARTLECT_JUDGE_MODEL'], env['SMARTLECT_EMBEDDING_MODEL']),
             '分层与逐题明细见 ragas-*.csv。', '', '| 指标 | ' + ' | '.join(s['tag'] for s in summaries) + ' |',
             '|---|' + '---|' * len(summaries)]
    for metric in ('faithfulness', 'answer_relevancy', 'context_precision', 'context_recall'):
        lines.append('| %s | %s |' % (metric, ' | '.join(
            '%.4f' % s['metrics'][metric] if s['metrics'].get(metric) is not None else 'null'
            for s in summaries)))
    if len(summaries) == 2:
        lines += ['', '## MoE（双跑漂移）', '', '| 指标 | run1 | run2 | 漂移 |', '|---|---|---|---|']
        for metric in ('faithfulness', 'answer_relevancy', 'context_precision', 'context_recall'):
            a, b = (s['metrics'][metric] for s in summaries)
            lines.append('| %s | %.4f | %.4f | %+.4f |' % (metric, a, b, b - a))
    (output_dir / 'report.md').write_text('\n'.join(lines) + '\n')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='support-ragas runner (RAGAS successor of quality-v2 support line)')
    parser.add_argument('command', choices=('collect', 'score', 'moe'))
    parser.add_argument('--output', default=None, help='collect: output dir (default artifacts/support-ragas/<timestamp>)')
    parser.add_argument('--input', default=None, help='score/moe: collect dir')
    parser.add_argument('--case', action='append', default=[], help='collect: question id subset (repeat/comma)')
    args = parser.parse_args()
    if args.command == 'collect':
        output = Path(args.output) if args.output else ARTIFACT / ('collect-' + datetime.now().strftime('%Y%m%dT%H%M%S'))
        cmd_collect(args)
        print(json.dumps({'collected_to': str(output)}, ensure_ascii=False))
        return
    input_dir = Path(args.input) if args.input else None
    if not input_dir or not input_dir.exists():
        raise SystemExit('missing_input; score/moe needs --input <collect dir>')
    samples, skipped = build_dataset(input_dir)
    if skipped:
        print('skipped_not_collected:', json.dumps(skipped, ensure_ascii=False))
    if not samples['id']:
        raise SystemExit('no_collected_samples')
    runs = 2 if args.command == 'moe' else 1
    summaries = [score_once(samples, input_dir, 'run%d' % (index + 1)) for index in range(runs)]
    (input_dir / 'scores.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    print(write_markdown(summaries, input_dir))


if __name__ == '__main__':
    main()
