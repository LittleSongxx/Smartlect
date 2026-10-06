# Agent 侧四项修正

日期：2026-10-07 ｜ 状态：已完成，300 tests OK

## P1: decision_record 预算常量统一 policy 源

- `decision_record.py` 的 `TOOL_LIMIT=10/RETRIEVAL_LIMIT=2/REPAIR_LIMIT=1` 原为硬编码复制
- 改为从 `policy.py` import（`TOOL_CALL_LIMIT/RETRIEVAL_CALL_LIMIT/ANSWER_REPAIR_LIMIT`）
- `ANSWER_REPAIR_LIMIT=1` 新增至 policy.py 作为唯一事实源；session.py 两处硬编码 `1` 同步改引用

## P2: 消融臂 DB 模板脱钩

- B 臂（`dispatch_enabled()=False`）时跳过 DB 模板解析，直接用代码 fallback
- 此前 DB active 行含派发条款会污染 B 臂实验数据（提示词与工具可见性不一致）

## P3: 子智能体注入检测 + compose 截断

- `compose_results` 输出前跑 `INSTRUCTION_PATTERN` 正则（与 knowledge chunk 同一检测器）
- 命中则整体隔离，替换为固定提示文本
- 新增 4500 字节行级截断（为 6500 观察上限留余量，防 result_too_large 三个结论全部丢失）

## P4: 移除 glm-5.3 + 成本汇总

- `CHAT_MODEL_WHITELIST` 移除 `glm-5.3`；`runtime_chat_options` 移除 ZHIPU 分支
- `ZHIPU_HOSTS` 保留（endpoint 白名单 region 推导，与模型选择无关）
- audit 新增 `cost_estimate_cny`（run 级求和）与 `elapsed_ms`（从 model_attempts 首末推导）
- 删除 `GlmProviderTests` 3 个过时测试

## 验证

- 300/300 全绿（64 skip 为 MySQL/live 依赖）
