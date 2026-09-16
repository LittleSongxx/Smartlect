# AI Agent 层高可用工程：盘点、补齐、压测与一次真瓶颈的挖掘（ai-agent-ha）

日期：2026-09-15 ｜ 状态：**已完成**（防护补齐 + 并发塌陷修复 + 双场景压测落档）
证据：服务器 `/opt/cluster/evidence/loadtest-20260915-{1531,1619}-growth/`（k6 日志与窗口戳）；提交 `62230a2`（防护）、`db2d182`（SSL 修复）

## 背景

此前所有压测只覆盖 Java 浏览链路（browse），AI Agent 层（growth：FastAPI + worker 两进程，Python asyncio + MySQL + RabbitMQ + LLM API）从未做过并发测试。本专题分三步：**工程化盘点 → 补齐缺失防护 → 压测**，并在压测中挖出一个让 AI 层并发塌陷到 ~3 req/s 的真瓶颈。

## 一、盘点结论（改动前）

已有且扎实：超时全覆盖（模型 25s 双重、run 85s、网关 95s、工具 30/15s、归因 200/500ms）；降级链完整（ProviderError→四类降级文案+建工单、mock/rule-fallback/live 三态、重排→规则、检索路由→空集）；持久化兜底强（run context 逐步落库、租约乐观锁、SSE 断线回放）；队列消费先落库后 ack、幂等 + 死信（Java 侧 DLX）；run 级预算（模型调用≤16、工具≤10）。

缺失（本专题补齐）：**熔断（完全没有）**、**growth 内部限流（并发对话数无上限）**、**缓存（query embedding 现算 / RAG 检索每次全量扫 ≤5001 chunk / LLM 响应无缓存）**、重试无退避、httpx 客户端每调用新建。

## 二、补齐的防护（提交 62230a2，零新依赖）

| 防护 | 实现 | 语义 |
|---|---|---|
| 熔断 | `Provider._Breaker` 按 MODEL/EMBEDDING 分端点：连续 4 次 `_request` 失败 → 开闸 30s，期间所有调用**立即** `model_circuit_open`（不再傻等 25s 超时）→ 冷却后单探针半开。env 可调（`SMARTLECT_MODEL_BREAKER_FAILURES/COOLDOWN_S`） |
| 并发闸 | 新 run 启动前两道门：每 actor 在飞 run ≤3（`actor_run_limit`）、全局 ≤24（`assistant_busy`），均 429；按进程内在跑任务计数，**幂等重放不经过闸**；shopping 与 merchant 运行都计入 |
| embedding 缓存 | `embed(cacheable=True)` 仅查询路径：同文本 30 分钟内复用向量（512 条 TTL 缓存），**不消耗 run 预算不占信号量**；索引发布路径强制不走缓存（重发布必须真调模型） |
| 检索缓存 | `knowledge.search` 精确结果缓存（键=身份+过滤器+向量哈希+catalog revision，5 分钟 TTL）：同问免掉两次 ≤5001 chunk 全量扫描；发布 bump revision 即失效。接受 expiry/ACL 变更最多 5 分钟滞后 |
| 重试退避 | 两次尝试间隔 0.2s→指数+抖动（上限 2s） |
| 连接复用 | Provider 进程内共享一个 httpx.AsyncClient（原每尝试新建） |
| 刻意不做 | **LLM 答案级缓存**——多轮 Agent 语义上不允许同文同答（上下文不同） |

测试：+7 个用例（熔断开/半开/分端点、embedding 缓存预算语义、共享客户端、TtlCache 边界、检索免扫、两道 429 闸），growth 389 全绿、`dev.sh check` 全绿。

## 三、压测挖出的真瓶颈：每连接重建 TLS/CA 上下文（提交 db2d182）

