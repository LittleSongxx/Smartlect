# ADR-0012: 借鉴 EchoMind 模式的 Agent 架构清晰化重构

日期：2026-10-04
状态：已接受（细化并扩展 ADR-0009 / 0010）

## 背景

对照分析 Smartlect assistant 与 EchoMind（`~/code/Agent/EchoMind`，一个约 5.4K 行的
多智能体客服框架）后确认：Smartlect 在**控制面工程**（预算/租约/幂等/审计/评测合同）
上全面领先，不应向 EchoMind 看齐；但 EchoMind 在**架构清晰度**上有七个模式值得移植——
本次重构的目标是架构与流程的可讲述性（每个组件的职责、路由、边界一眼可查），
不是上线成熟度。硬约束：不改变 ADR-0009 锁定的三节点图语义与 v27 评测合同的判定逻辑。

## 决定

### 1. AgentProfile 声明式角色契约（单一事实源）

新模块 `agents/shopping/profiles.py`：一个 frozen dataclass（name/role/mission/
input_contract/output_contract/tool_scope/boundaries/预算）同时驱动三件事——
系统提示词渲染（`render_profile`）、子智能体工具面收窄、契约测试断言。
主 Agent（`SHOPPING_MAIN`）的系统提示 = 契约块 + v27 叙事原文（版本升 v28，
走 PromptStore 既有的「代码版本高→DB 落 DRAFT 等人工激活」流程）。

### 2. 子智能体分型 + 可解释路由（细化 ADR-0010）

单一 `SUB_AGENT_PROMPT` 拆为三个 profile：`retrieval-scout`（知识+选品）、
`order-reader`（本人订单事实）、`comparator`（对照比较）——各自声明不同的只读工具面
与输出契约。派发前由 `route_sub_agent(task)` 做确定性关键词路由（比较信号 > 订单信号 >
默认检索），路由结果（profile + routing_reason）随 dispatch 元数据回传。
**不采用 EchoMind 的 LLM 意图识别**——路由本身零模型调用、可单测、错路由可在审计里直接定位。

### 3. 子智能体走完整 invoke() 路径（修复审计旁路）

ADR-0010 遗留问题：`sub_invoke` 直调 `_invoke`，绕过幂等台账、RBAC、product_scope
范围闸与 `gen_ai_span`——与「没有第二条更弱的进工具的路」的自我声明相悖。
现改为调用完整 `invoke()`（allowed=路由到的 profile 工具面；provider 不透传，
子智能体不能嵌套派发）。子调用以独立 call_id 记入主 run 的工具台账。

### 4. 派发结果确定性组装（Composer 降级模式）

`dispatch.compose_results`：gather 后不烧模型调用，纯结构化组装——分行结论
（✓/✗ + 路由 profile）、`all_succeeded` 汇总、`merge_instruction` 合并指导；
部分失败（timeout/failed）显式标注并要求主答复披露。台账 receipt 保留全量 results，
模型观察只投影组装层产物（6500 字节观察上限的既有防御不再被多任务结论撑爆）。

### 5. 工具「诚实边界」声明

19 个工具 description 统一补负面声明（「不做什么」）；订单/支付/退款回执经
`order_observation` 投影附加状态语义（受理≠终态、unknown≠失败、查询不构成办理）。
防护重心仍在执行侧（范围闸/引用复核），认知侧从工具层压制幻觉式越权叙述。

### 6. decision 可解释事件（routing_reason 模式）

`EVENT_TYPES` 新增 `decision`：澄清闸判定、子智能体路由结果、目录模板收口触发、
终答修复轮启动——每个关键分叉以 `{fork, reason, detail}` 落 `agent_run_event`
并随 SSE 透出；前端把 fork 映射为用户可读进度文案。「为什么这轮这么走」
在事件表里可查、可重放，不再只存在于管理端审计快照。

### 7. Skill 渐进披露 + 澄清闸 + 检索健康度

- `suggest_skills(question)`：按 Skill 的 intents 关键词确定性打分，注入一行
  「本轮Skill预告」——load_skill 仍由模型显式调用（保留审计台账）；
  `render_loaded_skills` 给指令注入加 6000 字符预算，超出披露名单并可单独 load_skill。
- `clarify_gate.needs_clarification`：两条零误报确定性判据（比较目标不足、纯功能词问句），
  命中注入「优先产出 clarify 型终答」引导并发 decision 事件；不强制改判、不新增往返。
- `knowledge.BackendHealth`：检索后端滑动窗口健康度，连续失败主动跳过（时间窗半开探测），
  跳过决策写入 `retrieval.backend_health` 元数据；ES BM25 与 Qdrant ANN 由串行改为
  `asyncio.gather` 并行召回（墙钟从相加变为取最大）。**不采用 EchoMind 的
  路由分数反馈环**——Smartlect 主 Agent 只有一个，健康度闭环落在检索后端选择上才有效。

### 8. 真 token 流式（修复最大名实不符）

`session.on_token` 用 `extract_streamed_answer` 从部分 JSON 流抽取 answer 字段，
双闸节流（≥120 字符或 ≥0.4s）以 `message_delta` 增量事件落库；`finish_answer`
的最终 `message_delta` 带 `replace: true` 作为权威全文收口，前端（增量拼接 + replace
覆盖 + completed 快照三级对账）重放幂等。修复了该函数两处潜伏 bug：非 JSON 缓冲
不剥尾部空白；转义序列跨块时中间态破坏前缀扩展性（改为「永远只返回可解码前缀」）。

### 9. 不借鉴的部分（显式记录）

- LLM 生成式记忆摘要（EchoMind 的会话压缩）——Smartlect 抽取式摘要是防漂移的刻意选择。
- 无审计工具层 / 进程内 trace——与「没有第二条更弱的路」冲突。
- 名为 mcp 的自研进程内工具框架——Smartlect 的 mcp.py 是真 JSON-RPC 端点，保持现状。
- 无流式架构——Smartlect 已有 SSE 基建，本次把流式做真而非推倒。

## 后果

- 新增/扩展测试：`test_profiles.py`（profile 契约 + 路由）、`test_dispatch_subagent.py`
  （分型工具面/组装器/并发合并）、`test_streaming_answer.py`（前缀扩展不变量）、
  `test_retrieval_health.py`（健康度 + 并行召回）、前端 `agent-stream.test.ts`
  （增量/replace/decision 事件）；全量 280×2 遍后端 + 76 前端测试绿。
- 清理收敛残留：merchant/ads `__pycache__`、`build/lib`、provider 死代码 `_stream()`、
  `attach_merchant_audit`、双处 `MODEL_CALL_LIMIT`、双处 rerank 提示词、
  `decision_record` 改从 policy 取预算常量（单一事实源）。
- PROMPT_VERSION v27→v28（契约块前置）；节点语义与评测合同判定逻辑未动，
  live 评测栈可按需另跑。
