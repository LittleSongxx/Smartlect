# -*- coding: utf-8 -*-
"""从种子商品目录提取品牌/品类词，拼成识别上下文提示。

qwen3-asr 系模型支持任意文本上下文（Prompt）提升专有名词识别；
其他模型（fun-asr / paraformer）不接受该参数，由 client 侧按模型名决定是否附带。
"""
from __future__ import annotations

from typing import Iterable

from app.domain.catalog.product import Product


def build_asr_context(products: Iterable[Product], extra: str = "", max_chars: int = 2000) -> str:
    """品牌 + 品类去重后拼接；超长时逐个收缩品牌列表（品牌数通常远大于品类），避免截出半截标签。"""
    brands: list[str] = []
    categories: list[str] = []
    seen_brands: set[str] = set()
    seen_categories: set[str] = set()
    for product in products:
        brand = (getattr(product, "brand", "") or "").strip()
        if brand and brand not in seen_brands:
            seen_brands.add(brand)
            brands.append(brand)
        category = (getattr(product, "category", "") or "").strip()
        if category and category not in seen_categories:
            seen_categories.add(category)
            categories.append(category)

    def join() -> str:
        parts = [f"品类：{'、'.join(categories)}"] if categories else []
        if brands:
            parts.append(f"品牌：{'、'.join(brands)}")
        if extra.strip():
            parts.append(extra.strip())
        return "；".join(parts)

    context = join()
    while brands and len(context) > max_chars:
        brands.pop()
        context = join()
    return context[:max_chars]
