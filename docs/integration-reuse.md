# Smartlect 最终融合取材清单

核对日期：2026-09-09。来源提交：`94d36aee925c75d286f48d2aee2eeea059a74dd9`。本清单依据该提交的 Git 对象，只读查看目录、依赖、源码、测试和演示知识；未读取工作区未提交文件或凭证，未启动原应用。冻结的最终文件数和校验和以 [integration-manifest.json](../handoff/integration-manifest.json) 为准。Vue 双端另见 [前端接入清单](frontend-integration.md)。

本文的“直接复用”是代码级候选判断；“适配”必须按新版合同修改后才能进入运行包；“替换”保留旧设计/测试作参考但实现新合同；“不迁入”表示不接入 Smartlect 运行链。冻结档案可以包含这些类别的纯源码用于解释取舍，不表示已完成集成或验证旧测试成绩。

## Python AI 来源与许可证

实际 Python 根目录为 `AI_Shop-backend/AI_Shop-agent/`，以下表格的 `app/`、`tests/`、`prompts/` 和 `evaluation/` 均相对于这个根目录。知识文档在相邻的 `AI_Shop-backend/data/demo_knowledge/`。

仓库根 `LICENSE.md` 为 MIT，版权声明为 `Copyright (c) 2026 Audreator`。冻结档案保留完整许可证，运行源码真正迁入时保留来源及声明。许可证核对仅针对本仓库声明；运行依赖的许可证随最终锁文件单独核对。

## AI 逐项复用判定

