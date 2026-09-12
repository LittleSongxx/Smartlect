# Handoff：质量指标评测体系 / 测评集 / 评测优化

> **2026-09-12 晚间清理说明**：本文 §3.3 提到的旧评测产物（`evals/rag_cases.jsonl`、`tool_tasks.jsonl` 及各 manifest、`artifacts/` 下 f0–f7 与 rag/merchant 系列）与 §6 引用的旧脚本已**全部删除**，仅存 git 历史。quality-v2 已建成并是唯一评测体系（现行合同 v4、官方成绩 `artifacts/quality-v2/official-v5-20260912`、留出已冻结未出题）；本文的「已锁定决定」（指标名、操作定义、作弊禁令）仍然有效，其余描述以 `IMPLEMENTATION_STATUS.md` 与 `docs/quality-eval-v2.md` 为准。

日期：2026-09-12。仓库：`/home/song/code/Smartlect`。

本文给**新开的 AI 对话**用。下一任只接这三件事：

1. 按已锁定的公开指标，设计可执行的评测体系（定义、分母、通过标准、分层：单测 / 离线集 / 模拟流量）。
2. 从零构建对应测评集（题型、标注、开发/留出、机器可判）。
3. 在该体系上做评测与优化（跑通、看失败、改评测或改系统时必须说清改的是哪一层）。

不要把本文当成 F6/F7 完成证明。系统合同与不可让渡规则仍以仓库里的实施状态和 `docs/` 为准；**指标选哪些、测评集怎么建，以本文「已锁定决定」为准**，不要倒回去用旧评测产物定义质量。

---

## 1. 下一任必须先读的决定（不要重新调研推翻）

上一轮已经做完领域调研，并和用户收束。下一任**不要**再打开「项目里该测什么指标」的讨论，除非用户明确要求改锁定。

### 1.1 评测主线只保留三条

| 主线 | 公开指标（各 1–2 个） | 不要再扩成主线的东西 |
|---|---|---|
| **导购选品** | `Precision@K`、`Pass@1` | 首页五路推荐的 NDCG、多样性 |
| **政策客服** | `Recall@K`、`Faithfulness` | 单独的「转人工正确率」主线（并进客服 Pass/Faithfulness） |
| **广告投放** | `CTR`、`CVR` | ROAS、增收、因果结论 |

明确**不纳入本轮主线**：首页推荐、交易成交（τ-bench 式终态）、商家经营、归因完整性（归因只作为 CVR 分子的前置条件，不单独开主线）。

成交合同（未确认不成交、报价指纹）仍然是系统红线，评测优化时不能破坏；只是**不作为本轮要设计的主指标**。

### 1.2 必须用公开标准名，禁止自造 KPI 当主名称

可用：`Precision@K`、`Recall@K`、`Pass@1`、`Faithfulness`（或等价说 `Citation Precision`）、`CTR`、`CVR`。

禁止作为主名称：约束满足率、找得对不对、办得对不对、决策编译正确率、硬约束零违规率。这些可以当解释，不能当报表表头。

校招要讲得清，但分母必须是公开定义，不是「看起来合理的自定义分」。

### 1.3 不要从旧评测倒推尺子

仓库里已有 F6 向的 RAG 开发集/留出、工具任务、经营病例、推荐 fixture。那是**历史实现与旧合同**，可以当语料/反例/基础设施参考，**不能**当作「质量指标应该是什么」的依据。

用户原话大意：不要看当前项目已有什么数据条件来凑指标；要按导购/客服/投放这条垂类的公开标准重做评测体系与测评集。

### 1.4 指标操作定义（锁定）

**导购选品**

