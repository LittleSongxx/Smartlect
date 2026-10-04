# -*- coding: utf-8 -*-
"""商品检索正式评测集生成器（300 例，紧凑档）。

设计原则：
- 完全确定性：无随机数，按目录稳定排序枚举；重跑输出逐字节一致。
- 金标去同源：查询只描述需求，金标由本脚本内置的独立约束谓词对
  data/catalog-v3.jsonl 全目录判定——谓词语义与线上 CatalogSearchUseCase
  的硬过滤对齐（首个有货 SKU 价格、缺货即剔除、材质/目的国/品类精确匹配），
  但实现独立，不复用线上代码。
- 负例必须可靠为空：只使用能被 spec 级硬约束证明不可满足的负例
  （预算低于最低价 / 排除品类全部材质 / 要求∩排除矛盾 / 目的国不可达），
  生成期逐一断言命中数为 0。
- 分级金标：带预算正例附 substitute_canonical_ids（同品类、同目的国、
  预算上浮 15% 带宽内的近邻实体），仅作观察项，不混入 Recall。
- 指纹绑定：产出 .fingerprint.json sidecar，runner 预检目录版本。

桶配比（正 220 + 负 80 = 300，dev 210 / release 90）：
    literal 30（标题原文冒烟，报告单列不进主口径）
    semantic 60（品类×材质×目的国，无价格约束的语义查询）
    composite 80（含价格上限/区间与排除材质的复合约束）
    colloquial 50（人工撰写口语查询，见 _COLLOQUIAL，约束要素程序硬校验）
    empty 80（负例：budget 26 / excluded_all 16 / contradictory 16 / unreachable 22）
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.catalog.exchange_rate import ExchangeRateTable  # noqa: E402

CATALOG_PATH = PROJECT_ROOT / "data" / "catalog-v3.jsonl"
DATASET_PATH = PROJECT_ROOT / "eval" / "v1" / "product_retrieval.jsonl"

_RATES = ExchangeRateTable().rates_to_cny
DESTINATIONS = ["CN", "US", "JP", "SG", "EU"]
# 价格容差：floor 侧仅影响本脚本自检（0.02）；cap 侧必须严于 eval_quality
# 的 +0.01 容差，否则边界价格会落进「生成器放行、校验器判违规」的缝隙。
_PRICE_EPS = 0.02
_CAP_EPS = 0.005

_CATEGORY_SYNONYMS = {
    "旅行装备": ["旅行", "背包", "行李", "出行"],
    "数码配件": ["数码", "电子", "配件", "充电", "耳机", "键鼠"],
    "家居生活": ["家居", "家里", "居家", "屋子"],
    "厨房餐饮": ["厨房", "餐具", "做饭", "烹饪"],
    "户外运动": ["户外", "露营", "徒步", "运动"],
    "办公学习": ["办公", "学习", "书桌", "上课"],
    "母婴宠物": ["母婴", "宝宝", "婴儿", "宠物", "猫", "狗"],
    "美妆个护": ["美妆", "护肤", "化妆", "个护"],
}
_MATERIAL_SYNONYMS = {
    "合成聚合物": ["塑料", "合成", "尼龙", "聚酯", "聚合物"],
    "天然纤维": ["棉", "麻", "天然纤维", "织物"],
    "金属": ["金属", "铝", "钢", "不锈钢"],
    "玻璃": ["玻璃"],
    "陶瓷": ["陶瓷", "瓷"],
    "天然材料": ["木质", "天然材料", "竹"],
    "纸": ["纸质", "纸"],
}
_DEST_SYNONYMS = {
    "CN": ["中国", "国内", "寄到家", "国内地址"],
    "US": ["美国", "美区"],
    "JP": ["日本"],
    "SG": ["新加坡"],
    "EU": ["欧洲", "欧盟"],
}

_SEMANTIC_TEMPLATES = [
    "想找{cat}类的东西，要{mat}材质的，{dest_clause}预算{cap}元以内",
    "帮我看看{mat}材质的{cat}，{dest_clause}{cap}元以内有什么",
    "{dest_clause}想买{mat}做的{cat}，{cap}元以内耐用点的",
    "有没有{mat}材质的{cat}推荐？{dest_clause}预算{cap}元。",
    "想要一件{mat}的{cat}，{dest_clause}{cap}元以内先给我几个候选",
    "{cat}这块想入个{mat}的，{dest_clause}{cap}元以内的都列一下",
]
_SEMANTIC_BAND_TEMPLATES = [
    "想找{cat}类的东西，要{mat}材质的，{dest_clause}预算{floor}到{cap}元之间",
    "{mat}材质的{cat}，{dest_clause}{floor}到{cap}元这个档位的有哪些",
    "{dest_clause}想买{mat}做的{cat}，价位{floor}到{cap}元就行",
]
_COMPOSITE_TEMPLATES = [
    "预算{cap}{unit}以内，{dest_clause}找{mat_clause}，要有现货。",
    "{mat_clause}，控制在{cap}{unit}以内，{dest_clause}，只要能买到的。",
    "我最多花{cap}{unit}，{dest_clause}要{mat_clause}，麻烦筛一下现货。",
    "帮我挑{mat_clause}，{dest_clause}，价格别超过{cap}{unit}。",
    "{dest_clause}需要{mat_clause}，预算{cap}{unit}封顶，先看有货的。",
    "想在{cap}{unit}预算内买{mat_clause}，{dest_clause}，有现货的优先。",
    "价格{floor}到{cap}{unit}之间，{dest_clause}的{mat_clause}，只要有货。",
    "{mat_clause}，{dest_clause}，预算大概{floor}到{cap}{unit}，给我现货。",
]
_BUDGET_NEGATIVE_TEMPLATES = [
    "我只有{cap}{unit}，{dest_clause}想买{mat_clause}，有现货吗？",
    "预算就{cap}{unit}，{dest_clause}的{mat_clause}，能不能买到？",
    "口袋里只剩{cap}{unit}了，{dest_clause}要{mat_clause}，找找看。",
    "{cap}{unit}的预算，{dest_clause}想入{mat_clause}，有合适的吗？",
]
_EXCLUDED_ALL_TEMPLATES = [
    "{cat}类商品我都不要{mats}材质的，还有能买的吗？",
    "想买{cat}，但{mats}这些材质我都不要，有别的可选吗？",
    "{cat}这块，{mats}材质统统排除，还能买到东西吗？",
    "帮我看{cat}，材质别是{mats}这几种的，有货吗？",
]
_CONTRADICTORY_TEMPLATES = [
    "要{mat}材质的{cat}，但千万别是{mat}的，有吗？",
    "想要{mat}的{cat}，同时不要{mat}材质，帮我找找。",
    "{cat}要{mat}材质的，{mat}的又不行，有办法吗？",
    "找个{mat}材质{cat}，材质上排除{mat}，有吗？",
]
_UNREACHABLE_TEMPLATES = [
    "帮我找{mat}材质的{cat}，{dest_clause}，有现货吗？",
    "{dest_clause}想买{mat}的{cat}，有能发的吗？",
    "{mat}材质的{cat}，{dest_clause}能寄吗？找找现货。",
    "{dest_clause}需要{mat}材质的{cat}，有哪些可选？",
]


def _load_canonicals() -> dict[str, list[dict]]:
    listings = [json.loads(line) for line in CATALOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    canonicals: dict[str, list[dict]] = {}
    for listing in listings:
        canonicals.setdefault(listing["canonical_product_id"], []).append(listing)
    return canonicals


def _first_stock_price_cny(listing: dict) -> float | None:
    """首个有货 SKU 的 CNY 价——与线上 primary_available_sku + 汇率换算同口径。"""
    for sku in listing["skus"]:
        if int(sku["stock"]) > 0:
            return float(sku["price_major"]) * _RATES[sku["currency"]]
    return None


def _listing_passes(listing: dict, c: dict) -> bool:
    if c.get("category") and listing["category"] != c["category"]:
        return False
    materials = set(listing["material_tags"] or [])
    if set(c.get("required") or []) - materials:
        return False
    if set(c.get("excluded") or []) & materials:
        return False
    if c.get("ship_to") and c["ship_to"] not in listing["ships_to"]:
        return False
    price = _first_stock_price_cny(listing)
    if price is None:  # 系统对缺货商品一律剔除
        return False
    cap = c.get("price_cap_cny")
    if cap is not None and price > cap + _CAP_EPS:
        return False
    floor = c.get("price_floor_cny")
    if floor is not None and price < floor - _PRICE_EPS:
        return False
    return True


def _gold(canonicals: dict[str, list[dict]], c: dict) -> list[tuple[str, list[dict]]]:
    """按谓词全目录判定；返回 (canonical_id, 满足约束的 listing 列表)，按 canonical 顺序。"""
    matched = []
    for cid, listings in canonicals.items():
        passing = [l for l in listings if _listing_passes(l, c)]
        if passing:
            matched.append((cid, passing))
    return matched


def _cell_index(canonicals: dict[str, list[dict]]) -> dict[tuple[str, str], list[str]]:
    cells: dict[tuple[str, str], list[str]] = defaultdict(list)
    for cid, listings in canonicals.items():
        categories = {l["category"] for l in listings}
        materials = {m for l in listings for m in (l["material_tags"] or [])}
        for category in categories:
            for material in materials:
                cells[(category, material)].append(cid)
    return dict(cells)


def _pick_rep(passing: list[dict], used: dict[str, set[str]], split: str) -> dict | None:
    """选择与 split 不冲突的代表 listing（防 product_id 级跨 split 泄漏）。

    优先选完全没用过的 product_id（多平台同款 listing 充足），其次选已用于
    同 split 的——绝不复用已属于另一 split 的 product_id。
    """
    fresh = [l for l in passing if l["product_id"] not in used]
    if fresh:
        return fresh[0]
    same_split = [l for l in passing if split in used[l["product_id"]]]
    return same_split[0] if same_split else None


def _substitutes(canonicals: dict[str, list[dict]], c: dict, gold_ids: set[str]) -> list[str]:
    """预算上浮 15% 带宽内的近邻实体（同品类、材质不冲突、同目的国、有货）。"""
    if c.get("price_cap_cny") is None:
        return []
    relaxed = {**c, "price_floor_cny": c["price_cap_cny"] + _PRICE_EPS, "price_cap_cny": c["price_cap_cny"] * 1.15}
    result = []
    for cid, passing in _gold(canonicals, relaxed):
        if cid not in gold_ids:
            result.append(cid)
        if len(result) >= 3:
            break
    return result


def _round_up(value: float, step: int = 10) -> int:
    return int(-(-value // step) * step)


def _dest_clause(dest: str | None) -> str:
    if dest is None:
        return ""
    names = {"CN": "中国", "US": "美国", "JP": "日本", "SG": "新加坡", "EU": "欧洲"}
    return f"要寄到{names[dest]}"


def _material_clause(c: dict) -> str:
    required = c.get("required") or []
    excluded = c.get("excluded") or []
    if required:
        return f"{required[0]}材质的{c['category']}"
    if excluded:
        return f"{c['category']}（不要{'、'.join(excluded)}）"
    return c["category"]


class RowBuilder:
    def __init__(self, canonicals: dict[str, list[dict]]) -> None:
        self.canonicals = canonicals
        self.rows: list[dict] = []
        self.used_products: dict[str, set[str]] = defaultdict(set)

    def next_split(self) -> str:
        return "dev" if len(self.rows) % 10 < 7 else "release"

    def can_place(self, gold: list[tuple[str, list[dict]]]) -> bool:
        """预检：这组金标在下一行的 split 下是否还有可用代表 listing。"""
        split = self.next_split()
        return all(_pick_rep(passing, self.used_products, split) is not None for _, passing in gold)

    def add(self, kind: str, query: str, c: dict, note: str, provenance: str | None = None,
            gold_override: list[tuple[str, list[dict]]] | None = None) -> dict | None:
        index = len(self.rows)
        if any(row["query"] == query for row in self.rows):
            return None  # 查询文本全局唯一
        split = "dev" if index % 10 < 7 else "release"
        if c.get("expected_empty"):
            row = self._base_row(kind, index, query, c, note, provenance)
            row["expected_empty"] = True
            row["relevant"] = []
            row["relevant_canonical_ids"] = []
            self.rows.append(row)
            return row
        # literal 桶金标 = 标题所属款本身（标题检索语义），不走谓词全量枚举
        gold = gold_override if gold_override is not None else _gold(self.canonicals, c)
        if gold_override is None and not (1 <= len(gold) <= 6):
            return None
        rep_listings = []
        for cid, passing in gold:
            rep = _pick_rep(passing, self.used_products, split)
            if rep is None:
                return None
            rep_listings.append((cid, rep))
        for _, rep in rep_listings:
            self.used_products[rep["product_id"]].add(split)
        relevant = [rep["product_id"] for _, rep in rep_listings]
        row = self._base_row(kind, index, query, c, note, provenance)
        row["relevant"] = relevant
        row["relevant_canonical_ids"] = [cid for cid, _ in rep_listings]
        substitutes = _substitutes(self.canonicals, c, {cid for cid, _ in rep_listings})
        if substitutes:
            row["substitute_canonical_ids"] = substitutes
        self.rows.append(row)
        return row

    def _base_row(self, kind: str, index: int, query: str, c: dict, note: str, provenance: str | None) -> dict:
        constraints = {
            "category": c.get("category"),
            "required_material_tags": list(c.get("required") or []),
            "excluded_material_tags": list(c.get("excluded") or []),
            "ship_to": c.get("ship_to"),
            "require_in_stock": True,
            "target_currency": c.get("target_currency", "CNY"),
        }
        cap = c.get("price_cap_cny")
        if cap is not None:
            constraints["price_max_major"] = self._in_currency(cap, c.get("target_currency", "CNY"), direction="up")
            # 携带 CNY 原值：自检与人工复核不必重放汇率换算
            constraints["price_max_cny"] = round(cap, 2)
        floor = c.get("price_floor_cny")
        if floor is not None:
            constraints["price_min_major"] = self._in_currency(floor, c.get("target_currency", "CNY"), direction="down")
            constraints["price_min_cny"] = round(floor, 2)
        row = {
            "id": f"prod-{index + 1:03d}",
            "kind": kind,
            "split": "dev" if index % 10 < 7 else "release",
            "group_id": f"retrieval-{kind}-{index:03d}",
            "template_family": f"retrieval-{kind}-{index:03d}",
            "query": query,
            "note": note,
            "category": c.get("category"),
            "target_currency": c.get("target_currency", "CNY"),
            "require_in_stock": True,
            "required_material_tags": list(c.get("required") or []),
            "excluded_material_tags": list(c.get("excluded") or []),
            "constraints": constraints,
        }
        if c.get("ship_to"):
            row["ship_to"] = c["ship_to"]
        if cap is not None:
            row["price_max_major"] = constraints["price_max_major"]
        if provenance:
            row["provenance"] = provenance
        return row

    @staticmethod
    def _in_currency(amount_cny: float, currency: str, *, direction: str = "nearest") -> float:
        import math

        if currency == "CNY":
            return round(amount_cny, 2)
        value = amount_cny / _RATES[currency]
        if direction == "up":
            return math.ceil(value * 100) / 100
        if direction == "down":
            return math.floor(value * 100) / 100
        return round(value, 2)


def _canonical_prices(canonicals: dict[str, list[dict]], c: dict) -> list[float]:
    """约束下各 canonical 的最低可用价（CNY），升序；空结果表示无候选。"""
    prices = []
    for _, passing in _gold({k: v for k, v in canonicals.items()}, {k2: v2 for k2, v2 in c.items() if k2 != "price_cap_cny"}):
        best = min(p for p in (_first_stock_price_cny(l) for l in passing) if p is not None)
        prices.append(best)
    return sorted(prices)


def _price_levels(canonicals: dict[str, list[dict]], c: dict) -> list[tuple[float, int]]:
    """约束下的 canonical 价格层：[(层价, 截至该层的累计款数)]，升序。

    目录价格大量并列（同一低价位常有几十款），只有按层切开才能得到
    金标数可控的窗口。
    """
    prices = _canonical_prices(canonicals, c)
    levels: list[list] = []
    for price in prices:
        if levels and abs(levels[-1][0] - price) < 1e-9:
            levels[-1][1] += 1
        else:
            levels.append([price, 1])
    cumulative = 0
    result = []
    for price, count in levels:
        cumulative += count
        result.append((price, cumulative))
    return result


def _calibrated_window(canonicals: dict[str, list[dict]], c: dict, keep: int, offset: int) -> tuple[float, float] | None:
    """按价格层取第 offset 层起、累计约 keep 款的窗口，返回 (floor, cap)。

    紧预算总是命中"最便宜的同一批款"，跨 split 复用会撞 product_id 泄漏约束；
    窗口偏移让同一约束胞的不同行落在不同金标切片上。窗口只取整层，
    保证金标集合与层边界一致。
    """
    levels = _price_levels(canonicals, c)
    if not levels:
        return None
    prices = [price for price, _ in levels]
    start = min(offset, len(levels) - 1)
    end = start
    cumulative = levels[start][1] - (levels[start - 1][1] if start > 0 else 0)
    while end + 1 < len(levels) and cumulative < keep:
        end += 1
        cumulative += levels[end][1] - levels[end - 1][1]
    import math
    # cap 向上取整到分：向下舍会把层价压到 cap 之下，被 eval_quality 的 +0.01 容差判违规
    cap = math.ceil(levels[end][0] * 100) / 100
    floor = None if start == 0 else round(prices[start] - _PRICE_EPS, 2)
    probe = {**c, "price_cap_cny": cap}
    if floor is not None:
        probe["price_floor_cny"] = floor
    size = len(_gold(canonicals, probe))
    if 1 <= size <= 6:
        return floor, cap
    return None


def _calibrated_cap(canonicals: dict[str, list[dict]], c: dict, low: int = 2, high: int = 5) -> float | None:
    """在价格网格上找使金标数落在 [low, high] 的最紧预算（10 元步进向上取整）。"""
    prices = _canonical_prices(canonicals, c)
    if len(prices) < low:
        return None
    for keep in range(low, min(high + 1, len(prices) + 1)):
        cap = float(_round_up(prices[keep - 1]))
        if low <= len(_gold(canonicals, {**c, "price_cap_cny": cap})) <= high:
            return cap
    return None


def _calibrated_caps_near(canonicals: dict[str, list[dict]], c: dict, preferred: float) -> list[float]:
    """按与优先预算的距离排序，返回金标数 1..5 的候选价位（价格层口径）。"""
    levels = _price_levels(canonicals, c)
    if not levels:
        return []
    import math
    previous = 0
    candidates: list[tuple[float, float]] = []
    for price, cumulative in levels:
        # cap = 该层价（向上取整到分）时金标是「截至该层的累计款数」，不是该层增量
        if 1 <= cumulative <= 5:
            cap = math.ceil(price * 100) / 100
            candidates.append((abs(cap - preferred), cap))
        previous = cumulative
    candidates.sort()
    return [cap for _, cap in candidates]


def _build_literal(builder: RowBuilder, canonicals: dict[str, list[dict]], target: int) -> None:
    def has_cjk(text: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in text)

    candidates: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for cid in sorted(canonicals):
        for listing in canonicals[cid]:
            if has_cjk(listing["title"]) and _first_stock_price_cny(listing) is not None:
                candidates[listing["category"]].append((cid, listing))
                break
    categories = sorted(candidates)
    emitted = 0
    round_index = 0
    max_pool = max((len(pool) for pool in candidates.values()), default=0)
    while emitted < target and round_index <= max_pool:
        for category in categories:
            if emitted >= target:
                break
            pool = candidates[category]
            if round_index >= len(pool):
                continue
            cid, listing = pool[round_index]
            row = builder.add(
                "literal", listing["title"],
                {"category": category, "target_currency": "CNY"},
                "标题原文冒烟题：金标为该标题所属 canonical 实体，不进主口径。",
                gold_override=[(cid, [listing])],
            )
            if row:
                emitted += 1
        round_index += 1


def _build_semantic(builder: RowBuilder, cells: dict[tuple[str, str], list[str]], canonicals: dict[str, list[dict]], target: int) -> None:
    usable = sorted(cells)
    emitted = 0
    iteration = 0
    while emitted < target and iteration <= 8:
        for cell in usable:
            if emitted >= target:
                break
            variant = iteration % 2
            dest = None if variant == 0 else DESTINATIONS[(iteration + len(cell[0])) % len(DESTINATIONS)]
            base = {"category": cell[0], "required": [cell[1]], "ship_to": dest, "target_currency": "CNY"}
            keep = 2 + (emitted + iteration) % 3
            placed = False
            for offset in (iteration, iteration + 1, iteration + 2):
                window = _calibrated_window(canonicals, base, keep=keep, offset=offset)
                if window is None:
                    continue
                floor, cap = window
                c = {**base, "price_cap_cny": cap}
                if floor is not None:
                    c["price_floor_cny"] = floor
                    template = _SEMANTIC_BAND_TEMPLATES[(emitted + offset) % len(_SEMANTIC_BAND_TEMPLATES)]
                    query = template.format(
                        cat=cell[0], mat=cell[1], cap=f"{cap:g}", floor=f"{floor:g}",
                        dest_clause=_dest_clause(dest) if dest else "",
                    ).replace("，。", "。")
                else:
                    template = _SEMANTIC_TEMPLATES[(emitted + variant) % len(_SEMANTIC_TEMPLATES)]
                    query = template.format(
                        cat=cell[0], mat=cell[1], cap=f"{cap:g}",
                        dest_clause=_dest_clause(dest) if dest else "",
                    ).replace("，。", "。")
                note_extra = (f"×{dest}" if dest else "") + (f"×价格[{floor:g},{cap:g}]" if floor is not None else f"×预算{cap:g}")
                row = builder.add("semantic", query, c, f"语义多约束：{cell[0]}×{cell[1]}{note_extra}")
                if row is not None:
                    placed = True
                    break
            if placed:
                emitted += 1
        iteration += 1


def _build_composite(builder: RowBuilder, cells: dict[tuple[str, str], list[str]], canonicals: dict[str, list[dict]], target: int) -> None:
    usable = sorted(cells)
    category_materials: dict[str, set[str]] = defaultdict(set)
    for category, material in cells:
        category_materials[category].add(material)
    emitted = 0
    iteration = 0
    while emitted < target and iteration <= 8:
        for cell in usable:
            if emitted >= target:
                break
            slot = emitted
            category, material = cell
            use_exclusion = slot % 5 in (3, 4)  # 40% 排除式
            excluded = sorted(category_materials[category] - {material})[:2] if use_exclusion else []
            base: dict = {
                "category": category,
                "excluded": excluded if use_exclusion else [],
                "required": [] if use_exclusion else [material],
                "ship_to": [None, "CN", "US", "JP", None, "SG", "EU"][slot % 7],
                "target_currency": "USD" if slot % 20 in (9, 12) else "CNY",  # 9 落 release 侧、12 落 dev 侧，保证双覆盖
            }
            c = dict(base)
            keep = 2 + slot % 3
            # USD 行只用无下限窗口：floor 经两次汇率换算会漂移出层边界
            offsets = (0,) if c["target_currency"] == "USD" else (iteration, iteration + 1, iteration + 2)
            placed = False
            for offset in offsets:
                window = _calibrated_window(canonicals, base, keep=keep, offset=offset)
                if window is None:
                    continue
                floor, cap = window
                c["price_cap_cny"] = cap
                c.pop("price_floor_cny", None)
                if floor is not None:
                    c["price_floor_cny"] = floor
                unit = "美元" if c["target_currency"] == "USD" else "元"
                cap_text = RowBuilder._in_currency(c["price_cap_cny"], c["target_currency"])
                templates = _COMPOSITE_TEMPLATES[6:] if floor is not None else _COMPOSITE_TEMPLATES[:6]
                template = templates[slot % len(templates)]
                floor_text = RowBuilder._in_currency(c["price_floor_cny"], c["target_currency"]) if floor is not None else 0
                query = template.format(
                    cap=f"{cap_text:g}" if cap_text is not None else "",
                    floor=f"{floor_text:g}" if floor_text else "",
                    unit=unit,
                    dest_clause=_dest_clause(c["ship_to"]),
                    mat_clause=_material_clause(c),
                ).replace("，。", "。")
                note = "复合约束：" + "×".join(filter(None, [category, material if not use_exclusion else f"排除{'+'.join(excluded)}", c["ship_to"], f"价格区间[{floor_text:g},{cap_text:g}]" if floor is not None else f"价格上限{cap_text:g}"]))
                row = builder.add("composite", query, c, note)
                if row is not None:
                    placed = True
                    break
            if placed:
                emitted += 1
        iteration += 1


# 口语桶：50 条人工撰写查询（含约束元数据）。查询文本由作者按真实买家口吻编写，
# 生成期用同义词表硬校验「品类/材质/目的国/预算数字」四要素确实在文本中表达。
_COLLOQUIAL: list[dict] = [
    {"t": "下个月要去东南亚玩，帮我找个塑料材质的旅行装备寄到新加坡，200元以内能买到吗？", "c": {"category": "旅行装备", "required": ["合成聚合物"], "ship_to": "SG", "cap": 200}},
    {"t": "家里桌面太乱，想买个合成材质的办公收纳，寄到国内，50块以内搞定", "c": {"category": "办公学习", "required": ["合成聚合物"], "ship_to": "CN", "cap": 50}},
    {"t": "露营装备想升级个金属的，人在美国，预算300元以内有合适的吗？", "c": {"category": "户外运动", "required": ["金属"], "ship_to": "US", "cap": 300}},
    {"t": "想给厨房添个玻璃材质的物件，能寄到欧洲，100元以内挑一个", "c": {"category": "厨房餐饮", "required": ["玻璃"], "ship_to": "EU", "cap": 100}},
    {"t": "宝宝用的东西想买棉麻材质的母婴用品，寄到日本，150元以内有货吗", "c": {"category": "母婴宠物", "required": ["天然纤维"], "ship_to": "JP", "cap": 150}},
    {"t": "护肤品类想要个玻璃瓶装的，国内地址，80元以内，别给我塑料的", "c": {"category": "美妆个护", "required": ["玻璃"], "ship_to": "CN", "cap": 80}},
    {"t": "出差想带个轻便背包，尼龙材质优先，寄到中国家里，120元以内", "c": {"category": "旅行装备", "required": ["合成聚合物"], "ship_to": "CN", "cap": 120}},
    {"t": "给家里猫主子买个不锈钢的宠物用品，新加坡收货，60元以内", "c": {"category": "母婴宠物", "required": ["金属"], "ship_to": "SG", "cap": 60}},
    {"t": "书桌上想要个陶瓷摆件类的办公物件，美国收货，90元以内有现货吗", "c": {"category": "办公学习", "required": ["陶瓷"], "ship_to": "US", "cap": 90}},
    {"t": "徒步要买个塑料水壶类的户外装备，寄到欧洲，70元以内，要现货", "c": {"category": "户外运动", "required": ["合成聚合物"], "ship_to": "EU", "cap": 70}},
    {"t": "宿舍想买个棉麻的家居用品，国内，45元以内便宜点的", "c": {"category": "家居生活", "required": ["天然纤维"], "ship_to": "CN", "cap": 45}},
    {"t": "耳机收纳想找个硅胶塑料材质的数码配件，中国收货，55元以内", "c": {"category": "数码配件", "required": ["合成聚合物"], "ship_to": "CN", "cap": 55}},
    {"t": "做饭想入个金属材质的厨房工具，寄到日本，180元以内", "c": {"category": "厨房餐饮", "required": ["金属"], "ship_to": "JP", "cap": 180}},
    {"t": "想要个竹木质地的旅行收纳，美国地址，260元以内有吗", "c": {"category": "旅行装备", "required": ["天然材料"], "ship_to": "US", "cap": 260}},
    {"t": "化妆包想要金属壳的，国内寄到家，130元以内", "c": {"category": "美妆个护", "required": ["金属"], "ship_to": "CN", "cap": 130}},
    {"t": "键鼠周边想买塑料材质的，新加坡，95元以内有货优先", "c": {"category": "数码配件", "required": ["合成聚合物"], "ship_to": "SG", "cap": 95}},
    {"t": "野餐想买个玻璃餐盒类的厨房用品，寄到欧洲，110元以内", "c": {"category": "厨房餐饮", "required": ["玻璃"], "ship_to": "EU", "cap": 110}},
    {"t": "书房想要纸质文件收纳类的办公用品，国内地址，300元以内", "c": {"category": "办公学习", "required": ["纸"], "ship_to": "CN", "cap": 300}},
    {"t": "后院露营想添个竹木材质的户外小件，寄到日本，300元以内", "c": {"category": "户外运动", "required": ["天然材料"], "ship_to": "JP", "cap": 300}},
    {"t": "客厅想摆个陶瓷花瓶类的家居物件，寄到中国，75元以内", "c": {"category": "家居生活", "required": ["陶瓷"], "ship_to": "CN", "cap": 75}},
    {"t": "出门带娃想买个塑料材质的母婴包，日本收货，160元以内", "c": {"category": "母婴宠物", "required": ["合成聚合物"], "ship_to": "JP", "cap": 160}},
    {"t": "旅行想换个金属框的行李配件，欧洲，220元以内有货吗", "c": {"category": "旅行装备", "required": ["金属"], "ship_to": "EU", "cap": 220}},
    {"t": "充电配件想买塑料外壳的，国内，40元以内最便宜那种", "c": {"category": "数码配件", "required": ["合成聚合物"], "ship_to": "CN", "cap": 40}},
    {"t": "厨房想换个不锈钢材质的收纳架，中国地址，200元以内", "c": {"category": "厨房餐饮", "required": ["金属"], "ship_to": "CN", "cap": 200}},
    {"t": "野外徒步想入个木质手柄的户外工具，美国，300元以内", "c": {"category": "户外运动", "required": ["天然材料"], "ship_to": "US", "cap": 300}},
    {"t": "不要塑料的母婴用品，寄到新加坡，棉麻类优先，120元以内", "c": {"category": "母婴宠物", "excluded": ["合成聚合物"], "ship_to": "SG", "cap": 120}},
    {"t": "家里不要金属材质的家居用品，国内发货，90元以内", "c": {"category": "家居生活", "excluded": ["金属"], "ship_to": "CN", "cap": 90}},
    {"t": "办公桌上的东西别用塑料的，美国寄送，150元以内", "c": {"category": "办公学习", "excluded": ["合成聚合物"], "ship_to": "US", "cap": 150}},
    {"t": "护肤品不要玻璃瓶的怕碎，寄到日本，100元以内", "c": {"category": "美妆个护", "excluded": ["玻璃"], "ship_to": "JP", "cap": 100}},
    {"t": "数码配件不要金属的（过安检麻烦），国内，85元以内", "c": {"category": "数码配件", "excluded": ["金属"], "ship_to": "CN", "cap": 85}},
    {"t": "长途旅行想买个木质收纳小件，寄到欧洲，400元以内", "c": {"category": "旅行装备", "required": ["天然材料"], "ship_to": "EU", "cap": 400}},
    {"t": "桌面想配个竹木底座的数码配件，新加坡寄，150元以内", "c": {"category": "数码配件", "required": ["天然材料"], "ship_to": "SG", "cap": 150}},
    {"t": "家里想要个木质小家具类的家居物件，美国地址，120元以内", "c": {"category": "家居生活", "required": ["天然材料"], "ship_to": "US", "cap": 120}},
    {"t": "数码配件想要不塑料的进阶款，国内，500元以内", "c": {"category": "数码配件", "excluded": ["合成聚合物"], "ship_to": "CN", "cap": 500}},
    {"t": "旅行装备想买个好的，金属材质，寄国内，600元以内", "c": {"category": "旅行装备", "required": ["金属"], "ship_to": "CN", "cap": 600}},
    {"t": "给新家买个像样的陶瓷类家居摆设，新加坡，450元以内", "c": {"category": "家居生活", "required": ["陶瓷"], "ship_to": "SG", "cap": 450}},
    {"t": "户外露营要个靠谱的金属炉具类，日本，700元以内", "c": {"category": "户外运动", "required": ["金属"], "ship_to": "JP", "cap": 700}},
    {"t": "专业摄影想配金属材质的数码配件，欧洲，900元以内", "c": {"category": "数码配件", "required": ["金属"], "ship_to": "EU", "cap": 900}},
    {"t": "母婴想入高端棉麻类用品，国内，400元以内", "c": {"category": "母婴宠物", "required": ["天然纤维"], "ship_to": "CN", "cap": 400}},
    {"t": "厨房想升级不锈钢高端线，美国，1000元以内", "c": {"category": "厨房餐饮", "required": ["金属"], "ship_to": "US", "cap": 1000}},
    {"t": "书房想要纸质类的办公收纳（环保），中国，300元以内", "c": {"category": "办公学习", "required": ["纸"], "ship_to": "CN", "cap": 300}},
    {"t": "美妆想要玻璃高端系列的，国内专柜价500元以内", "c": {"category": "美妆个护", "required": ["玻璃"], "ship_to": "CN", "cap": 500}},
    {"t": "轻量化徒步想入塑料材质户外件，新加坡，80元以内", "c": {"category": "户外运动", "required": ["合成聚合物"], "ship_to": "SG", "cap": 80}},
    {"t": "数码配件整个塑料便携套装，日本寄，60元以内", "c": {"category": "数码配件", "required": ["合成聚合物"], "ship_to": "JP", "cap": 60}},
    {"t": "美妆个护不要陶瓷材质的，国内寄，200元以内", "c": {"category": "美妆个护", "excluded": ["陶瓷"], "ship_to": "CN", "cap": 200}},
    {"t": "宠物水族箱要玻璃的，欧洲寄，100元以内", "c": {"category": "母婴宠物", "required": ["玻璃"], "ship_to": "EU", "cap": 100}},
    {"t": "通勤背包尼龙轻便款，美国，180元以内有货吗", "c": {"category": "旅行装备", "required": ["合成聚合物"], "ship_to": "US", "cap": 180}},
    {"t": "露营灯具要金属机身耐造，中国，280元以内", "c": {"category": "户外运动", "required": ["金属"], "ship_to": "CN", "cap": 280}},
    {"t": "办公椅配件塑料耐磨款，寄到欧洲，70元以内", "c": {"category": "办公学习", "required": ["合成聚合物"], "ship_to": "EU", "cap": 70}},
    {"t": "厨房小件陶瓷餐具入门款，国内，45元以内", "c": {"category": "厨房餐饮", "required": ["陶瓷"], "ship_to": "CN", "cap": 45}},
]


# 备用口语条目：主列表条目因金标 listing 跨 split 占用而无法放置时依次补位，
# 目标仍是口语桶合计 50 例。
_COLLOQUIAL_SPARES: list[dict] = [
    {"t": "做饭想换个棉麻围裙类的厨房用品，寄到日本，120元以内", "c": {"category": "厨房餐饮", "required": ["天然纤维"], "ship_to": "JP", "cap": 120}},
    {"t": "浴室想添个玻璃置物架类的家居物件，美国地址，90元以内", "c": {"category": "家居生活", "required": ["玻璃"], "ship_to": "US", "cap": 90}},
    {"t": "办公桌面想要个陶瓷笔筒类的物件，寄到欧洲，70元以内", "c": {"category": "办公学习", "required": ["陶瓷"], "ship_to": "EU", "cap": 70}},
    {"t": "阳台想摆个陶瓷花盆类的户外小件，国内，60元以内", "c": {"category": "户外运动", "required": ["陶瓷"], "ship_to": "CN", "cap": 60}},
    {"t": "美妆工具想要金属材质的，日本寄，150元以内", "c": {"category": "美妆个护", "required": ["金属"], "ship_to": "JP", "cap": 150}},
    {"t": "奶瓶收纳要玻璃材质的母婴用品，美国寄，80元以内", "c": {"category": "母婴宠物", "required": ["玻璃"], "ship_to": "US", "cap": 80}},
    {"t": "桌面想配个陶瓷底座的数码小件，国内，60元以内", "c": {"category": "数码配件", "required": ["陶瓷"], "ship_to": "CN", "cap": 60}},
    {"t": "旅行分装瓶要玻璃的，新加坡寄，50元以内", "c": {"category": "旅行装备", "required": ["玻璃"], "ship_to": "SG", "cap": 50}},
]


def _validate_colloquial_text(text: str, c: dict) -> list[str]:
    problems = []
    if not any(word in text for word in _CATEGORY_SYNONYMS[c["category"]]):
        problems.append(f"品类词缺失：{c['category']}")
    for material in c.get("required") or []:
        if not any(word in text for word in _MATERIAL_SYNONYMS[material]):
            problems.append(f"材质词缺失：{material}")
    for material in c.get("excluded") or []:
        if not any(word in text for word in _MATERIAL_SYNONYMS[material]):
            problems.append(f"排除材质词缺失：{material}")
    if c.get("ship_to") and not any(word in text for word in _DEST_SYNONYMS[c["ship_to"]]):
        problems.append(f"目的国词缺失：{c['ship_to']}")
    cap = c.get("cap")
    if cap is not None and str(cap) not in text:
        problems.append(f"预算数字缺失：{cap}")
    return problems


def _build_colloquial(builder: RowBuilder, canonicals: dict[str, list[dict]]) -> list[str]:
    problems: list[str] = []
    placed_count = 0
    target = 50
    for item in [*_COLLOQUIAL, *_COLLOQUIAL_SPARES]:
        if placed_count >= target:
            break
        meta = item["c"]
        base = {
            "category": meta["category"],
            "required": meta.get("required", []),
            "excluded": meta.get("excluded", []),
            "ship_to": meta.get("ship_to"),
            "target_currency": "CNY",
        }
        text = item["t"]
        cap = float(meta["cap"])
        text_problems = _validate_colloquial_text(text, meta)
        if text_problems:
            problems.append(f"{text[:24]}… {text_problems}")
            continue
        # 预算校准：口语句保留原句式，仅把预算数字替换为金标 2..5 的就近档位；
        # 代表 listing 冲突时依次退到次近档位
        candidates = _calibrated_caps_near(canonicals, base, preferred=cap)
        if not candidates:
            continue  # 该约束组合的价格层不支持小金标，留给备用条目补位
        # 只保留「代表 listing 可放置」的档位，取最近的一个
        placeable = [
            calibrated for calibrated in candidates
            if builder.can_place(_gold(canonicals, {**base, "price_cap_cny": calibrated}))
        ]
        if not placeable:
            continue  # 该条目的约束组合已无可用金标，留给备用条目补位
        placed = False
        for calibrated in placeable[:6]:
            candidate_text = text
            if int(calibrated) != int(cap):
                candidate_text = text.replace(str(int(cap)), str(int(calibrated)))
            c = {**base, "price_cap_cny": calibrated}
            row = builder.add(
                "colloquial", candidate_text, c,
                "口语查询（人工撰写，预算经目录校准）：" + "×".join(filter(None, [meta["category"], "≥".join(meta.get("required", [])) or "≠" + "+".join(meta.get("excluded", [])), meta.get("ship_to", ""), str(int(calibrated))])),
                provenance="human-authored-colloquial-v1（Smartlect 评测重建，未经外部人工复核）",
            )
            if row is not None:
                placed = True
                break
        if not placed:
            continue
        placed_count += 1
    if placed_count < target:
        problems.append(f"口语桶仅放置 {placed_count}/{target} 例，主列表与备用池均已耗尽")
    return problems


def _build_negatives(builder: RowBuilder, cells: dict[tuple[str, str], list[str]], canonicals: dict[str, list[dict]]) -> None:
    """负例只接受能被 spec 级硬约束证明不可满足的组合，显式全枚举后按配额取用。"""
    category_materials: dict[str, set[str]] = defaultdict(set)
    for category, material in cells:
        category_materials[category].add(material)

    budget: list[tuple[str, dict, str]] = []
    for cell in sorted(cells):
        category, material = cell
        for dest in DESTINATIONS:
            c = {"category": category, "required": [material], "ship_to": dest, "target_currency": "CNY"}
            base = _gold(canonicals, c)
            if not base:
                continue
            min_price = min(_first_stock_price_cny(l) for _, ls in base for l in ls)
            cap = max(1.0, round(min_price - 2.0))
            c["price_cap_cny"] = cap
            if _gold(canonicals, c):
                continue
            slot = len(budget)
            template = _BUDGET_NEGATIVE_TEMPLATES[slot % len(_BUDGET_NEGATIVE_TEMPLATES)]
            query = template.format(cap=f"{cap:g}", unit="元", dest_clause=_dest_clause(dest), mat_clause=f"{material}材质的{category}").replace("，。", "。")
            budget.append((query, {**c, "expected_empty": True}, f"负例-预算不足：{category}×{material}×{dest} 最低价 {min_price:.0f} > 预算 {cap:g}"))

    excluded_all: list[tuple[str, dict, str]] = []
    for category in sorted(category_materials):
        excluded = sorted(category_materials[category])
        for dest in [None, "CN", "US", "JP", "SG", "EU"]:
            c = {"category": category, "excluded": excluded, "ship_to": dest, "target_currency": "CNY"}
            if _gold(canonicals, c):
                continue
            slot = len(excluded_all)
            template = _EXCLUDED_ALL_TEMPLATES[slot % len(_EXCLUDED_ALL_TEMPLATES)]
            query = template.format(cat=category, mats="、".join(excluded))
            if dest:
                query = query.rstrip("？。") + f"，{_dest_clause(dest)}，有吗？"
            excluded_all.append((query, {**c, "expected_empty": True}, f"负例-排除全部材质：{category} 排除 {'+'.join(excluded)}" + (f"×{dest}" if dest else "")))

    contradictory: list[tuple[str, dict, str]] = []
    for cell in sorted(cells):
        category, material = cell
        c = {"category": category, "required": [material], "excluded": [material], "ship_to": None, "target_currency": "CNY"}
        if _gold(canonicals, c):
            continue
        slot = len(contradictory)
        template = _CONTRADICTORY_TEMPLATES[slot % len(_CONTRADICTORY_TEMPLATES)]
        contradictory.append((template.format(cat=category, mat=material), {**c, "expected_empty": True}, f"负例-矛盾约束：要求且排除 {material}"))

    unreachable: list[tuple[str, dict, str]] = []
    for cell in sorted(cells):
        category, material = cell
        for dest in DESTINATIONS:
            c = {"category": category, "required": [material], "ship_to": dest, "target_currency": "CNY"}
            if _gold(canonicals, c):
                continue
            slot = len(unreachable)
            template = _UNREACHABLE_TEMPLATES[slot % len(_UNREACHABLE_TEMPLATES)]
            unreachable.append((template.format(cat=category, mat=material, dest_clause=_dest_clause(dest)), {**c, "expected_empty": True}, f"负例-目的国不可达：{category}×{material} 无可送达 {dest} 的款"))

    quotas = {"unreachable": min(22, len(unreachable)), "excluded_all": min(16, len(excluded_all)),
              "contradictory": min(16, len(contradictory))}
    quotas["budget"] = min(80 - sum(quotas.values()), len(budget))
    emitted_total = sum(quotas.values())
    pools = {"budget": budget, "excluded_all": excluded_all, "contradictory": contradictory, "unreachable": unreachable}
    order = ["unreachable", "excluded_all", "contradictory", "budget"]
    for kind in order:
        for query, c, note in pools[kind][:quotas[kind]]:
            builder.add("empty", query, c, note)
    if emitted_total < 80:  # 某子类不足时由 budget 池兜底补足
        for query, c, note in budget[quotas["budget"]:quotas["budget"] + (80 - emitted_total)]:
            builder.add("empty", query, c, note)


def _self_check(rows: list[dict], canonicals: dict[str, list[dict]]) -> list[str]:
    problems: list[str] = []
    expected_buckets = {"literal": 30, "semantic": 60, "composite": 80, "colloquial": 50, "empty": 80}
    buckets: dict[str, int] = defaultdict(int)
    for row in rows:
        buckets[row["kind"]] += 1
    if dict(buckets) != expected_buckets:
        problems.append(f"桶配比异常：{dict(buckets)} != {expected_buckets}")
    splits = defaultdict(int)
    for row in rows:
        splits[row["split"]] += 1
    if dict(splits) != {"dev": 210, "release": 90}:
        problems.append(f"split 异常：{dict(splits)}")
    # 维度双覆盖（与 eval_quality 同口径）
    for dimension, key in (("category", "category"), ("target_currency", "target_currency"), ("ship_to", "ship_to")):
        coverage: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            coverage[str(row.get(key) or "ALL")].add(row["split"])
        for value, found in sorted(coverage.items()):
            if found != {"dev", "release"}:
                problems.append(f"维度 {dimension}={value} 未双覆盖：{sorted(found)}")
    # 金标与负例复检（USD 行把价格上限换回 CNY 再比对）
    for row in rows:
        if row["kind"] == "literal":
            continue
        cap_major = row["constraints"].get("price_max_major")
        cap_cny = row["constraints"].get("price_max_cny")
        if cap_cny is None and cap_major is not None:
            cap_cny = cap_major * _RATES[row["target_currency"]]
        floor_major = row["constraints"].get("price_min_major")
        floor_cny = row["constraints"].get("price_min_cny")
        if floor_cny is None and floor_major is not None:
            floor_cny = floor_major * _RATES[row["target_currency"]]
        c = {
            "category": row["category"], "required": row["required_material_tags"],
            "excluded": row["excluded_material_tags"], "ship_to": row.get("ship_to"),
            "price_cap_cny": cap_cny, "price_floor_cny": floor_cny,
        }
        if row["kind"] != "empty":
            gold = {cid for cid, _ in _gold(canonicals, c)}
            if gold != set(row["relevant_canonical_ids"]):
                problems.append(f"{row['id']} 金标复检不一致：复算 {sorted(gold)} vs 声明 {row['relevant_canonical_ids']}（cap_cny={cap_cny} floor_cny={floor_cny}）")
        # 查询唯一性与 product_id 级跨 split 泄漏（与 eval_quality 同口径）
    if len({row["query"] for row in rows}) != len(rows):
        problems.append("存在重复 query")
    pid_splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        for pid in row.get("relevant") or []:
            pid_splits[pid].add(row["split"])
    leaked = sorted(pid for pid, splits in pid_splits.items() if len(splits) > 1)
    if leaked:
        problems.append(f"商品金标跨 split 泄漏：{leaked[:5]}")
    return problems


def _fix_dimension_coverage(rows: list[dict]) -> None:
    """split 顺序生成的副作用是某维度值可能只落在一个 split；通过成对翻转修正。

    翻转规则：把「缺 release 的值」的一行 dev→release，同时把一个双覆盖值
    的行 release→dev，保持全局 70/30 不变。仅在同桶内翻转，桶内覆盖不回退。
    """
    dimensions = (("category", "category"), ("target_currency", "target_currency"), ("ship_to", "ship_to"))

    def coverage() -> dict[tuple[str, str], set[str]]:
        found: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in rows:
            for _, key in dimensions:
                found[(key, str(row.get(key) or "ALL"))].add(row["split"])
        return found

    for _ in range(200):
        cov = coverage()
        missing = [(dim, val) for (dim, val), splits in sorted(cov.items()) if splits != {"dev", "release"}]
        if not missing:
            return
        key, value = missing[0]
        need = "release" if cov[(key, value)] == {"dev"} else "dev"
        give = "dev" if need == "release" else "release"
        # 找一行：值为 value、split=give、且翻转后其桶内该值仍有 give 侧代表
        def flip_safe(row: dict, target: str) -> bool:
            # 翻转到 target 后不泄漏：行内每个 pid 在「target 侧」和「当前侧」
            # 都不得出现在其他行——否则翻转后 pid 同时落在两个 split。
            pids = set(row.get("relevant") or [])
            return not any(
                o is not row and o["split"] in {target, row["split"]} and pids & set(o.get("relevant") or [])
                for o in rows
            )

        donor = next((r for r in rows
                      if str(r.get(key) or "ALL") == value and r["split"] == give
                      and flip_safe(r, need)
                      and sum(1 for o in rows if o["kind"] == r["kind"] and str(o.get(key) or "ALL") == value and o["split"] == give) >= 2), None)
        if donor is None:
            return  # 无法继续修复，交给自检如实报告
        donor["split"] = need
        # 配平：找一个双覆盖值的 give 侧行翻回（不能是刚翻转的行）
        compensator = next((r for r in rows
                            if r is not donor and r["split"] == need
                            and not (set(r.get("relevant") or []) & set(donor.get("relevant") or []))
                            and str(r.get(key) or "ALL") != value
                            and cov[(key, str(r.get(key) or "ALL"))] == {"dev", "release"}
                            and flip_safe(r, give)
                            and sum(1 for o in rows if o["kind"] == r["kind"] and str(o.get(key) or "ALL") == str(r.get(key) or "ALL") and o["split"] == need) >= 2), None)
        if compensator is None:
            donor["split"] = give  # 无法配平则回滚
            return
        compensator["split"] = give


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="生成商品检索正式评测集（300 例）")
    parser.add_argument("--output", type=Path, default=DATASET_PATH)
    parser.add_argument("--check-only", action="store_true", help="只跑自检不写文件")
    args = parser.parse_args(argv)

    canonicals = _load_canonicals()
    cells = _cell_index(canonicals)
    builder = RowBuilder(canonicals)
    _build_literal(builder, canonicals, 30)
    # 口语桶（人工撰写）优先占位：模板桶有窗口偏移重试，能绕开已占用的金标
    colloquial_problems = _build_colloquial(builder, canonicals)
    _build_semantic(builder, cells, canonicals, 60)
    _build_composite(builder, cells, canonicals, 80)
    _build_negatives(builder, cells, canonicals)

    rows = builder.rows
    _fix_dimension_coverage(rows)
    problems = colloquial_problems + _self_check(rows, canonicals)
    for problem in problems:
        print(f"[problem] {problem}")
    if args.check_only:
        print(f"共 {len(rows)} 例；问题 {len(problems)} 项")
        return
    if problems:
        print("存在问题，拒绝写出数据集；先修复再生成。", file=sys.stderr)
        raise SystemExit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    from scripts.eval.dataset_fingerprint import write_fingerprint
    sidecar = write_fingerprint(args.output, CATALOG_PATH, generator="scripts/build_eval_retrieval.py")
    print(f"已写出 {len(rows)} 例 → {args.output}")
    print(f"指纹 sidecar → {sidecar}")


if __name__ == "__main__":
    main()
