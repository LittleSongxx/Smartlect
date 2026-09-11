# ADR 0003：Agent 控制面（认知 / 控制 / 数据）

日期：2026-09-11。状态：采用。
依据：[agent-design](../agent-design.md)、[ADR 0002](0002-decision-compile.md)、
[architecture-interview](../architecture-interview.md)。

## 问题

运行时只有 Shopping 与 Merchant 两个领域 Agent。控制后果（答/弃/转、提案、grant、Java 成交）
已经由确定性代码收口，但这些层散落在图节点、编译函数和人闸里，对外不容易指认。
补充可审计痕迹时，不能再加 Supervisor、反思模型或记忆摘要。

## 决定

把已实现的边界说成三面，并给每一轮追加只读快照。**不改变** `compile_decision`、提案确认、
商家 grant 或 Java 交易。

| 面 | 谁在跑 | 允许做什么 | 不允许做什么 |
|---|---|---|---|
| 认知面 | Shopping 选工具；Merchant 写一份 JSON 计划 | 提议下一步、声明 `request_kind` | 填写 `answer_status`、执行交易、改预算 |
| 控制面 | `compile_decision`、提案状态机、grant/CAS、工单接管 | 编译答/弃/转、绑定原参数、越界整单等待 | 用提示词阈值或第二个 LLM 改写后果 |
| 数据面 | Java、RAG、推荐、Ads、归因 | 价格库存订单、已发布知识、授权内执行 | 被包装成第三个 Agent |

Shopping 维持有界 ReAct；Merchant 维持无工具规划。Skill 是版本化说明书，不是 Agent。
终答与经营 run 落库 `decision`（声明、证据、编译结果、工具名、版本、预算）和 `checks`
（确定性自检，不是模型反思）。工单会话详情只放行这两块只读字段，不放工具参数。

## 后果

- 源码：`growth/src/smartlect/decision_record.py` 只追加字段。
- 用户端「本轮如何决定」、管理端客服/经营只读展示同一份快照。
- 不引入 Supervisor、意图分类器、记忆摘要 Agent，也不给 Merchant 开放 `tool_calls`。
- 本 ADR 不宣称 F6/F7 通过；评测仍以 [IMPLEMENTATION_STATUS](../../IMPLEMENTATION_STATUS.md) 为准。
