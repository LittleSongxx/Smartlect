# -*- coding: utf-8 -*-
"""品类知识正式评测集生成器（22 → 50 例）。

四类题型：
- single（13）：品类+主题词明确的问题，金标为对应主题文档；
- cross（9）：跨品类比较，金标为两篇文档；
- paraphrase（12）：口语化改写，不逐字命中文档标题——压制词面召回虚高的关键桶，
  问题锚定各主题文档独有的内容标记（隐性成本/参数堆砌/退换举证/三步入门）；
- unanswerable（9）：知识库不覆盖的主题，必须拒答；
- policy_refusal（7）：政策类问题，命中政策文档但全部非 fact_eligible，
  为 --formal-gates 的政策拒答桶提供统计输入。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "eval" / "category_recall.jsonl"

_SLUGS = {
    "travel": "travel-gear", "digital": "digital-accessories", "home": "home-living",
    "outdoor": "outdoor-sports", "beauty": "beauty-care", "kitchen": "kitchen-dining",
    "office": "office-study", "baby": "baby-pet",
}
_CN = {"travel": "旅行装备", "digital": "数码配件", "home": "家居生活", "outdoor": "户外运动",
       "beauty": "美妆个护", "kitchen": "厨房餐饮", "office": "办公学习", "baby": "母婴宠物"}


def _doc(slug: str, topic: str) -> str:
    return f"eval-{_SLUGS[slug]}-{topic}.md"


_SINGLE = [
    ("travel", "概览", "旅行装备选购的整体思路是什么"),
    ("digital", "参数判断", "数码配件要怎么判断参数好坏"),
    ("home", "避坑与合规", "家居生活选购有哪些常见的坑"),
    ("outdoor", "价格与预算", "户外运动的价格与预算怎么看"),
    ("beauty", "参数判断", "美妆个护看参数主要看哪些"),
    ("kitchen", "避坑与合规", "厨房餐饮要避开什么坑"),
    ("office", "概览", "办公学习用品怎么选总述"),
    ("baby", "价格与预算", "母婴宠物的价格预算注意什么"),
    ("travel", "参数判断", "旅行装备的参数口径怎么统一"),
    ("kitchen", "概览", "厨房餐饮选购的总体判断顺序"),
    ("digital", "避坑与合规", "数码配件有哪些合规风险"),
    ("home", "价格与预算", "家居生活的到手价怎么估"),
    ("outdoor", "概览", "户外运动新手入门怎么开始"),
]

_CROSS = [
    (("kitchen", "概览"), ("outdoor", "概览"), "厨房用品和户外装备的选购思路分别是什么"),
    (("digital", "参数判断"), ("office", "参数判断"), "数码配件和办公学习用品的参数判断有什么不同"),
    (("travel", "价格与预算"), ("home", "价格与预算"), "旅行装备和家居用品的预算口径差别在哪"),
    (("beauty", "避坑与合规"), ("baby", "避坑与合规"), "美妆个护和母婴用品各有什么坑要注意"),
    (("digital", "价格与预算"), ("travel", "价格与预算"), "数码配件与旅行装备的隐性成本分别是什么"),
    (("home", "参数判断"), ("kitchen", "参数判断"), "家居和厨房用品比参数时注意什么"),
    (("office", "概览"), ("digital", "概览"), "办公学习与数码配件的入门步骤分别怎么走"),
    (("outdoor", "避坑与合规"), ("travel", "避坑与合规"), "户外和旅行装备的合规风险清单分别有哪些"),
    (("baby", "参数判断"), ("beauty", "参数判断"), "母婴和美妆产品看规格参数的差异"),
]

# 口语改写：锚定各主题文档独有内容标记（隐性成本→价格与预算、堆参数→参数判断、
# 退换举证→避坑与合规、三步入门→概览），不使用文档标题词面
_PARAPHRASE = [
    ("travel", "价格与预算", "除了标价，买个行李箱还有哪些看不见的花销"),
    ("digital", "参数判断", "宣传页一堆参数看得眼晕，哪些才是真的有用"),
    ("home", "避坑与合规", "网上买易碎的东西，出了纠纷怎么举证"),
    ("outdoor", "概览", "第一次玩露营，从哪几步开始入手"),
    ("beauty", "价格与预算", "护肤品的到手成本里容易被忽略的是什么"),
    ("kitchen", "避坑与合规", "厨房用具收到有问题，售后该怎么留证据"),
    ("office", "参数判断", "买台灯这些桌面物件怎么绕开虚标"),
    ("baby", "概览", "刚有娃，买婴儿用品从哪儿开始下手"),
    ("travel", "概览", "出远门背东西，钱主要该花在哪些属性上"),
    ("digital", "避坑与合规", "充电器这类东西跨境买要注意什么风险"),
    ("home", "价格与预算", "大件家具寄回家，实际要花的钱怎么算"),
    ("outdoor", "参数判断", "装备的承重防水这些数字怎么看才不被忽悠"),
]

_UNANSWERABLE = [
    "吉他这类乐器怎么选购",
    "汽车脚垫哪种材质好",
    "宠物生病用药有什么注意事项",
    "运动蛋白粉怎么挑选",
    "办公室装修风水有什么讲究",
    "生鲜食品冷链运输怎么保证新鲜",
    "黄金首饰的成色怎么鉴别",
    "考研教材买哪个版本",
    "洗衣机维修上门费用一般多少",
]

_POLICY = [
    ("eval-policy-us.md", "美国方向的免税额度是多少，超过怎么算"),
    ("eval-policy-eu.md", "欧洲方向包裹的申报有什么要求"),
    ("eval-policy-jp.md", "寄日本的运费和体积重怎么算"),
    ("eval-policy-sg.md", "新加坡方向清关要注意什么"),
    ("eval-policy-cn.md", "中国跨境零售哪些品类可以买"),
    ("eval-policy-global-shipping.md", "跨境运费按什么规则计价"),
    ("eval-policy-battery.md", "带电池的商品能寄国外吗"),
]


def build_rows() -> list[dict]:
    rows: list[dict] = []

    def split_for_next() -> str:
        return "dev" if len(rows) % 10 < 7 else "release"

    def add(kind: str, query: str, relevant: list[str], note: str, **extra) -> None:
        row = {"id": f"cat-{len(rows) + 1:02d}", "kind": kind, "split": split_for_next(),
               "query": query, "relevant": relevant, "note": note}
        row.update(extra)
        rows.append(row)

    for slug, topic, query in _SINGLE:
        add("single", query, [_doc(slug, topic)], f"单品类主题题：{topic}")
    for (a, ta), (b, tb), query in _CROSS:
        add("cross", query, [_doc(a, ta), _doc(b, tb)], f"跨品类比较：{ta}")
    for slug, topic, query in _PARAPHRASE:
        add("paraphrase", query, [_doc(slug, topic)], f"口语改写（锚定{topic}独有内容标记）")
    for query in _UNANSWERABLE:
        add("unanswerable", query, [], "知识库未覆盖主题，必须拒答", expected_unanswerable=True)
    for doc, query in _POLICY:
        add("policy_refusal", query, [doc], "政策题：命中材料非 fact_eligible，只能给拒答口径",
            expected_behavior="require_realtime_source")
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="生成品类知识评测集（50 例）")
    parser.add_argument("--output", type=Path, default=DATASET)
    args = parser.parse_args(argv)
    rows = build_rows()

    problems: list[str] = []
    if len(rows) != 50:
        problems.append(f"总数 {len(rows)} != 50")
    kinds = Counter(row["kind"] for row in rows)
    if dict(kinds) != {"single": 13, "cross": 9, "paraphrase": 12, "unanswerable": 9, "policy_refusal": 7}:
        problems.append(f"题型配比异常：{dict(kinds)}")
    splits = Counter(row["split"] for row in rows)
    if dict(splits) != {"dev": 35, "release": 15}:
        problems.append(f"split 异常：{dict(splits)}")
    coverage: dict[str, set[str]] = {}
    for row in rows:
        coverage.setdefault(row["kind"], set()).add(row["split"])
    single_sided = [kind for kind, found in coverage.items() if found != {"dev", "release"}]
    if single_sided:
        problems.append(f"题型未双覆盖：{single_sided}")
    knowledge = {path.name for path in (PROJECT_ROOT / "knowledge").glob("*.md")}
    missing = [name for row in rows for name in row["relevant"] if name not in knowledge]
    if missing:
        problems.append(f"金标文档不存在：{sorted(set(missing))}")
    if len({row["query"] for row in rows}) != len(rows):
        problems.append("存在重复 query")
    if problems:
        for problem in problems:
            print(f"[problem] {problem}")
        raise SystemExit(1)

    args.output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    print(f"已写出 {len(rows)} 例 → {args.output}")


if __name__ == "__main__":
    main()
