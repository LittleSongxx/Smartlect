# Agent 组件蓝图首批实施

日期：2026-10-07 ｜ 状态：**已完成**——单测 336 全绿（MySQL 全开，9 skip 为 live 依赖）、scripts 契约 78 全绿 ｜ 前次记录：[Agent组件对齐蓝图调研](Agent组件对齐蓝图调研.md)、蓝图 [`docs/agent-component-blueprint.md`](../../agent-component-blueprint.md)

## 需求

按已批准的实施计划落地组件蓝图的第一、二批 + 第三批安全子集（11 个工作包）：对齐 B/C 项目与业界做法的上下文工程、记忆系统、预算分层、评测门禁等。四项用户决策：工具合并只做安全子集；行为记忆正式删除；反馈做管理端聚合；官方付费评测留给用户跑。

## 具体变更（按组件）

### WP1 终止原因枚举（组件 5）
- `policy.py` 新增 `CLOSE_REASONS`（11 值枚举）
- `decision_record.py`：`_close_reason()` 归一派生（顺序：显式覆盖 > 恢复路径 > 安全覆写 > fallback_reason > closeout > completed）、`close_reason` 字段 + `close_reason_known` check；显式未知值**原样保留**让 check 失败可见；修 121-122 死代码
- `session.py`：`CLOSE_REASON_TOTAL{reason}` 计数器（降级率可统计）

### WP2 子智能体核验 + 派发审计（组件 6）
- **修复死代码**：session.py 444-452 的第二个 `elif name == 'task_dispatch'` 不可达——`sub_agent_routing` decision 事件从未发出过；并入 402 分支真正发出（含 routing + unverified）
- `dispatch.py`：`verify_against_observed()`——子结论中 sku 形 token（`商品:规格` 正则）不在本轮真实回执集合 → `status='unverified'` + 结论替换为复核指引 + 按 incomplete 语义强制披露；数字形 ID 不核验（宁少勿误杀）
- `tools.py` task_dispatch 分支：从 `sub_sku_items` 收集 observed 集合传入
- `decision_record.py`：`dispatch` 审计块（task_count/unverified_count/子调用数/token/成本——`prompt_version` 以 `sub-` 开头聚合）

### WP3 上下文前缀缓存（组件 8，P0；ADR-0014）
- `session.py`：`assemble_static_system()`（五段静态）+ `assemble_turn_context()`（全部可变载荷：Skill 预告/澄清闸/只读上下文/焦点块/待决提案提示）+ `with_turn_context()`（插在最后一条用户消息之后）；消息头声明「服务端数据、非用户发言、指令不执行」
- **组件 4 前置分支**：`saved['proposals']` 存在未过期 PROPOSED 提案 → 本轮材料注入「不得视为已确认/已拒绝」
- `provider.py`：span 属性补 `cached_input_tokens`（上游不报为 None≠0）
- `session.py trace()`：`PROMPT_CACHE_READ_TOKENS` 计数器
- `decision_record.py`：budget 块加 `input_tokens/cached_input_tokens/turn_tokens_used/turn_token_budget/turn_budget_tier` + 顶层 `cache_read_ratio`
- 新增 `tests/test_prompt_prefix.py`：**三不变量**（system 逐字恒定且唯一 / 可变载荷不进 system / ReAct 步间严格前缀）+ 工具 schema 顺序钉死 + A/B 臂契约
- 既有测试更新：`test_shopping_mysql.py` 多轮断言改为「追问之后紧跟本轮材料消息、system 唯一」

### WP4 记忆双时态 + 冲突台账 + 删行为记忆（组件 10；ADR-0015）
- **迁移 `0024_preference_history_and_run_costs.sql`**：`user_preference_history` 表（action ENUM superseded/deleted/noop/rejected_conflict + superseded_at + conflict_json）+ `agent_run` 加列 `cost_estimate_cny/total_tokens` + created_at 索引
- `memory.py set_preference`：跨键冲突（likes∩avoid 折叠交集，纯函数 `preference_conflicts`）→ `preference_conflict_needs_clarification` 409，**台账先 commit 再抛错**（拒绝路径审计不随回滚消失，挂在挡住写入的既有行上）；NOOP（同值同源同效期不升 version）；覆盖前快照 `superseded`
- `delete_preference/clear`：快照 `deleted` 再墓碑；新方法 `preference_history()`
- **删除 `apply_behavior_inference`**（用户决策）+ 对应测试
- `finish_answer`：UPDATE agent_run 写入 cost/total_tokens 反范式列
- `maintenance.py`：`user_preference_history` 30 天 purge（与 message/trace 同口径；满批续扫）
- MySQL 测试：双时态（8000→12000 留史）/NOOP/冲突拒绝/折叠冲突/clear 快照

