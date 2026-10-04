# assistant/requirements.lock 重解 langgraph 依赖冲突（CI 红灯修复）

## 需求

main 分支 CI（run 37205188980，2026-10-04）assistant job 在「安装锁定依赖 + 本包」步骤失败：

```
ERROR: Cannot install -r assistant/requirements.lock (line 43) and langgraph-prebuilt==1.0.13
because these package versions have conflicting dependencies.
ERROR: ResolutionImpossible
```

原锁（ADR-0010 提交时未验证可装性）中 `langgraph-prebuilt==1.0.13` / `langgraph-sdk==0.3.15` / `websockets==17.1` 与 `langgraph==1.2.12` 的依赖区间互斥。

## 具体变更

`assistant/requirements.lock` 整体重解（作者 2026-10-04 工作区改动，本次验证后独立提交）：

- langgraph-prebuilt 1.0.13 → **1.1.0**，langgraph-sdk 0.3.15 → **0.4.5**（与 langgraph 1.2.12 可共存的组合）；
- 冻结来源：已通过 285 项 assistant 测试的部署 venv（smartlect.cn 生产实际运行组合）；
- 锁头部注释保留历次重解历史与 ADR 引用。

## 验证（计划/实现/回归标注）

- 回归（本次执行，本地临时 venv 完整复刻 CI 三步）：
  - `pip install -r assistant/requirements.lock` → exit 0；
  - `pip install --no-deps --no-build-isolation ./assistant` → exit 0；
  - `pip check` → `No broken requirements found.`
- CI 线上绿灯：未执行（本仓库当前约定不 push，待 push 后由 run 确认），标记未知。

## 启用与回滚

- 启用：随提交生效；已部署环境不受影响（生产 venv 本就是该组合）。
- 回滚：单提交 revert 恢复旧锁（旧锁不可装，回滚无意义，仅作历史记录）。

## 关联版本

基于 `c295d77`；同日 v16 官方质量评测（official-v16-20261004）即运行在该组合的 venv 上，评测环境与锁一致。
