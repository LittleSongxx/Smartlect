# 子智能体派发 live 复验（2026-10-06）

目的：验证 task_dispatch 子智能体执行链路在 live 模型下端到端可用（此前官方 v18 轮中
13 个子任务全部即时失败，仅主循环兜底；随后"子智能体预算审计修复"只解决了预算绕过，
执行缺陷是否修复未经 live 复验）。

## 证据链（同一评测合同，shop-d-16 / shop-d-49，逐轮定位-修复-复验）

| run | 现象 | 定位 |
| --- | --- | --- |
| [run2](run2/) | 主 Agent 派发 3 任务全部 `failed：ValueError`（17ms 即败），主循环兜底后 Pass@1=1 | `provider.chat` 抛 `only_registered_function_tools_allowed`：`bind_tools` 把 LangChain StructuredTool 对象原样透传，未转 OpenAI wire dict |
| [run4](run4/) | wire 修复后子智能体真实起跑（elapsed 4s），但子工具调用 `failed：StateError` | `tool_not_loaded`：子模型可见面是完整 profile 工具面，闸门只放行"与会话已加载 Skill 的交集"——模型看得见却调不动 |
| [run6](run6/) | **shop-d-49 t2 派发成功**：`all_succeeded=true`，`profile=retrieval-scout`，`reason=default_knowledge_and_catalog`，子任务真实执行 13.0s 并回传正确结论（预算内无鼠标、仅耳机，如实披露）；Pass@1=1 | 修复后链路闭环 |

说明：派发是模型策略选择，非每轮必触发（run5 六试验均直查 compare_skus，全对）；
run1 为网关端口被外部容器占用导致 SETUP_FAILED 的排查中间产物，与本缺陷无关。

## 修复内容（基于 899ed91 工作树，未单独提交）

1. `agents/shopping/model_adapter.py` `bind_tools`：StructuredTool 经
   `convert_to_openai_tool` 转 wire dict（dict 透传不变）。
2. `agents/shopping/dispatch.py` 新增 `visible_sub_scope`：子模型可见工具面 =
   profile 面 ∩ 主会话 skill 门控面；交集为空抛
   `StateError(sub_agent_no_available_tools)` 显式失败。
3. `tools.py` `sub_invoke` 暴露 `allowed_outer` 供 dispatch 收窄可见面（与调用时闸一致）。
4. `dispatch.one` 失败披露携带 StateError code（如 `tool_not_loaded`）。

## 验证

- 新增单测 5 个（wire 契约 2 + 可见面交集 3），`tests.test_dispatch_subagent` 19/19 绿；
  assistant 全量 `unittest discover` 297 通过（64 skip，2026-10-06 本机 venv）。
- live 复验经官方评测驱动（同一 scorer/合同，dev run 非官方基线，不写入 official 目录），
  provenance：git_head `899ed91d`，working_diff_sha256 见各 run summary.json。
- 复验期间暂停过抢占 18082 端口的外部容器（aimeeting-local-web-1），验证后已恢复；
  Smartlect 网关因此得以启动。端口冲突与项目代码无关，已如实记录。

## 未完成项

- 子智能体执行成功对整体指标的影响未单独量化（需官方评测轮；本次为链路可用性验证）。
- v18 官方基线不回溯改写；后续官方轮将自然覆盖本修复。
