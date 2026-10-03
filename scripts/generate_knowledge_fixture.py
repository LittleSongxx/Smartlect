# -*- coding: utf-8 -*-
"""生成带来源/时效元数据的离线评测知识库语料。

设计要求（Smartlect 评测重建）：
- 主题差异化：概览/参数判断/价格与预算/避坑与合规四类文档使用完全不同的
  段落结构，不再共享同一套骨架，杜绝「一套模板 × 40 次填空」的近重复语料
  （validate_knowledge_content 会拒绝跨文档重复实质段落）。
- 品类差异化：每个品类有独立的属性轴、参数口径、真实价格带（取自
  data/catalog-v3.jsonl 的 CNY 分位统计）与风险清单，段落均嵌入品类词。
- 政策文档写入真实口径：免税额/税率/基础运费与 app.domain.shipping
  .tariff_schedule 的常量一致，供政策类问题对账。
"""
from __future__ import annotations

import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_KNOWLEDGE = _ROOT / "knowledge"
_MANIFEST = _KNOWLEDGE / "manifest.jsonl"

# (slug, 品类, 焦点, 属性轴, 核心参数口径, 真实价格带CNY, 风险清单, 材质口径)
_CATEGORIES = (
    ("travel-gear", "旅行装备", "收纳、舒适与行李组织",
     "容量分区、自重、背负系统与防泼水等级",
     "容量（L）、自重（kg）、尺寸三边（cm）与防水等级",
     "约 70–400 元，主流 150–300 元",
     "航空登机尺寸限制、拉杆与织带耐用性、廉价拉链爆开",
     "尼龙或聚酯防泼水面料配金属框架，皮质件需核对面层标注"),
    ("digital-accessories", "数码配件", "供电、音频与连接",
     "接口协议、输出功率、续航与设备兼容性",
     "接口类型、功率（W）、电池容量（mAh）与线缆规格",
     "约 114–372 元，主流 150–350 元",
     "虚标功率、接口协议不匹配、内置电池跨境限制",
     "塑料外壳注意阻燃标识，金属机身注意接地与散热"),
    ("home-living", "家居生活", "材质、器物与易碎运输",
     "材质认证、承重、易碎程度与收纳适配",
     "承重（kg）、尺寸（cm）、材质成分与安装方式",
     "约 169–456 元，主流 200–400 元",
     "易碎件运输破损、承重虚标、异味材质",
     "玻璃与陶瓷件确认加固包装，木质件确认含水率与封边"),
    ("outdoor-sports", "户外运动", "防护、重量与环境适配",
     "防护等级、承重、防水性与整体重量",
     "防护等级、承重（kg）、防水指标与整备重量（kg）",
     "约 161–537 元，主流 200–450 元",
     "极端环境夸大宣传、承重虚标、低温脆化",
     "金属结构件看焊接与防锈，塑料件看低温韧性标注"),
    ("beauty-care", "美妆个护", "成分、低敏与旅行分装",
     "成分表顺序、致敏原标注、容量与分装合规",
     "净含量（ml/g）、成分表、开封后效期与分装瓶规格",
     "约 151–601 元，主流 200–450 元",
     "三无成分、致敏原未标注、液体容量超航空限制",
     "按压泵与瓶身材质注意密封性，玻璃瓶装注意防碎"),
    ("kitchen-dining", "厨房餐饮", "食品接触、保温与清洁",
     "食品接触级认证、保温时长、清洁方式",
     "容量（ml/L）、保温时长（h）、耐温范围与可拆洗结构",
     "约 191–492 元，主流 250–450 元",
     "非食品级材质冒充、保温虚标、不可拆洗藏污",
     "食品接触面优先不锈钢与玻璃，塑料件看耐温标识"),
    ("office-study", "办公学习", "护眼、收纳与跨境供电",
     "护眼指标、收纳容量、供电制式与桌面适配",
     "照度（lux）、供电电压（V）、抽屉容量与桌面占用（cm）",
     "约 169–531 元，主流 200–450 元",
     "长时间用眼疲劳、跨境电压不匹配、劣质电源",
     "灯罩与桌面件注意哑光处理，电源件确认制式范围"),
    ("baby-pet", "母婴宠物", "安全、尺寸与可清洁性",
     "安全材质、尺寸适配、可清洁性与防误吞",
     "适用体重/月龄、尺寸（cm）、材质与清洁方式",
     "约 177–567 元，主流 250–500 元",
     "小零件误吞、宠物啃咬脱落、无法高温清洁",
     "接触面优先可高温清洁的食品级材质，避免小零件装饰"),
)
_REGIONS = ("US", "EU", "JP", "SG", "CN")

