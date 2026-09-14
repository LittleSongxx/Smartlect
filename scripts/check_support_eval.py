#!/usr/bin/env python3
"""support-eval 题库质量门禁（离线，零依赖）。

检查项：
1. 结构完整（id/layer/question/reference_answer/points/gold_docs；id 唯一）
2. L6_absent（库外拒答桶）：gold_docs 与 points 必须为空、should_refuse=true
3. 可答层（L1–L5）：gold_docs 存在于语料、points 非空、should_refuse=false
4. 题目两两近重复：字符 2-gram Jaccard >= 0.6 报错、>= 0.45 提示（holdout3 同标准）
5. 参考答案溯源度：与金标正文 2-gram Jaccard >= 0.15（L5 否定式答案放宽到 0.10）
6. 分层分布与非干扰文档覆盖报告
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / 'evals/support-eval/corpus'
QUESTIONS = ROOT / 'evals/support-eval/questions.jsonl'
ANSWERABLE = ('L1', 'L2', 'L3', 'L4', 'L5')


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
        rid = row.get('id')
        for field in ('layer', 'question', 'reference_answer'):
            if not row.get(field):
                problems.append('%s: missing_%s' % (rid, field))
        if row['layer'] == 'L6_absent':
            if row.get('gold_docs'):
                problems.append('%s: absent_bucket_cannot_have_gold' % rid)
            if row.get('points'):
                problems.append('%s: absent_bucket_cannot_have_points' % rid)
            if not row.get('should_refuse'):
                problems.append('%s: absent_bucket_needs_should_refuse' % rid)
            continue
        if row.get('should_refuse'):
            problems.append('%s: answerable_bucket_cannot_refuse' % rid)
        if not row.get('points'):
            problems.append('%s: missing_points' % rid)
        for doc in row.get('gold_docs') or []:
            if doc not in corpus:
                problems.append('%s: gold_doc_missing:%s' % (rid, doc))

    q_grams = [(row['id'], bigrams(row['question'])) for row in rows]
    for i in range(len(q_grams)):
        for j in range(i + 1, len(q_grams)):
            score = jaccard(q_grams[i][1], q_grams[j][1])
            if score >= 0.6:
                problems.append('near_dup:%s/%s:%.2f' % (q_grams[i][0], q_grams[j][0], score))
            elif score >= 0.45:
                warnings.append('near_dup_watch:%s/%s:%.2f' % (q_grams[i][0], q_grams[j][0], score))

    for row in rows:
        if row['layer'] == 'L6_absent':
            continue
        gold_text = ''.join(corpus[doc] for doc in row['gold_docs'])
        score = jaccard(bigrams(row['reference_answer']), bigrams(gold_text))
        floor = 0.10 if row['layer'] == 'L5' else 0.15
        if score < floor:
            problems.append('weak_grounding:%s:%.2f' % (row['id'], score))
        elif score < floor + 0.05:
            warnings.append('grounding_watch:%s:%.2f' % (row['id'], score))

    covered = {doc for row in rows for doc in row['gold_docs']}
    unused = sorted(set(corpus) - covered)
    distractors = {path.stem for path in CORPUS.glob('*-old.md')} | {path.stem for path in CORPUS.glob('*-store.md')}
    unused_non_distractor = [doc for doc in unused if doc not in distractors]

    print('题数: %d | 语料: %d 篇' % (len(rows), len(corpus)))
    print('分层:', dict(sorted(Counter(row['layer'] for row in rows).items())))
    print('金标覆盖 %d/%d 篇；未被引用的非干扰文档: %s' % (
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
