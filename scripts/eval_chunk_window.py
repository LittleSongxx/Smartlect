#!/usr/bin/env python3
"""Offline lexical ablation: current 1400/0 vs mainstream 512/64.

Does not call models. Gold is document-level Recall@5 / MRR on support-eval
questions (same definition as eval_support_eval.py). Current published corpora
are all shorter than 512 characters, so the as-is set is a null check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "growth" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime import ROOT as _ROOT  # noqa: E402
from smartlect.knowledge import rank_chunks, split_document  # noqa: E402
from smartlect.memory import estimate_text_tokens  # noqa: E402

CORPUS_DIR = _ROOT / "evals/support-eval/corpus"
QUESTIONS = _ROOT / "evals/support-eval/questions.jsonl"
RECALL_K = 5
FILLER = "本节为排版占位，仅用于拉长同一标题下的正文，不构成任何经营承诺。"
ARMS = (
    {"id": "current_1400_0", "window": 1400, "overlap": 0},
    {"id": "mainstream_512_64", "window": 512, "overlap": 64},
    {"id": "control_512_0", "window": 512, "overlap": 0},
)


def load_corpus():
    return {path.stem: path.read_text() for path in sorted(CORPUS_DIR.glob("*.md"))}


def load_questions():
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    return [row for row in rows if row.get("gold_docs")]


def lengthen_same_heading(body, target=1800):
    text = body.rstrip() + "\n\n"
    while len(text) < target:
        text += FILLER
    return text


def straddle_policy(body, cut=512, into=40):
    heading = "# 政策\n\n"
    prefix = ""
    while len(heading) + len(prefix) < cut - into:
        prefix += FILLER
    prefix = prefix[: max(0, cut - into - len(heading))]
    return heading + prefix + body


def chunk_rows(corpus, window, overlap):
    rows = []
    for doc_id, body in corpus.items():
        pieces = split_document(body, window=window, overlap=overlap)
        title = next((line.lstrip("# ").strip() for line in body.splitlines() if line.startswith("#")), doc_id)
        for piece in pieces:
            rows.append({**piece, "doc_id": doc_id, "version": 1, "title": title,
                         "source_uri": "eval:" + doc_id, "checksum": "0" * 64, "facts_json": {}})
    return rows


def doc_ranks(ranked, gold):
    seen = {}
    for index, row in enumerate(ranked, start=1):
        doc_id = row["doc_id"]
        if doc_id in gold and doc_id not in seen:
            seen[doc_id] = index
    return [seen.get(doc_id) for doc_id in gold]


def recall_at_k(ranks):
    hits = sum(1 for rank in ranks if rank is not None and rank <= RECALL_K)
    return hits / len(ranks) if ranks else 0.0


def mrr(ranks):
    return mean([0.0 if rank is None else 1.0 / rank for rank in ranks]) if ranks else 0.0


def score_arm(corpus, questions, window, overlap):
    rows = chunk_rows(corpus, window, overlap)
    n_split = sum(1 for doc_id in corpus if sum(1 for row in rows if row["doc_id"] == doc_id) > 1)
    lengths = [len(row["content"]) for row in rows]
    tokens = [estimate_text_tokens(row["content"]) for row in rows]
    recalls, mrrs = [], []
    changed = 0
    for question in questions:
        ranked, _ = rank_chunks(rows, question["question"])
        ranks = doc_ranks(ranked, question["gold_docs"])
        recalls.append(recall_at_k(ranks))
        mrrs.append(mrr(ranks))
    return {
        "n_chunks": len(rows),
        "n_docs": len(corpus),
        "n_docs_split": n_split,
        "mean_chunk_chars": round(mean(lengths), 1) if lengths else 0,
        "mean_chunk_est_tokens": round(mean(tokens), 1) if tokens else 0,
        "max_chunk_chars": max(lengths) if lengths else 0,
        "recall_at_5": round(mean(recalls), 4),
        "mrr": round(mean(mrrs), 4),
        "n_questions": len(questions),
    }


def describe_raw(corpus):
    lengths = [len(body) for body in corpus.values()]
    tokens = [estimate_text_tokens(body) for body in corpus.values()]
    return {
        "n_docs": len(corpus),
        "min_chars": min(lengths),
        "median_chars": sorted(lengths)[len(lengths) // 2],
        "max_chars": max(lengths),
        "max_est_tokens": max(tokens),
        "n_over_512_chars": sum(1 for item in lengths if item > 512),
        "n_over_1400_chars": sum(1 for item in lengths if item > 1400),
    }


def main():
    raw = load_corpus()
    questions = load_questions()
    datasets = {
        "as_is": raw,
        "lengthened_1800": {doc_id: lengthen_same_heading(body) for doc_id, body in raw.items()},
        "straddle_512": {doc_id: straddle_policy(body) for doc_id, body in raw.items()},
    }
    report = {"source": "evals/support-eval lexical rank_chunks; no embedding",
              "raw_corpus": describe_raw(raw),
              "arms": list(ARMS),
              "datasets": {}}
    for name, corpus in datasets.items():
        report["datasets"][name] = {
            "corpus": describe_raw(corpus),
            "results": {arm["id"]: score_arm(corpus, questions, arm["window"], arm["overlap"]) for arm in ARMS},
        }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    out = _ROOT / "artifacts/chunk-window/lexical-ablation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")


if __name__ == "__main__":
    main()
