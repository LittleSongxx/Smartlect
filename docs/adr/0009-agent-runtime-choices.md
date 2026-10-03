# ADR-0009: Agent runtime 技术选型——openai SDK、手写有界 ReAct 保留、持久化提案优先于 graph interrupt

日期：2026-10-04
状态：已接受（2026-10 收敛重构）

## 决定一：模型层换 openai 官方 SDK（替换 580 行手写 httpx 管线）

`Provider` 传输层改 `AsyncOpenAI`（compatible-mode 端点白名单、模型白名单、消息协议校验全保留）。手写熔断器删除——fail-closed 一次不重试语义保留，重试退避交给 SDK。响应 dict 形状不变，trace/langfuse/审计不受影响。

## 决定二：手写三节点有界 ReAct 保留（不迁移 create_react_agent）

评估后不迁移 `langgraph.prebuilt.create_react_agent`，理由：

1. **HITL 实现已更强**：本项目提案确认是**跨请求持久化 HITL**（proposal 表 + WAIT_USER 终态 + version 乐观锁 + 幂等恢复），LangGraph 的 `interrupt()` 是进程内挂起——进程重启即失。跨请求 DB 状态在生产语义上优于 graph interrupt。
2. **控制权威位置正确**：预算（模型调用≤6/工具≤10/检索≤2/90s deadline）、租约 fencing、终答契约修复都在编排器 + MySQL，graph 只承担循环结构——这正是 checkpointer 该管与不该管的分界。
3. **迁移成本**：27 个版本的评测合同锁定在现有节点语义上，形式化迁移的收益（少 ~80 行图代码）远小于重验证成本。

诚实声明：这意味着「用了 LangGraph」但不「地道」——StateGraph + checkpointer + 条件边是正统用法，未用 prebuilt/interrupt/subgraph。面试时此决策可按本 ADR 陈述。

## 决定三：守卫模块保留

`shopping_mission`/`compile`/`guardrails`/`answer_guards`（合计 ~1300 行）经评估**不是过度设计**：每条守卫锚定 quality-v2 评测合同的具体失败案例（选择门/回退授权/引用复核），且有行为测试锁定。删除等于删除评测资产。

## 后果

- 自研面显著缩小：HTTP 管线、熔断器、pgvector 镜像、内存 BM25（主路径）、推荐/归因全部退役。
- 保留的自研（守卫/编排/提案状态机）全部有「评测合同锚定 + 测试锁定」的双重理由，符合「每个留下的组件都能在 30 秒内说出不选替代方案的理由」的收敛终点标准。
