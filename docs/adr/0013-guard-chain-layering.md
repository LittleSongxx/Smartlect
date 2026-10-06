# ADR-0013: 守卫链分层治理——意图帧启发式与证据契约校验分离，评测驱动降级

日期：2026-10-05
状态：已接受（分层声明与审计补强落地；逐条降级为后续评测驱动事项）

## 背景

架构评审（2026-10-05）指出：系统叙事是「模型声明 `request_kind`，控制器编译」，
但代码中存在约 10 个中文关键词正则启发式（`looks_like_*` / `answer_*_human_*` /
`shopping_mission.looks_like_*`）拥有**覆盖模型声明的改判权**——意图识别并没有
消失，而是拆散埋进了守卫链。成因正当：每条锚定 v11–v28 评测合同的具体失败样本
（ADR-0009 有据），是模型声明不可靠时的确定性兜底。代价是：

1. 中文表达多样性使关键词帧天然易误报（2026-10-05 前后已有 any-term 敏感门
   桥接词误报的修复先例），守卫间相互作用曾杀掉合法答案（v11 sup-d-50 等）；
2. `required_terms` 等口径需检索层、发布门、任务状态三方手工同步；
3. `answer_node` 单函数 330+ 行，15+ 守卫顺序执行，认知负荷到达边界。

一次性删除或降级这些帧等于删除评测资产（ADR-0009 决定三），且降级属行为变更，
受 27 版评测合同约束、须 live 评测验证（holdout 首测即烧毁的纪律不允许盲改）。

## 决定

### 1. 显式分两层，治理路线不同

**A 层：证据契约校验**（`bind_*` / `coerce_*` / 检索预算 / `no_business_claim_*` /
`answer_guards.unsupported_state_claims`）——校验「终答声明 × 本轮回执」的一致性，
无意图推断，是确定性不变量。**永久保留**，继续以行为测试锁定。

**B 层：意图帧启发式**（下表）——推断意图并改判。**声明为待退役层**：评测驱动
逐条降级为「提示注入 / 审计标记」，让 `request_kind` 声明 + `compile_decision`
成为唯一意图权威。

| 意图帧 | 改判点 | 当前效果 |
|---|---|---|
| `shopping_mission.looks_like_exception_request` | session.answer_node | inquire_fact → request_exception（开单） |
| `guardrails.looks_like_irreconcilable_sources` | session.answer_node | 非 exception 族 → request_handoff |
| `guardrails.answer_offers_human_transfer` 等 3 个 | session.answer_node | 强制置位 handoff_requested 并开单 |
| `guardrails.looks_like_catalog_fact_question` | compile.template_observed_catalog_result | 控制器模板收口（跳过模型终答） |
| `guardrails.looks_like_product_unique_fact` | compile_decision | 不足 → PRODUCT_UNCOVERED_ANSWER；已接地 → 无检索判 answered |
| `shopping_mission.looks_like_product_request` | 选品收口门 | insufficient 收口前强制补一次选品 |
| `guardrails.looks_like_service_request` | 目录模板排除项 | 服务请求不走模板收口 |

### 2. 本次落地的零行为变更治理

- `guardrails.py` 模块 docstring 与分节注释声明两层；每个意图帧函数 docstring
  标注改判点与退役判据；
- 审计补强：`irreconcilable_compiled` 旗标随 run 快照落库（与既有的
  `exception_frame_compiled`、`handoff_compiled_from_answer` 对齐），改判可回放；
- 本 ADR 作为唯一权威清单（此前散落在代码注释里）。

### 3. 降级路线（后续评测驱动，非本 ADR 授权直接执行）

对每条 B 层帧，按序：

1. 在 quality-v2 对应维度统计该帧的「改判纠错率」（帧改判后评测通过 vs 帧未
   触发时模型原声明的通过率）；
2. 纠错率不显著为正（或显著为负）→ 降级：改判权移除，保留 decision 事件与
   context 旗标（审计可见），提示词补充对应行为约束；
3. 纠错率显著为正 → 保留并记录证据，下一轮复审；
4. 任何降级须过全量 dev 集 + 新 holdout 首测，按评测纪律留档。

降级不设时间表：以模型 request_kind 声明的可靠率为唯一判据。

## 后果

- 守卫链的「为什么存在、何时可退」首次有单一权威文档；新守卫须先声明归属层。
- 新增守卫的准入门槛：A 层须锚定确定性不变量（与意图无关）；B 层新增原则上
  不接受——优先把约束写进提示词或 profile 契约，让模型声明、控制器编译。
- 评测合同与现有行为不受本次影响。