- `Precision@K`：Top-K 中满足**本轮硬约束**的条数 / K。硬约束包括预算、排除/必含词、可售、scope。热销凑数会降低 Precision。
- `Pass@1`：该题全部硬约束同时满足才为 1。`Precision@K=0.8` 但有一条超预算 → `Pass@1=0`。合法空集且未补无关商品 → `Pass@1=1`。比较题缺目标只标比不齐，不拿无关 SKU 填表，否则不 Pass。
- 公开对齐：IR 的 Precision；任务级对齐 WebShop Success / DeepShop holistic success（全约束同时成立）。
- 有标注满足集时，诊断可用 `Recall@K`，但主报仍是 Precision + Pass。满足集为空时改看 Pass，不硬算 Recall 失败。

**政策客服**

- `Recall@K`：标注的相关已发布文档是否进入检索前 K。这是 RAG 公开检索指标。
- `Faithfulness`：回答里可检查的事实/政策句，有多少能回到**本轮可见引用**（文档+版本）。检索对了但话说了文档没有的店规 → Faithfulness 低。公开对齐 RAGAS Faithfulness / Citation Precision。
- 该转人工：政策冲突、ACL 不可见、例外裁决等，应有持久工单且正文不编造未检索事实。可并进该题的 `Pass@1`，不必再开主线。

**广告投放**

- `CTR = 收费点击数 / 曝光数`。无曝光则为缺失（`None`），禁止补 0。
- `CVR = 归因到该活动的去重支付订单数 / 广告点击数`。无点击则为缺失。分子不是店内全部付款，不是「点了就算转化」。
- 这两条是**模拟流量上的记账比率**，定义与线上一致，**不能**说成投放效果、显著性或真实增收。经营观察里已有 `causal_conclusion_supported=false`。广告转化与推荐点击转化不可加总。

### 1.5 广告 CTR / CVR 在本仓库里能不能拿到（已核实，勿再猜）

能算，但不是往表里写一个假百分比。

- 公式已在 `growth/src/smartlect/ads/analytics.py` 的 `CampaignMetrics.ctr` / `cvr`。
- CTR 分子分母：`ad_interaction`（曝光）、`ad_spend`（一曝一收费点击）。前端可视提交 `/api/assistant/ads/exposures`，再 `/api/assistant/ads/clicks`。演示脚本与 `scripts/eval_comparison.py` 走同一 API。渠道是 `AD_SIMULATED`（模拟推广），但是真实落库事件。
- CVR 必须走完：**广告点击 → 用户确认下单 → 模拟支付 → 归因把 `campaign_id` 写到 PAYMENT**。只 mock 曝光/点击没有 CVR。只开 `SMARTLECT_MODEL_MODE=mock`、不打投放 API，也没有 CTR。
- 经营观察 `MerchantStore.observation` 按活动给出 `impressions`、`clicks`、`payment_conversions`；CTR/CVR 用这两个计数相除即可。管理端 UI 不一定渲染「CTR」字样。
- 低 CTR 筛查：至少 100 次曝光，基线 `clicks * 1000 < impressions * 5`（0.5%）。点击门槛 10 次才允许某些经营动作。这是成熟度门，不是本轮主指标的通过线。
- 广告点 A、买 B，仍可能记到该活动。未挂活动的付款进 `unknown_attribution`，不得塞进 CVR。

---

## 2. 项目是什么（给下一任的最小上下文）

Smartlect：独立单店 **AI 导购 + RAG 客服 + 模拟经营闭环**。

主路径：广告或自然来访 → Shopping 导购/有引用客服 → Java 真实 SKU → 用户确认具体交易 → Java 订单/付款/退款 → 广告与推荐**独立**归因 → Merchant 观察后再规划。

客服可以只回答或转人工结束，**不必**为了成交继续推荐。

两个领域 Agent，没有总 Supervisor：

- **Shopping**：有界 ReAct。`model → tools → answer`。Skill 并集：`shopping_advice` / `support_policy` / `order_service`。模型声明 `request_kind` 与 `handoff_requested`；`answer_status` 与是否建单由 `compile_decision` 编译（ADR 0002），模型不填 `answer_status`。
- **Merchant**：`plan → validate →` 确定性执行。必须有新的外生观测（曝光、点击、交易、库存）才能 Replan。

