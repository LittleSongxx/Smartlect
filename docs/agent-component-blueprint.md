# Agent 组件对齐蓝图

> 定位：从「完整 AI Agent 组件」视角，逐模块给出 Smartlect Agent 的目标形态、与现状的差距、以及参考来源（同题材项目 B/C 与业界成熟做法）。
> 性质：**调研与设计文档，未实施**。每条目标设计都写成可用一句话复述的形态，便于评审、拆分与验收。
> 日期：2026-10-07 ｜ 关联：[agent-design.md](agent-design.md)、[ADR 目录](adr/)、[quality-eval-v2.md](quality-eval-v2.md)

## 0. 参考项目与本文引用约定

| 简称 | 项目 | 关系 |
| --- | --- | --- |
| **A** | 本仓库 Smartlect（Java 后端 + Python assistant） | 被评估与改造对象 |
| **B** | `~/code/Agent/multi-agent/smartlect`（AgentScope 2.0.8 全栈版） | 同题材前代实现，上下文工程最完整 |
| **C** | `~/code/Java/mewhelp`（LangGraph 课程版客服） | 显式意图分类 + 知识飞轮 |

业界来源统一在[文末汇总](#七调研来源汇总)；正文用简称引用（如「Anthropic 上下文工程」）。所有外部结论均附 URL，A/B/C 结论附 `文件:行号`。

## 1. 组件全景（13 组件 / 6 层）

改造类型标记：**[保持]** 已达业界水平，只需文档化；**[对齐]** 增量补齐；**[重构]** 需要结构性改动。

| # | 组件 | 层级 | A 现状 | 目标一句话 | 类型 | 优先级 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 会话与状态一致性 | 会话 | MySQL 事实源 + 每轮重建（无 checkpointer） | 事实源与运行态分离；断线恢复语义明确为「事件可续传、轮次不续跑」 | [对齐] | P2 |
| 2 | 身份与访问控制 | 会话 | actor 三元组 + 访客禁写 + 跨主体 404 | 保持三元组隔离；把「记忆的作者-读者矩阵」写成可审计的契约 | [保持] | P3 |
| 3 | 查询理解 | 理解 | 无独立层，模型在 ReAct 内自由改写检索词 | 检索用词有唯一来源链；指代补全显式化、可评估、失败回落原句 | [重构] | P2 |
| 4 | 意图路由 | 理解 | 模型声明 request_kind + 按证据编译 | 保持声明式契约；补编排器前置分支；工具面回到 <20 软上限 | [对齐] | P2 |
| 5 | 主循环与预算 | 编排 | 三节点图 + 四重预算 + 确定性收口 | 保持；终止原因成为一等字段枚举，可统计降级率 | [对齐] | P1 |
| 6 | 子 Agent 协作 | 编排 | task_dispatch 1–3 个只读子 Agent，共享预算 | 保持只读并发；补「派发结果核验」与「派发理由+成本入审计」 | [对齐] | P1 |
| 7 | 人工审批与交易安全 | 编排 | 服务端提案 + 前端确认 + 幂等执行 | 保持（已是业界最强形态之一）；补齐 fail-closed 与拒绝理由回灌 | [保持] | P1 |
| 8 | 上下文拼装与缓存 | 上下文 | 九段 system 含可变内容；无缓存设计 | 静态前缀逐字恒定、动态内容走消息侧、缓存命中可观测 | [重构] | **P0** |
| 9 | 上下文压缩与归档 | 上下文 | 8 轮窗口 + 抽取式摘要（刻意不调模型） | 保持抽取式；补「归档 + result_ref 回查」，历史证据可追 | [对齐] | P2 |
| 10 | 记忆与画像 | 记忆 | 5 键偏好 + 12 槽 mission，生命周期完善 | 补双时态可回溯、冲突显式处置、投毒防护、行为记忆接线 | [对齐] | P1 |
| 11 | 工具系统 | 能力 | 19 工具 + Skill 按需加载 + 观察投影 | 工具合并至 <20 并留余量；错误即提示；投影带详略开关 | [重构] | P3 |
| 12 | 可靠性工程 | 质量 | 模型热切换 + 轮预算 + 成本估算落库 | 预算分层降级（main/lite/minimal/fallback）；成本按会话/意图/模型归因 | [对齐] | P2 |
| 13 | 质量体系 | 质量 | quality-v2 双主线 + 守卫分层 + 决策审计 | 评测三层化、pass^k 指标、门禁阈值规则、生产漂移监控、OTel 对齐 | [对齐] | P1 |

---

## 2. 逐组件设计

### 组件 1：会话与状态一致性 ｜ [对齐] P2

**现状**：会话事实源在 MySQL（`message` / `conversation_memory` / `agent_run`），图无 checkpointer（ADR-0009），每轮从事实源重建上下文；`_fence` 可取消在途 run 防止 late write（`memory.py:287-295`）。

**目标**：**「事实源 + 运行态」双轨**——事实（消息、摘要、mission、提案）永远以 MySQL 为准；运行态（本轮进行到哪一步、已发出哪些事件）落事件表。断线恢复的语义明确为：**事件可续传（前端重放已发生的事件），轮次不续跑（模型侧当前轮失效，重发即新轮）**。这比 B 的全量续跑简单，且与 A 的「每轮重建」哲学一致。

**关键机制**：
1. 新增 `agent_run_event` 表（`run_id + sequence + type + payload`），流式 token 事件除外，其余事件（decision/tool/answer）持久化——支持前端断线后按 `after=sequence` 续传。
2. 轮次幂等：重发同 `message_id` 走已有 `content_hash` 幂等（`state.py:172-173`），不产生重复回复。
3. 恢复语义写进 `support-contract.md`：断线超过 N 分钟重发视为新轮；进行中的提案不受影响（提案本就独立于轮次，5 分钟 TTL）。

**参考**：B 的 journal + `after=N` 断点续传 + run 租约（`ag_ui_journal.py:216-283`）；Anthropic「持久化执行、从中断处恢复」但 A 无需到该强度。

---

### 组件 2：身份与访问控制 ｜ [保持] P3

**现状**：所有查询谓词为 `(subject_type, actor_id, execution_scope_id)` 三元组，跨主体一律 404（不泄露存在性）；访客禁写长期偏好（`memory.py:177-178`）；知识检索带 ACL 平面（`knowledge_scope.py`）。

**目标**：保持现设计，**把「记忆的作者-读者矩阵」写成契约文档**——每类记忆（偏好/摘要/mission/工单/审计）写明：谁能写（用户/模型/运营）、谁能读（本人/访客/商家/管理端）、越权返回什么。现状散落在代码谓词中，文档化后可作为新功能的准入检查表。

**关键机制**：
1. 一页矩阵表：行=记忆资源，列=主体类型，格=读写允许与返回码（404 vs 403）。
2. 新增任何记忆资源时先填表再写代码（评审项）。

**参考**：B 的 buyer/session 双重归属校验；OWASP ASI06 的「per-tenant 命名空间」要求。

---

### 组件 3：查询理解 ｜ [重构] P2

**现状**：无独立层。检索用词由模型在 ReAct 中自由改写，`compose_search_query` 用改写**替换**提交词、原话并行供词法融合（`knowledge.py:170-191`）。多轮指代补全完全依赖主模型自觉。

**目标**：**检索用词有唯一来源链，且可评估**。检索文本 = 组装（用户原话 ∪ mission.required_terms ∪ 焦点钉扎词），模型改写只允许作为「附加变体」并行送入，不得替换原话。对指代式短问句（"那这个保修多久"）增加一次轻量改写步骤，失败回落原句。

**关键机制**：
1. **来源链收口**：`search_knowledge` / `search_skus` 的最终查询词由服务端组装，模型只提供可选的 `query_variant`（附加，不替换）——把「模型改写替换提交词」改为「原话必在、改写可加」。
2. **指代改写步骤**（可选、轻量）：仅当本轮问句命中「指代特征」（含"这个/那件/它"+ 短句）时，用一次小模型改写并结合焦点/mission 补全；规则纪律借鉴 C：**完整独立问句必须原样透传**（避免把订单号塞进通用政策检索）。
3. **降级契约**：改写失败/超时 → 回落原句，绝不阻断本轮（C 的 coref 降级语义）。
4. **评测**：建 20 例 coref 评测集（含"带指代补全"与"独立句透传"两类，后者是负例防过度改写），纳入 quality-v2 的 support 线。

**参考**：C 的 coref 节点（`coref.py:9-19` + `prompts.py:152-168` 业务规则 + `eval_coref.py`）；Anthropic「just-in-time 检索」的查询构造建议。

---

### 组件 4：意图路由 ｜ [对齐] P2

**现状**：无分类器；模型在终答 JSON 声明 `request_kind` 五分类，`compile_decision` 按「声明 × 证据」编译答/弃/转（`compile.py:42-72`）；Skill 预告按关键词打分注入（`business_skills.py:27-49`）。

**目标**：**保持声明式契约（不做独立分类器），补两层**：① 编排器前置分支兜住「不能交给模型」的情况；② 工具面收敛回 20 以下，避免「工具即路由」退化。

**关键机制**：
1. **前置分支**（编排器层，先于模型）：a) 存在未决提案/待确认卡时，新消息先提示"有待确认事项"（对齐 B 的 awaiting 拦截）；b) 访客/未知主体等确定性场景直接走模板，不调模型（对齐 B 的缓存快路径精神）。
2. **工具面红线**：工具数与路由准确性成反比（OpenAI 官方建议 <20）。A 现有 19 个已贴线，新增能力优先做成 Skill（已有 `load_skill` 延迟加载机制）；对 6 个 `get_*` 订单工具做合并评估（见组件 11）。
3. **留一个可触发的升级条件**（写进 ADR-0003）：当出现跨领域（导购+售后+商家）或需要小模型分流降本时，才引入向量路由做**工具预筛**，不替换主循环决策。

