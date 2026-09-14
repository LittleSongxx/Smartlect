# T1-5 LLM 成本/质量看板

日期：2026-09-14 ｜ 状态：**已完成** ｜ 组件：`/opt/monitoring/llm-exporter.py`（systemd `smartlect-llm-exporter.service`，127.0.0.1:9109）+ Prometheus job `llm` + 告警 2 条 + Grafana `Smartlect LLM 业务` 看板（8 面板）

## 做了什么

### 数据源（零业务代码改动）

growth 在 `agent_run.context_json.model_attempts` 里已持久化每次模型调用的完整画像：
`usage(input/output/total/cached tokens)`、`latency_ms`、`first_delta_ms`、`status`、`http_status`、`model_id`、`provider`、`prompt_version`、**`cost_estimate_cny`（系统侧按 price_version=aliyun-qwen3.7-plus-cn-beijing-2026-09-09-no-discounts 估算的成本）**；
质量维度来自 `result_json.answer_status`（answered/insufficient/conflicting/needs_human）与 `agent_run_event` 的 `error` 事件（`answered_by=controller_fallback` 兜底标记）。
因此本项只需一个只读聚合 exporter，Python 侧一行业务代码都不用改（也符合「不动 Java/交易表」约束）。

### Exporter 与面板

单文件 Python（growth venv，PyMySQL + prometheus_client，30s 刷新，DB 不可用时 `llm_exporter_up=0` 自暴露）：

| 指标 | 口径 |
|---|---|
| llm_attempt_total{model,status} / _24h / _5m | 调用次数（累计/24h/5m 窗口） |
| llm_latency_p95_ms / llm_first_delta_p95_ms | 60m 窗口 p95 |
| llm_tokens_total{direction} / _24h | token 用量 |
| llm_cost_cny_total / _last24h | 成本（元，growth 估算口径） |
| llm_runs_total{state,answer_status} / _24h | 会话结果分布 |
| llm_fallback_runs_24h | controller_fallback 兜底次数 |

Grafana `Smartlect LLM 业务`（`figures/llm-dashboard.png`）：成功率 / 24h 成本 / 转人工率 / fallback 次数四个 stat + 延迟 p95 / token / 累计成本 / 结果分布四个时序。

告警（`smartlect-llm` 规则组）：**SmartlectLLMAllFailing**（5m 窗口成功数为 0 且有调用，持续 5m，critical）；**SmartlectLLMFallbackHigh**（24h 兜底占比>30%，持续 30m，warning）。

## 怎么验证的

```text
$ curl :9109/metrics（节选）
llm_attempt_total{model="qwen3.7-plus",status="succeeded"} 87
llm_latency_p95_ms{model="qwen3.7-plus"} 7658.6
llm_tokens_total{direction="input"} 345857 / {direction="output"} 20354
llm_cost_cny_total 0.8545
llm_runs_total{answer_status="needs_human",state="COMPLETED"} 16
llm_runs_total{answer_status="answered",state="COMPLETED"} 8

$ /api/v1/targets → 15 个目标全部 up（新增 job=llm）
$ /api/v1/rules  → rule groups: [('smartlect-basic', 7), ('smartlect-llm', 2)]
看板截图见 figures/llm-dashboard.png（成功率 100%、24h 成本 0.855 元、
转人工率 61.5%、fallback 16 次、延迟/token/成本曲线齐全）
```

**看板当场暴露的真实质量信号**（这正是它的价值）：今日 24h 转人工率 61.5%（16/26）偏高——构成为压测期间预算受限（BudgetExceeded）走 controller_fallback 的对话与「品类不存在诚实转人工」样本；回答质量本身需结合 evals 轨道判断，不在本看板下结论。

## 遇到的坑

1. MySQL `JSON_TABLE` 的 `NESTED PATH` 列**不能用别名前缀引用**（`jt.in_tok` 报 Unknown column），直接用裸列名。
2. scp 到目录会保留源文件名——`llm-exporter.service` 落到 `/etc/systemd/system/` 后与单元名 `smartlect-llm-exporter.service` 不一致，`systemctl enable` 找不到文件；scp 时应写全目标路径。
3. attempts 无独立时间戳（挂在 run 的 context_json 里），24h/5m 窗口用 `agent_run.updated_at` 代理过滤——对当前「短会话」场景等价，若未来出现跨小时长 run 需改为 started_at 拆分。
4. SSH 隧道进程僵死会占住本地端口（Address already in use），重建前先 pkill；隧道建立加 `-o ExitOnForwardFailure=yes` 失败即退。

## 面试一句话

不改动一行业务代码，把 growth 侧已持久化的模型调用画像（tokens/延迟/首 token/成本估算/兜底标记/answer_status）聚合成 Prometheus 指标并出成本质量看板：上线当天即暴露「24h 转人工率 61.5%」的真实质量信号，同时给出全链路调用成功率 100%、累计成本 ¥0.85/88 次调用的量化基线，配「连续失败 5 分钟」「兜底占比 30%」两条告警闭环。
