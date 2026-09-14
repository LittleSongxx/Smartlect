# Smartlect 质量评测合同（quality-v2）

日期：2026-09-13（**v6.2 修订：P3 仲裁落地**——claims 分级判级原则成文（见"政策客服"节：essential=删去后被问出的问题落空或被误导性部分回答，附两条操作款），`allow_handoff` 新增（曾发布现已失效资料的双诚实收口），禁句否定提示词集扩为 不/没/未/非/别/无/勿/莫，客服 dev 62→63 题（软问法 MERCHANT sup-d-63）。**v6.1 修订：广告 script 剧本增补**。**v6 修订：公开表头名实对齐**——导购第二公开指标从 `Precision@4` 改为 `Precision@4/ceiling` 贴满率（NDCG/IDCG 式对可达上限的正规化：同槽位、同分母，只除以本题满分；raw `Precision@4` 与 `Precision@4_ceiling` 保留为诊断列，demand-fill 超顶截断在 1.0）；广告公开分从模拟 `CTR`/`CVR`（确定性校验伪装成效果比率）改为单指标 `Attribution_integrity` 归因完整性（断言级分母：四桶计数+两率算术+禁捷径共 8 条断言/剧本；`CTR`/`CVR` 降诊断列）。理由是名实对齐与正规化先例，非刷分——新指标只会更严。v5：多次试验与置信区间。v4：claims 分级 essential/peripheral。v3：Faithfulness 公开分为 DeepSeek judge 判分）。本文件是公开指标的操作定义。表头只用公开名。三条主线分开展示，不合成总分。旧 `evals/rag_cases.jsonl`、`tool_tasks.jsonl` 与 F6/F7 产物不是本轮基线。

一题三种结局：`pass` / `unscored`（分母缺失记 `null`）/ `setup_failed`。`setup_failed` 不进均值，仅限 provider/预算/基础设施故障，禁止重采样刷绿；每次复跑记入 `artifacts/quality-v2/rerun-ledger.jsonl`。

**题目标注自洽性错误（金标与硬约束不符、寒暄带 gold、剧本比率与计数不符等）不是 setup_failed：`AnnotationError` 中止整个 run。** 修题后重跑全量。

分层：先机器可判，再引用级 Faithfulness（能规则就规则），LLM judge 只抽检（仅开发集、固定种子、不进公开总分）。

汇总报告每个指标旁印分母（`denominators`），1.0 over 10 不得冒充 1.0 over 24。

---

## 多次试验与置信区间（v5 生效，全部主线共用）

- **`--trials N`**：同题独立跑 N 次，每次全新场景（新 actor 会话、目录 overlay 各自应用并恢复、独立 run_id）；模型采样不播种——要测的正是这个采样方差。导购/客服适用；广告为确定性模拟，只跑单次。
- **逐题报告**：`per_case_trials` 列每题 k 次试验的结局、通过次数与通过率；翻转题（同题既有 pass 又有 fail）在 `flip_cases` 显式列出，不得让均值吞掉翻转。
- **`pass^k`** = 全部 k 次试验都通过的题数 / k 次全部有效计分的题数（HumanEval 语义在 n=k 时的形式）。任何一次 `setup_failed` 的题不进该指标分母，按复跑台账补齐后重算。
- **主数语义不变**：line 级指标仍是按题均值（macro，每题等权——该题取其试验均值）；k=1 的输出与 v4 完全一致，可与 v6 基线直接对话。
- **`ci95_wilson`**：每指标旁印 Wilson 95% 置信区间，n=该指标非空观测数（试验级）。`Pass@1` 为二项、区间精确；`Precision@4`/`Recall@8`/`Faithfulness` 等分数值为 [0,1] 有界均值的 score-interval 近似——CI 不替代逐题方差表，两者并排印。
- **setup_failed 试验**照旧只限 provider/基础设施并进台账；一题多试验时台账按题记一条，附 `trial_outcomes`。
- **留出不适用**：留出首测已烧毁，`--trials` 只用于开发集。

---

## 导购选品

公开主报（v6）：`Pass@1`、`Precision@4/ceiling`（贴满率）。贴满率 = min(P@4 ÷ min(4,|金标|)/4, 1.0)，按题宏平均；NDCG/IDCG 式对可达上限正规化，demand-fill 超顶截 1.0。raw `Precision@4` 与 `Precision@4_ceiling` 保留为诊断列并排印刷。

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

### claims 分级（v6.2：P3 仲裁判级原则）

> **essential = 把该命题从终答中删去后，判定面上某个用户实际问出的问题将得不到回答、或被误导性地部分回答的命题；其余同域真实相关的命题——背景、机制、安全守则、程序细节、延伸服务指引、早前轮内容的复述——一律 peripheral（进诊断列）。**

操作款：