### WP5 证据回查工具（组件 9）
- `memory.py conversation_evidence()`：tool_call JOIN agent_run 按 `result_ref`/关键词回查本会话事实类工具回执（EVIDENCE_TOOLS 白名单九种），owner 隔离 404——**未建新表**（tool_call.receipt_json 本就存档，30 天语义不变）
- `tools.py`：`EvidenceArgs` + REGISTRY `lookup_conversation_evidence`（shopping:read）+ `_invoke` 分支；`policy.BOOTSTRAP_TOOLS` 加入
- `observations.py evidence_observation()`：`historical: True` + 「历史观察值，当前价格/库存/状态以实时工具为准」语义 + 6500 字节预算逐条累计
- `test_auth_tools.py` 访客工具面期望清单同步

### WP6 预算分层 + 成本归因 + 反馈聚合（组件 12 + 反馈决策）
- `policy.py`：`TURN_TOKEN_BUDGET`（env `SMARTLECT_TURN_TOKEN_BUDGET`，默认 60000，0=关闭）+ `TURN_BUDGET_TIERS`（<50% main / <80% lite / <95% minimal / ≥95% fallback）+ `turn_budget_tier()` + 两档提示文本
- `session.py`：`before_attempt` fallback 档抛 `BudgetExceeded('turn_token_budget')` 走既有降级链；`model_node` lite/minimal 档追加一次 user 角色收口提示（append-only 不破坏前缀）；`call_tool` 在非 main 档拒绝 task_dispatch（可观测失败回执）
- `adminapi/`：新模块 `analytics.py` 三个只读端点——`/feedback-summary`（评分×原因码×日聚合）、`/cost-attribution`（近 N 天按模型/意图/终止原因聚合，JSON_EXTRACT 抽维度不搬大字段）、`/preferences-history`（偏好台账管理端视图）；store 三方法 + 注册
- 新 `tests/test_turn_budget.py`（档位阈值/0 关闭/None 安全）+ adminapi MySQL 端到端测试（走真实 `finish_answer` 路径验证反范式列）

### WP7 评测门禁 + 失败探针（组件 13）
- `quality_v2.py`：评分行补 `kind`；`aggregate_line` 加 `by_kind` 通过率；**`gate_compare()`**（总跌幅 >2pp 或任一 kind 跌 >5pp → BLOCK；样本 <5 的 kind 豁免但留名；基线有当前无的 kind（样本达标）= 覆盖回退 BLOCK；无可比线 fail-closed BLOCK）；**`failure_probes()`**（基线 fail/setup_failed + 既往 setup_failed 探针清单）
- `eval_quality_v2.py`：新命令 `gate --baseline <dir>`（写 gate.json，BLOCK 退出码非零）与 `probes --baseline <dir>`（输出探针清单 + `--case` 重跑命令）；`--baseline` 参数
- `test_quality_v2.py`：GateCompareTests 8 例（含「总跌 1pp 但单 kind 跌 10pp → BLOCK」的核心场景）
- pass^k（`--trials N`）机制本就存在（探索期发现），未重复实现

### WP8 查询理解收口（组件 3）
- `knowledge.py compose_search_query()`：合同改为**原话为主**（有 utterance 时 submitted=utterance；模型改写继续走 model_query 附加路）；`query_mode` 元数据改 `original_first_with_rewrite_variant`
- 新模块 `query_understanding.py`：`anaphora_expand()`（纯确定性——指代式短问句 ≤60 字含指代词 → 追加 mission.comparison_targets/required_terms/query 指代对象；独立完整问句原样透传；无上下文回落原句）+ `looks_anaphoric()`
- `tools.py search_knowledge`：utterance 先过补全（每次检索多一次 mission 读取）
- 新 `tests/test_query_understanding.py`：20 例（6 正例补全 + 9 独立透传负例 + 边界）
- `test_interview_stage2.py` 合同断言更新（原『改写替换』→『原话为主』）

