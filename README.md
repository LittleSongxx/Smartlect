# Smartlect · 从商品检索到交易确认的电商 Agent

一个基于 **AgentScope、AG-UI 和 React** 的全栈 Agent 实战项目：从自然语言需求理解出发，完成商品检索、方案比较与交易确认，覆盖 Agent 应用的关键工程问题——业务工具调用、长期记忆、长对话上下文治理，以及在刷新、断线和人工审批之间保持状态一致。

> 当前使用版本化样例商品目录和本地订单账本，尚未接入真实电商供给、支付或物流。

## 一次选购，从描述需求开始

> 预算 300 元以内，帮我找一个寄到中国的轻便背包。

Agent 根据需求调用检索与业务工具，页面随运行过程展示回答和结构化商品卡（每次默认推荐三张，对应检索 K=3 的业务口径）。你可以继续比较、补充条件，或生成交易确认单。

| 你可以这样说 | 对应的交互 |
| --- | --- |
| "比较刚才两个候选，重点看重量和容量。" | 查看候选差异，继续缩小选择范围 |
| "记住我偏好轻便设计。" | 展示记忆变更审批，批准后保存偏好 |
| "这次不要黑色，换几个其他颜色的。" | 在当前选购中更新需求 |
| "为我选中的商品生成确认单。" | 查看交易信息，明确批准后执行本地订单与库存事务 |

常用的选购方法也可以写成个人 Skill（Markdown 步骤，对话中输入 `/` 选择）；长期偏好支持增删与版本化，负向约束自动落到业务过滤。

## 质量指标（2026-10-04 评测体系重建基线）

评测口径：主模型 `deepseek-flash`，embedding/reranker 百炼 `qwen3.7` 系，Agent 门禁 judge＝glm-5.3 中转（与被测不同家族），全 live 路径真实运行。评测集为本日重建版本（见 [docs/改动记录/2026-10-04/](docs/改动记录/2026-10-04/)），与旧集读数不可比。完整证据、失败样本与 badcase 见各证据目录（含 SHA256 指纹清单）。

| 指标 | 结果（新集首次读数） | 严读数 R@1 |
| --- | --- | --- |
| 商品召回正式门禁（release 90 例＝66 正＋24 负，K=3 业务口径） | **BLOCK**：Recall@3 0.499 / MRR 0.624 / NDCG@3 0.496 / 负例 24/24 / 过滤准确率 1.000；主口径（去 literal 冒烟桶）R@3 0.420；K=8 监控线 R@8 0.580 | 0.304（主口径 0.194） |
| 检索分桶（release） | literal R@1 1.000（词面回声，仅冒烟）/ colloquial 0.369 / semantic 0.136 / composite 0.129——紧约束与价格区间是结构性短板 | — |
| keyword_2gram 离线基线（同集重批） | recall 0.635 / MRR 0.740 / NDCG 0.688，offline-fallback 门禁 PASS（基线绑定选集指纹） | — |
| 品类知识门禁（50 例，K=3） | **BLOCK**：Recall@3 0.927 ✓ / MRR 0.772 ✗ / NDCG 0.794 ✗ / 不可回答准确率 0.000 ✗（9 例域外题全部被当作可答）/ 政策拒答 1.000 ✓ | — |
| Agent 正式门禁（release 54 例，程序断言＋独立 judge） | **BLOCK**：合并 40 PASS / 11 FAIL / 4 ERROR（judge 网关超时）；首轮均分 0.668；失败构成＝偏好写入未调用工具 5＋口语排除未过滤 3＋金额不可溯源 3（faithfulness 程序断言首跑即抓到真实编造） | — |
| 记忆提取（30 例） | 29/30（两次运行；唯一失败为 negative_scope 模型非确定性漂移，如实记录） | — |
| 后端回归 | 1478 passed / 2 failed（嵌入排序敏感，回退提交已注明的已知项）；队列测试用 redis7 二进制两次运行 16/16 与 15/16（1 项租约测试已知偶发；系统 redis 6 下另有 12 项已知环境失败）。证据 `eval/verification/full-tests-20261004.log`、`full-tests-redis7-queue-20261004.log` | — |

读数说明：

- **本表读数显著低于历史版本（旧集 R@3 0.99+）**：旧评测集查询与目录同源模板、金标由生成规则逆推，读数系统性虚高；新集（300 例五桶、独立谓词金标、口语桶、价格区间/排除材质约束）挤出的是真实水平。门禁阈值未随新集调整——检索与品类门禁如实 BLOCK，扣分构成与 badcase 清单见 [质量指标复跑与badcase](docs/改动记录/2026-10-04/质量指标复跑与badcase.md)，系统修复属于后续独立决策。
- 商品检索正式集与运行时目录以 SHA256 指纹绑定（`eval/v1/product_retrieval.fingerprint.json`），目录演进击穿金标会被 runner 预检直接拒绝。
- literal 桶（标题原文查询）R@1 恒为 1.000 属词面回声，仅作回归冒烟，正式读数用"主口径（去 literal）"。
- Agent 门禁 judge 与被测模型不同家族（glm-5.3 vs deepseek-flash），manifest 记录同源警示开关；金额与政策结论由程序化断言对账（`scripts/eval/faithfulness.py`），不依赖 judge。

## 技术栈

