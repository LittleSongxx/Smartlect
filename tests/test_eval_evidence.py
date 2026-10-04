# -*- coding: utf-8 -*-
"""评测事件证据的确定性断言。"""

import pytest

from scripts.eval.evidence import AssertionDefinitionError, evaluate_trace_assertions


EVENTS = [
    {
        "type": "tool.invoke",
        "payload": {"tool": "product_search_tool", "args": {"price_max_major": 300}},
    },
    {
        "type": "tool.result",
        "payload": {
            "tool": "product_search_tool",
            "hits": [
                {"product_id": "P1008", "price_major": 89, "stock": 18, "material_tags": ["金属"]},
            ],
        },
    },
    {
        "type": "tool.invoke",
        "payload": {"tool": "create_order_tool", "args": {}},
    },
    {
        "type": "tool.result",
        "payload": {"tool": "create_order_tool", "order": {"status": "CONFIRMED"}},
    },
]


def test_required_and_forbidden_tools_are_checked_from_trace():
    results = evaluate_trace_assertions(
        [
            {"criterion": "调商品检索", "kind": "required_tools", "tools": ["product_search_tool"]},
            {"criterion": "不下单", "kind": "forbidden_tools", "tools": ["cancel_order_tool"]},
        ],
        EVENTS,
    )

    assert [item["pass"] for item in results] == [True, True]


def test_product_constraint_leak_is_deterministically_captured():
    results = evaluate_trace_assertions(
        [
            {
                "criterion": "预算库存材质均不得泄漏",
                "kind": "product_hits", "price_max_major": 100, "require_in_stock": True,
                "excluded_material_tags": ["合成聚合物"],
            },
        ],
        EVENTS,
    )
    assert results[0]["pass"] is True

    bad_events = [*EVENTS]
    bad_events[1] = {
        "type": "tool.result",
        "payload": {"tool": "product_search_tool", "hits": [{"product_id": "P-bad", "price_major": 101, "stock": 0, "material_tags": ["合成聚合物"]}]},
    }
    bad = evaluate_trace_assertions(
        [{"criterion": "预算库存材质均不得泄漏", "kind": "product_hits", "price_max_major": 100,
          "require_in_stock": True, "excluded_material_tags": ["合成聚合物"]}],
        bad_events,
    )
    assert bad[0]["pass"] is False
    assert "P-bad" in bad[0]["reason"]


def test_product_constraint_reads_stock_from_real_product_card_skus():
    """线上商品卡没有顶层 stock，评测必须从 SKU 判断有货。"""
    events = [{
        "type": "tool.result",
        "payload": {
            "tool": "product_search_tool",
            "hits": [{
                "product_id": "P-card", "price_major": 99, "material_tags": ["金属"],
                "skus": [{"sku_id": "P-card-S1", "stock": 3}],
            }],
        },
    }]

    result = evaluate_trace_assertions(
        [{"criterion": "SKU 有货", "kind": "product_hits", "require_in_stock": True}],
        events,
    )

    assert result[0]["pass"] is True


def test_empty_but_successful_search_has_no_constraint_leak():
    events = [{
        "type": "tool.result",
        "payload": {"tool": "product_search_tool", "hits": []},
    }]

    result = evaluate_trace_assertions(
        [{"criterion": "不得泄漏禁用材质", "kind": "product_hits", "excluded_material_tags": ["合成聚合物"]}],
        events,
    )

    assert result[0]["pass"] is True
    assert "候选 0 个" in result[0]["reason"]


def test_order_status_and_unknown_assertion_fail_closed():
    results = evaluate_trace_assertions(
        [{"criterion": "订单已确认", "kind": "order_statuses", "expected": ["CONFIRMED"]}],
        EVENTS,
    )
    assert results[0]["pass"] is True

    with pytest.raises(AssertionDefinitionError):
        evaluate_trace_assertions([{"criterion": "坏断言", "kind": "unsupported"}], EVENTS)


def test_forbidden_tool_before_turn_checks_only_the_pre_confirmation_trace():
    assertion = [{
        "criterion": "确认前不下单", "kind": "forbidden_tools_before_turn",
        "tools": ["create_order_tool"], "before_turn": 1,
    }]
    safe_then_confirmed = [
        {"type": "tool.invoke", "payload": {"tool": "product_search_tool"}},
        {"type": "eval.turn.complete", "payload": {"turn_index": 1}},
        {"type": "tool.invoke", "payload": {"tool": "create_order_tool"}},
    ]
    premature_order = [
        {"type": "tool.invoke", "payload": {"tool": "create_order_tool"}},
        {"type": "eval.turn.complete", "payload": {"turn_index": 1}},
    ]

    assert evaluate_trace_assertions(assertion, safe_then_confirmed)[0]["pass"] is True
    assert evaluate_trace_assertions(assertion, premature_order)[0]["pass"] is False