**参考**：OpenAI function calling 指南（<20 软上限、tool search 延迟加载）；Anthropic routing 模式的适用前提；Microsoft ISE 语义路由实测（可扩展性收益 vs 延迟）；B 的 `orchestrator.py:297-334` 五分支。

---

### 组件 5：主循环与预算 ｜ [对齐] P1

**现状**：手写三节点图，四重预算（6 模型调用 / 10 工具 / 2 检索 / 90s deadline），超限 `close_degraded_turn` 确定性收口并记录终态。

**目标**：**保持；让「为什么结束」成为一等数据**。每轮结束原因归一为枚举，落 `decision_record`，使降级率可统计、可告警。

**关键机制**：
1. **终止原因枚举**：`budget_exceeded / deadline / retrieval_empty / guard_violation / repair_exhausted / handoff / completed`（现状是散落的文本与标记，收敛为枚举字段 `close_reason`）。
2. **MAST 自检表**：把 MAST 论文 14 项失败模式与本项目现有护栏的对应关系写成检查表（已在 ADR-0013 分层中覆盖大半），作为后续每次新增能力的"防回归清单"。
3. **降级率指标**：`close_reason != completed` 的占比进 observability 面板（当前只有零散日志）。

**参考**：OpenAI Agents SDK `error_handlers` 按 `max_turns` 等分类返回受控兜底；MAST《Why Do Multi-Agent LLM Systems Fail》（14 项失败模式，"更强基座不足以解决，需要结构性方案"）。

