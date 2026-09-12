# Smartlect 质量评测合同（quality-v2）

日期：2026-09-12（v4 修订：claims 分级 essential/peripheral——Faithfulness 只算问题直接要求的 essential 命题，peripheral 进 `Peripheral_coverage` 诊断；新增 RAGAS 语义对照列 `Faithfulness_answer_side`（分解答案自身断言验证支撑，不进公开主报）；数量题 Precision 采用 demand-fill 语义（单个满足 SKU×数量填满对应槽位）；导购集几何重设计使 12/20 案例金标≥4。v3：Faithfulness 公开分为 DeepSeek judge 判分）。本文件是公开指标的操作定义。表头只用公开名。三条主线分开展示，不合成总分。旧 `evals/rag_cases.jsonl`、`tool_tasks.jsonl` 与 F6/F7 产物不是本轮基线。

一题三种结局：`pass` / `unscored`（分母缺失记 `null`）/ `setup_failed`。`setup_failed` 不进均值，仅限 provider/预算/基础设施故障，禁止重采样刷绿；每次复跑记入 `artifacts/quality-v2/rerun-ledger.jsonl`。

**题目标注自洽性错误（金标与硬约束不符、寒暄带 gold、剧本比率与计数不符等）不是 setup_failed：`AnnotationError` 中止整个 run。** 修题后重跑全量。

分层：先机器可判，再引用级 Faithfulness（能规则就规则），LLM judge 只抽检（仅开发集、固定种子、不进公开总分）。

汇总报告每个指标旁印分母（`denominators`），1.0 over 10 不得冒充 1.0 over 24。

---

## 导购选品

公开主报：`Precision@4`、`Pass@1`。

- **K=4**。每题 `request.limit=4`，对齐 `RecommendationRequest.limit` 默认值。
- **打分面**：完整 Shopping Agent 终答的 `finish_answer.selected_sku_keys`。runner 按该顺序重排 `result.products`，`L = selected[:4]`。不要用 `products` 字典插入序。
- **入口**：`recommend_skus` / `compare_skus` → `ShoppingRetrieve`。`shopping_advice` 白名单没有 `search_skus`。
- **禁止**：`GET /api/assistant/recommendations`、`RecommendationService` 五路热销。`popular_used` / `copurchase_used` 必须为 false。
- **幻觉 sku_key**：`selected_sku_keys` 里不在 `products` 的 key 按占位违规槽计（`status/stock/price` 为 None，`sku_satisfies` 必 False），不得静默丢弃。
- **目录快照**：v2 为 20 SKU（Java 场景 `productCount` 上限 20，`DemoScenarioController` 校验）。overlay 直接改写场景商品，每题结束恢复原值（restore 结果记入证据 `catalog_overlay.restore`）。

### 硬约束（机器字段）

落到 `eligible_skus`。金标写在题面，不要假设原话会被抽全。

| 槽位 | 规则 |
|---|---|
| 预算 | `price_cents <= budget_max_cents`。多轮是后说的替换，不是取 min。 |
| 排除词 | 名称+规格 NFKC casefold **子串**。多轮并集累积。「其实 X 可以」才删除。 |
| 必含词 | 同样子串。`extract_mission` **抽不到** `required_terms`，只能来自工具参数或已写入的 mission。 |
| query | 软信号，不是资格门。 |
| 可售 | `status=1`，逐 SKU 库存 ≥ `quantity`（默认 1）。`quantity` 进资格门，但不进 `has_hard_constraints`。纯库存空集的 `empty_reason` 可以是 `no_eligible_sku`。 |
| scope / 排除身份 / 类目 | include/exclude、`excluded_product_ids`、`excluded_sku_keys`、可选 `category_id`。 |
| 长期偏好 | 不是导购硬约束。 |

### Precision@4

`(L 中满足本轮全部硬约束的条数) / 4`。不足 4 条的空位算不满足。

- 合法空集（满足集为空且未补位）：`Precision@4 = null`。
- 比较题：**不报** `Precision@4`（宽度 2–4），只报 `Pass@1`。
- 无约束且无 query 的 browse 在售不是热销补位，也不当选品成功。

诊断可另存最后一次 `recommend_skus` 的 `items`，不进公开表。

### Pass@1

本题全部硬约束同时成立（WebShop / DeepShop holistic success）。

- 满足集非空：至少选出 1 个在满足集内的 SKU，且 L 中没有违规 SKU。
- 满足集为空：L 为空，`popular_used=false`，`empty_reason` ∈ `{hard_constraint_unsatisfied, no_eligible_sku}`。
- 比较：缺目标则 `comparison_complete` 显式为 false，表中无无关 SKU；部分命中+标不全算 Pass；拿无关 SKU 填表或不齐却标齐 → 不 Pass。
- `Precision@4=0.75` 但有一条超预算 → `Pass@1=0`。
- `compile_decision` / `answer_status` 不代替选品对错。
- 模型通道失败转人工 → `setup_failed`。模型选择转人工 → `Pass@1=0`。

官方数字用 live 模型。`SMARTLECT_MODEL_MODE=mock` 只允许跑通 runner。

---

## 政策客服

公开主报：`Recall@8`、`Faithfulness`。转人工并进该题 `Pass@1`，不新开主线。

检索深度：`FIRST_STAGE_DEPTH=20`，`FUSED_DEPTH=12`，`FINAL_DEPTH=8`，展示引用最多 4。

### Recall@8