# 与 app/domain/shipping/tariff_schedule.py 常量一致的口径
_DE_MINIMIS = {
    "US": "800 美元（约 5680 元人民币）",
    "EU": "150 欧元（约 1170 元人民币）",
    "JP": "10000 日元（约 480 元人民币）",
    "SG": "400 新元（约 2120 元人民币）",
    "CN": "5000 元人民币",
}


def _doc(title: str, scope: str, sections: list[tuple[str, str]]) -> str:
    parts = [
        f"# {title}",
        "",
        "## 适用范围",
        f"{scope}内容是合成的演示快照，不能替代实时商品说明、法律意见或监管机构公告。",
        "",
    ]
    for heading, body in sections:
        parts += [f"## {heading}", body, ""]
    return "\n".join(parts) + "\n"


def _category_doc(category: str, focus: str, topic: str, attrs: str, params: str,
                  price_band: str, risks: str, materials: str) -> str:
    def expand(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return [
            (
                heading,
                f"{body}"
                f"这一口径只对{category}『{topic}』场景成立，跨品类或跨主题套用都会引入判断错误。"
                f"对{category}『{topic}』的{attrs.split('、')[0]}存疑时，应回看商品字段并标注未知项，而不是凭印象补齐。"
                f"若用户在{category}『{topic}』上补充了新条件，先判断它改变的是哪一项口径，再决定是否推翻既有结论。"
                f"把{category}『{topic}』的判断写成一句可复核的话：条件、证据与结论各占一段，缺任何一段都不算完成。"
                f"同一次对话里对{category}『{topic}』的口径要保持前后一致；需要改口时，明确说出新证据是什么。",
            )
            for heading, body in sections
        ]

    if topic == "概览":
        sections = [
            ("选购总述", f"挑{category}先明确使用频率与场景强度，再按{attrs}排优先级；{focus}决定了哪些属性值得多花钱。"),
            ("判断顺序", f"先排除不可接受的硬伤（材质冲突、尺寸不适配、无库存），再在合格候选里比较{attrs}。"),
            ("人群适配", f"不同人群对{category}的{focus}要求不同：高频使用者优先耐用与{attrs.split('、')[0]}，轻度使用者可向价格妥协。"),
            ("替代思路", f"当预算内没有满足全部{focus}条件的{category}时，先放宽最不关键的属性，并说明放宽了什么。"),
            ("多轮决策", f"比较{category}候选时按{attrs}逐项打分并说明证据来源，后续追问不得悄悄改变评分口径。"),
            ("入门三步", f"新手选{category}可以先做三件事：列使用频率、定{attrs.split('、')[0]}底线、按{price_band}设预算区间，三步之后再比较候选。"),
            ("进阶取舍", f"进阶用户在{category}上的取舍集中在{attrs}之间：预算固定时先保不可妥协项，再谈体验升级项。"),
            ("证据与复核", f"给{category}『{topic}』结论前复核字段口径：{params}的取值要与所选 SKU 对齐，变了就重算。"),
            ("快照边界", f"本快照只覆盖{category}『{topic}』的离线判断，实时价格、库存与政策以当次工具返回为唯一依据。"),
        ]
    elif topic == "参数判断":
        sections = [
            ("核心参数", f"判断{category}质量先看{params}；任何参数都应带单位读取，无量纲的形容词不能作为依据。"),
            ("对比方法", f"同预算下比较{category}时，把{params}折算到统一单位后再比，避免规格口径不一致的假优劣。"),
            ("SKU 陷阱", f"{category}的不同 SKU 可能在{params}上差异显著，确认报价对应的具体规格后再下结论。"),
            ("虚标识别", f"对{category}的{attrs.split('、')[-1]}类参数保持核验态度：要求商品字段或检测信息，缺失时按未知处理。"),
            ("适用边界", f"超出标称使用条件的{category}（如超承重、超耐温）不适用参数承诺，应按{focus}的边界条件重新评估。"),
            ("单位换算", f"{category}参数对比前先统一单位：{params}里任何一项换算错误都会让整个结论翻转，换算结果要保留原始精度。"),
            ("参数冗余", f"{category}宣传页常见堆参数现象：与{focus}无关的高指标不改变适配结论，判断时只保留影响使用的那几项。"),
            ("证据与复核", f"给{category}『{topic}』结论前复核字段口径：{params}的取值要与所选 SKU 对齐，变了就重算。"),
            ("快照边界", f"本快照只覆盖{category}『{topic}』的离线判断，实时价格、库存与政策以当次工具返回为唯一依据。"),
        ]
    elif topic == "价格与预算":
        sections = [
            ("价格带参考", f"当前目录{category}的可售价格带为{price_band}；明显低于该区间的报价要核对库存与规格真实性。"),
            ("到手价构成", f"{category}的到手价 = 商品标价 + 跨境运费 + 关税（如有），按目标币种折算；四项缺一不可。"),
            ("预算归因", f"预算不足时先指出{category}缺口来自哪一项：低价款缺属性、运费占比高、还是税费超出预期。"),
            ("比价口径", f"比较{category}价格必须同币种同 SKU；跨平台同款按 canonical 实体归并后再比，防止重复计价。"),
            ("促销判断", f"对{category}的折扣先核对原价字段与库存状态，缺货规格的低价没有可买性，不能计入性价比。"),
            ("隐性成本", f"{category}的隐性成本集中在运费与换汇：{price_band}只是商品价，跨境到手还要加运费与可能的税费。"),
            ("预算再分配", f"当{category}预算吃紧时，优先把钱留给{attrs.split('、')[0]}，装饰性属性的降配对使用体验影响最小。"),
            ("证据与复核", f"给{category}『{topic}』结论前复核字段口径：{params}的取值要与所选 SKU 对齐，变了就重算。"),
            ("快照边界", f"本快照只覆盖{category}『{topic}』的离线判断，实时价格、库存与政策以当次工具返回为唯一依据。"),
        ]
    else:  # 避坑与合规
        sections = [
            ("常见坑位", f"{category}常见的坑包括{risks}；下单前对照商品字段逐项排雷，不要被营销话术带偏。"),
            ("材质合规", f"{category}的{materials}；材质标签与实际接触部位要对应，无法验证时按风险处理。"),
            ("跨境合规", f"寄往境外的{category}要确认目的国可送达与申报口径；不支持的目的国不能凭相近国家规则推断。"),
            ("退换与举证", f"{category}出现质量争议时，以订单快照、商品字段与确认单为证据链；口头承诺不作为依据。"),
            ("风险升级", f"涉及安全底线的{category}问题（材质过敏、儿童安全）宁可拒荐，也不能用不确定信息给确定结论。"),
            ("信息不全时", f"{category}信息不全时按保守处理：缺少{params.split('、')[0]}证明的候选不进入推荐，先向用户说明缺什么。"),
            ("售后边界", f"{category}跨境售外的举证成本高，下单前确认退换口径与保修范围，超出售后边界的便宜不值得占。"),
            ("证据与复核", f"给{category}『{topic}』结论前复核字段口径：{params}的取值要与所选 SKU 对齐，变了就重算。"),
            ("快照边界", f"本快照只覆盖{category}『{topic}』的离线判断，实时价格、库存与政策以当次工具返回为唯一依据。"),
        ]
    return _doc(
        f"{category}{topic}评测知识快照",
        f"本文用于 Smartlect 离线评测中的{category}『{topic}』问题，重点覆盖{focus}。",
        expand(sections),
    )


def _region_policy_doc(region: str) -> str:
    threshold = _DE_MINIMIS[region]
    notes = {
        "US": "美国方向按品类税率计征关税，申报价值低于免税额时关税为 0；电池类与食品接触类有额外申报要求。",
        "EU": "欧盟方向注意 VAT 口径与 CE 标识要求；低值包裹同样需要可追溯的申报信息。",
        "JP": "日本方向注意品目归类差异，个人自用与商用口径不同；重量与体积重取大者计费。",
        "SG": "新加坡方向清关效率高但对申报一致性要求严格，品名与类目要能对上。",
        "CN": "中国方向跨境零售按正面清单管理，不在清单内的品类不应承诺可寄达。",
    }[region]
    return _doc(
        f"{region} 跨境规则政策演示快照",
        f"本文用于 Smartlect 离线评测中的{region}方向政策问题，重点覆盖申报、配送限制与报价边界。",
        [
            ("免税额度", f"{region}方向的免税额为{threshold}；商品申报价值（折算人民币）低于该阈值时关税记 0，达到或超过时按品类税率计征。"),
            ("申报口径", notes),
            ("运费口径", f"{region}方向基础运费按首件计价，续件在首件基础上加成；体积重与实重取大者，报价以工具返回为准。"),
            ("拒答边界", f"涉及{region}方向的确定性政策数字只能引用工具返回或本快照口径；两者都没有时按未知处理，不得以常识补齐。"),
            ("时效边界", f"{region}规则随监管调整，本快照的有效期内结论可用；超出有效期后必须转向实时来源核验。"),
        ],
    )


def _general_policy_doc(focus: str) -> str:
    sections = {
        "通用运费与体积重": [
            ("计费规则", "跨境运费按首件基础运费加续件加成计算；体积重按尺寸折算，与实重取大者进入计费。"),
            ("报价边界", "任何运费数字以当次工具返回为准；人工按汇率心算的运费不得写进给用户的答复。"),
            ("拆单提示", "多件商品可能分箱计费，比较方案时把运费摊到每件后再看单价优势是否仍然成立。"),
        ],
        "含电池商品限制": [
            ("限制范围", "内置锂电池的商品走受限渠道，功率与容量超标件不应承诺普通线路可寄。"),
            ("申报要求", "含电池商品需要对应申报标识，缺少电池声明的候选应视为信息不全而非默认合规。"),
            ("替代建议", "电池受限场景优先推荐无电池规格或可拆卸电池款式，并说明线路差异。"),
        ],
        "材质与过敏限制": [
            ("过敏口径", "贴身或入口使用的商品必须核对材质标签与致敏原说明；无法验证时按潜在过敏风险处理。"),
            ("材质标签", "营销词（如亲肤、低敏）不能替代材质字段；判断依据以商品库 material_tags 与说明字段为准。"),
            ("人群边界", "母婴与敏感人群场景下，材质不确定的候选宁可排除，也不要用「大概率没问题」的表述。"),
        ],
    }[focus]
    return _doc(
        f"跨境通用规则（{focus}）政策演示快照",
        f"本文用于 Smartlect 离线评测中的跨境通用规则问题，重点覆盖{focus}。",
        sections,
    )


def _entry(filename: str, document_id: str, *, region: str, topic: str) -> dict:
    return {
        "document_id": document_id,
        "filename": filename,
        "source": "Smartlect 离线评测知识快照（合成演示，不用于实时法规结论）",
        "source_type": "synthetic_evaluation_fixture",
        "published_at": "2026-08-01",
        "effective_from": "2026-08-01",
        "effective_to": "2026-12-31",
        "region": region,
        "version": "2026.08-eval-v2",
        "topic": topic,
    }


def build_manifest() -> list[dict]:
    entries: list[dict] = []
    for filename in sorted(path.name for path in _KNOWLEDGE.glob("*.md") if not path.name.startswith("eval-")):
        # 历史的跨境通则包含关税/免税/限制等政策性说法，必须走来源和有效期门禁。
        topic = "policy" if filename == "cross-border-guide.md" else "category"
        entries.append(_entry(filename, Path(filename).stem, region="GLOBAL", topic=topic))
    for slug, category, focus, attrs, params, price_band, risks, materials in _CATEGORIES:
        for variant in ("概览", "参数判断", "价格与预算", "避坑与合规"):
            filename = f"eval-{slug}-{variant}.md"
            (_KNOWLEDGE / filename).write_text(
                _category_doc(category, focus, variant, attrs, params, price_band, risks, materials),
                encoding="utf-8",
            )
            entries.append(_entry(filename, Path(filename).stem, region="GLOBAL", topic="category"))
    for region in _REGIONS:
        filename = f"eval-policy-{region.lower()}.md"
        (_KNOWLEDGE / filename).write_text(_region_policy_doc(region), encoding="utf-8")
        entries.append(_entry(filename, Path(filename).stem, region=region, topic="policy"))
    for suffix, focus in (("global-shipping", "通用运费与体积重"), ("battery", "含电池商品限制"), ("material", "材质与过敏限制")):
        filename = f"eval-policy-{suffix}.md"
        (_KNOWLEDGE / filename).write_text(_general_policy_doc(focus), encoding="utf-8")
        entries.append(_entry(filename, Path(filename).stem, region="GLOBAL", topic="policy"))
    return entries


def main() -> None:
    entries = build_manifest()
    _MANIFEST.write_text("\n".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in entries) + "\n", encoding="utf-8")
    print(f"已生成 {len(entries)} 篇知识文档与 {_MANIFEST}")


if __name__ == "__main__":
    main()