---

### 组件 6：子 Agent 协作 ｜ [对齐] P1

**现状**：`task_dispatch` 派发 1–3 个只读子 Agent（`create_react_agent`），`asyncio.gather` 并发，各自独立上下文，只回传结论文本；模型/工具调用计入主循环同一预算与审计（`before_attempt` / `tool_tick`）。

**目标**：**保持只读并发架构；补两件事**：派发结果的证据核验、派发决策的可回归数据。

**关键机制**：
1. **派发结果核验**：子 Agent 回复文本中的商品/订单 ID，与本轮真实工具回执做差集；未核验 ID 存在时，把结论替换为"请用业务工具复核"（对齐 B 的做法）。
2. **派发审计补两列**：每次 `task_dispatch` 记录「派发理由（可并行/需隔离/链路深）+ 子 Agent token 消耗」——使"派发是否值得"可用消融数据回答（已有 `子智能体消融实验` 可产出此表）。
3. **只读约束的理由固化进 ADR-0010**：子 Agent 只读不只是权限最小化，而是**保证并行分支之间不存在需要共享的隐式决策**（Cognition 原则；否则并行会产生互相冲突的决策）。

**参考**：B 的 `task_dispatch_tool.py:120-142` 未核验 ID 拒绝采信；Anthropic 多 Agent 系统（子 Agent=智能压缩器，只回传 1–2k token）；Cognition《Don't Build Multi-Agents》（冲突决策边界）。

