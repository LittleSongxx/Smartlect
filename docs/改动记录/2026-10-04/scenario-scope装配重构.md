# scenario scope 装配重构：register_scope 迁入 ScenarioScopeStore + create_app 可注入

## 需求

Phase3a 退役 AttributionStore 后，`product_scope` / `save_recommendation`（推荐回执落账）与 scope 注册逻辑分散在 AdminScopeStore 一侧，职责错位。架构清晰化重构要求：scope 域逻辑统一收口到 `ScenarioScopeStore`，并让 `create_app` 支持注入以便测试替身。

## 具体变更

- `assistant/src/smartlect/scenario_scope.py`：`ScenarioScopeStore` 新增 `product_scope`（per-actor 商品可见域解析，委托 catalog_scope）与 `save_recommendation`（自删除的 AttributionStore 移植，recommendation_receipt 表键序不变）。
- `assistant/src/smartlect/app.py`（hunk 级拆分提交，仅含装配三段）：
  - `create_app` 新增 `scenario_scope=None` 注入参数（缺省仍自建 `ScenarioScopeStore(store.connect)`）；
  - `actor_for` 内对已注册用户执行 `scenario_scope.resolve_actor`，把 store scope 解析到 execution_scope（无注册行保持 store）。
- `scripts/scenario_client.py`：scope 注册改走 `ScenarioScopeStore`（注释注明迁移来源）。
- `assistant/tests/test_scope_reset.py`：测试注入 `scenario_scope` 替身适配新装配。

## 验证

- 回归：`test_scope_reset.py` 属 assistant 套件，因 v16 官方评测运行中推迟到评测结束后随全量 unittest 补跑（见 [assistant-小修复.md](assistant-小修复.md)）；HTTP 层装配路径由该测试的 `create_app(scenario_scope=...)` 直接覆盖。
- 行为影响：生产默认装配与旧路径等价（store 自建同一对象），注入参数仅测试可见——设计上无行为变化。

## 回滚

单提交 revert；revert 后 test_scope_reset 的注入参数同样被回退，自洽。

## 关联版本

基于 `1c0505b`；实现为作者 2026-10-04 工作区改动，本次按主题拆分提交（与 answer-feedback、ensure_schema 修复分离）。
