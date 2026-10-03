# -*- coding: utf-8 -*-
"""数据集与运行时目录的指纹绑定。

背景：正式评测集的金标是对着某一版商品目录标注的。目录演进（扩容、改价、
上下架）可能静默击穿负例或让金标失效，把"标注漂移"误判成"检索退化"。
生成器在产出数据集时写入 sidecar 指纹；评测 runner 启动时比对运行时目录
的 SHA-256，不一致即拒绝开跑——数据集与目录必须同版本进、同版本出。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 数据集 → 其金标所依据的目录文件。
DATASET_CATALOGS: dict[str, str] = {
    "eval/v1/product_retrieval.jsonl": "data/catalog-v3.jsonl",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sidecar_path(dataset: Path) -> Path:
    return dataset.with_suffix(".fingerprint.json")


def write_fingerprint(dataset: Path, catalog: Path, *, generator: str) -> Path:
    """生成器专用：把数据集与目录指纹写入 sidecar。"""
    def display(path: Path) -> str:
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:  # 临时目录等工程外路径（测试夹具）
            return str(path)

    payload = {
        "schema_version": 1,
        "dataset": display(dataset),
        "dataset_sha256": sha256_file(dataset),
        "catalog": display(catalog),
        "catalog_sha256": sha256_file(catalog),
        "generator": generator,
    }
    path = sidecar_path(dataset)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def check_dataset_fingerprint(dataset: Path, *, catalog_override: Path | None = None) -> list[str]:
    """runner 专用预检：返回问题列表；空列表表示数据集与运行时目录同版本。

    没有 sidecar 的旧数据集不阻断（兼容诊断集），但正式门禁集必须携带。
    """
    problems: list[str] = []
    path = sidecar_path(dataset)
    if not path.is_file():
        return [f"数据集缺少指纹 sidecar：{path.name}（正式门禁集必须由生成器产出）"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        return [f"指纹 sidecar 不可读：{err}"]
    declared_catalog = Path(payload.get("catalog", ""))
    catalog = catalog_override or (declared_catalog if declared_catalog.is_absolute() else PROJECT_ROOT / declared_catalog)
    if not catalog.is_file():
        problems.append(f"指纹声明的目录不存在：{payload.get('catalog')}")
        return problems
    actual = sha256_file(catalog)
    if actual != payload.get("catalog_sha256"):
        problems.append(
            f"运行时目录 {payload.get('catalog')} 与数据集标注版本不一致"
            f"（期望 {str(payload.get('catalog_sha256'))[:16]}…，实际 {actual[:16]}…）；"
            "请用生成器对当前目录重标，不能把标注漂移当检索退化"
        )
    dataset_sha = sha256_file(dataset)
    if dataset_sha != payload.get("dataset_sha256"):
        problems.append("数据集内容与指纹 sidecar 不一致：数据集被手工改动或 sidecar 过期")
    return problems