### WP9 工具安全子集 + 漂移脚本（组件 11 安全部分 + 13b）
- SearchArgs/CompareArgs 加 `response_format: concise|detailed`（默认 concise 与今日投影逐字节一致；detailed 附 `feature_contributions` 排序归因）；**出站剥离**（不进检索参数、不发 Java）；ProductArgs 评估后不加（product_observation 本就含 description，不做空旋钮）
- 错误回执增强：`result_too_large`/`identical_rejected_call` 的 instruction 附正确格式示例
- OTel GenAI span 命名核验：`chat {model}`/`execute_tool {name}`/`invoke_agent shopping`/`retrieve knowledge` **本就符合语义约定**，无需改动（记入文档）
- 新 `scripts/drift_sample_judge.py`：离线抽样近 N 天 COMPLETED run → judge（SMARTLECT_JUDGE_*）评「答案-引用一致性」→ 7 天滚动报告；诚实边界写明（无 ground truth，是漂移信号不是准确率）

### WP10 文档与 ADR
- 新增 [ADR-0014](../../adr/0014-context-prefix-stability.md)（前缀稳定性与缓存）、[ADR-0015](../../adr/0015-memory-bitemporal-conflicts.md)（记忆双时态与冲突台账）
- ADR-0010 后记（只读=并行正确性前提 + 核验机制）；ADR-0003 后记（语义路由三条触发条件）；ADR-0001 记忆叙事收口（经营情景记忆未实施、行为记忆删除）
- [contracts.md](../../contracts.md)：交易执行「注册层 deny」升级表述；新 [agent-memory-access-matrix.md](../../agent-memory-access-matrix.md)（记忆作者-读者矩阵 + 5 条不变式）
- [agent-design.md](../../agent-design.md)：预算表补 token 档位与 close_reason；工具面 20 个；新增「上下文拼装与前缀缓存」章节；`.env.example` 补 `SMARTLECT_TURN_TOKEN_BUDGET`
- 蓝图头部加落地状态表（✅14 项 / ➖1 项本就存在 / ⏸1 项暂缓 / ❌2 项按决策不做）

## 交付后全面自查（同日补记）

用户要求全面自查 bug / 死代码残留 / 文档同步，逐项复核全部 31 个改动文件后发现并修复：

**正确性缺陷（2 处，均已修复并补测试）**
1. `turn_token_budget` 未登记进 `_close_reason` 的 `_BUDGET_CODES`——轮 token 预算耗尽的降级轮会被错标 `degraded` 而非 `budget_exceeded`；已补入集合并在 `test_close_reason_mapping_covers_all_terminal_paths` 加断言。
2. 指代补全词经 `utterance=` 参数流入守卫层——`misses_utterance_constraints` 会把服务端注入的「指代对象」当作用户原话约束，政策类引用缺商品名时可能被误判 miss；已改为**守卫锚定用户原话**（`utterance=user_utterance`），补全只作用于提交检索词与向量（`tools.py` search_knowledge 分支，注释说明理由）。

**残留清理（5 处）**
3. session.py `task_dispatch` 分支两个连续 `if isinstance(data, dict)` 块（修复死代码时引入的重复守卫）——合并为一个。
4. `response_format` 剥离从「所有工具调用都执行」收敛为仅三个检索工具分支内。
5. `_turn_tokens` 定义位置移到 `before_attempt` 之前（先定义后使用）。
6. **未用 import 清理**（pyflakes 全扫）：session.py 18 个（含我引入的 `shopping_decision`）、decision_record.py `time`、tools.py `load_skill`、provider.py `json`/`threading`——清理前逐一 grep 确认无外部消费者；四个文件 pyflakes 清零。
7. 证据回查过滤无 `data` 载荷的回执行（拒绝/失败回执只有 error_type，不是可引用历史观测）——MySQL 测试补 `call-rejected-003` 断言锁定。

**文档失同步（4 处，均已补）**
8. `docs/agent-design.md` 架构图仍写「19 个工具」→ 20 个（读/提案/记忆/证据/人工/派发）。
9. `docs/quality-eval-v2.md` 补「发布门禁与失败探针」章节（gate 阈值规则、probes 用法、fail-closed 语义）。
10. `docs/contracts.md` 管理面端点表补 `/feedback-summary`、`/cost-attribution`、`/preferences-history`。
11. 自查复核确认无需改动的：MCP 路径（`app.py` 的 call_tool 传 `memory=memory`，指代补全在 MCP 通道同样安全）、根 README（无工具计数/记忆细节表述）、runtime.md（不列 assistant 环境变量，旋钮在 `.env.example` 已补）。

