# -*- coding: utf-8 -*-
"""商品展示媒体：仅映射已生成的示意资源，不推断真实平台商品照片。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ProductMedia:
    image_url: str | None
    image_kind: Literal["illustration", "placeholder"]
    image_alt: str
    # 目录系列键（GX-xx 的两位序号）：前端据此绘制产品级线稿占位。
    # 仍是 placeholder 语义——线稿是抽象示意，不是实拍，也不还原颜色材质尺寸。
    illustration: str | None = None


# 这些资源由前端静态目录托管，图像来源与使用边界见 products/README.md。
# 映射在商品层，不代表某个 SKU 的实际颜色、材质或尺寸。
_ILLUSTRATION_FILES = {
    "P1003": "wanderlite.png",
    "P1018": "drypack.png",
    "P1049": "budgetpack.png",
}


# 合成目录的商品系列编号（GX-01 … GX-32）；不是按商品名猜形，而是目录自带的分组。
_ILLUSTRATION_SERIES = frozenset(f"{index:02d}" for index in range(1, 33))
_SERIES = re.compile(r"\bGX-(\d{2})(?:-|\b)")


def product_media(product_id: str, title: str) -> ProductMedia:
    filename = _ILLUSTRATION_FILES.get(product_id)
    if filename is not None:
        return ProductMedia(
            f"/products/{filename}", "illustration", f"{title}：AI 生成示意图，非商品实拍",
        )
    match = _SERIES.search(title)
    illustration = match.group(1) if match and match.group(1) in _ILLUSTRATION_SERIES else None
    return ProductMedia(None, "placeholder", f"{title}：暂无商品图片", illustration)
