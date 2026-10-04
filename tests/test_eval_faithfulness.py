# -*- coding: utf-8 -*-
"""忠实度对账（金额溯源 / 政策结论）单测。

重点复刻三类历史失败模式：免税额误读（把 de_minimis_applied 当免税事实、
把别国免税额安到本国订单上）、编造工具未返回的价格区间、跨目的国政策数字。
另覆盖中文数字、万/亿量级、区间两端、百分比与跨币种换算的常规口径。
"""
import pytest

from scripts.eval.faithfulness import (
    check_answer_numbers_grounded,
    check_policy_statements,
    extract_marked_numbers,
    observed_destinations,
)


def _search_event(hits: list[dict]) -> dict:
    return {"type": "tool.result", "payload": {"tool": "product_search_tool", "hits": hits}}


def _hit(product_id="P1", price=100.0, currency="CNY", **landed) -> dict:
    hit = {"product_id": product_id, "price_major": price, "currency": currency,
           "skus": [{"spec": "标准", "price_major": price, "currency": currency, "stock": 5}]}
    if landed:
        hit["landed_price"] = {"currency": "CNY", "ship_to": landed.get("ship_to", "CN"), **landed}
    return hit


class TestExtractMarkedNumbers:
    def test_arabic_with_units(self):
        numbers = extract_marked_numbers("总价 258 元，运费 30 块")
        assert [n.value for n in numbers] == [258, 30]
        assert all(n.currency == "CNY" for n in numbers)

    def test_chinese_number_and_scale(self):
        assert extract_marked_numbers("预算三百元")[0].value == 300
        assert extract_marked_numbers("运费两千日元")[0].value == 2000
        assert extract_marked_numbers("约 3 万日元")[0].value == 30000

    def test_foreign_currency_words(self):
        assert extract_marked_numbers("800 美元")[0].currency == "USD"
        assert extract_marked_numbers("150 欧")[0].currency == "EUR"
        assert extract_marked_numbers("400 新元")[0].currency == "SGD"
        assert extract_marked_numbers("128 円")[0].currency == "JPY"

    def test_range_extracts_both_ends(self):
        values = [n.value for n in extract_marked_numbers("价格区间约 180-350 元")]
        assert values == [180, 350]

    def test_percent_and_no_bare_integers(self):
        numbers = extract_marked_numbers("关税 13%，共 3 件，评分 4.8")
        assert len(numbers) == 1 and numbers[0].value == 13 and numbers[0].currency is None


class TestAnswerNumbersGrounded:
    def test_grounded_price_passes(self):
        events = [_search_event([_hit(price=258.0)])]
        passed, violations = check_answer_numbers_grounded(["到手约 258 元"], events)
        assert passed and not violations

    def test_fabricated_range_fails(self):
        events = [_search_event([_hit(price=258.0)])]
        passed, violations = check_answer_numbers_grounded(["这个品类大概 180-350 元"], events)
        assert not passed
        assert len(violations) == 2 and "180" in violations[0] and "350" in violations[0]

    def test_cross_currency_conversion(self):
        events = [_search_event([_hit(price=71.0, currency="USD")])]
        passed, _ = check_answer_numbers_grounded(["约 504 元"], events)
        assert passed  # 71 USD × 7.10 ≈ 504 CNY，1% 容差内

    def test_cn_order_citing_us_threshold_fails(self):
        """历史失败模式：寄 CN 订单引用美国免税额 800 美元。"""
        events = [_search_event([_hit(price=258.0, ship_to="CN", de_minimis_applied=True,
                                      subtotal_major=258.0, freight_major=20.0,
                                      tariff_major=0.0, landed_total_major=278.0)])]
        passed, violations = check_answer_numbers_grounded(["已适用美国免税额度 800 美元"], events)
        assert not passed

    def test_cn_threshold_in_cn_context_passes(self):
        events = [_search_event([_hit(price=258.0, ship_to="CN", de_minimis_applied=True,
                                      subtotal_major=258.0, freight_major=20.0,
                                      tariff_major=0.0, landed_total_major=278.0)])]
        passed, _ = check_answer_numbers_grounded(["中国免税额度为 5000 元"], events)
        assert passed

    def test_no_tool_facts_all_amounts_fail_closed(self):
        passed, _ = check_answer_numbers_grounded(["大概 200 元"], [])
        assert not passed


class TestPolicyStatements:
    def test_consistent_free_claim(self):
        events = [_search_event([_hit(price=258.0, ship_to="CN", de_minimis_applied=True,
                                      subtotal_major=258.0, freight_major=20.0,
                                      tariff_major=0.0, landed_total_major=278.0)])]
        passed, detail = check_policy_statements(["该订单免征关税"], events)
        assert passed, detail

    def test_free_claim_contradicts_flag(self):
        """历史失败模式：de_minimis_applied=false 却宣称免税。"""
        events = [_search_event([_hit(price=258.0, ship_to="CN", de_minimis_applied=False,
                                      subtotal_major=258.0, freight_major=20.0,
                                      tariff_major=39.0, landed_total_major=317.0)])]
        passed, detail = check_policy_statements(["放心，免征关税"], events)
        assert not passed and "de_minimis_applied=false" in detail

    def test_due_claim_contradicts_flag(self):
        events = [_search_event([_hit(price=258.0, ship_to="CN", de_minimis_applied=True,
                                      subtotal_major=258.0, freight_major=20.0,
                                      tariff_major=0.0, landed_total_major=278.0)])]
        passed, _ = check_policy_statements(["需要缴纳关税"], events)
        assert not passed

    def test_claim_without_facts_fails_closed(self):
        passed, detail = check_policy_statements(["这个订单免关税"], [])
        assert not passed

    def test_observed_destinations(self):
        events = [_search_event([_hit(ship_to="US", de_minimis_applied=False,
                                      subtotal_major=1, freight_major=1, tariff_major=1, landed_total_major=3)])]
        assert observed_destinations(events) == {"US"}
