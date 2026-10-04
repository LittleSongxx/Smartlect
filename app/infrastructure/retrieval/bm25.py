"""应用层 BM25：Unicode 词项、完整型号、汉字/假名二元词项。"""
from __future__ import annotations
import asyncio
from collections import Counter
from functools import lru_cache
import math
import re
import unicodedata

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\u3005\U00020000-\U0002ffff]+")
_WORD = re.compile(r"[^\W_]+(?:[-_.][^\W_]+)*", re.UNICODE)


def terms(text: str) -> list[str]:
    # 统一全角型号与组合重音，同时保留语义不同的重音字母；不擅自音译。
    value = unicodedata.normalize("NFKC", text).casefold()
    tokens = _WORD.findall(_CJK.sub(" ", value))
    for segment in _CJK.findall(value):
        tokens.extend(segment[i:i+2] for i in range(len(segment)-1))
        if len(segment) == 1:
            tokens.append(segment)
    return tokens


def _subwords(words) -> list[str]:
    # 德语/荷兰语/瑞典语常把商品名写成复合词。字符字段仅辅助召回，
    # 数字及带连接符的型号不拆分，避免 WH-1000XM5 与其它型号靠片段混淆。
    return [word[i:i+3] for word in words if word.isalpha() and 5 <= len(word) <= 64
            for i in range(len(word)-2)]


@lru_cache(maxsize=8192)
def _document_terms(text, tokenizer):
    # 只缓存不可变正文派生的词项；库存/报价仍逐次读取权威数据。
    # tokenizer 也是键的一部分，离线消融使用旧分词器时不会串用缓存。
    words = tokenizer(text)
    return Counter(words), Counter(_subwords(words))


def _field_scores(query_terms, documents, *, k1, b):
    lengths = [sum(doc.values()) for doc in documents]
    average = sum(lengths) / max(1, len(documents))
    frequencies = Counter(term for doc in documents for term in doc)
    scored = []
    for document, length in zip(documents, lengths):
        score = 0.0
        for term in query_terms:
            frequency = document[term]
            if not frequency:
                continue
            idf = math.log(1 + (len(documents) - frequencies[term] + .5) / (frequencies[term] + .5))
            score += idf * frequency * (k1 + 1) / (frequency + k1 * (1-b + b*length/max(average, 1)))
        scored.append(score)
    return scored


def bm25_rank(query: str, products: list, *, k1: float = 1.2, b: float = .75,
              subword_weight: float = .25) -> list[tuple[float, object]]:
    if not math.isfinite(subword_weight) or subword_weight < 0:
        raise ValueError("子词权重必须为有限非负数")
    fields = [_document_terms(p.searchable_text(), terms) for p in products]
    query_words = set(terms(query))
    word_scores = _field_scores(query_words, [f[0] for f in fields], k1=k1, b=b)
    query_subwords = set(_subwords(query_words))
    subword_scores = (_field_scores(query_subwords, [f[1] for f in fields], k1=k1, b=b)
                      if subword_weight and query_subwords else [0.] * len(products))
    # 按查询扩展数量归一化，避免长单词产生大量子词后压过完整词项。
    scale = subword_weight / max(1, len(query_subwords) / max(1, len(query_words)))
    scored = [(whole + scale * subword, product)
              for product, whole, subword in zip(products, word_scores, subword_scores)
              if whole + scale * subword > 0]
    return sorted(scored, key=lambda pair: (-pair[0], pair[1].product_id))


def reciprocal_rank_fusion(*rankings: list, k: int = 60, weights=None) -> list:
    weights = tuple(weights) if weights is not None else (1.0,) * len(rankings)
    if (len(weights) != len(rankings) or not any(weights)
            or any(not math.isfinite(w) or w < 0 for w in weights)
            or type(k) is not int or k < 1):
        raise ValueError("融合权重须等长、有限、非负且至少一项大于零；k 须为正整数")
    scores, products = {}, {}
    for ranking, weight in zip(rankings, weights):
        if weight == 0:
            continue
        seen = set()
        for rank, (_, product) in enumerate(ranking, start=1):
            key = product.product_id
            if key in seen:
                continue
            seen.add(key)
            products[key] = product
            scores[key] = scores.get(key, 0) + weight/(k+rank)
    return [(scores[key], products[key]) for key in sorted(scores, key=lambda key: (-scores[key], key))]


