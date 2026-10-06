# 子智能体执行缺陷修复与 live 复验

日期：2026-10-06 ｜ 状态：已修复并 live 复验通过（发现 2 个执行层缺陷，均为 live 才暴露、scripted 单测漏检）

## 需求

v18 官方评测轮中 `task_dispatch` 的全部 13 个子任务即时失败（主循环兜底后题目仍通过）。
前序"子智能体预算审计修复"（[2026-10-05](../2026-10-05/子智能体预算审计修复.md)）解决了
预算绕过，但执行链路是否可用需 live 复验。本条补齐发现→修复→复验闭环。

## 具体变更

1. **bind_tools wire 格式修复**（`assistant/src/smartlect/agents/shopping/model_adapter.py`）：
   create_react_agent 传入的是 StructuredTool 对象，原实现 `list(tools)` 原样透传，
   live 下被 `provider.chat` 的 `only_registered_function_tools_allowed` 严格校验拒绝
   （scripted 假 Provider 不校验格式，故单测全绿）。现经 `convert_to_openai_tool` 转换，
   dict 视为已保证 wire 格式透传。
2. **子模型可见工具面收窄**（`dispatch.py` 新增 `visible_sub_scope`）：可见面 =
   路由 profile 工具面 ∩ 主会话 skill 门控面。此前完整 profile 面下发、仅调用时拦截，
   模型必然撞 `tool_not_loaded` 403；交集为空抛 `StateError(sub_agent_no_available_tools)`
   显式失败。`tools.py` 的 `sub_invoke` 暴露 `allowed_outer` 供收窄。
3. **失败披露增强**（`dispatch.one`）：降级 answer 携带 StateError code，
   如 `子智能体执行失败：StateError:tool_not_loaded`。
4. **新增单测 5 个**（`tests/test_dispatch_subagent.py`）：wire 契约 2 个 +
   可见面交集 3 个，锁定"可见即可调"。

## 验证方式与证据

- live 复验证据链（run2 复现 ValueError → run4 复现 StateError → run6 派发成功，
  shop-d-49 t2 `all_succeeded=true`、`profile=retrieval-scout`、子任务真实执行 13.0s
  回传正确结论、Pass@1=1）：[eval/verification/subagent-dispatch-live-20261006/verify.md](../../eval/verification/subagent-dispatch-live-20261006/verify.md)
- `tests.test_dispatch_subagent` 19/19 绿；assistant 全量 297 通过（64 skip）。
- 派发为模型策略选择非每轮必触发（多轮直查 compare_skus 同样全对）。

## 未完成项

- 修复对整体指标的影响待后续官方评测轮量化；v18 官方基线不回溯改写。

## 关联代码版本

基于 `899ed91` 工作树（含未提交的预算审计修复）；本次改动文件：model_adapter.py、
dispatch.py、tools.py、tests/test_dispatch_subagent.py。
