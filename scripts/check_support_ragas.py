#!/usr/bin/env python3
"""support-ragas 题库质量门禁（离线，零依赖）。

检查项：
1. 结构完整（id/layer/question/reference_answer/gold_docs 齐全且唯一）
2. gold_docs 均存在于语料库
3. 题目两两近重复检测：字符 2-gram Jaccard >= 0.6 告警（holdout3 同标准）
4. 参考答案溯源度：与金标文档正文的字符 2-gram Jaccard >= 0.15（经验阈值——
   参考答案须基本由金标文本支撑，超出部分应可判为改写而非新事实）
5. 分层分布与语料覆盖报告
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / 'evals/support-ragas/corpus'
QUESTIONS = ROOT / 'evals/support-ragas/questions.jsonl'


def bigrams(text):
    folded = ''.join(text.split())
    return {folded[i:i + 2] for i in range(len(folded) - 1)} if len(folded) >= 2 else {folded}


def jaccard(a, b):
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def main():
    problems, warnings = [], []
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    corpus = {path.stem: path.read_text() for path in sorted(CORPUS.glob('*.md'))}

    ids = [row.get('id') for row in rows]
    if len(ids) != len(set(ids)):
        problems.append('duplicate_question_ids')
    for row in rows:
        for field in ('layer', 'question', 'reference_answer', 'gold_docs'):
            if not row.get(field):
                problems.append('%s: missing_%s' % (row.get('id'), field))
        for doc in row.get('gold_docs') or []:
            if doc not in corpus:
                problems.append('%s: gold_doc_missing:%s' % (row['id'], doc))
        if not str(row.get('question', '')).strip().endswith(('？', '?', '吗？', '呢？')):
            warnings.append('%s: question_not_interrogative' % row['id'])

    # 近重复（题目间）
    q_grams = [(row['id'], bigrams(row['question'])) for row in rows]
    for i in range(len(q_grams)):
        for j in range(i + 1, len(q_grams)):
            score = jaccard(q_grams[i][1], q_grams[j][1])
            if score >= 0.6:
                problems.append('near_dup:%s/%s:%.2f' % (q_grams[i][0], q_grams[j][0], score))
            elif score >= 0.45:
                warnings.append('near_dup_watch:%s/%s:%.2f' % (q_grams[i][0], q_grams[j][0], score))

    # 参考答案溯源度（与全部金标合并文本）
    for row in rows:
        gold_text = ''.join(corpus[doc] for doc in row['gold_docs'])
        score = jaccard(bigrams(row['reference_answer']), bigrams(gold_text))
        if score < 0.15:
            problems.append('weak_grounding:%s:%.2f' % (row['id'], score))
        elif score < 0.20:
            warnings.append('grounding_watch:%s:%.2f' % (row['id'], score))

    covered = {doc for row in rows for doc in row['gold_docs']}
    unused = sorted(set(corpus) - covered)
    distractors = {path.stem for path in CORPUS.glob('*-old.md')} | {path.stem for path in CORPUS.glob('*-store.md')}
    unused_non_distractor = [doc for doc in unused if doc not in distractors]

    print('题数: %d | 语料: %d 篇' % (len(rows), len(corpus)))
    print('分层:', dict(sorted(Counter(row['layer'] for row in rows).items())))
    print('金标覆盖 %d/%d 篇；未被任何题引用的非干扰文档: %s' % (
        len(covered), len(corpus), unused_non_distractor or '无'))
    if unused_non_distractor:
        warnings.append('unused_core_docs:' + ','.join(unused_non_distractor))
    for line in warnings:
        print('WARN', line)
    for line in problems:
        print('FAIL', line)
    if problems:
        sys.exit(1)
    print('questions_ok')


if __name__ == '__main__':
    main()