---

### 组件 7：人工审批与交易安全 ｜ [保持] P1

**现状**：`propose_*` → 服务端提案（5 分钟 TTL）→ 前端确认卡（前端独立向 Java 复核商品/地址）→ 用户确认（CSRF + version 乐观锁）→ 幂等执行（`recover_only`）→ SUCCEEDED/FAILED/UNKNOWN；**没有任何模型工具可以直接成交**。

**目标**：**该形态已是业界最强之一，保持；补齐三处语义并文档化**。

**关键机制**：
1. **参数畸形 fail-closed**：提案参数在服务端校验；任何缺失/畸形/越界一律拒绝并转人工提示——不得落入"宽容解析"（对齐 OpenAI：畸形参数不进判定函数，直接转人工）。
2. **拒绝理由回灌**：提案失败/过期/被拒时，原因作为下一轮观测注入，模型可直接修正重提（对齐 `rejection_message` 语义）。
3. **授权只认服务端快照**：确认卡上的商品/地址/金额必须来自服务端快照，前端只回传 decision（A 已实现"前端独立复核"，把它在文档中标注为**安全依据**而不仅是体验设计）。
4. **不可绕过的表述升级**：把"没有任何模型工具可以直接成交"从权限约定升级为工具注册层 deny（deny 在任何模式下生效）——写进 `contracts.md`。

**参考**：OpenAI Agents SDK HITL（`RunState` 持久化暂停/恢复、`needs_approval` 谓词、fail-closed）；Claude Agent SDK 权限求值顺序（deny 规则在 `bypassPermissions` 下仍生效）；ADK `require_confirmation` 谓词。

---

### 组件 8：上下文拼装与缓存 ｜ [重构] **P0**

**现状**：system prompt 九段拼接，其中「只读上下文」（preferences/summary/mission）与「焦点事实块」每轮可变（`session.py:533-558`）；全仓无任何 prompt 缓存设计与观测。

**目标**：**静态前缀逐字恒定，动态内容全部走消息侧，缓存命中可观测**。这是本轮改造中收益最明确的一项：官方数据为缓存读 0.1×（省 90%）、长 prompt 延迟降最多 85%；生产侧经验（Manus，agent 输入输出比 ~100:1）称 KV-cache 命中率是生产 Agent 最重要的单一指标。

**关键机制**：
1. **前缀重排**：`工具定义 → system（角色契约 + 冻结策略 + Skill 目录）→ 会话消息`。system 内**不得出现**任何每轮可变值（时间戳、偏好、mission、焦点、订单状态）——这些移入「本轮材料」消息（A 已有 `_turn_context` 形态的插入点，改为消息侧即可）。
2. **动态内容位置**：本轮材料插在最后一条用户消息**之后**（现状机制保留），保证 ReAct 第 1 步的 prompt 是第 2 步的严格前缀。
3. **工具 schema 稳定**：工具列表与字段顺序确定性排序（B/Mewhelp 均已按此做，A 的 REGISTRY 需固定序）。
4. **缓存断点标记**：若上游支持显式断点（Anthropic 最多 4 个），标在工具定义与 system 之后；OpenAI 系自动前缀匹配则只需保证 1、2 两条。注意最小缓存门槛（Claude 系 512–4096 token、OpenAI 1024），确认前缀真的过线。
5. **观测**：`provider.chat` 的 usage 中 `cache_read/cached_tokens` 写入 `model_attempts` 与日志（A 已有 usage 采集，加一列即可）。
6. **不变量测试**：三条单测钉死（对齐 C 的做法）—— ① system 逐字恒定且唯一；② 可变载荷不出现在 system；③ ReAct 步间严格前缀。

**参考**：C 的三不变量 + 单测（`test_prompt_cache_prefix.py`，实测 cache_read 2048→0 的教训）；B 的 `prompt_cache.py`（标记/审计/回退三件套 + PrefixTracker 漂移审计）；Anthropic prompt caching（写 1.25×、读 0.1×、4 断点、chained 失效顺序 tools→system→messages）；OpenAI cookbook（durable content 在前、volatile 在后；schema key 变化即失效）；Manus（前缀稳定、append-only、mask don't remove）。

---

### 组件 9：上下文压缩与归档 ｜ [对齐] P2