Java 是价格、库存、订单、支付、退款的唯一权威。Python Growth（`smartlect`）不直改交易表。金额整数分。支付与广告费均为本地模拟，无真实资金、无对外投放。

用户确认绑定具体提案版本、SKU、数量、报价。商家首次批准稳定 grant；新 plan/round **不重置**累计预算。

---

## 3. 当前工作进展（诚实）

实施状态原文见 `IMPLEMENTATION_STATUS.md`（更新 2026-09-11）。那份是当时的「唯一现状来源」，但 **09-12 又做了导购检索隔离**，Skill/测试数字可能比 09-11 文档新。冲突时以源码和你自己跑出的测试为准，不要用旧文档覆盖新代码。

### 3.1 功能大体已在

- Java 电商底座 + Growth Agent/RAG/推荐/广告/归因/账本。
- 用户端商城与导购；管理端活动、经营、知识库、人工客服。
- 决策编译、引用再验证、合法空集、人工接管 fencing。
- 广告：服务端曝光/点击、CPC、疲劳配速、售罄保护。
- 推荐与广告资格门共享 `catalog_gate`；**导购选品已从首页推荐服务拆出**。

### 3.2 09-12 导购检索隔离（最近一轮实现，评测要接这条，不要接旧首页五路）

计划已落地（不要改计划文件本身）。要点：

- `growth/src/smartlect/catalog_gate.py`：共享资格（库存、价格、词、scope）。
- `growth/src/smartlect/shopping_mission.py`：会话槽位（预算、排除/必含、比较目标）；可反转。
- `growth/src/smartlect/shopping_retrieve.py`：导购专用检索。`searchOnSale` 变体 + 硬门。**有硬约束且无命中时禁止热销补位**，`empty_reason=hard_constraint_unsatisfied`。
- `compare_skus`：比较 2–4 个 SKU；缺目标则 `comparison_complete=false`，不补无关商品。
- `conversation_memory.mission_json`（migration `0011_shopping_mission.sql`）。
- Skill `shopping_advice` **1.10.0**（09-11 状态文仍写 1.8.0，已过时）。
- 用户端 `AgentCompareTable.vue`。
- 单测当时：Growth 336 passed；user vitest 69；定向 MySQL 70。浏览器实机比较句曾因**模型通道失败**转人工，不能当成比较 UI 坏了。

评测导购时：必须打 `recommend_skus` / `ShoppingRetrieve` / `compare_skus`，**禁止**用首页 `RecommendationService` 五路热销补位的结果冒充导购质量。

### 3.3 旧评测进展（参考，不是本轮要延续的分数）

以下数字**可以当背景，不能当本轮通过标准，也不能和即将新建的测评集混算**。

- RAG 开发集 v9：确定性 64/64；独立语义 58 pass / 6 fail。当时绑定与现在 Skill 可能不一致。
- RAG holdout 12×2：**已开、未通过**（4 待审 / 20 失败保留）。未按留出改实现。不能宣称 holdout 通过，不能与开发集混成一个分。
- 工具任务 v10：曾报 40/40、强不变量 0。那是旧 20 例合同，不是本轮三条主线测评集。
- 经营病例、F6、F7：**均未完成**。`formal_f6_complete=false`，`formal_f7_complete=false`。
- 禁止宣称：F6 完成、F7 完成、holdout 通过、模拟 CTR/CVR 等于线上效果。

旧集位置：`evals/rag_cases.jsonl`、`evals/dataset-manifest.json`、`evals/tool_tasks.jsonl`、`evals/recommendations-manifest.json`、`evals/merchant-case-manifest.json`。产物在 `artifacts/`。F4/F5 阶段曾限制打开全量 RAG JSONL；本轮若要借鉴题型可以读，但**不要改旧 JSONL 来刷分**，新体系请新文件、新 manifest、新产物目录。