| 能力 | 判定 | 已提交源码依据 | Smartlect 处理与验证边界 |
|---|---|---|---|
| FastAPI 路由、流式会话 | 适配 | `app/main.py`、`app/api/routes/agent.py`、`app/api/websocket.py`、`app/services/stream_service.py`、`message_service.py` | 复用会话/卡片/消息状态概念。API 改 SSE 和持久任务查询；身份只由 Java 会话桥产生，不复制原 WebSocket token 或原数据库连接。 |
| Shopping ReAct 编排 | 替换 | `app/graph/builder.py`、`state.py`、`stages/agent.py`、`orchestration_policy.py` | 旧图存在 workflow/single-agent/multi-agent 自适应路由，状态字段还包括 fanout/synthesis。按新规格保留有界工具循环、取消和终态思路，落为单任务 Shopping 图；不整体搬入庞大的路由链。 |
| Supervisor 与多专家群 | 不迁入 | `app/graph/multi_agent.py`、`app/harness/agents/registry.py`、`app/graph/experimental.py` | 旧实现含 SupervisorPlan、SpecialistTask、Send fanout；不是新版 Merchant Agent。新系统只由可信入口选择 Shopping 或 Merchant，不通过 LLM 总控派发专家。 |
| 提示词与 Skills | 适配 | `prompts/agent.txt`、`global.txt`、`compress.txt`、`react_supplement.txt`、`app/services/prompt_service.py` | 保留“业务事实来自回执”“政策独立分支”“写操作先提案”等规则；移除旧品牌、让模型填写 userId、强绑定 MCP 和“不能代客下单”等旧合同。按 HANDOFF 的 6 个业务 Skills 渐进加载，不把原提示词拼成一个大总提示。 |
| 模型客户端 | 适配 | `app/services/llm_factory.py`、`app/observability/llm_metrics.py`、`tests/test_llm_factory.py`、`test_llm_usage_metrics.py` | 复用配置解析、连接复用、请求超时、使用量记录。统一 `qwen3.7-plus`；不用旧默认 DeepSeek 或自动 fallback 模型，live/mock/fallback 记录分离。供应商工具/结构化输出仍须本项目实测。 |
| 工具参数与执行边界 | 适配 | `app/tools/engine.py`、`schemas.py`、`arguments.py`、`app/domain/tool_policy.py`、`app/services/tool_invoke_result.py` | 复用 Pydantic 校验、读操作有限重试、写操作不自动重发、超时与回执分类。旧公共 schema 明确暴露 userId/runId，必须改为模型不可填的 ActorContext；保留 Java 对最终身份/归属/报价的校验。 |
| Java 内部接口适配 | 适配 | `app/services/java_internal_client.py`、`tests/test_agent_delegated_identity.py` | 复用 `ContextVar` 委托作用域及退出恢复模式，按 Smartlect 的受控接口裁剪；不能恢复旧 search、图片/通知/FAQ 等整条服务链。仍以现有 `growth/src/smartlect/commerce.py` 与 Java 接口为基线。 |
| 管理员签名校验 | 适配 | `app/auth/admin_assertion.py`、`tests/test_admin_assertion.py` | 已实现 method/path/body hash/主体/权限/时窗/HMAC/nonce 校验，可参照现有 Java signer 对齐；生成独立 Smartlect 签名密钥，并使用本项目持久/共享 nonce 状态，严禁继承默认口令或旧 secret。 |
| 交易提案与恢复 | 适配 | `app/services/pending_action_store.py`、`pending_action_service.py`、`action_execute_service.py`、`tests/test_pending_action_business_key.py`、`test_action_execute_service.py` | 旧 MySQL 提案状态有 PENDING/EXECUTING/INCONCLUSIVE/MANUAL_REVIEW 等，可复用条件更新/归属/幂等思路。新增具体确认报价绑定、下单和付款恢复；“命令受理”不能等同“业务已终结”。不覆盖现有 Java 金额/库存修复。 |
| RAG 召回流程 | 替换 | `app/rag/retriever.py`、`catalog.py`、`app/services/java_internal_client.py` 的 knowledge/FAQ 方法 | 旧流程依赖 Java search/Elasticsearch 与旧目录版本。按新规格由 Python/MySQL 保存版本化文档和切片，先落词法两步检索；不恢复 ES 或旧 Java AI 服务。 |
| RAG 引用与拒答 | 适配 | `app/rag/grounding.py`、`prompt_builder.py`、`evidence_selector.py`、`result_projection.py`、`tests/test_rag_answer_scope.py`、`test_rag_output_closure.py` | 保留引用证据与回答域分离、引用不足拒答思路；新引用绑定实际 doc/chunk/version/ACL。旧 canonical facts 不能直接用作 Smartlect 已发布政策或正确答案。 |
| RAG 发布/ACL/有效期 | 适配 | `app/rag/lifecycle.py`、`tests/test_rag_lifecycle.py` | 旧代码缺 ACL 时视为 PUBLIC、缺 status 时不会拒绝；新文档必须显式记录发布状态与访问策略并从可信身份过滤。不能只移植旧过滤器即声称安全门禁完成。 |
| Embedding 与 rerank | 适配 | `app/rag/embedding.py`、`reranker.py`、`tests/test_embedding_evaluation.py`、`test_rerank_config.py` | 可复用供应商协议、响应索引校验和降级标记，替换 `mall:rag:*` 缓存命名空间；去掉运行时依赖旧 evaluation 包。有限索引从新 MySQL 切片/向量重建，不接旧向量缓存/服务。 |
| RRF 与本地 hash embedding | 适配 / 不迁入语义路径 | `app/rag/rrf.py`、`local_embedding.py` | RRF 排名公式可复用，但 `rrf_merge(limit=0)` 原实现仍返回 1 个结果，要修正空上限并覆盖重复候选。hash embedding 只能作为明确的测试/降级，不能冒充语义向量或混合检索成绩。 |
| token 预估 | 直接复用候选 | `app/memory/token_estimator.py` | 纯标准库估算器不持有身份或外部状态；只用于上下文截断预算，实际 token/费用必须用供应商回执。后续按新包名迁入并保留可运行检查。 |
| 会话摘要与短期上下文 | 适配 | `app/memory/context_builder.py`、`compress_service.py`、`session_memory_service.py`、`models.py`、`tests/test_memory_context.py`、`test_session_memory_revision.py` | 保留完整轮次截断、结构化摘要与 revision 防陈旧覆盖。旧存储按 user_id 聚合；新隔离键必须包含 actor/session/execution scope，摘要不作为价格/库存事实，删除和禁用偏好按新合同处理。 |
| 用户长期偏好 | 适配 | `app/services/shopping_profile_service.py`、`shopping_mission_service.py`、`tests/test_shopping_profile.py`、`test_shopping_mission.py` | 复用显式预算/偏好/约束、来源、到期和用户更正思路；裁剪旧类目硬规则，重做存储隔离；隐式点击低权重，不能反向覆盖当前用户明确限制。 |
| 可售 SKU 与推荐 | 适配 | `app/services/final_offer_snapshot_service.py`、`product_constraint_evidence.py`、`recommendation_contract_service.py`、`recommendation_event_store.py` | 复用最终 SKU 证据、报价快照与触点契约概念；金额改用整分/Decimal、候选来自现有 Java，补持久分桶和广告/推荐独立归因。不能采用旧 Python 快照替代 Java 创建订单时确认报价匹配。 |
| 经营分析 | 适配后替换执行入口 | `app/services/data_analyst_service.py`、`analytics_semantic_compiler.py`、`analytics_catalog.py`、`analytics_policy.py`、`sql_guard.py` | 旧服务存在模型生成 `SqlDraft` 和直接只读 SQL 执行，即便有 SQL guard 也不接给新 Agent。只复用指标目录、时间窗、缺数据拒答与证据披露，执行端改白名单指标/维度 DSL → 参数化查询新增长库。 |
| Merchant 规划与情景经验 | 新增 | 旧 analytics/inventory 服务只提供分析参考，未发现满足新授权 envelope 与跨轮预算合同的完整实现 | F5 使用新成交账本/活动回执 Observe→Plan→Grant→Execute→Await→Replan；新 run/plan 不重置累计预算。经验必须可审核，不自动改写 prompt/Skills。 |
| Trace 与成本 | 适配 | `app/services/episode_service.py`、`episode_query_service.py`、`app/graph/tracing.py`、`app/observability/llm_metrics.py`、`tests/test_episode_service.py`、`test_trace_admin_api.py` | 复用脱敏、ContextVar 绑定、步骤/终态/usage、first-token 观测；保留新业务任务/交易主键关联。旧 writer 同时涉及 commerce_outcome_ledger，不迁其 SQL；使用新 schema，财务 ACK 不等待模型/trace。 |
| Badcase 闭环 | 适配 | `app/services/badcase_service.py`、`episode_review_service.py`、`tests/test_badcase_admin_api.py` | 复用 NEW→TRIAGED→LABELED→REGRESSION_ADDED 等审核概念、脱敏样例与回归关联。历史候选/聊天/人工标注不复制，重新从本项目执行结果产生。 |
| 回归与评测 | 适配 | `app/services/regression_replay_service.py`、`app/services/episode_evaluator.py`、`evaluation/core/`、`evaluation/adapters/`、`tests/test_regression_replay_service.py` | 旧 replay 仅对文本执行 `resolve_intent(allow_llm=False)` 或重新判定存档 Episode；这不等于真实模型端到端重跑。复用断言/故障注入思路，新建版本冻结场景、独立状态四分支与 live 两次重跑。 |
| 旧财务账本/消费者 | 不迁入运行包 | `app/services/commerce_outcome_ledger_service.py`、`commerce_outcome_queue_consumer.py` | Smartlect 已有更贴合金额/重投/乱序的 `events.py` 与实测记录；只参考旧测试场景，不替换当前账本、消费 ACK 或订单代码。 |
| MCP、视觉、学习管线 | 不迁入首版运行链 | `app/mcp/`、`mcp_server/`、`services/mcp_*`、`visual/`、`learning/`、旧 OTLP 部署配置 | 首版直接用共享内部工具与 Java HTTP；视觉检索、自训练数据管线和外部观测基础设施不是新主线所需。保留必要纯源码档案，不新增依赖/进程。 |

