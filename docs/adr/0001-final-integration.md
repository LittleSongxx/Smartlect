# ADR 0001：最终融合的领域、状态和 Python 依赖边界

日期：2026-09-09。状态：采用；这是 F0 架构和依赖决定，业务能力按 F1–F7 分别验收。
依据：[HANDOFF Final Integration v1](../../HANDOFF.md) 第 4–10、17 节。
源码取材版本：`94d36aee925c75d286f48d2aee2eeea059a74dd9`；导出范围和校验和由
[`handoff/integration-manifest.json`](../../handoff/integration-manifest.json) 记录。
现有 Java 交易修复、库存与独立增长账本保留，不整体回迁旧 Java 或执行旧启动链。

## 两领域、两模式

系统只有 Shopping 和 Merchant 两个领域 Agent，每次任务由一个 Agent 持有控制权。
Shopping 对导购、政策客服和本人订单服务采用有界 ReAct：模型依据新的工具观测选择下一步，
写意图只生成提案，登录用户确认具体动作后由后端执行。默认每请求最多 6 次模型调用、10 次工具调用、
90 秒；模型每次 25 秒、含重试至多 2 次；重试和格式修复都计入调用数。
知识问答可以直接带引用结束，无需生成商品推荐或订单。

Merchant 采用 Observe → Plan → Grant → Execute → Await observation → Replan。
模型规划，确定性执行器核验商家批准的稳定授权范围、资源版本、库存、幂等和累计广告预算。
每轮一份有效计划、至多 8 个动作、最多一次格式或事实修复。新 plan、round 或 run 不重置 grant 的
累计预算；范围内调整沿用原 grant，越界、过期或撤销后等待批准。没有新观测就不重复宣布优化成功。
模型默认 `qwen3.7-plus`，不设置累计模型金额封顶，不自动换昂贵旗舰；这不削弱广告预算硬限制。

两个领域通过版本化业务事实、事件和策略协同，不互发文本授予权限。
RAG、推荐、指标、预算、广告执行器及素材生成函数都是工具或确定性服务。
不引入全能 Agent、LLM 总 Supervisor、Team 群聊、下级 Worker Agent 或跨角色自由 handoff。
以后改变拓扑须有同模型、同工具和同任务集的质量、成本、延迟对照证据。

## 框架与业务阶段恢复

一个 `smartlect` 包使用 FastAPI/Pydantic/native SSE 和 LangGraph `StateGraph`。
API 与增长 worker 为独立受监管进程；财务事件消费不等待模型运行。
官方 `StateGraph` 支持有类型状态、普通函数节点及条件边；这些节点不等于多个 Agent。
本项目单次图只运行一个有界业务阶段。[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)

跨请求的任务、确认提案、动作、grant、租约和版本保存在独立 Growth MySQL。
等待用户或新观测时持久化业务阶段并结束请求；恢复时从记录开启新 invocation。
Java 的订单、价格、库存、付款和退款仍是唯一交易事实来源；Python 不直改交易表。
网络超时进入 UNKNOWN/WAIT_OUTCOME，按原 action_id 与幂等键查询 Java 回执；不能换键重发。
命令受理、业务待定和业务完成分别记录，退款申请成功不代表退款已完成。

