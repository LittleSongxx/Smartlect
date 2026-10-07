# Agent 组件对齐蓝图（调研与设计）

日期：2026-10-07 ｜ 状态：**调研与设计完成，未实施任何代码改动** ｜ 关联：`docs/agent-component-blueprint.md`

## 需求

在完成三方对比（本仓库 / `~/code/Agent/multi-agent/smartlect`（B）/ `~/code/Java/mewhelp`（C））后，要求：全面对齐 B、C 的优点与业界成熟做法，以"清晰完整可描述"为目标，从完整 AI Agent 组件视角给出本仓库各模块的重构参考方案，并联网调研。

## 交付物

**主文档**：[`docs/agent-component-blueprint.md`](../../agent-component-blueprint.md) —— 13 组件 / 6 层的对齐蓝图，含：

- 组件全景表（现状 → 目标一句话 → 改造类型 [保持]/[对齐]/[重构] → 优先级）
- 逐组件设计：现状（附 `文件:行号`）→ 目标 → 关键机制（每条一句话）→ 参考
- 三批落地路线与验收口径、与现有 ADR 的关系、未决问题、调研来源汇总（含 URL）

## 调研过程与证据

1. **B/C 源码级分析**（三个 Explore 子任务，逐文件核对）：
   - B 的意图路由/编排：`orchestrator.py:297-334` 五分支、`task_dispatch_tool.py:120-142` 未核验 ID 拒绝采信
   - B 的上下文工程：`context_governance.py:598-645` 白名单校验摘要、`prompt_cache.py` 缓存三件套、`context_evidence` + `conversation_fact_lookup` 归档回查、token 网关实测校准（`context_governance.py:373-437`）
   - B 的记忆：`semantic_memory.py` 事实+向量同事务、(memory_id, version, statement) 三元组审批、材质硬过滤链路
   - C 的 coref/意图/飞轮：`coref.py:9-19`、`intent.py:23-34`、`flywheel.py:42-75`
2. **联网调研**（四路 general-purpose 子任务，均要求一手来源）：上下文工程与缓存（Anthropic/OpenAI/Manus/Chroma/LangChain/Cursor）、记忆系统（MemGPT/Letta、mem0、Zep/Graphiti、OWASP ASI06、LongMemEval）、架构与编排（Building effective agents、多 Agent 研究系统、Cognition、MAST、OpenAI Agents SDK、ADK、Claude Agent SDK）、评测/守卫/可观测性（Demystifying evals、Microsoft 电商门禁案例、MT-Bench、lethal trifecta、OTel GenAI）。全部 URL 已汇总进主文档第七章。

## 核心结论（摘要）

- **P0（收益最明确）**：组件 8 上下文拼装与缓存 —— 现状 system prompt 含每轮可变内容且无缓存设计；目标为"静态前缀逐字恒定、动态内容走消息侧、cache_read 可观测"，参考 C 的三不变量单测与 B 的完整实现。
- **P1**：终止原因枚举（组件 5）、子 Agent 结果核验（组件 6）、记忆双时态与冲突处置（组件 10）、pass^k 与 per-intent 门禁（组件 13）。
- **[保持]**：交易提案审批（组件 7）、身份三元组（组件 2）——已达业界最强形态，只需文档化。
- **[重构]**：查询理解（组件 3）、工具面收敛（组件 11）——结构性改动，排第三批。

## 验证方式

- 本次为设计文档，无代码改动、无测试执行；B/C 与 A 的结论均有 `文件:行号` 证据（HEAD = 2026-10-07）。
- 主文档明确标注"未实施"，并列出三处未决问题（行为记忆是否接线、语义缓存是否引入、answer_feedback 消费者）。

## 未完成项

- 蓝图未拆分为可执行的 issue/PR；建议按主文档第三章批次推进，第一批动工前先立评测关卡（沿用 10-06 经验：涉及大文件替换的改造必须小步 + 评测把关）。
- 建议新增的两份 ADR（"上下文前缀稳定性与缓存""记忆的双时态与冲突处置"）尚未撰写。