**现状**：8 整轮 / 6500 token 窗口 + 抽取式摘要（更早 user 原话截 240 字符 / 1400 token 预算 / 最多 32 条，标 `not_business_facts`，显式披露 `dropped`；`memory.py:33-85`）；tool 消息天然不进历史（`session.py:510-515`）。

**目标**：**保持抽取式摘要（反漂移，是 A 相对 B/C 的优点）；补「归档 + 引用回查」，让跨轮历史证据可追**。

**关键机制**：
1. **工具回执归档表**：工具结果完整落库（`run_id + tool_call_id + payload + sha256`），上下文仅保留投影（A 已有投影）+ `result_ref` 引用。
2. **回查工具**：新增 `lookup_conversation_evidence(result_ref | product_id | batch)`，返回历史事实并**显式标注"历史观察值，当前价格/库存必须以实时工具为准"**（对齐 B 的 `observation_scope`）。
3. **压缩边界不动摇**：抽取式摘要、dropped 披露、`not_business_facts` 标记全部保留——业界压缩失败案例（Devin 自写笔记不完整、摘要漂移）恰恰支持"事实不进摘要"的路线。
4. **压缩相关观测**：记录触发次数与压缩前后 token（A 目前无此指标）。

**参考**：B 的 `context_evidence` + `conversation_fact_lookup` + `result_ref`（含被拒摘要不可召回）；Anthropic context editing（清旧工具结果：token -84%，且是最安全的压缩形式）；LangChain Deep Agents（>20k token 工具结果 offload 到文件系统，留路径 + 10 行预览）；A 自身的抽取式摘要哲学（`memory.py:33-42`）。

---

### 组件 10：记忆与画像 ｜ [对齐] P1

**现状**：`user_preference` 5 键 + 来源（explicit/inferred）+ 证据溯源（逐字引用）+ TTL（inferred 30 天）+ 墓碑删除 + version 乐观锁；mission 12 槽会话级；`apply_behavior_inference` 已实现但**无调用点**；`answer_feedback` 无消费者。

**目标**：**在已有的正确地基上（来源优先级/证据/墓碑/TTL 四条业界主线都已踩中），补齐四条**：可回溯、冲突显式处置、投毒防护、行为记忆接线。

**关键机制**：
1. **双时态最小版**：`user_preference` 写入新值时把旧值留成历史行（`superseded_at`），查询支持 `as_of`——回答"上周预算是 8 千还是 1 万"，客诉时可复现当时推荐依据（对齐 Zep 的 invalidate-not-delete）。
2. **冲突显式处置**：写入前比对同键旧值，产出 `ADD/UPDATE/DELETE/NOOP` 决策并记台账；补**跨键一致性校验**（"likes=红色 vs avoid=红""purpose=送礼 vs budget=9.9包邮"），冲突时标冲突并要求澄清而非静默覆盖（`catalog_gate` 已有 `conflicting` 语义可复用）。
3. **投毒防护**（OWASP ASI06 口径）：a) 禁止 agent 自身输出写回偏好（当前 `remember_preference` 已有逐字引用原话约束，把它升级为"证据必须是 user 角色消息"的硬断言）；b) inferred 偏好只影响排序、不得触发交易动作（固化为测试断言）；c) 每条写入留 provenance（explicit/inferred/behavior）+ 支持批量回滚。
4. **行为记忆接线**：为 `apply_behavior_inference` 选择接线点（浏览/点击流数据源在 Java 侧）或**显式宣布不接线**并从四层记忆叙事中移除，不留悬空设计。
5. **评测补三类负样本**（对齐 LongMemEval 五能力）：知识更新（预算变化后旧问题给新答案）、时序（过期 inferred 不参与）、遗忘（删除后同行为不复活）、弃权（无记忆不编造）。
6. **5 键当 core memory 精修**：给每键补「给模型看的 description」（何时读/何时写/合法值域）与容量上限说明——这是 Letta memory block 的核心实践。

**参考**：Zep 双时态知识图谱（t_valid/t_invalid，失效不删除）；mem0 四操作（ADD/UPDATE/DELETE/NOOP）；Letta memory block（label+description+limit）；OWASP Agentic Top 10 2026 ASI06（记忆投毒、禁止再摄入 agent 自身输出）；LongMemEval（知识更新/时序/弃权）；Generative Agents（recency 0.995 衰减可选进阶）。

---

