# PostgreSQL env 写入门控（P1，保留 checkpointer 机制）

## 需求

`scripts/runtime.py` bootstrap 对已存在 env 无条件补写 5 个 `SMARTLECT_POSTGRES_*` 变量、新建 env 默认写入 3 键 + 密码，但 `infra_up`/`infra_check` 的容器列表不含 postgres（compose 里挂 `profiles: ["postgres"]` 默认不启动）——默认 dev 环境下 `dsn_from_env()` 返回非空、`checkpointer()` 走 PostgresSaver 分支却无库可连，`ensure_postgres_tables()` 存在运行时连接失败隐患。用户决策：**保留 checkpointer 机制**，仅修复 env 写入。

## 具体变更

- `scripts/runtime.py`：`bootstrap(with_postgres=False)`——
  - 已存在 env 分支：5 个 PG 键（HOST/PORT/USER/PASSWORD/DATABASE，含端口探测）移入 `with_postgres` 条件；
  - 新建 env 分支：3 个 PG 键、`POSTGRES_PASSWORD` 生成、端口分配循环的 `POSTGRES` 项同样门控（注释写明动机）；
  - `main()`：`bootstrap --with-postgres` 传开关。
- `deploy/compose.yaml` postgres 服务（已有 profile 隔离）、`graph_runtime.py`/`postgres.py`/相关测试**不动**。
- `docs/runtime.md`：基础设施表改「6 个容器 + 可选 PostgreSQL」，PG 行标注启用方式与 MemorySaver 回退；更新日期 2026-10-05。
- 根 `README.md` 存储行标注 PostgreSQL 可选。

## 验证

- `py_compile` 通过；`bootstrap` 默认路径不再产生任何 `SMARTLECT_POSTGRES_*` 键（代码审查级，未重建 runtime.env 实测——已有 env 文件不被删改）。

## 启用与回滚

- 启用 PG checkpointer：删 `run/runtime.env` 后 `./scripts/dev.sh bootstrap --with-postgres` + compose profile `postgres` 启容器；或在已有 env 手工补 5 键。
- 回滚：`bootstrap`（默认）即可，PG 键不再写入；已写入的旧 env 需手工删除 5 个 `SMARTLECT_POSTGRES_*` 行（本次未自动清理既有文件，避免动用户凭证文件）。

## 未完成项

- 存量 `run/runtime.env` 中已被写入的 PG 键未自动清除（避免触碰用户生成文件）；已按上节说明手工处理。

## 关联代码版本

基于 `7773906` 工作树（本批未单独提交）。
