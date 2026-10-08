# ADR-0010: 并行子智能体（SubAgent-as-Tool）与框架原生组件采纳

日期：2026-10-04
状态：已接受（修订 ADR-0009 的部分立场）

## 背景

ADR-0009 曾以「跨请求持久化 HITL 更强」为由保留全部手写编排。复审后按「引入框架就尽量用框架」的原则，
在不削弱既有契约（预算、fail-closed、评测断言）的前提下，把框架已有的组件逐步换成原生实现。

## 决定

### 1. 多智能体形态：主 Agent 单干优先 + `task_dispatch` 按需派发（SubAgent-as-Tool）

- **不是** supervisor-workers 常驻架构——演示店没有持续并行负载，常驻 worker 只会增加成本与故障面。
- 主 Agent（手写有界 ReAct）新增 `task_dispatch` 工具：把 1-3 个**独立只读检索任务**并行交给子智能体。
- 每个子智能体 = **`langgraph.prebuilt.create_react_agent`**（框架预构建 ReAct 循环），工具面收窄为
  7 个只读工具（`StructuredTool` 包装既有 REGISTRY，args_schema 复用 Pydantic strict 模型），
  `asyncio.gather` 并发，只回传最终结论文本——中间工具事件不进主上下文（上下文隔离正是派发判据之一）。
- 派发判据写进系统提示词：**可并行 / 需上下文隔离 / 调用链深**，其一成立才用；单点检索直接调普通工具。
- 子智能体预算：单任务 25s 超时 + recursion_limit 12；失败/超时降级为该任务的结果标注，不拖垮整批。
- 交易工具不在子智能体工具面内——提案仍归主 Agent（模型只建议不成交的边界不变）。

### 2. 模型接口：`ProviderChatModel`（langchain-core `BaseChatModel` 适配器）

openai SDK Provider 包装为框架原生模型接口（`_agenerate` + `bind_tools`），
create_react_agent 等预构建组件可直接消费；消息在 LangChain 对象与 OpenAI wire dict 间无损往返。
端点白名单、预算计数、trace 仍在 Provider 内（成本治理不是 BaseChatModel 的职责）。

### 3. 上下文裁剪：`langchain_core.trim_messages` 替换手写窗口

strategy=last + start_on=human + include_system；token_counter 复用既有估算（含 14400 上限）。
两个原契约显式保留为护栏：
- **身份保持**：trim 只决定保留集合，返回原始 wire dict（评测断言逐字节兼容）；
- **fail-closed**：本轮窗口（最后用户消息到结尾）不完整或超 43200 字节硬界 → `BudgetExceeded`，
  框架「静默丢弃超限消息」的行为被翻译回原失败语义。

### 4. 主 Agent 循环暂不迁移 create_react_agent

理由不变（ADR-0009）：27 版评测合同锁定手写节点语义； HITL 已是跨请求持久化提案。
但该决策从「永久保留」降级为「暂缓」——子智能体已用 prebuilt，主循环迁移的剩余成本
主要是终答契约节点化，留待下一轮。

## 后果

- 多智能体叙事成立且克制：supervisor 模式 + 并行 sub-agent + 工具面权限隔离，评测/演示可解释。
- langgraph 升级 1.2.12（prebuilt 1.0.13 的运行时依赖），lock 已同步。
- 新增 5 个子智能体契约测试；全量 255×2 遍测试绿。


## 后记（2026-10-07，组件蓝图 WP2）

两个补强落地：

1. **只读不仅是权限最小化，更是并行正确性的前提**——并行分支各自持有隐式
   决策时，冲突的决策产生冲突的产物（Cognition《Don't Build Multi-Agents》：
   "Actions carry implicit decisions, and conflicting decisions carry bad results"）。
   「子 Agent 永远只读、提案永远归主 Agent」因此升格为不可协商约束：未来任何
   「让子 Agent 也能下单」的提议，本 ADR 有据可驳。
2. **派发结论引用核验**（`dispatch.verify_against_observed`）：子 Agent 只回传
   结论文本，答案里的 sku 形 token（`商品:规格`）必须在本轮真实工具回执集合
   （sub_invoke 收集的 items）内，未核验任务降级 `unverified` 并按 incomplete
   语义强制披露——「结论文本当证据」不开放第二条路。派发路由与未核验计数随
   `sub_agent_routing` decision 事件与 decision_record.dispatch 审计落库
   （原实现该事件挂在不可达死代码上，从未发出过，本次一并修复）。