### 组件 11：工具系统 ｜ [重构] P3

**现状**：19 个工具（REGISTRY 集中定义）+ Skill 按需加载 + 按工具定制的观察投影（6500 字节上限）+ 权限门 + "不做什么"的诚实边界描述（ADR-0012 决定 5）。

**目标**：**工具面回到「少而工作流化」**——19 个已贴 OpenAI 的 20 软上限，继续增长会稀释模型的选择准确率。

**关键机制**：
1. **合并评估**：6 个 `get_*` 订单只读工具 → 1–2 个「按需返回字段」的查询工具（Anthropic `get_customer_context` 思路）；`search_skus/recommend_skus/compare_skus` 检查语义重叠，保留差异化的三个、其余收敛。
2. **`response_format` 枚举**：投影加 `concise|detailed` 开关，让模型在预算紧张时自选（Anthropic 实测 concise 约为 detailed 的 1/3 token）。
3. **错误即提示**：错误回执含「正确格式示例 + 下一步建议」（A 的 `unknown≠失败` 语义已达标，补格式示例）。
4. **命名空间**：工具名前缀统一（`shopping_*` / `order_*` / `knowledge_*`），减少模型混用。
5. **工具迭代带评测**：每次改工具描述/参数，跑 quality-v2 对应桶，看工具调用次数与 token 变化。

**参考**：Anthropic《Writing effective tools for agents》（少而工作流化、response_format、25k 上限、错误即提示、工具要跑 eval）；OpenAI（<20 软上限、tool search）；B 的 `capability_registry` 白名单与工具面收窄。

---

### 组件 12：可靠性工程 ｜ [对齐] P2

**现状**：模型热切换（`model_runtime_config` 5s TTL）+ 端点/模型白名单 + 轮预算（6/10/2）+ `cost_estimate_cny` 落 decision_record。

**目标**：**预算从「耗尽即收口」升级为「分层降级」；成本可归因**。

**关键机制**：
1. **预算四档降级**（对齐 B 的 `budget.py`）：>50% main / 20–50% lite（换小模型）/ 5–20% minimal（加简洁约束）/ <5% fallback（规则兜底不调模型）。A 目前是单档熔断，改造面小。
2. **降级顺序**（对齐 LiteLLM 实践）：缩上下文 → 换小模型 → 确定性收口/转人工。
3. **成本归因三要素**：按会话 / 意图（request_kind）/ 模型分别汇总 token 与成本（A 已有 run 级汇总，加两个 group by 即可）。
4. **缓存收益核算**：与组件 8 联动，按「缓存读 token / 总输入 token」出命中率报表。

**参考**：B 的 `budget.py:32-37` 四档 + 预留-结算两段式（"不能把未知成本当免费"）；LiteLLM 多层级预算与 429 前置拦截；FrugalGPT/RouteLLM（按难度付费，简单问答走小模型）。

---

### 组件 13：质量体系 ｜ [对齐] P1

**现状**：quality-v2 双主线（shopping 87 题 + support 83 题，含 14+8 多轮）；守卫分层（ADR-0013：证据契约永久 + 意图帧可降级）；`decision_record` 全量审计（prompt 版本/预算/成本）；相似度拒答阈值；judge 校准集 `judge-calibration.jsonl`。

**目标**：**评测三层化 + 面向稳定性的指标 + 门禁阈值有依据 + 生产漂移可发现**。

