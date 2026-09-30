# -*- coding: utf-8 -*-
"""在冻结的 v1 正式评测集上做确定性增量扩充（商品检索）。

背景：release 判定集仅 45 条（37 正例 + 8 负例），门禁判定的 Wilson 95% CI
下界低于门禁线，统计不稳健。本生成器把判定集扩到统计可用规模。

与 generate_eval_v1.py 的关系：只读复用其常量与推导函数，不改原文件的
历史语义；原有 150 行逐字节保留（冻结），新增行追加。

正确性机制（与原生成器同源并加强）：
1. 金标由结构化约束在 catalog-v3（运行时真实目录）上反向枚举，不人工拍标；
   原生成器基于 catalog-v1，是负例曾被 v3 击穿的根源，此处修正为 v3。
2. 新增金标 canonical 与现有集零交集（统计独立性）；新增集内部允许复用
   （同原生成器 semantic/composite 共池切片的设计）。
3. canonical→split：现有 103 个实体沿用现有分配；新增实体按排序后交错分配。
4. 负例对 v3 求"品类×材质×目的地"组合的最低小计价，预算=下限−0.01；
   运行时由 validate_empty_cases 用运行时仓库穷举复核。
5. 完全确定性：无随机数，行序 + 排序驱动；查询与现有集查重。
6. 负例数量找平，保证文件总数精确 70/30（eval_quality 的既有契约）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_eval_v1 import (  # noqa: E402
    _RATES_TO_CNY, _is_available, _primary_available, _price_in,
    _eligible_records, _base_product_row, _MATERIAL_NEEDS, _CATEGORY_NEEDS,
)

CATALOG = ROOT / "data" / "catalog-v3.jsonl"
DATASET = ROOT / "eval" / "v1" / "product_retrieval.jsonl"

# 目标配额（上限，实际按目录容量自适应；负例找平 70/30）
TARGETS = {
    "literal": {"dev": 122, "release": 50},
    "semantic": {"dev": 114, "release": 50},
    "composite": {"dev": 114, "release": 50},
    "empty": {"dev": 140, "release": 60},
}
CURRENCIES = tuple(_RATES_TO_CNY)

# 语义查询的同义句式（需求表达不复述品类/材质词的目标不变，仅句式多样化，
# 突破"品类×首材质"二元组的查询文本上限，更接近真实查询的措辞分布）。
_SEMANTIC_TEMPLATES = (
    "我想找一件东西，{category_need}，同时{material_need}，请按这些限制推荐。",
    "帮我看看有什么能{category_need}；要{material_need}的。",
    "想要个{material_need}的物件，平时{category_need}。",
    "有没有{category_need}的选择？最好是{material_need}的那种。",
)


def _semantic_query(record: dict, variant: int) -> str:
    return _SEMANTIC_TEMPLATES[variant].format(
        category_need=_CATEGORY_NEEDS[record["category"]],
        material_need=_MATERIAL_NEEDS[record["material_tags"][0]],
    )


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_expansion(records: list[dict], existing_rows: list[dict]) -> list[dict]:
    # ---- 现有集的状态（冻结事实） ----
    existing_queries = {row["query"] for row in existing_rows}
    used_canonical: set[str] = set()
    existing_split: dict[str, str] = {}
    for row in existing_rows:
        for canonical_id in row.get("relevant_canonical_ids") or []:
            used_canonical.add(canonical_id)
            existing_split.setdefault(canonical_id, row["split"])

    # ---- 新增实体的 split 分配（沿用原生成器 %10<7 交错粒度） ----
    # 更粗的交错粒度让"系列邻居"（价格/材质相近、互为约束合格集的实体）大概率
    # 同侧，组合的金标"全部同 split"才可能满足；同时交错仍防止整批系列落同侧。
    fresh = sorted({
        record["canonical_product_id"] for record in records
        if _is_available(record) and record["canonical_product_id"] not in used_canonical
    })
    fresh_split = {
        canonical_id: ("dev" if index % 10 < 7 else "release")
        for index, canonical_id in enumerate(fresh)
    }
    split_of = {**fresh_split, **existing_split}  # 现有分配优先

    # ---- literal：每条一个独立新增实体（种子即金标） ----
    representatives: dict[str, dict] = {}
    for record in records:
        if _is_available(record):
            representatives.setdefault(record["canonical_product_id"], record)
    literal_rows: list[dict] = []
    literal_used: set[str] = set()
    for split, quota in TARGETS["literal"].items():
        for canonical_id, record in representatives.items():
            if len([r for r in literal_rows if r["split"] == split]) >= quota:
                break
            if canonical_id in used_canonical or canonical_id in literal_used:
                continue
            if split_of[canonical_id] != split:
                continue
            query = record["title"]
            if query in existing_queries:
                continue
            constraints = {
                "category": record["category"], "target_currency": _primary_available(record)["currency"],
                "require_in_stock": True, "required_material_tags": [], "excluded_material_tags": [],
            }
            literal_rows.append(_base_product_row(
                0, "literal", query, [record["product_id"]], [canonical_id],
                split=split, constraints=constraints,
                note="精确商品名检索，按 canonical 实体计分（v3 扩充）。",
            ))
            literal_used.add(canonical_id)
            existing_queries.add(query)

    # ---- semantic / composite：约束组合池（金标与现有集零交集） ----
    # ---- 实体归属追踪：eval_quality 断言的原始语义是"同一 canonical 不得
    # 出现在两个 split 的金标里"。literal 先构建并 claim 自己的实体；组合的
    # 实体可与任意侧实体共存，只要该实体未被对侧 claim（冲突即弃，不取
    # 原生成器"组合内全同侧"的保守实现——那是断言的充分非必要条件）。
    claimed: dict[str, str] = dict(existing_split)
    for row in literal_rows:
        for canonical_id in row["relevant_canonical_ids"]:
            claimed[canonical_id] = row["split"]

    def composite_pool(split: str) -> list[tuple[dict, dict, list[dict]]]:
        # 两遍扫描：先取"金标全为新增实体"的组合（统计独立性最佳）；
        # 第二遍放宽为"可含现有实体，但不得与其实体归属 split 冲突"。
        # 无归属约束的唯一组合约 577 个，两遍保证优先级与容量兼得。
        options: list[tuple[dict, dict, list[dict]]] = []
        for require_fresh_only in (True, False):
            for record in records:
                if not _is_available(record):
                    continue
                # 种子只提供约束来源，不限侧别：组合的统计归属由金标 claim 决定。
                if record["material_tags"][0] not in _MATERIAL_NEEDS:
                    continue  # 语义措辞词典未覆盖的材质只进 composite/literal
                primary = _primary_available(record)
                currency = primary["currency"]
                base = {
                    "category": record["category"], "ship_to": record["ships_to"][0],
                    "target_currency": currency,
                    "require_in_stock": True,
                    "required_material_tags": list(record["material_tags"]),
                    "excluded_material_tags": [],
                }
                # 合格集先按"种子价+0.01"反查（保留种子价格档的组合多样性）；
                # 实体数超过 4 时收紧到"第 k 便宜实体（k<=4）的价格"兜底。
                # v3 同品类同材质的相近实体成群，纯种子价合格集常达 5-9 个实体。
                ranked = sorted(_eligible_records(records, {**base, "price_max_major": 1e9}),
                                key=lambda item: (_price_in(item, currency), item["canonical_product_id"]))
                caps = [round(_price_in(record, currency) + 0.01, 2)]
                caps += [round(_price_in(ranked[k - 1], currency) + 0.01, 2) for k in (4, 3, 2, 1) if len(ranked) >= k]
                for cap in caps:
                    constraints = {**base, "price_max_major": cap}
                    eligible = _eligible_records(records, constraints)
                    eligible_by_canonical: dict[str, dict] = {}
                    for item in eligible:
                        eligible_by_canonical.setdefault(item["canonical_product_id"], item)
                    canonical_ids = sorted(eligible_by_canonical)
                    if not 1 <= len(canonical_ids) <= 4:
                        continue
                    if any(claimed.get(c, split) != split for c in canonical_ids):
                        continue  # 已被对侧 claim
                    if require_fresh_only and any(c in used_canonical for c in canonical_ids):
                        continue
                    if not require_fresh_only and not any(c not in used_canonical for c in canonical_ids):
                        continue  # 第二遍仍要求至少一个新增实体
                    for c in canonical_ids:
                        claimed[c] = split
                    options.append((record, constraints,
                                    [eligible_by_canonical[c] for c in canonical_ids]))
                    break
            if len(options) >= TARGETS["semantic"][split] + TARGETS["composite"][split]:
                break
        return options

    semantic_rows: list[dict] = []
    composite_rows: list[dict] = []
    # release 是判定集，先构建优先保配额；dev 随后按剩余容量落地
    for split in ("release", "dev"):
        pool = composite_pool(split)
        sem_quota, comp_quota = TARGETS["semantic"][split], TARGETS["composite"][split]
        if len(pool) < sem_quota + comp_quota:
            print(f"  [warn] {split} 组合池 {len(pool)} < 目标 {sem_quota}+{comp_quota}，按容量落地")
        # 池按（品类×首材质）分组轮转排序：语义查询文本由该二元组决定，
        # 轮转让有限配额覆盖尽量多的品类×材质组合，而非堆在少数组里。
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for option in pool:
            key = (option[1]["category"], option[1]["required_material_tags"][0])
            groups[key].append(option)
        rotated: list = []
        while any(groups.values()):
            for key in sorted(groups):
                if groups[key]:
                    rotated.append(groups[key].pop(0))
        cursor = 0
        placed_sem = 0
        placed_comp = 0
        # 逐 option 交错消费：先按 semantic 需求句式尝试（同义变体轮转），
        # 查重失败立即回退为 composite 显式模板——同一组合池同时喂两种 kind，
        # 避免顺序两段消费时 semantic 的查重失败烧掉组合配额。
        while cursor < len(rotated) and (placed_sem < sem_quota or placed_comp < comp_quota):
            record, constraints, relevant_records = rotated[cursor]
            cursor += 1
            consumed = False
            if placed_sem < sem_quota:
                for variant in range(len(_SEMANTIC_TEMPLATES)):
                    query = _semantic_query(record, variant)
                    if query in existing_queries:
                        continue
                    semantic_rows.append(_base_product_row(
                        0, "semantic", query,
                        [item["product_id"] for item in relevant_records],
                        [item["canonical_product_id"] for item in relevant_records],
                        split=split, constraints=constraints,
                        note="需求表达不复述品类或材质标签，金标由结构化约束完整推导（v3 扩充）。",
                    ))
                    existing_queries.add(query)
                    placed_sem += 1
                    consumed = True
                    break
            if consumed or placed_comp >= comp_quota:
                continue
            material = "、".join(constraints["required_material_tags"])
            query = (f"预算 {constraints['price_max_major']:.0f} {constraints['target_currency']} 以内，"
                     f"寄到 {constraints['ship_to']} 的{material}{constraints['category']}，要有现货。")
            if query in existing_queries:
                continue
            composite_rows.append(_base_product_row(
                0, "composite", query,
                [item["product_id"] for item in relevant_records],
                [item["canonical_product_id"] for item in relevant_records],
                split=split, constraints=constraints,
                note="品类、材质、预算、配送和库存均为硬约束，金标由目录完整推导（v3 扩充）。",
            ))
            existing_queries.add(query)
            placed_comp += 1

    # ---- 负例：品类×材质×目的地组合 × 币种轮转，预算=组合最低小计−0.01 ----
    # 配额动态找平：eval_quality 要求 dev == total*7//10（整数精确），
    # 在正例落地后解出负例数；断言形式 (dev, release)==(total*7//10, total*3//10)
    # 要求 total 被 10 整除，两个负例配额一起解。
    new_dev_pos = sum(1 for r in literal_rows + semantic_rows + composite_rows if r["split"] == "dev")
    new_rel_pos = sum(1 for r in literal_rows + semantic_rows + composite_rows if r["split"] == "release")
    existing_dev_total = sum(1 for r in existing_rows if r["split"] == "dev")
    empty_dev_target, empty_rel_target = next(
        (ed, er)
        for er in range(TARGETS["empty"]["release"], 300)
        for ed in range(0, 800)
        if (total := len(existing_rows) + new_dev_pos + new_rel_pos + ed + er) % 10 == 0
        and existing_dev_total + new_dev_pos + ed == total * 7 // 10
    )
    print(f"  负例找平：dev {empty_dev_target} / release {empty_rel_target}"
          f"（新增正例 dev {new_dev_pos} / release {new_rel_pos}）")
    combos: dict[tuple[str, str, str], None] = {}
    for record in records:
        if not _is_available(record):
            continue
        for material in record["material_tags"]:
            for ship_to in record["ships_to"]:
                combos.setdefault((record["category"], material, ship_to), None)
    empty_rows: list[dict] = []
    combo_list = sorted(combos)
    for turn in range(5):  # 币种轮转轮次（同组合不同币种视为不同题）
        for combo_index, (category, material, ship_to) in enumerate(combo_list):
            placed = Counter(row["split"] for row in empty_rows)
            if placed["dev"] >= empty_dev_target and placed["release"] >= empty_rel_target:
                break
            currency = CURRENCIES[(combo_index + turn) % len(CURRENCIES)]
            prices = [
                _price_in(item, currency) for item in records
                if _is_available(item) and item["category"] == category
                and ship_to in item["ships_to"] and material in item["material_tags"]
            ]
            if not prices:
                continue
            budget = max(0.0, round(min(prices) - 0.01, 2))
            if budget <= 0:
                continue
            # 找平 70/30：两桶都未满时按 dev 优先交替放
            split = "dev" if placed["dev"] < empty_dev_target else "release"
            constraints = {
                "category": category, "ship_to": ship_to, "target_currency": currency,
                "price_max_major": budget, "require_in_stock": True,
                "required_material_tags": [material], "excluded_material_tags": [],
            }
            query = (f"我只剩 {budget:.2f} {currency}，要寄到 {ship_to}，"
                     f"请找{material}{category}现货。")
            if query in existing_queries:
                continue
            row = _base_product_row(
                0, "empty", query, [], [], split=split, constraints=constraints,
                note="近邻无结果题：候选语义存在，但最便宜的合格商品仍超预算（v3 下限推导）。",
            )
            row["expected_empty"] = True
            empty_rows.append(row)
            existing_queries.add(query)

    rows = literal_rows + semantic_rows + composite_rows + empty_rows
    # 重编 id/组族（接续现有行号）
    start = len(existing_rows)
    for offset, row in enumerate(rows):
        index = start + offset
        row["id"] = f"prod-{index + 1:03d}"
        family = f"product-{row['kind']}-{row['split']}-{index % 3}"
        row["group_id"] = family
        row["template_family"] = family
        # 键序与原生成器一致（sort_keys 序列化）
        ordered = {key: row[key] for key in sorted(row)}
        rows[offset] = ordered
    return rows


def main() -> None:
    records = _load_jsonl(CATALOG)
    existing = _load_jsonl(DATASET)
    expansion = build_expansion(records, existing)
    stats = Counter((row["kind"], row["split"]) for row in expansion)
    print("新增配额（kind, split）:", dict(stats))
    pos_release = sum(1 for r in expansion if r["split"] == "release" and not r.get("expected_empty"))
    neg_release = sum(1 for r in expansion if r["split"] == "release" and r.get("expected_empty"))
    total_new = len(expansion)
    total = len(existing) + total_new
    dev_total = sum(1 for r in existing + expansion if r["split"] == "dev")
    release_total = total - dev_total
    print(f"release 正例 {37 + pos_release}（新增 {pos_release}），release 负例 {8 + neg_release}（新增 {neg_release}）")
    print(f"文件总数 {total} = dev {dev_total} / release {release_total}（70/30 断言需 {total * 7 // 10}/{total * 3 // 10}）")
    ok = dev_total == total * 7 // 10 and release_total == total * 3 // 10
    print("70/30 精确比例:", "满足" if ok else "不满足——需调整负例配额")
    if "--write" in sys.argv:
        with open(DATASET, "a", encoding="utf-8") as handle:
            for row in expansion:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"已追加 {total_new} 行 → {DATASET}")
    else:
        print("dry 模式（--write 写入）")


if __name__ == "__main__":
    main()
