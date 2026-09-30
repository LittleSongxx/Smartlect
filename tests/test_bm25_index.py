# -*- coding: utf-8 -*-
"""BM25 预计算索引与旧全量实现的逐分数一致性测试（D4）。

BM25Index 把词项统计/倒排/文档长度预计算到目录版本上，rank 只遍历命中
postings；数学与旧 bm25_rank 完全相同，因此两组分数必须逐项相等。
"""
from types import SimpleNamespace

from app.infrastructure.retrieval.bm25 import BM25Index, bm25_rank

_CATALOG = [
    ("P0001", "轻便露营灯 电池供电 户外照明"),
    ("P0002", "登山杖 铝合金 可调节"),
    ("P0003", "旅行收纳袋 六件套 压缩"),
    ("P0004", "降噪耳机 无线 蓝牙"),
    ("P0005", "lightweight backpack for travel water resistant"),
    ("P0006", "noise cancelling earbuds with charging case"),
    ("P0007", "Campinglampe batteriebetrieben LED"),
    ("P0008", "ランダム バックパック 軽量 旅行用"),
    ("P0009", "行李箱 20寸 登机箱 万向轮"),
    ("P0010", "咖啡杯 保温 316不锈钢"),
]


def _products():
    return [
        SimpleNamespace(product_id=product_id, searchable_text=lambda text=text: text)
        for product_id, text in _CATALOG
    ]


def _scores(ranked):
    return [(round(score, 10), product.product_id) for score, product in ranked]


class TestBM25IndexParity:
    def test_rank_scores_match_legacy_bm25_rank(self):
        products = _products()
        index = BM25Index(products)
        for query in (
            "露营灯", "轻便 背包", "noise cancelling earbuds",
            "ランダム 軽量", "收纳 压缩", "不存在的关键词xyzq",
        ):
            legacy = _scores(bm25_rank(query, products))
            indexed = _scores(index.rank(query))
            assert indexed == legacy, f"BM25Index 与 bm25_rank 分数不一致：{query}"

    def test_index_reuses_precomputed_terms(self):
        products = _products()
        index = BM25Index(products)
        # 重复查询应命中缓存的词项计数，不重新分词
        first = index.rank("露营灯")
        second = index.rank("露营灯")
        assert _scores(first) == _scores(second)

    def test_empty_and_single_results(self):
        index = BM25Index(_products())
        assert index.rank("") == []
        assert index.rank("不存在的关键词xyzq") == []