---

## 4. 用户要下一任交付什么

按优先级：

### P0 评测体系（先写清，再写题）

为三条主线各出一份短合同，建议放新目录，例如 `evals/quality-v2/`（名称可改，不要覆盖 `evals/rag_cases.jsonl`）。

每条主线必须写明：

- 指标名（只能用已锁定的公开名）
- 分子、分母、K 的默认值、缺失时记 `null` 不记 0
- 一道题如何判定 Pass / 不算分 / setup 失败
- 输入从哪来（用户原话、商品快照、知识版本、曝光点击、归因付款）
- 禁止的作弊（热销补位、模型自称成功、把推荐点击算进广告 CVR、按留出调题）

建议分层，不要一上来只靠 LLM-as-judge：

1. **机器可判**：约束是否落在 SKU 字段上；检索 doc_id 是否在相关集；曝光/点击/归因付款计数。
2. **引用级 Faithfulness**：句子 ↔ 本轮 citation 的可检查对齐（能规则就规则）。
3. **仅当规则判不了**：才上 LLM judge，且要有抽检，不能当唯一总分。

### P1 测评集构建

三条主线分开建，开发 / 留出先切后出题。留出未冻结前不读、不改、不用来调系统。

**导购选品集（优先）**

- 每例：用户话、冻结商品快照、原子硬约束、满足集（可空）、期望 `Pass@1`、用于算 Precision 的 K（建议 5 或 8，与线上 limit 对齐后写死）。
- 必覆盖：预算截断、排除词、合法空集、比较缺目标、多轮后来说的新约束覆盖旧预算、有货但超预算不能用热销顶上。
- 走 `ShoppingRetrieve` / `compare_skus`，不走首页推荐。

**政策客服集**

- 每例：用户话、本轮可发布知识（含版本）、相关文档 id、期望引用边界、是否应转人工。
- 必覆盖：已发布政策可答、过期/撤回不可当现证、ACL 不可见、冲突、寒暄不必检索、例外要工单。
- 指标：检索 `Recall@K`（K 与现网精排 8 / 常用 4 对齐并写死）+ 终答 `Faithfulness`。
- 可以参考旧 RAG 题的**类型**，不要复制旧期望来迁就当前模型，也不要按 holdout 失败加词表。

**广告投放集**

- 每例是一条**可复现的流量剧本**，不是一张静态 QA。
- 最小剧本：创建/批准活动 → N 次曝光 → M 次点击 →（可选）确认+模拟支付。
- 输出：该活动 `impressions`、`clicks`、`payment_conversions`，再算 CTR、CVR。
- 至少两类剧本：只有曝光点击（有 CTR、CVR 为 null）；走完归因支付（CTR、CVR 都有数）。
- 样本会很小。报告必须带分母和「模拟、非因果」。不要为了数字好看去灌点击。

规模建议（可调整，但要先定再采）：每条主线开发集几十例即可，留出另锁一小撮。校招叙事用得动，比堆 500 例空壳重要。

### P2 评测运行与优化

- 写出 runner：固定种子、固定快照、写 `artifacts/` 新目录，带 git 脏检查或至少记录 commit + 未提交哈希。
- 先跑通开发集，报三条主线的指标，**分开展示**，不要合成一个「总分」。
- 优化顺序：先修评测 bug（题错、分母错、打到首页推荐上），再修系统的一类失败（合法空集被补位、引用未绑定版本、CVR 吃了未归因付款）。
- **禁止**：为单题加关键词表；按留出调参；重采样失败例直到变绿；把旧 v9 64/64 写进新报告。
- 改系统前确认用户要「改产品」还是「只建评测」。默认先把评测跑出诚实数字，再问是否改代码。

---

## 5. 下一任不要做的事