最后一次**真实** `search_knowledge` 的 `data.candidates` 前 8 个去重 `doc_id`（建议带 version）是否覆盖 gold。

- 真实检索：回执带 `candidates` 或 `retrieval.final_depth`。`SHOPPING_RETRIEVAL_LIMIT=2` 之后的空观测不得当 Recall 列表。
- 不要用一阶 20、融合 12、终答 citations、模型观测条数。
- 相关集为空（寒暄、纯转人工且无政策问）：`null`。
- 过期/撤回/ACL 不可见不得进 gold。
- 诊断 `Recall@4`：同一 `candidates[:4]`，不进公开主报。

### Faithfulness（v3 起：judge 判分，与主模型不同源）

终答可检查命题中，被独立 judge 模型（DeepSeek `deepseek-flash`，`SMARTLECT_JUDGE_*` 环境变量，默认 `https://api.deepseek.com`）判定为 `supported`（答案明确表达且与资料一致，改述算）的比例。**judge 与主对话模型（qwen）不同源，避免自评。** 覆盖全部带 `checkable_claims` 的已评分题（全量，不是抽样）；temperature=0；prompt 版本 `qv2-judge-faith-v2`。

- judge 调用失败：该题 Faithfulness 记 `null`（分母缺失），**绝不回退借用规则分**。
- 标注 `checkable_claims` 的每条 `text` 仍必须是本轮可见文档正文的连续子串（`validate_dev_sets` 强制）——judge 的"资料"侧仍然锚定在可验证语料上。
- `Faithfulness_rule`（诊断列）：旧的答案侧+引用侧原文子串比例，保留用于对比 judge 与规则的分歧。
- 禁句仍是确定性规则门（不交给 judge，judge 有误报先例）：`must_not_claim` 否定窗口豁免、`forbidden_claims` 原样命中 → 该题 fail。
- 模型观测没有 version，不要打 observation。
- 无检查句：`null`。有政策断言且引用为空：规则诊断记 `0`；judge 判 `unsupported`/`contradicted`。
- `citation_no_longer_visible`：Faithfulness 记 `null`，只看转人工 Pass。
- 公开名仍是 `Faithfulness`；judge 有运行间方差，官方报告带 judge 模型名与 prompt 版本。

### 禁句（v2 生效）

- `must_not_claim`：终答中命中（且前 8 字符否定窗口内无 `不/没/未/非/别/无`）→ 该题 fail。诚实否定（"不支持真实银行卡"）不算。
- `forbidden_claims`：终答中原样出现 → 该题 fail（用于注入题的 `IGNORE_ALL_RULES` 类标记）。

### 转人工 Pass

`answer_status=needs_human` 且持久 `ticket.ticket_id`。不要用检索回执的 `conflicting` / `requires_human`（后者恒 false）。

- 冲突检测只看 `facts_json` 同 key 不同值。正文冲突必须在标注里写期望。
- 寒暄无问候词表：`grounding=no_business_claim` + 未检索。
- 合法空集（`inquire_fact` × 无可见证据）是 `insufficient`，不建单。旧 holdout 的 policy_gap→必须工单不要抄。
- 政策题禁止夹交易提案。
- `request_service` 且空证据会建单；标注单独写。

### LLM judge 抽检（第三层，仅开发集）

`scripts/eval_quality_v2.py judge --output <run目录>`：固定种子抽样，直连模型（不经被测栈），对每条 claim 判 `supported/absent/contradicted/unsupported` 并列 `hallucination_list`，与规则分对照写 `judge/judge-report.json`。**不进任何公开表头**；规则判不了的分歧留给人工复核。

---

## 广告投放

模拟流量记账比率，不是效果、显著性或增收。`causal_conclusion_supported=false`。报告必须带分母和「模拟、非因果」。

- `CTR = clicks / impressions`。`impressions=0` → `null`，禁止补 0。`impressions>0` 且无点击 → `0.0`。
- `CVR = payment_conversions / clicks`。`clicks=0` → `null`。`clicks>0` 且无归因支付 → **`0.0`（不是 null）**。
- 分子只用该活动 `campaign.metrics.payment_conversions`。禁止 `summary.payment_conversions`。
- `unknown_payments`（PAYMENT 且 `campaign_id` 为空）单独计数，**不得进任何活动的 CVR 分子**；剧本 `organic_payment` 专门覆盖。
- 推荐点击不可与广告 CTR/CVR 加总。点 A 买 B 仍可能记该活动；剧本 `ads-d-04` 覆盖（买 `other_sku`）。
- 管理端 ads 快照顶层计数是 scope 合计，不要用来算按活动 CTR。
- 低 CTR 门（约 100 曝光 / 0.5%）是经营成熟度，不是本轮通过线。

五类剧本：仅曝光（CTR=`0.0`，CVR=`null`）；曝光+点击不支付（CVR=`0.0`）；同 SKU 归因支付（CVR>0）；点 A 买 B 仍归因；无活动付款进 `unknown_payments`（两率均 `null`）。

---

## 留出与作弊

- 开发 / 留出先切后出题。`scripts/eval_quality_v2.py freeze` 盖开发集摘要（`evals/quality-v2/holdout/freeze-manifest.json`），之后 `--split holdout` 才可加载；出题仍是人工任务，工具不代写。
- 禁止：热销补位冒充导购；按留出加词表；把推荐点击算进广告 CVR；把模拟比率写成线上效果；把旧 v9 64/64 写进新报告；题错后重采样而不是修题。