**关键机制**：
1. **评测三层**（成本对齐）：L1 确定性断言（每次改动跑，秒级——引用 ID 必须在检索结果里、金额必须与 Java 回执一致）；L2 轨迹 + judge（按节奏跑，判 outcome 不判固定路径）；L3 A/B（仅大改动）。
2. **pass^k 指标**：客服场景要"连续 k 轮都对"而非"至少一次对"（单次 75% → 3 次全过仅约 42%）；对对外承诺类指标用 pass^k（k=3）。
3. **门禁阈值规则**（对齐 Microsoft 电商案例）：总通过率跌幅 >2pp 阻断、**任一意图类目跌幅 >5pp 阻断**（总分掩盖单类目回退）；阈值按本项目评测噪声定（重复跑波动 ±1% 则设 2%）。
4. **badcase 闭环**：每个修复的问题固化为"历史失败探针"用例，永久保留；评测集随主干刷新，不冻结。
5. **judge 可靠性**（多数已达标，补齐）：异家族 judge（已有）、每条回答换位各评一次取平均、参考解 + CoT 引导、每维度独立 judge、允许 "Unknown"。
6. **生产漂移监控**：1% 随机采样线上会话跑同一套 judge，7 天滚动均值告警——抓"代码没变但模型/上游变了"的退化。
7. **OTel GenAI 语义对齐**：span 命名（`invoke_agent`/`execute_tool`/`chat`/`retrieval`）、属性带模型/token/工具名/错误、prompt 版本入 metadata、内容捕获默认关闭按需脱敏（`gen_ai.*` 目前均为 Development 状态，锁版本）。**注意：AWS 的 contextual grounding check 官方明确不支持对话式判答，对话场景的 grounding 闸门需自建**（A 的引用复核已在做）。
8. **幻觉防护三件套确认**：程序化回链（已有：引用提交前 `FOR SHARE` 复核）+ 语义闸门（相似度阈值已有，补按 request_kind 分档）+ 拒答作为一等公民写进评分规则。
9. **lethal trifecta 检查**：A 目前"不可信内容"（商品/知识/评价）+ "有害动作"（退款/取消）同时存在，但没有自由外发能力（无邮件/短信/HTTP 外发工具）——**保持现状即安全**；把"不引入自由外发工具"写成红线。

**参考**：Anthropic《Demystifying evals for AI agents》（评测词汇表、deterministic-first、pass@k vs pass^k、read the transcripts）；Microsoft 电商回归案例（per-intent 门禁、canary、历史探针、7 天滚动告警）；MT-Bench judge 研究（位置/自增强偏差及缓解）；Simon Willison lethal trifecta；OTel GenAI 语义约定；RAGAS faithfulness。

---

## 3. 落地路线（按「收益 / 成本」排序）

### 第一批：P0–P1，收益明确、改动面小

| 项 | 组件 | 交付物 | 验收 |
| --- | --- | --- | --- |
| 1 | 8 上下文缓存 | 前缀重排 + usage 采集 + 三不变量单测 | cache_read 占比可观测；单测绿；quality-v2 不回归 |
| 2 | 5 终止原因 | `close_reason` 枚举 + 决策记录字段 | 降级率出现在审计与报表 |
| 3 | 6 子 Agent 核验 | 未核验 ID 拒绝采信 + 派发理由/成本入审计 | 单测 + 消融实验表 |
| 4 | 10 记忆双时态 | `superseded_at` 历史行 + `as_of` 查询 | 单测：预算变更后可查旧值 |
| 5 | 13 pass^k + 门禁 | pass^3 指标 + per-intent 阻断规则 | 评测报告新口径 |

### 第二批：P2，结构化补齐

| 项 | 组件 | 交付物 |
| --- | --- | --- |
| 6 | 9 证据归档回查 | `tool_evidence` 表 + `lookup_conversation_evidence` 工具 |
| 7 | 3 查询理解收口 | 检索词来源链 + 指代改写 + 20 例 coref 评测 |
| 8 | 10 冲突处置 + 投毒防护 | 四操作台账 + 跨键校验 + "证据必须是 user 消息"断言 |
| 9 | 12 预算分层 | 四档降级 + 成本三要素归因 |
| 10 | 1 事件续传 | `agent_run_event` 表 + 断线续传 |

### 第三批：P3，结构性重构（独立 PR + 评测关卡）

| 项 | 组件 | 交付物 |
| --- | --- | --- |
| 11 | 11 工具合并 | 19 → ≤15；工具迭代评测流程 |
| 12 | 13 漂移监控 + OTel | 1% 采样 judge + span 语义对齐 |
| 13 | 10 行为记忆 | 接线或正式宣告不接线 |

**风险提示**（来自 10-07 批次五/六的教训）：涉及 `provider.py` / 切分逻辑等大文件的批量替换必须先立评测关卡（v17 冻结基线口径不变），小步改造、逐步验证。

## 4. 与现有 ADR 的关系

- **不推翻**：ADR-0009（无 checkpointer）与 ADR-0013（守卫分层）在本蓝图中是**被保持**的设计。
- **需补充**：ADR-0010 补「子 Agent 只读的理由」；ADR-0003 补「何时引入语义路由」的触发条件；新增 ADR 建议：「上下文前缀稳定性与缓存」（组件 8）与「记忆的双时态与冲突处置」（组件 10）。