- 不要重开指标调研，不要把主线扩回 6 条。
- 不要宣称 F6/F7/holdout 通过。
- 不要执行会拆当前正在跑的栈的命令（`./scripts/dev.sh build`、`down`、`eval --suite acceptance`），除非用户明确要求并另开隔离运行时。
- 不要按 holdout 改 prompt/Skill/检索/词表。
- 不要把广告 CTR/CVR 写成线上效果或 ROAS。
- 不要用首页热销补位成绩代替导购 Precision/Pass。
- 不要更新 git config、不要主动 commit/push（除非用户要）。
- 不要对外发布、不要接真实支付/真实广告。
- 回复用户用简体中文。

---

## 6. 关键路径（从这里读代码，不要全库漫游）

**导购**

- `growth/src/smartlect/shopping_retrieve.py`
- `growth/src/smartlect/shopping_mission.py`
- `growth/src/smartlect/catalog_gate.py`
- `growth/src/smartlect/agents/shopping.py`（`recommend` / `compare` / `compile_decision`）
- `growth/src/smartlect/skills/shopping_advice.json`（1.10.0）
- `growth/tests/test_shopping_retrieve.py`、`test_compare_skus.py`、`test_shopping_mission.py`

**客服 / RAG**

- `growth/src/smartlect/knowledge.py`
- ADR `docs/adr/0002-decision-compile.md`
- `growth/src/smartlect/skills/support_policy.json`
- 旧集仅参考：`evals/dataset-manifest.json`（先读 manifest，新体系不要改这份当主集）

**广告 / CTR / CVR**

- `growth/src/smartlect/ads/analytics.py`
- `growth/src/smartlect/ads/store.py`（曝光、一曝一击）
- `growth/src/smartlect/merchant/store.py`（`observation` 里的 impressions/clicks/payment_conversions）
- `growth/src/smartlect/attribution.py`
- `docs/ads-contract.md`、`docs/merchant-contract.md`
- 流量剧本参考：`scripts/seed_store_playbook.py`、`scripts/eval_comparison.py`（点击模型是模拟器，不是线上）

**现状与合同**

- `IMPLEMENTATION_STATUS.md`
- `docs/architecture-interview.md`
- `docs/agent-design.md`
- `docs/contracts.md`

上一轮调研画布（指标讨论，不是评测结果）：

- `/home/song/.cursor/projects/home-song-code-Smartlect/canvases/shopping-vertical-quality-metrics.canvas.tsx`
- `/home/song/.cursor/projects/home-song-code-Smartlect/canvases/per-line-public-metrics.canvas.tsx`

---

## 7. 建议开工顺序

1. 用一页纸把三条主线的指标合同写成新文件（分子分母、K、缺失、Pass）。交给用户确认后再铺题。
2. 先做导购选品开发集 + runner（最贴最近代码，机器可判）。
3. 再做政策客服开发集（Recall + Faithfulness）；旧 RAG 只借鉴题型。
4. 再做 2–3 条广告剧本，打出 CTR，至少 1 条打出 CVR，报告写明分母与非因果。
5. 三线开发集都跑通后，再冻留出；冻结前不读留出。
6. 优化：先报失败结构，再问用户改评测还是改系统。

---

## 8. 对用户说话时的边界

用户是校招导向：要能用 `Precision@K` / `Pass@1` / `Recall@K` / `Faithfulness` / `CTR` / `CVR` 讲 30 秒，不要堆 SoP、pass^k、ShoppingComp。

内部实现可以更严，对外报告和文档表头用公开名。

若必须提到旧成绩：开发集与留出分开说；旧 v9 不是新体系的基线。

---

## 9. 一句话交接

为 Smartlect 的导购、政策客服、广告三条主线，用公开指标（Precision@K + Pass@1，Recall@K + Faithfulness，CTR + CVR）从零设计评测合同、新建测评集和 runner，跑出诚实数字；不要从旧 F6 产物倒推尺子，不要把模拟投放比率说成效果，不要在未确认前扩大主线或改 holdout。