首次控制面压测（50-400 VU 打 session+recommendations）出现荒诞现象：**growth 单进程烧 8 核、并发塌陷到 ~3 req/s**，20 个并发请求全部 ~7s 齐步完成。py-spy 现场抓栈，12 个 worker 线程全部停在同一处：

```
pymysql.connections.__init__ → _create_ssl_ctx → ssl.create_default_context → load_default_certs
```

两个独立缺陷叠加：

1. **pymysql 2.x 的 PREFERRED 模式**：不传 ssl 参数也会为每条新连接构造 SSL 上下文 = 完整加载一遍系统 CA 库（数百张证书，纯 CPU 100-300ms）。而 growth **每次 db() 跳都新建 MySQL 连接**（无连接池），每请求 6-10 跳 = 每请求数 CPU 秒。
2. **auth/commerce 每次调用新建 `httpx.AsyncClient`**：构造函数在**事件循环线程上**同步加载 CA——每请求的循环被自己的证书加载阻塞，单循环 rps 被钉死。

修复：`connect_from_env` 加 `ssl_disabled=True`（MySQL 仅 loopback，TLS 无意义）；IdentityBridge / AsyncCommerceClient 改为实例级共享客户端（与 Provider 同款）。

修复前后（20 并发 recommendations）：**med 7.0s → 1.1s，max 7.2s → 1.37s**，完成时间摊开（真并行）。教训入档：**asyncio 应用的并发塌陷，先 py-spy 抓栈再谈架构**；每连接/每调用重建重量级对象（TLS 上下文、CA 存储）是 Python 服务最隐蔽的 CPU 黑洞。

## 四、压测结果（修复后）

### 对话链路（真 LLM，node2 单发，每轮完整 Agent run）

| 并发 | 完成数/2min | run 时延 med / p95 | 失败 | 429 |
|---|---|---|---|---|
| 1 VU | 20 | 6.2s / 7.2s | 0 | 0 |
| 2 VU | 27 | 6.2s / 19.1s | 0 | 0 |
| 4 VU | 28 | 12.3s / 30.2s | 0 | 0 |
| 8 VU | 27 | 27.5s / 55.2s | 0 | 0 |

- **AI 吞吐天花板 ≈ 0.20 run/s（12 轮/分钟），2 VU 起封顶**——这是 `Semaphore(2)` 模型并发闸的刻意设计（成本保护），超发并发只放大时延（~线性），零失败零降级。
- 缓存实证：同一问题冷跑 22s（curl 探针）→ 热路径 **6.2s**（embedding+检索缓存命中，少一轮向量化调用与全量扫描）。
- 8 VU 时 27.5s med 仍远离 85s run 死线；闸门（actor 3 / 全局 24）未被触发（每个 VU 独立 visitor）。

### 控制面（session+recommendations，双发）

| 总 VU | req/s | med | p95 | 失败 |
|---|---|---|---|---|
| 50 | 29 | 348ms | 3.3s | 0% |
| 100 | 30 | 620ms | 6.4s | 0% |
| 200 | ~16 | 1.5s | 31s | 0% |
| 400 | ~14 | 7.3s | 60s(超时) | 10.9% |

- 控制面吞吐平台 ≈ **30 req/s**（修复前实测同场景 ≈3 req/s + 大面积超时）。
- 400 VU 仍拥塞：剩余瓶颈为 to_thread 默认 12 线程 + Java 召回往返。（后续「全面加强浪潮」已把每事务新建连接换成线程本地长连接并复测：控制面平台没有因此上移，剩余瓶颈是推荐链路多跳深度。）

## 五、下一排杠杆（按性价比，未做）

1. ~~growth 侧 MySQL 连接池~~——线程本地长连接已落地（1e0652f），复测 30 req/s 平台未上移；
2. uvicorn workers>1 或多进程（突破单事件循环）；
3. recommendations 链路里 Java 召回结果的短 TTL 缓存；
4. 模型信号量按负载分级（如队列深度>阈值时临时放大并加告警）。