## 5. 未决问题（需要独立决策）

1. 行为记忆是否接线（组件 10）——取决于 Java 侧是否有可用的行为数据源与合规边界。
2. 是否引入语义缓存（B 的快路径）——A 首轮即需检索，收益场景不同，建议不做。
3. `answer_feedback` 的消费者（暂保持展示，或接飞轮式知识缺口池——C 的模式）。

## 6. 调研方法说明

- A/B/C 结论均来自源码逐行核对（附 `文件:行号`），B/C 的完整分析见当日改动记录。
- 业界结论均来自一手来源（官方工程博客/论文/官方文档），URL 见文末；二手推断已在来源汇总中标注。
- 本蓝图**未实施任何代码改动**；所有"现状"描述对应 2026-10-07 的 HEAD。

## 七、调研来源汇总

**上下文工程与缓存**
- Anthropic《Effective context engineering for AI agents》https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic 上下文管理公告（context editing 数据）https://claude.com/blog/context-management
- Anthropic prompt caching https://claude.com/blog/prompt-caching
- OpenAI Prompt Caching 201 https://github.com/openai/openai-cookbook/blob/main/examples/Prompt_Caching_201.ipynb
- AWS Bedrock prompt caching（4 断点/最小 token/链式失效）https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html
- Manus《Context Engineering for AI Agents》https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- Chroma《Context Rot》https://www.trychroma.com/research/context-rot
- LangChain Deep Agents 上下文管理 https://www.langchain.com/blog/context-management-for-deepagents
- Cursor 自总结训练 https://cursor.com/blog/self-summarization

**记忆系统**
- MemGPT 论文 https://arxiv.org/abs/2310.08560 ｜ Letta memory blocks https://docs.letta.com/guides/agents/memory-blocks
- mem0 论文 https://arxiv.org/abs/2504.19413 ｜ mem0 how-it-works https://docs.mem0.ai/core-concepts/how-it-works
- Zep 论文（双时态）https://arxiv.org/abs/2501.13956 ｜ Graphiti https://github.com/getzep/graphiti
- Generative Agents https://arxiv.org/abs/2304.03442
- OWASP Agentic Top 10（2026）https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- LongMemEval https://arxiv.org/abs/2410.10813 ｜ LoCoMo https://arxiv.org/abs/2402.17753
- Claude Code memory https://code.claude.com/docs/en/memory ｜ ChatGPT memory FAQ https://help.openai.com/en/articles/8590148-memory-faq

**架构与编排**
- Anthropic《Building effective agents》https://www.anthropic.com/engineering/building-effective-agents
- Anthropic 多 Agent 研究系统 https://www.anthropic.com/engineering/multi-agent-research-system
- Cognition《Don't Build Multi-Agents》https://cognition.com/blog/dont-build-multi-agents
- MAST《Why Do Multi-Agent LLM Systems Fail》https://arxiv.org/abs/2503.13657
- OpenAI Agents SDK HITL https://openai.github.io/openai-agents-python/human_in_the_loop/
- Claude Agent SDK 权限 https://code.claude.com/docs/en/agent-sdk/permissions
- Google ADK 工具确认 https://adk.dev/tools-custom/confirmation/
- Anthropic《Writing effective tools for agents》https://www.anthropic.com/engineering/writing-tools-for-agents
- OpenAI function calling guide https://platform.openai.com/docs/guides/function-calling

**评测、守卫与可观测性**
- Anthropic《Demystifying evals for AI agents》https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Microsoft 电商回归测试案例 https://learn.microsoft.com/en-us/training/modules/aaai-design-evaluation-frameworks-multi-agent-azure/5-build-regression-test-agent-drift
- MT-Bench（LLM-as-a-judge）https://arxiv.org/abs/2306.05685
- Simon Willison《The lethal trifecta for AI agents》https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
- Google 分层注入防御 https://blog.google/security/mitigating-prompt-injection-attacks/
- OTel GenAI 语义约定 https://github.com/open-telemetry/semantic-conventions-genai
- AWS contextual grounding check https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html
- RAGAS faithfulness https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/

**B/C 项目分析证据**：见 `docs/改动记录/2026-10-07/Agent组件对齐蓝图调研.md`（含 B/C 源码逐行证据索引）。
