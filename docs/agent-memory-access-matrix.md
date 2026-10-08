# 记忆的作者-读者矩阵（组件 2）

> 每类记忆「谁能写、谁能读、越权返回什么」的单一事实源。**新增任何记忆资源前先填
> 本表再写代码（评审项）。** 更新于 2026-10-07（组件蓝图实施）。
> 关联：[ADR-0015](adr/0015-memory-bitemporal-conflicts.md)、[ADR-0001](adr/0001-final-integration.md)

## 矩阵

| 记忆资源 | 谁能写 | 谁能读 | 越权/未知返回 | 保留 |
|---|---|---|---|---|
| `message`（会话消息） | 系统经 run 收口（assistant）；用户消息经入口 | 本人（owner 三元组） | 404 `conversation_not_found`（不泄露存在性） | 30 天 purge |
| `conversation_memory.summary_json` | 读时惰性重算（抽取式，`working_context`） | 本轮上下文组装 | 随会话越权 404 | 30 天；遗忘/清空置 NULL |
| `conversation_memory.mission_json`（任务槽） | 本轮工具参数 > 本轮抽取 > 已存槽（`merge_mission`），带 lease | 本轮上下文组装；`get_conversation_memory` 工具 | 随会话越权 404 | 随会话；遗忘清空 |
| `user_preference`（活表） | 本人的显式 REST 写；模型的 `remember_preference`（inferred，须逐字引用本人 user 消息） | 本人（偏好页/隐私页）；排序层（推荐/比较）；本轮上下文组装 | 401（访客）；他人 404 | inferred 30 天过期；explicit 永久（用户可删） |
| `user_preference_history`（双时态历史） | 覆盖/删除/NOOP/冲突拒绝时的自动快照 | 本人（`preference_history`）；管理端（admin:legacy，scope 内） | 用户侧他人 404/空；管理端跨 scope 不可见 | 30 天 purge（与 message/trace 同口径） |
| `agent_run.context_json`（轮内工作记忆） | run 执行期（lease 持有者） | 管理端白名单键（CONTEXT_KEYS）；用户侧不直接暴露 | 管理端跨 scope 不可见 | 30 天洗白为 `'{}'` |
| `tool_call.receipt_json`（工具回执存档） | invoke 台账（start/finish_tool_call） | `lookup_conversation_evidence` 工具（本人会话）；管理端 run 详情 | 他人 404 | 30 天 |
| `knowledge_document/chunk` | 管理端发布流（DRAFT→PUBLISHED） | 按 ACL 平面（PUBLIC/USER/ACTOR/MERCHANT）+ 商品/店规语料 | 不可见不进候选；acl_denied 只露存在性 | 有效期 + 撤回 |
| `support_ticket` | `request_handoff` 工具/编译建单；人工管理 | 工单归属者；管理端 | 404 | resolution 30 天置 NULL，工单事实保留 |
| `answer_feedback` | 本人（点赞/踩） | 管理端（run 详情 + 聚合报表） | 他人写 404 | 永久（无 purge；低敏） |
| `prompt_template` / Skills | 管理端（版本化，tools 只能收窄）；代码种子 | 全体运行时（resolve 后的正文） | — | 版本化，retired 保留 |

## 不变式（测试锁定）

1. 偏好写入的证据必须是**该会话内本人 30 天内的 `role='user'` 消息**（`evidence_not_found`）；
   inferred 不得覆盖未过期 explicit（`explicit_preference_has_priority`）。
2. **硬约束槽绝不来自长期偏好**——mission 硬槽只来自本轮工具参数与会话任务状态
   （shopping_request 合并路径，蓝图 WP4 固化为断言方向）。
3. 跨主体一律 404 而非 403——不泄露资源存在性（`_actor` 三元组谓词全表一致）。
4. 访客禁写长期偏好（401 `login_required`），访客会话消息仍按会话保留。
5. 删除偏好写墓碑（`deleted_at`），遗忘连在途 run 一并 `_fence` 作废——late write
   不能把已遗忘内容写回来。