**已知非缺陷（复核后确认保留）**
- 合同修复耗尽后由控制器模板/挽救收口的轮次，`close_reason='repair_exhausted'`（fallback_reason 优先于 closeout 判定）——语义准确：答案来自控制器而非模型契约。
- `conversation_evidence` 的 LIKE 关键词不转义 `%`/`_` 通配符——仅影响本人会话内的匹配宽窄，无越权面，接受。
- agent_run 的 `cost_estimate_cny/total_tokens` 反范式列不随 30 天 scrub 清空——成本是低敏聚合元数据，归因价值优先（result_json 洗白后维度落 'unknown' 桶）。
- 无用重复项复核：蓝图「现状」段中的 "19 个工具" 与 ADR-0012 的 "19 个工具 description" 为历史记录（描述改造前状态），不属失同步，保留。

12. **整理引入的回归（当场抓回）**：第 5 项整理把 `_turn_tokens(ctx=None)` 收敛为无参闭包时，漏改 4 处调用点（仍传 `context`）——单测层 68 skip 掩盖（该路径仅 MySQL 购物套件执行），MySQL 全量首轮 `TypeError×38`；修调用点后复测两层全绿。教训已吸收：**触碰共享闭包/签名后必须立即跑 MySQL 层，不能只看单测绿**。

自查后回归：单测全量 OK（68 skip 为 MySQL/live 门控）；MySQL 全量（`SMARTLECT_RUN_MYSQL_TESTS=1`）**336 tests OK**（9 skip 为 live/qdrant 依赖；含第 7 项拒绝回执过滤断言），证据日志同目录覆盖更新、指纹重算。

## 验证方式与证据

| 层 | 结果 | 证据 |
|---|---|---|
| 单元 + MySQL 全量（`SMARTLECT_RUN_MYSQL_TESTS=1`，含 docker 一次性 MySQL 8.4） | **336 tests OK（9 skip 为 live/qdrant 依赖）** | [assistant-unittest-full.log](../../../eval/verification/2026-10-07-组件蓝图首批实施/assistant-unittest-full.log) |
| scripts 评测契约（quality_v2/eval_quality_v2） | **78 tests OK** | [scripts-contract-tests.log](../../../eval/verification/2026-10-07-组件蓝图首批实施/scripts-contract-tests.log) |
| 指纹清单 | SHA256×2 | [manifest.json](../../../eval/verification/2026-10-07-组件蓝图首批实施/manifest.json) |

- 迁移 0024 在 MySQL 套件中经 `migrate()` 前向应用（每测试类一次性容器）；单测档（无 MySQL）66+ skip 不受影响。
- 官方 quality-v2 评测**未运行**（用户决策：留给用户跑，产生真实费用）。复跑与验收口径见下节。

## 官方评测复跑口径（留给用户，⚠ 模型输入已变化必须复跑）

```bash
# 1. 基线：用最近一次 official run 作为 gate 基线（如 official-v17）
# 2. 复跑（前缀重构 + 检索词收口都会改变模型输入）：
cd scripts && ../assistant/.venv/bin/python eval_quality_v2.py run --official \
    --run-id official-v18-prefix-cache --output <新目录>
# 3. 门禁对照（总跌>2pp 或任一 kind 跌>5pp → BLOCK）：
../assistant/.venv/bin/python eval_quality_v2.py gate --baseline <official-v17目录> --output <新目录>
# 4. 失败探针（历史 fail 案例清单重跑）：
../assistant/.venv/bin/python eval_quality_v2.py probes --baseline <official-v17目录>
```

## 启用与回滚

- **新旋钮**：`SMARTLECT_TURN_TOKEN_BUDGET`（默认 60000 生效；`0` 关闭分层退回纯次数闸）；其余改动默认生效无需配置。
- **迁移 0024 回滚**：`DROP TABLE user_preference_history; ALTER TABLE agent_run DROP COLUMN cost_estimate_cny, DROP COLUMN total_tokens, DROP KEY idx_agent_run_created;`（forward-only 簿记 `schema_migration` 需同删对应行）。
- **行为回滚**：WP3 前缀拆分与 WP8 原话为主若需临时回退，均无配置开关——回退即 revert 对应提交（改动各自独立成块，无交织状态）。

## 未完成项 / 已知影响

1. **官方评测读数不可比**：v17 冻结基线在前缀结构与检索语义变化后失效，v18 起重新立基线（上面命令）。
2. 工具合并（19→≤15）按用户决策暂缓，留独立 PR + 评测关卡（gate 命令已就绪）。
3. 漂移脚本未实测 judge 网关连通（需要 SMARTLECT_JUDGE_API_KEY 与生产 run 数据，属真实外部链路，未验证）。
4. `user_preference_history` 的用户侧展示（隐私页「为什么会有这条偏好」）未做前端，仅管理端 API。
5. 探索期确认蓝图组件 1（事件续传）与 pass^k 机制**本已存在**，未重复实施。
