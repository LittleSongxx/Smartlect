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

## 质量指标（2026-09-30 当前配置基线）

评测口径：聊天模型 `deepseek-flash` + 百炼 `qwen3.7` 系 embedding/reranker，全 live 路径真实运行。完整证据、失败样本与数值适用边界见 [eval/verification/rerun-20260930/](eval/verification/rerun-20260930/)（含 SHA256 指纹清单）。

| 指标 | 结果 | 严读数（R@1＝首位命中任一金标） |
| --- | --- | --- |
| 商品召回正式门禁（v1 release 225 例＝155 正例＋70 负例，K=3 业务口径） | **PASS**：Recall@3 0.991 / MRR 1.000 / NDCG@3 0.981 / 负例 70/70 / 零降级 / 同款重复 0；K=8 监控线 0.994 | 1.000（155/155，复算值） |
| 品类知识召回门禁（22 例，库内 5 篇，诊断档口径） | **PASS**：Recall@3 1.000 / MRR 0.977 / NDCG 0.979 | 0.955（21/22，复算值） |
| 检索管线对照（v2-hard 无品牌提示，54 例＝48 正例＋6 负例） | R@5 0.995 | **R@1 0.649 / R@3 0.906** |
| Agent 正式门禁（30 例，程序断言 + LLM judge） | 27/30 PASS，均分 0.950 | — |
| 记忆提取（50 例＝原 12＋38 扩充） | **50/50 PASS** | — |
| 上下文治理（6 场景×2 策略×3 次＝36 runs） | 36/36 通过；分层治理 input token 相对 legacy 降幅 **34.68%** | — |
| 后端回归 | 1465 passed / 2 failed / 1 skipped（2026-10-01 冻结树复跑，1468 项收集）；另有 1 项队列租约测试为已知偶发（单独复跑 5 次 4 失败 1 通过），两次全量分别落在 3 项与 2 项失败。失败项均与检索链路无关 | — |

读数说明：

- **R@1 只有 [retrieval_v2.py](scripts/eval/retrieval_v2.py) 会一次运行直接产出**；[run_product_recall.py](scripts/eval/run_product_recall.py) 与 `run_category_recall.py` 的报告只有 Recall/Precision/MRR/NDCG@K，**没有 @1 分档**——表中前两行的 R@1 是从逐题召回序离线复算的，复算脚本与输出见 [eval/verification/readme-metrics-20261001/](eval/verification/readme-metrics-20261001/)。R@3 是贴近"每次推三张商品卡"的业务口径，@5 及以上是管线对照值。
- 商品召回门禁已于 2026-09-30 从 45 例（37 正例＋8 负例）扩到 **225 例**：扩充集把 R@3 压到 0.742 BLOCK、如实暴露"紧价格约束 × 语义召回"的结构性盲区，修复（主链路约束预过滤＋金标完备性回补）后回到 0.991 PASS。旧集的 Recall@3 0.946 / MRR 0.946 / NDCG@3 0.927 只作过程证据保留，**不再是门禁口径**；更接近真实难度的参照是同一批数据的 **Recall@8 0.973**（单正例、无品牌提示、含负例约束）。
- 检索评测集是**合成目录上的受控实验**（多正例、查询与描述同源模板），v2 的 0.99+ 不代表真实用户查询召回率；各集规模、扣分构成与已知局限见证据目录 README 的"数值适用边界"节。Agent 门禁的 LLM judge 与被测模型同为 `deepseek-flash`（自评偏宽风险），P0 关键断言为程序判定不受影响。

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

```bash
# 商品召回正式门禁（K=3 业务口径，需 embedding+reranker）
uv run python -m scripts.eval.run_product_recall --dataset eval/v1/product_retrieval.jsonl \
    --split release --formal-gates --report-dir <新目录>

# 检索管线对照（@1/@3/@5 阶梯；v2-hard 为去品牌提示视角）
uv run python -m scripts.eval.retrieval_v2 --split holdout --live --output <新目录>
uv run python -m scripts.eval.retrieval_v2 --split holdout --live \
    --dataset eval/v2-hard/product_retrieval.jsonl --output <新目录>

# 品类知识 / 记忆 / 上下文治理
uv run python -m scripts.eval.run_category_recall --formal-gates --report-dir <新目录>
uv run python -m scripts.evaluate_memory --output <新文件>
uv run python -m scripts.eval.run_context --cases-file eval/context/cases-v3.jsonl \
    --split holdout --case <场景> --strategies legacy,layered --repetitions 3 --output <新目录>

# Agent 门禁需先起服务；judge 直连环境变量，先 source .env 再运行
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
