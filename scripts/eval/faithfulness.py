# -*- coding: utf-8 -*-
"""faithfulness —— 回复金额与政策陈述的忠实度对账（纯函数）。

回复里出现的「带币种标记的金额」与「百分比」必须能溯源到本轮工具返回
（商品卡、到手价、订单）或政策事实表（关税/免税额/基础运费，从领域常量
推导）；免税/关税结论必须与工具返回的 de_minimis_applied 一致。全部逻辑
不依赖 LLM，fail-closed：证据缺失即不通过。

口径：
- 只抽取带币种/百分比标记的数字；裸整数（库存、件数、序号）与评分不做对账。
- 金额容差：绝对 0.5（覆盖取整表述）或相对 1%（覆盖汇率换算与大数量级）。
- 合法金额来源三类：a) 商品/到手价工具返回；b) 订单与确认单金额（分→元换算）；
  c) 政策事实表。跨币种匹配经 ExchangeRateTable 换算后比对。
- 政策结论：声称「已免税/免关税」或「需缴关税」时，本轮 landed_price 事实
  中的 de_minimis_applied 必须与声明一致；没有 landed 事实即不通过。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.catalog.exchange_rate import ExchangeRateTable
from app.domain.shipping import tariff_schedule

_RATES = ExchangeRateTable().rates_to_cny

# 币种词表：正则捕获组 → 标准币种（顺序影响匹配优先级，长词在前）
_CURRENCY_UNITS: tuple[tuple[str, str], ...] = (
    (r"人民币|CNY|¥", "CNY"),
    (r"美元|美金|US\$|USD|\$", "USD"),
    (r"日元|日圆|JPY|円", "JPY"),
    (r"欧元|欧\b|EUR|€", "EUR"),
    (r"新加坡元|新元|坡币|SGD|S\$", "SGD"),
    (r"元|块", "CNY"),
)

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_SCALES = {"万": 10_000, "亿": 100_000_000}


def _parse_cn_number(text: str) -> float | None:
    """解析中文数字（支持 十/百/千/万/亿 与阿拉伯混写），失败返回 None。"""
    if not text:
        return None
    total, section, value = 0.0, 0.0, None
    for char in text:
        if char in _CN_DIGITS:
            value = float(_CN_DIGITS[char])
        elif char in _CN_UNITS:
            unit = _CN_UNITS[char]
            section += (value if value is not None else 1.0) * unit
            value = None
        elif char in _CN_SCALES:
            scale = _CN_SCALES[char]
            total += (section + (value or 0.0)) * scale
            section, value = 0.0, None
        elif char == "点":
            break
        else:
            return None
    if value is not None:
        section += value
    return total + section if (total + section) > 0 else None


def _number_literal(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return _parse_cn_number(text)


@dataclass(frozen=True)
class ExtractedNumber:
    value: float
    currency: str | None  # None 表示百分比
    raw: str


_AMOUNT_PATTERN = re.compile(
    r"([0-9]+(?:\.[0-9]+)?|[零一二两三四五六七八九十百千万亿]+(?:点[零一二三四五六七八九]+)?)"
    r"\s*(万|亿)?\s*(" + "|".join(unit for unit, _ in _CURRENCY_UNITS) + r")(?![A-Za-z])"
)
_PERCENT_PATTERN = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
_RANGE_PATTERN = re.compile(
    r"([0-9]+(?:\.[0-9]+)?|[零一二两三四五六七八九十百千万亿]+)\s*[-~～到至]\s*"
    r"([0-9]+(?:\.[0-9]+)?|[零一二两三四五六七八九十百千万亿]+)\s*(万|亿)?\s*(" + "|".join(
        unit for unit, _ in _CURRENCY_UNITS
    ) + r")(?![A-Za-z])"
)


def extract_marked_numbers(text: str) -> list[ExtractedNumber]:
    """抽取带币种标记的金额与百分比；区间（180-350元）两端都抽。"""
    results: list[ExtractedNumber] = []
    masked = text
    for match in _RANGE_PATTERN.finditer(text):
        low = _number_literal(match.group(1))
        high = _number_literal(match.group(2))
        if low is None or high is None:
            continue
        scale = {"万": 10_000, "亿": 100_000_000}.get(match.group(3) or "", 1)
        unit_token = match.group(4)
        currency = next((code for pattern, code in _CURRENCY_UNITS if re.fullmatch(pattern, unit_token)), "CNY")
        results.append(ExtractedNumber(value=low * scale, currency=currency, raw=match.group(0)))
        results.append(ExtractedNumber(value=high * scale, currency=currency, raw=match.group(0)))
        masked = masked.replace(match.group(0), " " * len(match.group(0)), 1)
    for match in _AMOUNT_PATTERN.finditer(masked):
        number = _number_literal(match.group(1))
        if number is None:
            continue
        scale = {"万": 10_000, "亿": 100_000_000}.get(match.group(2) or "", 1)
        unit_token = match.group(3)
        currency = next((code for pattern, code in _CURRENCY_UNITS if re.fullmatch(pattern, unit_token)), "CNY")
        results.append(ExtractedNumber(value=number * scale, currency=currency, raw=match.group(0)))
    for match in _PERCENT_PATTERN.finditer(text):
        try:
            results.append(ExtractedNumber(value=float(match.group(1)), currency=None, raw=match.group(0)))
        except ValueError:
            continue
    return results


def tool_fact_numbers(events: list[dict]) -> list[ExtractedNumber]:
    """从 tool.result 事件收集合法金额：商品卡、到手价、订单/确认单。"""
    facts: list[ExtractedNumber] = []

    def add(value, currency):
        try:
            facts.append(ExtractedNumber(value=float(value), currency=currency, raw=f"{value}{currency}"))
        except (TypeError, ValueError):
            return

    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") != "tool.result":
            continue
        tool = payload.get("tool")
        if tool == "product_search_tool":
            for hit in payload.get("hits") or []:
                currency = hit.get("currency")
                if hit.get("price_major") is not None:
                    add(hit["price_major"], currency)
                for sku in hit.get("skus") or []:
                    if isinstance(sku, dict) and sku.get("price_major") is not None:
                        add(sku["price_major"], sku.get("currency", currency))
                landed = hit.get("landed_price")
                if isinstance(landed, dict):
                    for field in ("subtotal_major", "freight_major", "tariff_major", "landed_total_major"):
                        if landed.get(field) is not None:
                            add(landed[field], landed.get("currency", currency))
        elif tool in {"create_order_tool", "cancel_order_tool", "query_order_tool"}:
            order = payload.get("order") or {}
            if order.get("total_amount_minor") is not None:
                add(int(order["total_amount_minor"]) / 100, order.get("currency"))
            for item in (payload.get("confirmation") or {}).get("payload", {}).get("items", []) or []:
                if item.get("unit_price_minor") is not None:
                    add(int(item["unit_price_minor"]) / 100, item.get("currency"))
    return facts


def policy_fact_numbers(destinations: set[str]) -> list[ExtractedNumber]:
    """政策事实表：免税额（按目的国币种与人民币双表述）、税率、基础运费。

    按目的国裁剪：只保留本轮工具事实涉及的目的国口径。寄 CN 的订单引用
    「美国免税额」即使数字本身对，也不算可溯源——那是另一个目的国的事实。
    """
    facts: list[ExtractedNumber] = []

    def add(value, currency):
        facts.append(ExtractedNumber(value=float(value), currency=currency, raw="policy"))

    region_currency = {"US": "USD", "EU": "EUR", "JP": "JPY", "SG": "SGD", "CN": "CNY"}
    region_native = {"US": 800.0, "EU": 150.0, "JP": 10000.0, "SG": 400.0, "CN": 5000.0}
    for region, minor in tariff_schedule._DE_MINIMIS_CNY_MINOR.items():
        if destinations and region not in destinations:
            continue
        cny = int(minor) / 100
        add(cny, "CNY")
        if region in region_currency:
            native = region_native.get(region, round(cny / _RATES[region_currency[region]], 2))
            add(native, region_currency[region])
    for country, rates in tariff_schedule._TARIFF_RATES.items():
        if destinations and country not in destinations:
            continue
        for value in rates.values():
            facts.append(ExtractedNumber(value=float(value) * 100, currency=None, raw="policy-rate"))
    for country, minor in tariff_schedule._BASE_FREIGHT_CNY_MINOR.items():
        if destinations and country not in destinations:
            continue
        add(int(minor) / 100, "CNY")
    return facts


def observed_destinations(events: list[dict]) -> set[str]:
    """本轮工具事实里出现过的目的国（landed_price.ship_to）。"""
    destinations: set[str] = set()
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") != "tool.result" or payload.get("tool") != "product_search_tool":
            continue
        for hit in payload.get("hits") or []:
            landed = hit.get("landed_price")
            if isinstance(landed, dict) and landed.get("ship_to"):
                destinations.add(str(landed["ship_to"]))
    return destinations


def _amount_matches(value: float, currency: str, fact: ExtractedNumber) -> bool:
    if currency == fact.currency:
        return abs(value - fact.value) <= 0.5 or abs(value - fact.value) <= 0.01 * fact.value
    if fact.currency is None or currency is None:
        return False
    try:
        fact_in_currency = fact.value / _RATES[fact.currency] * _RATES[currency]
    except KeyError:
        return False
    return abs(value - fact_in_currency) <= 0.5 or abs(value - fact_in_currency) <= 0.01 * abs(fact_in_currency)


def check_answer_numbers_grounded(answer_texts: list[str], events: list[dict]) -> tuple[bool, list[str]]:
    """回复中每个带标记金额/百分比都必须能溯源；返回 (通过, 违规清单)。"""
    facts = tool_fact_numbers(events) + policy_fact_numbers(observed_destinations(events))
    violations: list[str] = []
    for text in answer_texts:
        for number in extract_marked_numbers(text):
            matched = any(
                _amount_matches(number.value, number.currency, fact)
                if number.currency is not None
                else (fact.currency is None and abs(number.value - fact.value) <= 0.05)
                for fact in facts
            )
            if not matched:
                violations.append(number.raw)
    return (not violations), violations


_TAX_FREE_CLAIM = re.compile(r"免(?:征|缴纳?)?关税|免税[额]?已?适(?:用|用)|关税[为是]?\s*0|无需缴(?:纳)?关税|不用交关税")
_TAX_DUE_CLAIM = re.compile(r"需(?:要|须)缴(?:纳)?关税|关税[为是]?\s*[1-9]|要交关税|会产生关税")


def check_policy_statements(answer_texts: list[str], events: list[dict]) -> tuple[bool, str]:
    """免税/关税结论必须与工具返回的 de_minimis_applied 一致；无事实即不通过。"""
    applied_values: list[bool] = []
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") != "tool.result" or payload.get("tool") != "product_search_tool":
            continue
        for hit in payload.get("hits") or []:
            landed = hit.get("landed_price")
            if isinstance(landed, dict) and isinstance(landed.get("de_minimis_applied"), bool):
                applied_values.append(landed["de_minimis_applied"])
    combined = "\n".join(answer_texts)
    free_claim = bool(_TAX_FREE_CLAIM.search(combined))
    due_claim = bool(_TAX_DUE_CLAIM.search(combined))
    if not free_claim and not due_claim:
        return (not applied_values or True), "未作免税/关税结论"
    if not applied_values:
        return False, "作出政策结论但本轮无 de_minimis_applied 事实"
    observed = applied_values[0]
    if len(set(applied_values)) > 1:
        return False, f"多笔到手价的免税状态不一致 {applied_values}，不能给单一结论"
    if free_claim and observed is False:
        return False, "声称免税/免关税，但工具返回 de_minimis_applied=false"
    if due_claim and observed is True:
        return False, "声称需缴关税，但工具返回 de_minimis_applied=true"
    return True, f"政策结论与 de_minimis_applied={observed} 一致"
