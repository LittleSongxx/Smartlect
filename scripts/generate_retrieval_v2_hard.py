# -*- coding: utf-8 -*-
"""派生 v2-hard 检索评测集：去掉查询中的品牌系列前缀，金标继承 v2 冻结标注。

难度设计（通用机制，非逐题改写）：
- v2 正例查询全部带"在 Roamix 系列中"品牌提示，且目录 500/1000 件与该品牌
  同品类——品牌词把候选空间收窄到一半目录，送分明显；
- v2-hard 仅剥掉该前缀，查询语义、split、kind、金标全部不变。非 Roamix 的
  500 件同品类商品开始作为真实干扰项参与竞争；
- 金标不按去品牌后的检索结果重标（与 v2 生成声明同准则），非金标命中一律
  计为漏报——方向是压分而非抬分。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "eval/v2/product_retrieval.jsonl"
TARGET = ROOT / "eval/v2-hard/product_retrieval.jsonl"
_PREFIX = re.compile(r"^在\s*Roamix\s*系列中[，,]\s*")


def main() -> None:
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    out, stripped = [], 0
    for row in rows:
        query = row["query"]
        query = _PREFIX.sub("", query)
        if query != row["query"]:
            stripped += 1
        out.append({**row, "query": query})
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in out), encoding="utf-8")
    print(f"派生 {len(out)} 条（去品牌前缀 {stripped} 条）→ {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