## 实际冻结范围与后续适配建议

以下白名单已由 [freeze_integration.py](../handoff/freeze_integration.py) 导出，逐文件 SHA-256/Git blob ID 记录于 manifest；这仍是输入档案，不是运行时安装清单。后续源码只从 Smartlect 冻结包取材。

`shop-ai-python.zip` 实际 542 个文件，SHA-256 为 `bf6078002b4b5b1f336fd8653405a4303c665f109cfe5f9ed3d35fc616c15ddf`：app 246（含 3 份非 Python 源码配置）、tests 188、evaluation 70、fault_drill 5、prompts 17、依赖清单 3、演示知识 Markdown 12、许可证 1。`shop-frontends.zip` 实际 426 个文件，SHA-256 为 `7be44cae181067e4e4d993b25e56bbb9813656da8eb22619895d334561933da2`；6 个来源未明的二进制装饰素材已从初次未提交快照移除，最终包不包含这些媒体、public/PWA 内容或 PWA 生成脚本。

| 路径范围 | 内容与限制 |
|---|---|
| `AI_Shop-backend/AI_Shop-agent/app/**/*.py` | Python 纯源码；包括被判为不迁入运行链的模块，便于后续按固定版本核对；不可整体作为新 app 包启动。 |
| `AI_Shop-backend/AI_Shop-agent/tests/**/*.py` | 单元/集成测试源码；合成 fixture 以 Python 常量存在时仅作测试参考。依赖旧数据库、私有 holdout、历史结果的测试不属于可直接运行门禁。 |
| `AI_Shop-backend/AI_Shop-agent/evaluation/**/*.py`、`fault_drill/**/*.py` | 评测与故障代码；不含运行产物或数据集。静态源码可能指向未冻结材料，适配时重建本项目输入而非回原目录读取。 |
| `AI_Shop-backend/AI_Shop-agent/prompts/*.txt` | 17 份提示词源码，仅供适配，不直接装为生产 Skills。 |
| `AI_Shop-backend/AI_Shop-agent/app/config/search_taxonomy.yml`、`search_runtime_taxonomy.yml` | 手写类目、同义词和规格证据词表，不含订单/用户行；按 Smartlect 演示目录裁剪。 |
| `AI_Shop-backend/AI_Shop-agent/app/resources/analytics-catalog-v0.provisional.json` | 指标字段、权限、口径、数据类型元数据，明确 `provisional`/`releaseGateEligible=false`；不能当作新系统经营事实。 |
| `AI_Shop-backend/AI_Shop-agent/pyproject.toml`、`requirements.lock`、`uv.lock` | 保存原依赖证据；Smartlect 不整套安装，应保留一个新锁定方式。 |
| `AI_Shop-backend/data/demo_knowledge/*.md` | 12 份项目演示政策/流程，未含用户/交易记录。需更名、删除旧支付/服务能力承诺、与本项目确认报价和模拟支付合同一致后才能发布。 |
| `LICENSE.md` | 原 MIT 完整许可证。 |

