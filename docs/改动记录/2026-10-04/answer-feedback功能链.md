# 答案反馈（赞/踩 + 理由）全链路：迁移、存储、API、双端 UI 与测试

## 需求

导购答复质量评测需要真实用户反馈信号：用户端对每条终答可赞/踩，踩必选理由（枚举 + 可选自由文本）；管理端运行浏览器可看到反馈明细。反馈按 (agent_run_id, actor) 幂等，重复提交原位更新。

## 具体变更

- 数据库：`assistant/src/smartlect/migrations/0023_answer_feedback.sql`（迁移号与 0001-0022 连续，migrate.py 按目录序自动发现）——`answer_feedback` 表，唯一键 (agent_run_id, subject_type, actor_id)。
- 存储：`assistant/src/smartlect/state.py`——`FEEDBACK_REASONS` 枚举 + `SessionStore.save_feedback`（校验 rating/reason_code，`_owned_record` 归属检查，`INSERT ... ON DUPLICATE KEY UPDATE` 幂等，rowcount==2 判定原位更新）。
- API：`assistant/src/smartlect/app.py`——`POST /api/assistant/runs/{run_id}/feedback`（write 权限 actor，Prometheus 计数 `assistant_feedback_total{rating}`）；`FeedbackRequest` 用 Literal 锁枚举。
- 管理端回读：`assistant/src/smartlect/adminapi/store.py`——run detail 附带 `feedback` 字段。
- 用户端：`web/user/src/api/client.ts` `sendFeedback`；`web/user/src/components/agent/AgentChatItem.vue` 赞/踩条 + 踩选理由面板（未提交理由前不发请求）；`web/user/tests/agent-feedback.test.ts` 断言请求形状与交互时序（带 CSRF、负面先展开面板、FAILED/waiting 不出反馈条）。
- 管理端：`web/admin/src/views/ai/AgentRunsView.vue` `feedbackReason()` 中文展示；`web/admin/tests/ai-ops.test.js` 补断言。
- reason 枚举前后端一致（irrelevant/outdated/citation_mismatch/fabricated/other）。

## 验证

- 回归：web/user vitest 79/79（含新增 agent-feedback.test.ts）、web/admin vitest 31/31（含 ai-ops 反馈断言）——本次执行通过。
- assistant 侧单测（`test_answer_feedback.py` 120 行、`test_adminapi_mysql.py` 反馈断言、`test_scope_reset.py` 不属于本功能）：因 v16 官方评测占用运行环境（2026-10-04 进行中），推迟到评测结束后全量补跑，见 [assistant-小修复.md](assistant-小修复.md)。真实 MySQL 契约未在本次执行，标记待补。

## 回滚

单提交 revert：端点/表/前端入口整体消失，无存量数据迁移风险（新表独立）。

## 关联版本

基于 `857462b`。功能实现为作者 2026-10-04 工作区改动；本次将其从混合工作区中按主题拆分独立成提交（app.py 经 hunk 级拆分，仅含 feedback 三段）。