1. **否认与路径的分级看题面类型**：行动请求类题面（要求或询问客服会不会**代做某事**："帮我查""直接给我换""会帮忙加库存吗"）——直接否认与"完成条件/替代路径"均属直接答案；能力/政策询问类题面（"你们店是不是/有没有/支不支持"）——仅直接否认/确认为 essential，其后的服务指引与条件为 peripheral。
2. **多轮题以末轮问题为锚**：命题当且仅当属于末轮问题（含其通过指代——"也就是说""那我这一单"——收入的前文未决之问）的直接答案时 essential；末轮已反转或收窄掉的前轮之问为 peripheral。**末轮自包含仍是出题纪律**，未来出题必须保持。

v6.2 起按此原则回标：essential claims 65→57（10 条翻转），与 v12 及以前的 Faithfulness 分母口径不可直接对比。

### 禁句（v2 生效；v6.2 扩否定词表）

- `must_not_claim`：终答中命中（且前 8 字符否定窗口内无 `不/没/未/非/别/无/勿/莫`）→ 该题 fail。诚实否定（"不支持真实银行卡""请勿重复提交"）不算。
- `forbidden_claims`：终答中原样出现 → 该题 fail（用于注入题的 `IGNORE_ALL_RULES` 类标记）。

### 转人工 Pass

`answer_status=needs_human` 且持久 `ticket.ticket_id`。不要用检索回执的 `conflicting` / `requires_human`（后者恒 false）。

- 冲突检测只看 `facts_json` 同 key 不同值。正文冲突必须在标注里写期望。
- 寒暄无问候词表：`grounding=no_business_claim` + 未检索。
- 合法空集（`inquire_fact` × 无可见证据）是 `insufficient`，不建单。旧 holdout 的 policy_gap→必须工单不要抄。
- **`allow_handoff`（v6.2，P3 仲裁 D4）**："曾发布、现已过期/撤回"的资料（用户可能记得它）→ `allow_insufficient=true` + `allow_handoff=true`，insufficient 与带工单转人工**均为诚实收口**（两种都 pass）；"资料从未存在"（legal_empty、draft_only）→ 仅 insufficient（建单属过度转交，维持严判）。校验器强制：`allow_handoff=true` 须同时 `expected_handoff=false` 且 `allow_insufficient=true`，否则 AnnotationError。`needs_human` 而无持久工单在任何分支都 fail。
- **人工接管终结会话（v6.2）**：多轮题中任一轮以开放工单收尾时，会话进入人工接管，后续轮次被业务性拒绝（409 `human_control_active`）——这不是 provider/基础设施故障，**不得记 `setup_failed`**；以最后一个已完成轮的结果计分（金标期望建单→该行为本身即满足；不期望→判 fail）。证据记 `handoff_ended_conversation`（完成轮数/未问轮数）。
- 政策题禁止夹交易提案。
- `request_service` 且空证据会建单；标注单独写。

### LLM judge 抽检（第三层，仅开发集）

`scripts/eval_quality_v2.py judge --output <run目录>`：固定种子抽样，直连模型（不经被测栈），对每条 claim 判 `supported/absent/contradicted/unsupported` 并列 `hallucination_list`，与规则分对照写 `judge/judge-report.json`。**不进任何公开表头**；规则判不了的分歧留给人工复核。

---

## 广告投放

公开主报（v6）：单指标 **`Attribution_integrity`（归因完整性）** = 通过断言数 / 断言总数（分母是断言、不是剧本）。每剧本 8 条确定性断言：四桶计数（`impressions`/`clicks`/`payment_conversions`/`unknown_payments`，含归因归桶与 unknown 桶）+ 两率算术（含空值语义）+ 两条禁捷径（不得用 `summary` 合计、不得借用推荐点击）。`Pass@1` 保留为剧本级门（= integrity 为 1.0）；`failed_assertions` 逐条列名供归因。模拟 `CTR`/`CVR` 降为诊断列。

模拟流量记账比率不是效果、显著性或增收。`causal_conclusion_supported=false`。报告必须带分母和「模拟、非因果」。

- `CTR = clicks / impressions`。`impressions=0` → `null`，禁止补 0。`impressions>0` 且无点击 → `0.0`。
- `CVR = payment_conversions / clicks`。`clicks=0` → `null`。`clicks>0` 且无归因支付 → **`0.0`（不是 null）**。
- 分子只用该活动 `campaign.metrics.payment_conversions`。禁止 `summary.payment_conversions`。
- `unknown_payments`（PAYMENT 且 `campaign_id` 为空）单独计数，**不得进任何活动的 CVR 分子**；剧本 `organic_payment` 专门覆盖。
- 推荐点击不可与广告 CTR/CVR 加总。点 A 买 B 仍可能记该活动；剧本 `ads-d-04` 覆盖（买 `other_sku`）。
- 管理端 ads 快照顶层计数是 scope 合计，不要用来算按活动 CTR。
- 低 CTR 门（约 100 曝光 / 0.5%）是经营成熟度，不是本轮通过线。