不冻结 `.env`、证书、原日志、用户上传、运行数据、权重、依赖目录、原启动/停止/清库脚本。`evaluation-evidence/` 与 `docs/evidence/` 是历史结果，不能迁作本项目验收；`evaluation/datasets/`、`evaluation/fixtures/` 来源/隐私未完整核验，不作为本轮输入。`demo_knowledge*/catalog*.json` 和 `fact-metadata*.json` 是旧目录/事实索引，不自动继承；v2–v5 不作首版必需知识，尤其 v5/19 的真实品牌商品目录文本不属于已核验的纯合成商品集。

## 模型配置白名单依据

下表列旧代码确实使用的字段名及后续适配决定，未读取或记录凭证值。新配置必须位于 Git 忽略且权限 600 的 `run/model.env`，使用非执行 dotenv 解析；模型字段以外一律不映射。模型配置的实际迁移状态由根实施记录给出。

F0 已实现 [migrate_model_env.py](../handoff/migrate_model_env.py)：实际只映射主模型 key/base URL、embedding 的 key/base URL/model/dimensions/provider、rerank 的 key/base URL/model/API format，并识别表内 DashScope/provider 别名；统一写 `SMARTLECT_` 前缀并固定主模型 ID。fallback、memory 独立模型、rerank instruct/timeout 未继承，按需由新实现配置。当前迁移器只接受核验过的阿里模型供应商 HTTPS endpoint，不执行插值或 shell 内容。启动器仅将这些模型字段合并给 Python 应用，不能覆盖业务凭证。