class _PrecomputedField:
    """单个字段（完整词项/子词）的预计算 BM25 统计：长度、均值与倒排。"""

    __slots__ = ("lengths", "average", "postings", "idf")

    def __init__(self, documents: list[Counter]) -> None:
        self.lengths = [sum(doc.values()) for doc in documents]
        self.average = sum(self.lengths) / max(1, len(documents))
        frequencies = Counter(term for doc in documents for term in doc)
        total = len(documents)
        self.idf = {
            term: math.log(1 + (total - df + .5) / (df + .5))
            for term, df in frequencies.items()
        }
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for doc_index, doc in enumerate(documents):
            for term, frequency in doc.items():
                self.postings.setdefault(term, []).append((doc_index, frequency))

    def score(self, query_terms: set[str], *, k1: float, b: float) -> list[float]:
        scores = [0.0] * len(self.lengths)
        for term in query_terms:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for doc_index, frequency in self.postings[term]:
                scores[doc_index] += idf * frequency * (k1 + 1) / (
                    frequency + k1 * (1 - b + b * self.lengths[doc_index] / max(self.average, 1))
                )
        return scores


class BM25Index:
    """目录版本上的 BM25 预计算索引；打分与 ``bm25_rank`` 逐项一致。

    ``rank`` 只遍历查询词命中的 postings，不重扫全目录；重复查询直接复用
    已构建的词项统计。旧 ``bm25_rank`` 保留为评测脚本兼容基线。
    """

    def __init__(self, products: list, *, k1: float = 1.2, b: float = .75,
                 subword_weight: float = .25) -> None:
        if not math.isfinite(subword_weight) or subword_weight < 0:
            raise ValueError("子词权重必须为有限非负数")
        self._products = list(products)
        self._k1, self._b, self._subword_weight = k1, b, subword_weight
        fields = [_document_terms(p.searchable_text(), terms) for p in self._products]
        self._words = _PrecomputedField([f[0] for f in fields])
        self._subwords = _PrecomputedField([f[1] for f in fields])

    def rank(self, query: str) -> list[tuple[float, object]]:
        query_words = set(terms(query))
        word_scores = self._words.score(query_words, k1=self._k1, b=self._b)
        query_subwords = set(_subwords(query_words))
        subword_scores = (self._subwords.score(query_subwords, k1=self._k1, b=self._b)
                          if self._subword_weight and query_subwords
                          else [0.0] * len(self._products))
        # 按查询扩展数量归一化，避免长单词产生大量子词后压过完整词项。
        scale = self._subword_weight / max(1, len(query_subwords) / max(1, len(query_words)))
        scored = [(whole + scale * subword, product)
                  for product, whole, subword in zip(self._products, word_scores, subword_scores)
                  if whole + scale * subword > 0]
        return sorted(scored, key=lambda pair: (-pair[0], pair[1].product_id))


class BM25IndexCache:
    """按目录指纹 (商品数, 最大 updated_at) 缓存 BM25Index；构建与打分一律线程池执行。

    种子重载导致目录版本变化时指纹改变，下一次调用自动重建；纯内存对象，
    进程重启即清空。
    """

    def __init__(self) -> None:
        self._fingerprint: tuple | None = None
        self._index: BM25Index | None = None

    @staticmethod
    def defingerprint(products: list) -> tuple:
        return (len(products), max((p.updated_at or "" for p in products), default=""))

    async def rank(self, query: str, products: list) -> list[tuple[float, object]]:
        fingerprint = self.defingerprint(products)
        if self._index is None or self._fingerprint != fingerprint:
            self._index = await asyncio.to_thread(BM25Index, products)
            self._fingerprint = fingerprint
        return await asyncio.to_thread(self._index.rank, query)
