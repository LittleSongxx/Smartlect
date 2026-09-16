# Smartlect 模型 Provider

F2 使用已有 `httpx==0.28.1` 直接调用百炼 OpenAI-compatible Chat Completions 与 embedding API。
模型凭证仅由启动器从 Git 忽略且权限 600 的 `run/model.env` 合并到 Python 进程；检查脚本通过
`runtime.model_env()` 读取相同白名单。不能把该文件交给前端，也不能 `source` 旧项目环境。

`Provider(config)` 默认且只接受 `qwen3.7-plus` 和已核对同系列快照
`qwen3.7-plus-2026-05-26`；不会自动换型号。当前仅允许已核验的百炼 HTTPS
`/compatible-mode/v1` 地址，不接受旧应用实例、URL 凭证或重定向。后续换供应商需要显式适配和重新运行能力检查。
官方描述当前别名与上述快照等效；真实响应若只返回别名，trace 的 `resolved_snapshot` 仍为
`null`，不把文档别名对应关系冒充供应商实际返回的快照证据。
[模型及价格](https://help.aliyun.com/zh/model-studio/qwen3-7-plus)

普通客服、结构化输出及工具调用显式设置 `enable_thinking=false`、`enable_search=false`，
仅接受普通 function 工具；没有供应商联网、浏览器、代码执行或任意 `extra_body` 透传。
正文与 function arguments 是业务输出；`reasoning_content` 不返回、不存 trace、不回放给下一次调用。
采用 `max_completion_tokens`，默认 1024、硬上限 4096。经营有限思考不是 F2 已验证能力，后续需显式加入并单独验证。
[思考参数](https://help.aliyun.com/zh/model-studio/deep-thinking/)

普通对话、tool call、strict JSON Schema、stream 均分别实测；JSON 模式的成功不能代替业务
Pydantic/schema、权限、金额和事实校验。tool call 只返回请求，仍由现有 Tool Registry 控制实际执行。
Shopping 当前请求使用 `response_format={"type":"json_object"}` 加工具 schema，最终再由
`FinalAnswer` 严格验证；独立 strict JSON Schema smoke 成功不表示 Shopping 的所有答复天然满足最终合同。
当前流式只实测正文，流式 function fragments 的拼接另有 MockTransport 协议检查，不能宣称实测
stream+tools 组合。当前兼容文档对该组合的支持描述有限，不在主线依赖它。
[兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、
[结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)

每个 attempt 有 25 秒总 deadline，包含完整读取流；超时、连接失败、429 和 5xx 至多重试一次，
SDK 不承担隐含重试。其他 4xx、格式错误、截断或无终结的流直接失败；正文已经流出后不自动重试。
`before_attempt()` 在每次 HTTP 前调用，Shopping 用它把 chat、查询 embedding、重试和格式修复
一并计入每请求 6 次实际 attempt 限制；计数先持久化，回调拒绝后不会发请求。
`on_trace(dict)` 每次完成或失败时记录状态、重试次数、token、耗时、首字延迟、模型/区域、
prompt/skill/schema 版本；`on_delta(str)` 只收到正文。回调支持普通函数和 async 函数。
API 全进程复用一个实例，chat 与 embedding 共用两个并发槽。Shopping 同会话串行、最多 10 次工具和
2 次检索，图最多使用 85 秒并从原 90 秒 deadline 中预留 5 秒收尾；索引发布不是 Shopping 对话请求。
这些限制由 Agent 执行器负责，Provider 不替用户确认任何交易。

返回格式：

```python
result = await provider.chat(messages, tools=tool_schemas, before_attempt=count_request,
                             on_trace=save_trace, prompt_version="shopping-react-v5",
                             skill_versions={"support_policy": "1.0.0"}, schema_version="shopping-answer-v1")
message = result["message"]  # role/content/tool_calls；可作为下一次模型的 assistant 消息
vectors = await provider.embed(["合成知识片段"], before_attempt=count_request, on_trace=save_trace)
```

`chat` 返回 `message/usage/metadata/attempts`；`embed` 返回
`embeddings/usage/metadata/attempts`。每次调用的 token 缺失为 `null`，失败不伪填 0。
`metadata.request_parameters` 记录温度、输出上限、响应格式类型、函数数量和 embedding 维度；
`resolved_snapshot` 仅在供应商明确返回快照 ID 时填写。Shopping 将 attempt trace 写入持久 run context，
索引初始化脚本另写索引产物，不把业务正文或隐藏思考塞进 Provider trace。

管理端知识发布使用独立的 `knowledge_index_attempt` 表（迁移 `0004`），不创建 Agent run。
每个发布请求有 `publication_id`，每批 embedding 的每次实际请求前先提交 `started` 记录；
Provider 的 `on_trace` 将其更新为 `succeeded / failed / cancelled`，关联商家、scope、文档版本、
批次与重试序号。进程中断留下的 `started` 表示结果未知，token 和费用未知时仍为 `null`。
写入仅接受模型、区域、版本、用量、耗时、状态等白名单字段，嵌套参数同样过滤；
不保存文档正文、向量、HTTP headers、供应商错误 body 或隐藏推理。
审计写入失败会中止发布；已发布版本重放直接复用结果，不再调用 embedding。
现有 30 天清理任务按每批 1,000 行删除过期索引调用记录，不删除知识、Agent 确认或交易账本。
这是管理端索引路径的独立审计，Shopping 和检查脚本保留原有 trace 路径，不重复写入此表。

北京 qwen3.7-plus 费用按 2026-09-09 官方每百万 token 阶梯原价估算，不含账户折扣和缓存优惠，
不是实际账单；其他区域或缺用量时费用为 `null`。embedding 费用尚未核价，同样为 `null`。
模型费用无累计封顶，和商家活动的强制广告预算分别处理。

已配置的 `text-embedding-v4` 真实使用 1024 维；每次 1–10 个非空文本，单文本至多 8000 字符，
校验返回索引一一对应、维度、非零和有限数值。`metadata.model_id/dimensions` 可用于知识索引版本。
知识层控制发布、ACL、失效和检索候选；向量成功不证明召回质量。rerank 配置暂保留但未调用，
F2 优先 embedding/RRF 路径。
[embedding API](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)

## 已实测的工具 schema 兼容问题

不能只凭“支持 OpenAI-compatible”推断所有 Pydantic schema 都能直接使用。
Shopping v3/v4 对 `search_skus.max_price_cents` 发送包含 `integer/null` 的 `anyOf` 时，
实际原始工具参数探针返回 `"2000"` 字符串；Pydantic `strict=True` 正确拒绝，相关运行最终用尽额度并降级。
这属于当前供应商兼容路径的实测现象，不是所有供应商或所有联合类型的通用结论。

当前 [`tools.tool_schema()`](../growth/src/smartlect/tools.py) 只调整发给供应商的参数描述：
展开 `$defs/$ref`，去掉默认 `null`，将只有一个非空分支的可空联合展开为直接类型。
可选字段仍可省略；缺省值继续由服务端 Pydantic 模型处理。调整后的数值探针实际返回整数 `2000`，
通过相同 `SearchArgs` 严格验证，v5 纵向链路随后返回预算内真实有货 SKU。
服务端仍为 `strict=True, extra="forbid"`，没有通过 `int("2000")` 或全局 coercion 接受错误类型。

v1 原型也曾遇到最终 JSON 合同失败；v5 的成功链路中，记忆和 SKU 两轮仍各进行了一次有限格式修复。
修复调用照常记入 6 次额度，不能把修复前拒绝隐藏成零故障。实现和事务收尾边界见
[Agent 设计](agent-design.md)。

可重跑检查（已安装当前 growth 包时不需要 `PYTHONPATH`）：

```bash
PYTHONPATH=growth/src growth/.venv/bin/python -m unittest discover -s growth/tests -p test_provider.py -v
PYTHONPATH=growth/src growth/.venv/bin/python scripts/check_model.py
```

[`f2-provider-capabilities.json`](../artifacts/f2-provider-capabilities.json) 的初次版本记录 7 次 HTTP attempt：
文本、工具调用及结果回传、strict JSON Schema、正文 stream、真实认证错误和两文本 embedding。
它是最初协议能力快照；之后增加数值 schema 用例时，以报告内的 capability、时间、调用数和源码 SHA 为准，
不能把最初 7 次调用当作所有后续源码和组合参数均已验证。
错误项用故意无效的合成 key 验证供应商返回 401/403 且只请求一次，不打印响应 body。

当前另有 [`f2-live-vertical.json`](../artifacts/f2-live-vertical.json)：
`shopping-react-v5` 真实模型五轮政策/记忆/SKU/下单提案/退款提案通过，用户分别确认交易，
Java 模拟支付与退款均为 1,000 分，净额 0 分、库存 5 → 5。它不等于完整 F6 评测；
已冻结 44 条 RAG 合同中的 12 条 holdout 仍未执行，不得从本次 smoke 推导其成绩。

最终独立协议重跑见 [f2-provider-final.json](../artifacts/f2-provider-final.json)：7类能力、8次实际HTTP请求全部通过，新增可省略整数工具参数的真实类型验证。初次7请求报告保留；不把两个报告简单累加成模型质量样本。最终源码hash随报告保存，生产运行与索引调用另保存在各自审计记录。


## 运行时模型切换（ai-ops，2026-09）

`model_runtime_config` 表存储 chat 角色的激活模型选择（admin 端「AI 资产 · 模型配置」页）。
约束与边界：

- 仅允许当前 `SMARTLECT_MODEL_BASE_URL` 端点族可服务的模型（dashscope↔qwen 系、
  zhipu↔glm-5.3）；跨厂商切换需更换端点（部署操作）。
- Provider 以 5s TTL 读取该表；空表、DB 异常时回落 env 快照（`SMARTLECT_MODEL_ID`）。
- API Key、Base URL、embedding 模型与维度白名单不受此表影响，仍由 run/model.env 托管。
- 保存时白名单校验 + updated_by 审计；「测试连接」走一次 1-attempt 的小额探测并
  返回延迟/错误码。
- trace 中的 model_id 始终为当次调用实际生效的模型。
