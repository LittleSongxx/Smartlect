# ADR 0004：导购检索可观测性与交易意图编译

日期：2026-09-12。状态：部分采用（代码级机制采用；提示层纪律包因 12k 窗口零余量暂缓，待窗口决策）。
依据：quality-v2 v7 官方 run（39 题 × 3 试验，零翻转）四个确定性失败的共同根因分析
（`artifacts/quality-v2/official-v7-20260912`，验证 run `fixverify*-20260912`）。

## 问题

v7 的四个稳定失败（shop-d-19/26/33/34）暴露三个类级根因：

1. **空集观察无归因**。`ShoppingRetrieve._finish` 早已算出逐约束淘汰计数
   （`initial_filtered`：`not_on_sale`/`stock_unavailable`/`price_constraint`/`term_constraint`），
   但 `saved_payload` 只转发三个诊断键。模型看到"hard_constraint_unsatisfied"却不知道是库存、
   价格还是词表淘汰了候选，只能逐个删参数盲扫（shop-d-26 七连检索后撞上下文窗口）。
2. **购买数量不是会话槽**。`quantity` 只活在单次工具参数里：模型去掉它重查即可绕开库存门，
   再以 `buyCount=4` 提案满足"买 6 个"的用户（v7 shop-d-26 实录）。提案路径没有
   ADR-0002 式的"模型声明、系统编译"——`compile_decision` 只编译答/转，不编译交易意图。
3. **召回与资格门混淆**。browse 空关键词回补要求 `not hard`（shopping_retrieve 旧 181 行），
   而预算进 mission 即 hard——"100元以内有什么"因此零召回（shop-d-33）。本设计中所有硬约束
   都是快照后可过滤谓词；旧代码自己就为 required_terms（188 行重试）与 category（184 行）
   开了空关键词召回，预算是唯一没被覆盖的硬槽，属不对称而非原则。

## 决定（已实施）

1. **空集归因进入模型观察**：`saved_payload` 在结果为空时转发
   `{eligible_skus, initial_filtered, final_filtered, recall_relaxed}`（`filter_report`），
   `sku_observation` 透传。**仅在空集时转发**：非空结果本来自明，而 12k 有界窗口没有
   逐观察余量（见下）。
2. **quantity 升为 mission 槽**：`extract_mission` 从购买帧（买/购买/要/来 + 数量 + 量词，
   阿拉伯与简单中文数字）抽取；合并语义与预算一致（工具参数 > 本轮抽取 > 已存槽，后说替换）；
   `apply_mission_to_request` 在请求未声明时回填；`ground_tool_params` 溯源——模型给的数量
   必须等于本轮抽取或已存 mission，否则丢弃并由 mission 回填（静默调小数量绕空集的门从此关死）。
3. **提案意图披露编译（ADR-0002 补齐到交易路径）**：`proposal_intent_note` 比对提案
   `orderList` 总件数与 mission 数量，不一致时由控制器把差额说明**强制**拼进两条收口路径
   （`attach_proposal_confirmation` 与 `close_degraded_turn`），模型无法省略；审计存
   `context['proposal_intent_note']`。部分满足仍合法，但不再是静默改单。
4. **召回放宽**：关键词召回为空且无 product_id/category 时，允许空关键词召回 + 资格门全量
   后置过滤（`recall_relaxed` 诊断标记，`popular_used` 恒 false）。`hard` 只决定
   `empty_reason` 语义，不再阻断召回。策略版本升至 `shopping-constraint-v2`。
   大目录注意：`searchOnSale` 无服务端价格过滤，召回窗口 `MAX_PRODUCTS=50`，
   20 SKU 场景精确；更大目录需 Java 侧价格参数（独立后续项）。

## 暂缓：提示层纪律包（证据已备好，等窗口决策）

针对"回退授权不执行"（shop-d-19：用户说"按可售来"，模型复述授权后仍反问）与
"必含词少报"（shop-d-34：`required_terms=[白色]` 少了"入门耳机"），验证过一个约
+300 token 的提示包（skill 纪律句 + schema 字段描述 + applied_constraints 回显），
实测：**d-19 从 0/3 → 2/3 通过、d-34 从 0/3 → 1/3 通过**（`fixverify3-20260912`）。

但 v7 基线就有 **24/117 试验的上下文峰值 >11400**（窗口 12000），其中五个当前通过题
（d-05/22/25/35/37）头部空间仅 24–110 token。该提示包实测把 **d-05、d-37 推下悬崖**
（`atrisk-probe-20260912`：context_limit setup_failed）。以通过题换修复题不可接受，
故全部回退（skill 保持 1.12.0 原文、schema 描述原文、回显删除）。

**待用户决策**：有界窗口 12000（agents/shopping.py `bounded_messages`）是否上调
（建议 12000→14400，+20%；远低于供应商模型上下文上限，代价是每调用略增 token）。
上调即可无损落地该提示包，同时解除 sup-d-21（客服线同根因：重复检索观察撑爆窗口）
的整个类。这是产品参数决策，不由评测侧单方面更改。

## 不做

- 不为灰色/下架/入门等具体词加词表或特例；不改宽 d-19/d-34 金标；不把 quantity 挪出资格门。
- 不在非空结果上附加观察负载（窗口零余量）。
- 已知局限：数量为会话级标量（"2个A和3个B"未建模）；无量词数量（"买2 USB线"）不抽取，
  模型显式声明的此类数量会被守卫保守丢弃。