五类剧本：仅曝光（CTR=`0.0`，CVR=`null`）；曝光+点击不支付（CVR=`0.0`）；同 SKU 归因支付（CVR>0）；点 A 买 B 仍归因；无活动付款进 `unknown_payments`（两率均 `null`）。

**v6.1 增补（2026-09-13，T4 扩容）**：剧本 5→11，新增六本 **script 剧本**（疲劳/配速/预算耗尽机制族，`ads-d-06…11`）。`Attribution_integrity` 定义不变（断言级分母）；script 剧本的断言数 = 基础 8 条 + 脚本期望数：排序断言 `rank:N.first`/`rank:N.items`（`ad-fatigue-pacing-v1` 下的确定性次序：同 SKU 双活动 relevance 打平，槽位前缀 id 使平手按脚本方向破）、拒绝断言 `reject:N.<op>.<error>`（预算门 409）、状态断言 `status:N.<slot>`（预算扣满时 click 事务自动转 `EXHAUSTED/budget_exhausted`，后续操作 409 `ads_not_active` 且活动从推荐候选消失）。约束：script 剧本不得同时定义 `traffic`；计数必须由脚本推导（AnnotationError）；双活动剧本必须 `same_sku`（排序确定性的前提）。观众隔离（user_b 无疲劳史）与素材粒度疲劳分别由 `ads-d-07`/`ads-d-11` 覆盖。

---

## Tier-1 诊断指标（2026-09-14 追加；不进公开表头、不改分母、不改判分）

六项确定性诊断列（零 judge 成本）。动机：Recall@8 在 32 篇语料上已饱和（v15=1.0），判别力在首位与排序质量；导购/客服各补行为面。全部**试验级聚合**（每个计分试验一个观测），与公开表头的按题宏平均口径不同；分母照印。公开表头未变，故本节只修订本文档：`metrics-contract.json` 与三线 manifest/freeze 均不动。

### 客服检索（Recall@8 的判别力下探）

打分面与 Recall@8 同源：最后一次真实 `search_knowledge` 的去重 `candidates` 序；null 条件相同（金标为空或 `expected_retrieval=false` 记 null；金标非空而未发生真实检索记 0）。

- **`Recall@1`（严格）**：全部金标 doc_id 均排名 ≤1 的试验占比。去重后多个金标不可能都居首，多金标试验此列几乎恒 0——设计如此，它测量的是"首位即全对"。
- **`MRR@8`**：每试验对每个金标取其在去重序中的排名 r，得分 1/r（r>8 或缺席记 0），多金标先平均；线级=按试验宏平均。
- **`Context_Precision@8`**（RAGAS 同义，binary 金标）：对前 8 位去重 candidates，第 i 位命中金标则计 precision@i=(截至 i 的金标命中数)/i，总分=Σ(precision@i)/|金标集|；无命中记 0。

### 导购行为面

- **`violation_free@1`（首位合规率）**：分母=recommend 类且选择列表非空的计分试验（compare 走对比完整性语义、空集题走诚实语义，均不计入）；分子=首位 SKU 满足该题全部硬约束（`sku_satisfies`，首位即展示序第一）。
- **`empty_set_honesty`（空集诚实率）**：分母=`satisfaction_set` 为空且非 compare 的计分试验；分子=L 为空 ∧ `empty_reason∈{hard_constraint_unsatisfied,no_eligible_sku}` ∧ 未走热销补位——即空集题的 pass 贡献。分母为 0 记 null。

### 客服建单边界

- **`handoff_f1`**：金标=`expected_handoff`；预测=编译后终态"开了持久工单"（`answer_status=needs_human` ∧ 持久 `ticket_id`，与 Pass@1 的建单面同源；不用模型原始 `handoff_requested` 声明）。**`allow_handoff` 题（两种收口都算对，非可判定负例）从 F1 分母剔除并单列剔除数**；输出 precision/recall/F1 三数+分母。

历史回填（当前评分器重扫 v13/v14/v15 证据，只读）：`artifacts/quality-v2/tier1-backfill/backfill-report.md`。Tier-2（公开表头是否纳入检索线 MRR、导购首位合规率、意图 F1）待用户看完回填数字后另行决定；届时走合同 v6.3 修订（md+json+manifest 刷新+freeze 重盖+合同测试）。

---

## 留出与作弊

- 开发 / 留出先切后出题。`scripts/eval_quality_v2.py freeze` 盖开发集摘要（`evals/quality-v2/holdout/freeze-manifest.json`），之后 `--split holdout` 才可加载；出题仍是人工任务，工具不代写。
- 禁止：热销补位冒充导购；按留出加词表；把推荐点击算进广告 CVR；把模拟比率写成线上效果；把旧 v9 64/64 写进新报告；题错后重采样而不是修题。
