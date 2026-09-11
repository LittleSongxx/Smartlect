# 人工客服工单与会话详情

F6 在原工单列表和接管接口上增加只读详情；由同一个 `MemoryStore` 读取本项目已保存记录，
不调用模型、不伪造用户身份、不绕过用户接口，也不查询或修改 Java 交易状态。

| 接口 | 含义 |
|---|---|
| `GET /admin-api/assistant/support` | 当前 scope 的工单队列摘要，最多 100 项 |
| `GET /admin-api/assistant/support/{ticket_id}` | 工单权限下最近 100 条消息及关联运行、原引用、当前持久提案 |
| `GET /admin-api/assistant/support/{ticket_id}?before_sequence=N` | 读取 sequence 小于 N 的前一页 |
| `PATCH /admin-api/assistant/support/{ticket_id}` | 原 `take_over/reply/close`，请求携带所见 `version` |

详情只接受已认证 merchant 的 `admin:legacy` 权限。工单关联会话必须在当前已选择的
`execution_scope_id`；不存在或跨 scope 返回 `ticket_not_found`（404）。未分配工单可由同 scope
客服查看，已分配工单（含 CLOSED）只有 `assigned_actor_id` 本人可以查看，否则返回
`ticket_assigned_to_another`（403）。同一用户的其他会话不会因一个工单而开放。
队列仍提供调度摘要；其他接管人的“查看会话”和写操作在 UI 禁用，详情权限由服务端再次检查。

只读事务按原写操作顺序先共享锁定 conversation，再共享锁定 ticket，确保读取本页时分配关系稳定。
GET 不接管、不回复、不结束、不产生确认提案或业务动作。PATCH 保留原 conversation/run/ticket
锁顺序、版本比较及 takeover fencing；用户与在途 Agent 的原互斥保护保持。

响应字段为 `ticket/conversation/messages/runs/proposals/next_before_sequence`。
消息按 sequence 正序返回；还有更早消息时给出下一页游标，UI 可逐页加载完整历史并按 ID 合并，
没有将超过 100 条的内容静默丢弃。每页 runs 和 proposals 由本页消息关联的 run ID 查询，并再次
绑定 conversation；更早运行的引用/提案随更早消息加载。人工回复的独立消息也在历史内。
重开或刷新详情读取最新一页及当前提案状态；历史引用是当时保存的 doc/version/chunk、原文与位置，
不代表文档目前仍生效，不按客服身份重新检索替换。提案来自 proposal 表当前记录，
不展示 run.result 内可能过期的提案副本。未暴露租约凭证、工具参数或隐藏运行 context。

Vue 详情展示用户/助手/人工消息、运行状态与 live/mock/降级标记、历史引用、提案参数和原回执。
内容使用文本插值，不执行消息/引用中的 HTML，不把任意 source_uri 作为可执行链接。
提案状态与 UNKNOWN 原样显示；工单页面没有交易确认按钮。接管、回复或结束工单均不表示
用户批准下单、支付、取消或退款，交易仍须本人明确确认并由 Java 维护权威事实。

验证代码：`growth/tests/test_knowledge_memory.py` 的权限/游标检查，
`growth/tests/test_knowledge_memory_mysql.py` 的真实分页、引用/提案、接管人/跨 scope 拒绝与重启读取，
以及 `web/admin/tests/support.test.js` 的详情展示、分页、拒绝后清除上下文和无隐式写入。
既有 takeover fencing 与版本冲突测试继续保留；当前阶段实际运行结果由 IMPLEMENTATION_STATUS.md 记录。