def test_tool_error_assertion_requires_the_expected_reproducible_failure():
    assertion = [{
        "criterion": "不支持目的国要如实报错", "kind": "tool_error",
        "tool": "product_search_tool", "contains": "暂不支持的目的国",
    }]
    events = [{
        "type": "tool.result",
        "payload": {"tool": "product_search_tool", "error": "暂不支持的目的国：BR"},
    }]

    assert evaluate_trace_assertions(assertion, events)[0]["pass"] is True


def test_landed_price_consistency_is_checked_from_tool_facts():
    assertion = [{"criterion": "到手价恒等式", "kind": "landed_price_consistency"}]
    good = [{
        "type": "tool.result",
        "payload": {
            "tool": "product_search_tool",
            "hits": [{
                "product_id": "P1",
                "landed_price": {
                    "subtotal_major": 219,
                    "freight_major": 9.15,
                    "tariff_major": 0,
                    "landed_total_major": 228.15,
                    "currency": "USD",
                },
            }],
        },
    }]
    bad = [{
        **good[0],
        "payload": {
            **good[0]["payload"],
            "hits": [{
                "product_id": "P1",
                "landed_price": {
                    "subtotal_major": 219,
                    "freight_major": 9.15,
                    "tariff_major": 0,
                    "landed_total_major": 230,
                    "currency": "USD",
                },
            }],
        },
    }]

    assert evaluate_trace_assertions(assertion, good)[0]["pass"] is True
    assert evaluate_trace_assertions(assertion, bad)[0]["pass"] is False


def _turn_event(final_text: str) -> dict:
    return {"type": "eval.turn.complete", "payload": {"turn_index": 1, "final_text": final_text}}


def _landed_event(de_minimis: bool = True, ship_to: str = "CN") -> dict:
    return {"type": "tool.result", "payload": {"tool": "product_search_tool", "hits": [{
        "product_id": "P1", "price_major": 258.0, "currency": "CNY",
        "skus": [{"spec": "标准", "price_major": 258.0, "currency": "CNY", "stock": 5}],
        "landed_price": {"currency": "CNY", "ship_to": ship_to, "subtotal_major": 258.0,
                         "freight_major": 20.0, "tariff_major": 0.0 if de_minimis else 39.0,
                         "landed_total_major": 278.0 if de_minimis else 317.0,
                         "de_minimis_applied": de_minimis},
    }]}}


class TestFaithfulnessAssertions:
    def test_answer_numbers_grounded_passes_on_tool_price(self):
        results = evaluate_trace_assertions(
            [{"criterion": "金额可溯源", "kind": "answer_numbers_grounded"}],
            [_landed_event(), _turn_event("到手价 278 元，含运费 20 元。")],
        )
        assert results[0]["pass"] is True

    def test_answer_numbers_grounded_fails_on_fabricated_amount(self):
        results = evaluate_trace_assertions(
            [{"criterion": "金额可溯源", "kind": "answer_numbers_grounded"}],
            [_landed_event(), _turn_event("这个品类一般 180-350 元。")],
        )
        assert results[0]["pass"] is False

    def test_answer_numbers_grounded_fails_closed_without_turn_text(self):
        results = evaluate_trace_assertions(
            [{"criterion": "金额可溯源", "kind": "answer_numbers_grounded"}],
            [_landed_event()],
        )
        assert results[0]["pass"] is False

    def test_policy_fact_grounded_matches_flag(self):
        results = evaluate_trace_assertions(
            [{"criterion": "政策结论一致", "kind": "policy_fact_grounded"}],
            [_landed_event(de_minimis=True), _turn_event("该订单免征关税。")],
        )
        assert results[0]["pass"] is True

    def test_policy_fact_grounded_rejects_contradiction(self):
        results = evaluate_trace_assertions(
            [{"criterion": "政策结论一致", "kind": "policy_fact_grounded"}],
            [_landed_event(de_minimis=False), _turn_event("放心，这个订单免征关税。")],
        )
        assert results[0]["pass"] is False