| 层次 | 选型 | 用途 |
| --- | --- | --- |
| Agent 框架 | AgentScope 2.0.8（锁定版本） | Agent 执行、工具调用、子 Agent 派发、Middleware 与原生人工审批 |
| 后端服务 | Python 3.11–3.13、FastAPI、Uvicorn | 业务 API、Agent 运行入口与流式响应 |
| 前端应用 | React 18、TypeScript、Vite | 对话界面、商品卡、Skill 编辑、偏好管理与订单页面 |
| 交互协议 | AG-UI、SSE、A2UI v0.9 | 文本、商品与运行状态；自定义 ShoppingForm 以 AG-UI 扩展事件传输 |
| 模型接入 | OpenAI 兼容 API（示例 deepseek-flash） | 聊天模型、工具调用与流式生成；DeepSeek 思考模式协议适配 |
| 商品检索 | Embedding、Qdrant 稠密向量、HTTP reranker；应用层 BM25 + 加权 RRF 为实验档 | 线上主链是稠密向量二阶段召回 + 精排（门禁读数即出自该链路）；召回池按同款（canonical）限流保持款多样性，结果层同款去重。混合召回由 `HYBRID_RECALL_ENABLED` 控制，默认关闭 |
| 品类知识 | Markdown + AgentScope KnowledgeBase | 品类选购知识 RAG；评测快照与线上库分目录维护 |
| 持久化 | SQLite、本地文件 | 会话、运行事件、偏好、Skill、确认单、订单与库存 |
| 缓存与队列 | Redis、Redis Streams（可选） | 缓存、共享限流、异步任务消费；未配置时零外部依赖 |
| 可观测性 | OpenTelemetry、OTLP、Langfuse（可选） | API/Agent/模型/工具全链路 trace，导出前白名单脱敏 |
| 测试与评测 | 后端/前端回归、自定义评测 harness | 确定性契约测试 + 真实模型评测，负例漂移有前置校验 |
| 构建部署 | uv、npm、Docker Compose、Nginx | 依赖管理、全栈部署、静态资源与 API 反代 |

## 工程设计

- **业务分层**：DDD 洋葱架构（domain / application / infrastructure / presentation），`composition.py` 统一装配。
- **Agent 协作**：MainAgent 直接处理简单任务；需要任务拆分或上下文隔离时按需派发 SearchAgent / TradeAgent（SubAgent as Tool，同轮并发）。
- **上下文治理**：语义偏好召回、Skill 按需加载、工具证据归档与 `result_ref` 回查、同款去重、白名单校验的摘要压缩、按网关实测的 token 校准。
- **可靠性**：本地事务与幂等控制、会话 lease/fencing/CAS、模型层限流闸门（名额持有到流耗尽）与备用模型回退、熔断与半开单探测、断线后运行恢复。
- **人工审批**：记忆变更走原生 ASK 审批（AG-UI 事件流 + REST `confirmations` 通道），交易走确认卡，刷新后待审批状态可恢复。

## 快速开始

本机模式（SQLite + 本地 Qdrant 嵌入，无需预装数据库）：

```bash
cp .env.example .env   # 填入 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 等
uv sync --locked
uv run python -m uvicorn app.presentation.server:app --host 127.0.0.1 --port 8000

cd frontend && npm ci && npm run dev   # http://localhost:5173
```

embedding/reranker 未配置时检索自动降级关键词召回；Redis/Langfuse 留空即关闭。容器部署见 `docker/docker-compose.yaml`。

## 评测复跑

评测集由确定性生成器产出（改目录/改配比后重新生成并过 `validate_datasets`）：

```bash
# 生成器（改动后按当前目录重算金标并写指纹 sidecar）
uv run python scripts/build_eval_retrieval.py    # 商品检索 300 例
uv run python scripts/build_eval_agent.py        # Agent 180 例（冻结原 100 + 追加）
uv run python scripts/build_eval_category.py     # 品类知识 50 例
uv run python scripts/build_eval_memory.py       # 记忆 30 例
uv run python -m scripts.eval.validate_datasets  # 数据集契约自检（必绿前置）

# 商品召回正式门禁（K=3 业务口径，需 embedding+reranker；目录指纹不一致会拒绝开跑）
uv run python -m scripts.eval.run_product_recall --dataset eval/v1/product_retrieval.jsonl \
    --split release --formal-gates --report-dir <新目录>
# 关键词降级档（离线，基线已绑定选集指纹）
uv run python -m scripts.eval.run_product_recall --dataset eval/v1/product_retrieval.jsonl \
    --split release --strategy keyword_2gram --profile offline-fallback \
    --baseline-file eval/v1/baselines/keyword_2gram.json --report-dir <新目录>

# 品类知识 / 记忆
uv run python -m scripts.eval.run_category_recall --formal-gates --report-dir <新目录>
uv run python -m scripts.evaluate_memory --output <新文件>

# Agent 门禁需先起服务（SEMANTIC_CACHE_ENABLED=0）；judge 走独立网关，先 source .env 再运行
set -a; source .env; set +a
uv run python scripts/eval_regression.py --cases eval/v1/agent_cases.yaml \
    --split release --base-url http://127.0.0.1:8000 --report-dir <新目录>
```

注意：评测输出目录必须是不存在的新目录（防覆盖原始证据）；模型类评测产生真实 API 费用；换模型后指标不与旧基线可比。

## 目录结构

```
app/            后端（DDD 洋葱架构：agents/tools/prompts/usecases + infrastructure + presentation）
frontend/       React 对话与商品卡界面
eval/           评测数据集与验证证据（verification/ 下按日期归档，含指纹清单）
knowledge/      品类知识库（Markdown + AgentScope KnowledgeBase）
scripts/        评测与工具脚本（eval/ 子目录为各评测入口）
tests/          后端测试与第三方协议契约
docker/         Compose 部署
```

工程协作约定见 [AGENTS.md](AGENTS.md)。