| 旧字段 | 已提交消费方 | 新配置处理 |
|---|---|---|
| `LLM_API_KEY`、`LLM_BASE_URL` | `app/services/llm_factory.py:chat_llm_config` | 仅映射为新主模型 key/供应商 endpoint；确认是模型供应商，不复用原应用 localhost 端口。 |
| `LLM_MODEL` | 同上 | 不继承旧值，新默认固定 `qwen3.7-plus`；供应商不支持时明确失败，不能自动升级旗舰。 |
| `LLM_FALLBACK_API_KEY`、`LLM_FALLBACK_BASE_URL`、`LLM_FALLBACK_MODEL` | `chat_llm_config(fallback=True)` | 证明旧客户端存在独立 fallback；新首版不继承自动模型切换。若用于识别用户已有 Qwen 供应商配置，只能映射主模型所需 key/endpoint，不复用旧型号。 |
| `MEMORY_LLM_API_KEY`、`MEMORY_LLM_BASE_URL`、`MEMORY_LLM_MODEL` | `create_memory_llm` / `_resolve_memory_llm_config` | 旧摘要客户端有独立覆盖，空字段回主模型；新首版共享已核验主模型配置即可，不增加第二套模型路由。 |
| `EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSIONS` | `app/rag/embedding.py` | 按需白名单映射；请求是 OpenAI-compatible `/embeddings`，维度必须绑定切片索引版本并实测。 |
| `EMBEDDING_PROVIDER` / `SPRING_AI_MODEL_EMBEDDING` | `settings.py` 的别名及 `embedding.py` | 只接受新实现支持的 provider，旧 `local` 是 hash 测试实现，不宣称真实向量模型。 |
| `RERANK_API_KEY` / `DASHSCOPE_API_KEY` | `settings.py` 的别名及 `rag/reranker.py` | 只映射为 rerank key；不能用通配符抓取所有 key。 |
| `RERANK_BASE_URL`、`RERANK_MODEL`、`RERANK_API_FORMAT`、`RERANK_INSTRUCT`、`RERANK_TIMEOUT` | `app/rag/reranker.py` | endpoint 是完整 rerank URL，支持 `compatible` 与 `dashscope_native` 两种请求体。先按真实字段值核验供应商和协议，再决定启用；失败必须可观测。 |

`INTERNAL_TOKEN`、`AISHOP_INTERNAL_TOKEN`、`ADMIN_ASSERTION_*`、数据库/缓存/消息/支付凭证、pilot/privacy secret 均禁止继承。超时、循环次数、重试数由 Smartlect 新运行约束提供；旧累计费用硬上限和模型单价不作为新事实。

## 依赖与未验证范围

源 `pyproject.toml` 声明 Python `>=3.11,<3.14`，FastAPI `0.141.1`、LangGraph `1.0.10`、langchain-openai `1.1.14`，同时包含 MCP、OTLP、视觉、SQL 分析等整套依赖。该清单是来源事实，不是 Smartlect 的兼容测试结果。F0 已建立本项目 [requirements.lock](../growth/requirements.lock)，保留 Pika/PyMySQL 账本依赖，直接选 FastAPI/Pydantic/原生 SSE、LangGraph、httpx 和 python-dotenv；模型用 httpx 兼容接口，不安装 langchain-openai/MCP/OTLP/视觉等旧应用依赖集合。实际安装和依赖合同检查见 [ADR](adr/0001-final-integration.md) 与根实施状态，旧三套清单不作为新包安装入口。

本次仅做源码审读与取材判定，没有运行旧应用、旧测试或真实模型调用；因此不报告旧项目测试数、召回率、增长收益或模型能力为 Smartlect 新成绩。现有交易与事件账本不作覆盖迁移。

## F2 实际落地

以上表格保留F0审读依据；F2已经用冻结ZIP适配落地：Provider协议/usage边界、单Shopping图、3项用户Skills、共享严格工具与提案回执、中文词法与RRF思路、版本引用/拒答、完整轮次上下文和偏好。旧依赖Java/ES的检索器改为MySQL切片+BM25+真实embedding；未迁hash语义向量。上下文改为更保守UTF8字节预算，旧token估算器最终未直接搬入。摘要使用可追溯用户原话抽取，不另增加摘要模型。

32份新合成店铺政策重新编写，旧运行知识/用户上传/结果未导入。MIT版权保留在 `growth/licenses/shop-ai-python-LICENSE`。用户端实际选取和改造见 [frontend-integration.md](frontend-integration.md)，管理员断言最终未接为第二套登录。旧Badcase/完整评测与Merchant实现仍不算迁入完成；新44例RAG集只是冻结预期，实际评测留F6。