不自研 MySQL `BaseCheckpointSaver`，不新增 Postgres，不把内存 checkpointer 当持久化。
首版承诺业务阶段恢复，不承诺逐 token 或任意图节点原位恢复。官方说明 interrupt 恢复可能重跑节点，
所以即便未来采用原生 checkpoint，外部副作用仍需独立幂等和回执核验。
[LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

## 四层记忆与 Skills

| 层 | 首版保存方式 | 权限和事实边界 |
|---|---|---|
| 短期会话 | MySQL 会话、消息、摘要；最近 8 轮与有版本/消息范围的摘要 | 只能读取本人会话；未完成交易不能摘要为完成 |
| 用户长期偏好 | 结构化偏好、来源、置信度、证据、观察/过期时间 | 用户可查看、更正、删除；明确陈述优先；推断默认 30 天失效 |
| 经营情景记忆 | 已提交的快照、计划、动作、结果和失败原因 | 模型总结先为 DRAFT，人工批准后才成为可复用经营规则 |
| 程序性知识 | Git 版本化 Skills、SOP 和提示词 | 只由开发/审核流程发布；不能由模型、用户文档或网页改写权限 |

六个业务 Skill 为 `shopping_advice`、`support_policy`、`order_service`、`campaign_plan`、
`performance_review`、`creative_copy`。Shopping 开场只有目录工具（`load_skill` / `search_knowledge` / 记忆 / `request_handoff`），业务工具由 `load_skill` 按已审核 Skill 并入本轮；Merchant 按阶段加载所需提示词、契约和工具子集，不创建新 Agent。
Skill 只能缩小 ActorContext 的工具范围；管理端热改也只能再缩小已加载 Skill 的 `tools`。上下文初值上限 12k token，工具调用与结果成对保留。
记忆不存 key、会话 token、完整支付信息或隐藏推理；默认对话/trace 保留 30 天。
清理记忆撤销相关摘要和索引，不删除交易审计事实；价格和库存始终重新查询 Java。

## 共享工具与 MCP

两个 Agent 使用同一 Tool Registry，各自加载角色允许的子集：Pydantic 输入/输出、超时、
读写类别、幂等和审计规则。主体来自 Java 会话查询桥和后端 ActorContext，不能来自模型参数。
Pydantic 严格模式可拒绝隐式类型转换，但 schema 通过不意味着资源归属或授权通过。
[Pydantic Strict Mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)

主线通过共享工具层调用 Java 受控 HTTP，不新增 MCP 服务器或第二套登录链。
旧 MCP 仅取材工具契约和适配实现；出现独立客户端需要时再加只读薄 MCP 适配，复用同一 registry，
单独认证并绑定受众，禁止任意透传上游 token。MCP 不是记忆、编排或交易幂等机制。

## 依赖选择和重现

先读取固定提交的 `AI_Shop-backend/AI_Shop-agent/pyproject.toml`、`requirements.lock`，
以其已锁版本约束需要复用的依赖。原锁只是版本来源，旧测试不作为当前兼容性证据。
保留现有 `pika==1.4.1`、`PyMySQL[rsa]==1.2.0`、`cryptography==50.0.1`、
`cffi==2.1.1`、`pycparser==3.0` 账本依赖和 `setuptools==80.9.0` 构建版本。

| 新增直接依赖 | 版本 | 选择证据/用途 |
|---|---|---|
| FastAPI | 0.141.1 | 固定来源版本；内置 `fastapi.sse.EventSourceResponse/ServerSentEvent`，不用额外 SSE 包 |
| Pydantic | 2.13.4 | 固定来源版本；输入严格校验、工具和计划 schema；匹配 `pydantic-core==2.46.4` |
| Uvicorn | 0.32.1 | 固定来源版本；基本 ASGI 启动，不带 `standard` extra；SSE 主线设置 `ws="none"` |
| LangGraph | 1.0.10 | 固定来源版本；只使用 `StateGraph`，不追随无业务需要的新版本 |
| httpx | 0.28.1 | 固定来源版本；异步受控 HTTP/模型兼容接口，以及 ASGI 兼容检查 |
| python-dotenv | 1.2.2 | 固定来源版本；非执行式读取白名单模型配置，禁用变量插值；不 source/eval 旧 `.env` |

FastAPI 官方在 0.135.0 加入原生 SSE；0.141.1 的包元数据要求 Python ≥3.10、Pydantic ≥2.9、
Starlette ≥0.46，当前组合满足。LangGraph 1.0.10 要求 Pydantic ≥2.7.4、checkpoint ≥2.1/<5、
prebuilt ≥1.0.8/<1.1、SDK ≥0.3/<0.4；锁定组合经新环境解析和实际调用验证。
[FastAPI SSE](https://fastapi.tiangolo.com/tutorial/server-sent-events/) ·
[FastAPI 0.141.1 元数据](https://pypi.org/pypi/fastapi/0.141.1/json) ·
[LangGraph 1.0.10 元数据](https://pypi.org/pypi/langgraph/1.0.10/json)

运行锁为 [`growth/requirements.lock`](../../growth/requirements.lock)，覆盖全传递闭包及构建依赖。
`pyproject.toml` 声明直接依赖，安装入口统一先用这份锁，再 `--no-deps --no-build-isolation` 安装本包。
不另维护 uv/Poetry 锁。`langgraph-sdk`、`langchain-core`、`langsmith` 等来自 LangGraph 的强制传递依赖，
不代表启用另一套 Agent 编排、云运行平台或外部观测服务。
不迁入旧 MCP、langchain-openai、独立 OpenAI SDK、ORM、自由 SQL、遥测全家桶和未用的异步驱动。
后续知识解析确需新依赖时再纳入同一锁并执行对应验收，不一次复制旧环境。

```bash
python3 -m venv growth/.venv-f0-locked
growth/.venv-f0-locked/bin/python -m pip install -r growth/requirements.lock
growth/.venv-f0-locked/bin/python -m pip install --no-deps --no-build-isolation ./growth
growth/.venv-f0-locked/bin/python -m pip check
SMARTLECT_RUN_MYSQL_TESTS=0 growth/.venv-f0-locked/bin/python -m unittest discover -s growth/tests -v
```

F0 实测平台为 CPython 3.13.11/Linux x86_64；其他解释器与平台尚未验证。
[`test_framework_contract.py`](../../growth/tests/test_framework_contract.py) 验证严格输入拒绝、
有类型图执行/步数上限、原生 SSE 和 Uvicorn 配置加载，不调用模型或业务服务。
Starlette 1.6.0 的 TestClient 对 httpx 提示未来弃用，检查直接使用 httpx `ASGITransport`，不新增 httpx2。
初次 smoke 因测试假定 JSON 没有空格失败，改为解析 SSE data 的 JSON 后通过；没有更改框架或删除安全检查。
完整安装及检查证据记录在 [`artifacts/f0-python-stack.json`](../../artifacts/f0-python-stack.json)。
这些检查仅证明依赖可安装和基本接口兼容，不代表 F1 身份/交易或 F2 真实模型能力已验收。
