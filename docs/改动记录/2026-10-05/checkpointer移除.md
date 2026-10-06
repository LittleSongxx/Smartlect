# Checkpointer 彻底移除

> 前次记录：[postgres-env门控.md](postgres-env门控.md)（同日早些时候，决策为「保留机制仅修 env 写入」）。本文记录决策变更后的彻底移除。

## 需求

用户决策变更：从「保留 checkpointer 机制、门控 env 写入」改为「一步到位清理」。依据（评审结论 + 对话确认）：checkpointer 写入无任何消费者——每 run 独立 `checkpoint_ns` 跨 run 不复用、崩溃恢复走 run 租约与幂等台账而非图状态续跑、不用 `interrupt()`（HITL 是跨请求持久化提案）；所有等待点（提案确认/转人工/澄清）均为跨请求语义、由 MySQL 领域状态机覆盖；等待期需保留的事实全部结构化落库，图状态无保留价值。

## 具体变更

**Python 运行时**
- `graph_runtime.py` 重写（76→29 行）：删 `MemorySaver`/`PostgresSaver`、`checkpointer()`、`ensure_postgres_tables()`、`reset_for_tests()` 与 `dsn_from_env` 依赖；保留 `shopping_session` ContextVar（graph.py 节点注入依赖）；`shopping_graph()` 无 checkpointer 编译；`invoke_config()` 无参化（仅 `recursion_limit: 25`）。
- `session.py`：删 `ensure_postgres_tables()` 调用与 import；`invoke_config()` 无参调用。
- 删 `smartlect/postgres.py`（`dsn_from_env`/`available`，无其他消费者）。
- `test_interview_stage2.py`：删 checkpointer/dsn 相关 import 与 `test_checkpointer_is_memory_without_dsn`；新增行为守卫 `test_graph_runtime_has_no_checkpointer`（编译产物 `checkpointer is None`、模块不暴露 saver 入口、invoke_config 只含递归上限）——防止将来被无声加回。

**依赖与打包**
- `pyproject.toml`：删 `psycopg[binary,pool]==3.3.2`、`langgraph-checkpoint-postgres==3.0.4`（`langgraph-checkpoint` base 是 langgraph 主包传递依赖，保留）。
- `requirements.lock`：删 4 行（`langgraph-checkpoint-postgres`、`psycopg`、`psycopg-binary`、`psycopg-pool==3.3.1`），顶部加移除说明（保留 2026-09-19 redo 历史注释）。

**脚本与部署**
- `scripts/runtime.py`：`bootstrap()` 恢复无参（整体移除同日早前加的 `--with-postgres` 门控）；PORTS 表删 `POSTGRES` 条目。
- `deploy/compose.yaml`：删 postgres 服务段与 volumes 的 `postgres` 键。
- 删 `deploy/postgres-init.sql`。

**文档**
- `docs/runtime.md`：基础设施回到「6 个容器」，附移除说明。
- 根 `README.md`：存储行去 PostgreSQL。
- `ADR-0009` 加后记（不改写原文）：移除理由、退役清单、未来恢复路径（thread_id 固定 + 重引 PG saver + 副作用幂等前提）。
- `docs/assets/architecture.svg`：「PostgresSaver checkpointer · trim_messages 上下文裁剪」→「trim_messages 上下文裁剪」。

## 验证

- **依赖真移除验证**：venv 中 `pip uninstall psycopg psycopg-binary psycopg-pool langgraph-checkpoint-postgres` → 重装包（METADATA 不再声明）→ `pip check` 干净 → **无 PG 依赖环境下**非 MySQL 全量 292 用例 OK（64 skip）。
- **真机图回归**：MySQL 套件 63 用例 OK（9 skip）——`test_shopping_mysql` 以 live 模式经无 checkpointer 的 `shopping_graph()` 执行，`model_calls` 断言（来自 before_attempt，与 checkpointer 无关）全过。
- `test_interview_stage2 + test_dispatch_subagent` 27 用例 OK（含新守卫）。
- `py_compile scripts/runtime.py` 通过；`deploy/compose.yaml` yaml 解析 OK 且 postgres 零残留。

## 启用与回滚

- 回滚：整体 git revert；依赖重装 `pip install psycopg[binary,pool]==3.3.2 langgraph-checkpoint-postgres==3.0.4`。
- 存量 `run/runtime.env` 中的 `SMARTLECT_POSTGRES_*` 键移除后无人读取（无害），可手工删除；PG 容器数据卷（如曾启用）可 `docker volume rm deploy_postgres`。

## 未完成项

- 无。对外可观测行为无差异：被删的 checkpoint 写入本就无读取方。

## 关联代码版本

基于 `7773906` 工作树叠加同日前序改造（未提交）。
