# ADR-0015: 记忆双时态与冲突台账——活表不变、历史留痕、冲突要求澄清

日期：2026-10-07
状态：已接受（组件蓝图 WP4 落地；MySQL 契约测试锁定）

## 背景

`user_preference` 此前是单行覆盖式（`ON DUPLICATE KEY UPDATE` 原地改写），
version 只递增不分行：旧值被销毁，无法回答「上周预算是 8 千还是 1 万」，
客诉时无法复现当时的推荐依据。同键写入无冲突判定——"likes=红色"与
"avoid=红色"可同时成立，静默互相覆盖。行为记忆 `apply_behavior_inference`
设计完备但全仓无调用点（悬空设计）。业界参照：Zep 双时态知识图谱
（invalidate-not-delete）；mem0 的 ADD/UPDATE/DELETE/NOOP 四操作决策；
OWASP Agentic Top 10（2026）把 Memory Poisoning 列为 ASI06。

## 决定

### 1. 双时态最小版：历史表快照，活表热路径不变

迁移 0024 新增 `user_preference_history`（镜像列 + action + superseded_at +
conflict_json）。`set_preference` 覆盖前先把旧值快照进历史（action=
`superseded`），活表保持单行唯一——读取热路径（每轮 `_preferences`）零变化。
`preference_history()` / 管理端点供回溯与审计。

### 2. 写入决策台账：superseded / deleted / noop / rejected_conflict

- **NOOP**：同值同源同效期重复写入不升 version、不重置过期，只记一条 noop
  ——重复点击/重复推断不制造版本噪声；
- **DELETE**：`delete_preference` / `clear` 先快照再打墓碑；
- **rejected_conflict**：跨键冲突被拒的写入，把「挡住这次写入的既有行」快照
  进台账并在事务内先提交再抛错——拒绝路径的审计不随回滚消失。

### 3. 跨键冲突要求澄清，不静默覆盖

`preference_conflicts`（纯函数）：新写入与现存偏好的 likes∩avoid 折叠交集
非空 → `StateError('preference_conflict_needs_clarification', 409)`。单键内
的新值覆盖不算冲突（那是 UPDATE 语义）。已锁定的投毒防护不变量：inferred
不覆盖 explicit、证据必须是本人 user 消息、偏好绝不进入硬约束槽（mission
硬槽只来自本轮参数与会话任务状态）。

### 4. 保留与遗忘同口径

历史表随 maintenance 30 天 purge（个人数据最小化优先于无限期审计回溯）；
`user_preference` 活表与 explicit 行的既有保留语义不变。

### 5. 行为记忆正式不接线并删除

`apply_behavior_inference` 删除（用户决策 2026-10-07）：Java 侧无可用行为
数据源与合规边界，悬空设计违背「设计即实现」的可描述性要求。将来需要时按
新设计（数据源 + 写入门控 + 评测）重新立项。

## 后果

- 成本：每次偏好覆盖多一次 INSERT（偏好写入是低频路径，可忽略）。
- 兼容：读路径零变化；`_preferences` 查询未动；旧数据无历史行（首次覆盖起
  开始留痕），可接受。
- 拒绝采纳的替代方案：把 PK 改为 (owner, key, version) 分行存储——读路径
  每轮要过滤最新版，热路径回归风险不值当。
