# Smartlect 面试可讲改造 changelog

范围：阶段 0–6 已按任务书接线（能接的接真线，接不上的标明未接线）。未 commit。

权威：任务书 > 行业通行做法 > 测试（冲突则改测试）> 现有代码。

用户已拍板：

- A. 首页推荐 treatment 真接 `semantic_rerank`，保留 `StrategyStore`，删除未接线 `ABTestEngine`，失败回落规则排序。
- B. 待评价只靠 `commentStatus`，删除落库状态 `WAIT_COMMENT=8`。
- C. `search_skus` / `recommend_skus` 拆成两个函数；推荐走约束检索，不走首页五路。
- D. `decision_record` 改名为审计、audit-only、预算对齐 `SMARTLECT_MODEL_CALL_LIMIT`，不改 `answer_status`。

## 阶段 0 — 空招牌拆除 + 文案名实

### 改了什么 / 为什么

1. **MCP**（`growth/src/smartlect/mcp.py`，`app.py` MCP `invoke`）
   - 删除 Streamable HTTP 自称。`tools/call` 的 `search_knowledge` 传入与购物相同的 `embed_query`。
   - 未知协议版本回已支持版本，并返回 `protocolVersionDowngraded` / `requestedProtocolVersion` / `supportedProtocolVersions`。
   - 面试：这是单次 JSON-RPC POST，不是 MCP Streamable HTTP 会话。

2. **购物 prompt 热更**（`agents/shopping.py`）
   - `provider.chat` 传 `context['prompt_version']`（热更后的 `prompt_label`），不再写死常量 `shopping-react-v25`。
   - 打包默认 label 仍可叫 `shopping-react-v25`，那是提示词版本名，不是检索/推荐算法版本。

3. **熔断半开**（`provider.py` `_Breaker`）
   - 冷却后只放行 one probe；`_half_open_inflight` + 锁。注释与实现一致。

4. **Skill 文案**
   - 去掉「无需先调用 `load_skill`」；写明 Skills 预装、`load_skill` 只刷新说明。
   - 商家 Skill JSON 删除未注册的 `get_merchant_context` / `save_merchant_plan`。

5. **`get_my_addresses`**
   - 不改用户地址页 `UserAddressVO`（仍带电话）。管理端 `searchProbe` 只改注释。

6. **A/B**
   - 删除死代码 `recommendation/ab_test.py`。
   - 线上实验仍是 `StrategyStore` control=`rules-v1` / treatment=`content-v1`。
   - `GET /api/assistant/recommendations` 始终传入 `homepage_semantic_rerank`；control 不进入精排，treatment 进入；失败 `content_rule_fallback`，不 500。

7. **Rerank 招牌**
   - 管理端写明：有 Rerank Key ≠ 厂商精排已接线。阶段 2 再接厂商。

8. **算法版本号**
   - 检索/推荐/归因/广告字段改为 `content_hash`，不再写 `zh-coverage-proximity-v2`、`sku-rank-paid-units-v1`、`ad-fatigue-pacing-v1`、`last_valid_ad_click_v1+sku_click_24h_v1`。
   - 新增 `growth/src/smartlect/algo_version.py`。

9. **支付默认 mock**
   - `PayChannel4Mock` / `MockPaymentController` / `PayAttemptService` 的 `matchIfMissing` 改为 false。本地/测试须显式 `smartlect.payment.mode=mock`。

10. **901**
    - `CODE_901` 只表示未认证/会话失效。限流走 HTTP 429（`CODE_429` / `HttpBusinessException(429)`）。网关 Sentinel 已是 429。

11. **WAIT_COMMENT**
    - 删除枚举 `WAIT_COMMENT=8`。`confirmOrderReceipt` 仍写 `COMPLETED=3`。待评价靠 `commentStatus`。
    - `AccountView` / `OrdersView` 传 `commentPending=1`，不再传 `status: '8'`。
    - `OrderController.loadMyOrder` 用 `commentPending` 过滤已完成+未评价，去掉 8→3 兼容层。

12. **支付宝回调**
    - `notifyDTO == null` 回 `failure`。
    - 查单与回调都认 `TRADE_SUCCESS` 与 `TRADE_FINISHED`。

## 阶段 1 — 正确性地雷

### 改了什么 / 为什么

1. `compile_decision`：`inquire_fact` + `unobserved` → `insufficient`，不得编成 `answered`。
2. 意图改写：询问服务规则不再被改写成建单/办理（`looks_like_service_request` 排除疑问句）。
3. `citations` 按 `chunk_id` 累积去重，不再 `clear()`。
4. `compile_search_filter` 优先生效模型 `product_id`。
5. 购物主路径 `tool_choice=auto`。终答仍走 `finish_answer` + `validated_json_message`。阶段 1 **不删** `finish_answer`。
6. 合同修复注入 `role=system`，不伪造 `role=user`。
7. `finish_reason=length` → `model_output_truncated`（可重试），提高 `max_tokens`，不转人工。
8. 购物 lease 每轮 `renew_lease(ttl_seconds=90)`，与商家心跳一致。
9. 发工具前服务端生成 `uuid` `call_id`，不用模型 `tool_call.id` 当地久主键。
10. 熔断半开与阶段 0 同一实现。
11. `decision_record`：`attach_shopping_audit` 只写 `audit`/`audit_checks`（保留 `decision`/`checks` 别名兼容）。预算 `SHOPPING_MODEL_LIMIT` 读 `SMARTLECT_MODEL_CALL_LIMIT`。不改 `answer_status`。
12. 第 2 次检索改写不再用覆盖率一票否决。
13. `search_skus` = `ShoppingRetrieve.search()` 查询相关性；`recommend_skus` = `ShoppingRetrieve.recommend()` 约束检索。禁止 `return await recommend(params)`。不接 homepage 五路。
14. 热销：`paid_amount IS NOT NULL` 且排除已退款/全退订单。`basis=confirmed_payment_units_excluding_refunds`。
15. 广告 last-click 必须匹配商品或 SKU。窗口可配：默认广告 7 天、推荐点击 24 小时。
16. 广告疲劳改为观众 24h 曝光次数 `1/(1+N)`，点击不再把疲劳钉死为 1。
17. CJK `required_terms` 用 jieba，禁止 `[:2]+[-2:]`。
18. 两套类目不合并：店面 `desk/audio/acc/furn`，广告推理 `200xx`。显式映射表 `catalog_taxonomy.py` + 测试。
19. 库存：不合并库、不上 Seata。`lockAndVerify` 成功、`changeStockBatch` 失败时写明确 outbox（记录拟扣减，不编造回补）。补回归测试。
20. 购物车 `cartId` 改 UUID，列宽 `varchar(36)`。单行数量封顶 **99**（任务书未给数字，changelog 以此为准）。
21. `trial_turns` 从进程内 dict 落到 MySQL `trial_chat_budget`（迁移 `0019_trial_chat_budget.sql`）。超限不消耗溢出次数。

依赖：`growth/pyproject.toml` 增加 `jieba==0.42.1`。本地 venv 已 editable 安装当前包。下次启动 Growth 会应用 0019。

## 本轮测试

- Growth：`PYTHONPATH=src` / editable 安装后 `unittest discover -s tests`，448 项，305 通过，143 跳过（`SMARTLECT_RUN_MYSQL_TESTS` 未开）。
- Java：`OrderCreationIntegrityTest`、`OrderCommerceInternalControllerTest`、`PayChannel4MockTest` 通过。
- Growth `--check` mock 模式 `status=ok`。
- 未跑 MySQL 集成、quality-v2、前端浏览器、支付宝真回调。

## 面试怎么讲

- **空招牌**：对外能力声明与代码路径一致。MCP 不是 Streamable HTTP；有 Key 不是厂商精排完成；901 不是限流；待评价不是订单状态 8；算法版本是内容 hash 不是 `-v25` 贴纸。
- **A/B**：对照组规则排序，实验组真走 homepage 精排，失败回落，页面不 500。
- **导购拆工具**：搜索看相关性，推荐看硬约束。推荐空集就是空集，不拿首页热销填。
- **审计不是闸门**：`audit` 对照预算和证据，终答状态仍由 `compile_decision` 编译。
- **库存**：先锁后扣，中间失败进 outbox，承认「未知结果要核对」，不假装分布式事务。

## 阶段 2 — Checkpointer / 结构化终答 / 按需 Skill / 真流式

自主决策（任务书 > 行业通行做法）：

- Checkpointer：`thread_id=conversation_id`，`checkpoint_ns=agent_run_id`。无 `SMARTLECT_POSTGRES_DSN` 用 `MemorySaver`，有 DSN 用 `PostgresSaver`。图进程内 compile once，节点经 ContextVar 取本轮闭包。MySQL lease 仍是互斥。
- 终答：工具列表不再广告 `finish_answer`。无 tool_calls 时解析 JSON；修复轮走 `response_format=json_schema`。测试假模型仍可发 `finish_answer`，记为 `legacy_finish_answer_tool`。`memory.finish_answer` 只是落库函数名。
- Skills：开场 `BOOTSTRAP_TOOLS={load_skill,search_knowledge,get_conversation_memory,request_handoff}`，业务工具 load 后出现。未加载调用 → `tool_not_loaded` 403。
- 流式：模型 token `on_delta` 写增量 `message_delta`；终答落 `message_complete`，避免前端累加整段。SSE 已有 `id=` / `Last-Event-ID`。
- Token：tiktoken `cl100k_base`，不再用 CJK×2 当硬顶。
- compose：`deploy/compose.yaml` 加 Postgres 16 + pgvector，未拆 MySQL/Redis/Rabbit/Nacos。

## 阶段 3 — 检索漏斗

- 切块 512 token + ~10% overlap（heading-first）。
- 词法：jieba BM25。不再把 MySQL `vector_json` LIMIT 5001 点积当主路径。
- 稠密：有 DSN 才走 pgvector HNSW ANN；否则 `vector_backend=unavailable`，只走词法。
- 融合：RRF。有 `SMARTLECT_RERANK_API_KEY` 才 HTTP 厂商 rerank；无 key / 失败 → `rrf_only` / `rrf_fallback`，不假装交叉编码器。
- `compose_search_query`：改写替换提交查询；原话并行词法，不再拼接。
- 缓存 key 含 ACL + 时间窗（分钟）。facts 仍须原文摘录。
- 未做：本地交叉编码器权重、完整 ANN 评测集上线指标。不要讲召回率。

## 阶段 4 — 鉴权合成

- 一种凭证：Cookie 优先，否则 `Authorization: Bearer`。不再让自定义 `token` 头压过 Cookie。
- 访客：HS256 JWT（exp/iat/jti）。旧 2 段 HMAC cookie 仍能验，避免已发会话全失效。
- CSRF：payload 带 jti，`csrf_nonce` 一次性消费；重放 403 `csrf_replay`。
- `autoLogin` GET 只滑 TTL，不轮转 token。
- `vuzPteqk` 仅 `production-ready=false` 的开发绕过。
- 未做：整站 OIDC。

## 阶段 5 — 商品与金额

- 商品搜索：`MATCH ... AGAINST` + ngram FULLTEXT，不再用 `product_name LIKE` 冒充搜索。
- 隔离目录：`catalog_scope=store|eval`。9100/9300 只在 SQL 回填，运行时不猜前缀。要看 eval 目录须显式 `scope:eval`。
- 0 元：`normalizeChannelPayAmount` 保持 0，不抬 0.01；下单跳过渠道表单（`FREE`）；支付宝拒发 0 元单。
- 未做：Two-Tower、拍卖、MTA。

## 阶段 6 — 前端合同 / 观测 / 账本

- 前端引用只认 `chunk_id`，禁止按标题正则贴标。
- SSE 解析 `id:` / `event:`；`message_complete` 覆盖流式正文。
- Langfuse：无 PUBLIC/SECRET key 时 no-op，不假装已观测。OTEL 仍仅在配置了 exporter 时启用。
- **标准件补线（可大胆替换的三处）**：
  - `gen_ai_span` 已接到 `provider._request` / `tools.invoke` / `knowledge.search` / 购物与商家 `invoke_agent`。无 exporter 或未安装 SDK `TracerProvider` 时仍 no-op。属性跟官方 GenAI（`gen_ai.operation.name` / model / tool.name），不再写 `gen_ai.system=smartlect`，不采集正文和工具入参。
  - Java `TraceIdFilter` 优先从 W3C `traceparent` 回填 MDC；没有该头时的 UUID 只做日志关联，不伪造 `traceparent`。`FeignTraceInterceptor` 只转发已有 MDC，不再发明 UUID。
  - 访客 JWT 改 **PyJWT** 签发/验签；手写 compact HS256 仍能验。旧 2 段 HMAC cookie 仍走 `auth._verify`。未上 OIDC。
- 账本按 `pay_order_id` 锁（`commerce_ledger_lock_key`）；未知事件进 exception/DLQ，不入账。`SMARTLECT_GROWTH_MYSQL_SSL!=1` 才关 TLS。
- 评价分析阈值进环境变量，version 随阈值 hash；`problems` 允许空列表。
- 未做：完整 Langfuse 生产看板、编造 QPS。

## 明确没做（遵守不要做清单）

- 完整 MCP Streamable HTTP（仍是单次 JSON-RPC POST）
- Two-Tower / MTA / 广告拍卖
- Temporal
- Java 整站 OIDC
- 编造 QPS / 召回率 / GMV

## 本轮（阶段 2+）测试

- Growth：`unittest discover -s tests`，461 项，318 通过，143 skip（未开 `SMARTLECT_RUN_MYSQL_TESTS`）。标准件补线后重跑全绿。
- Java：`W3cTraceContextTest`（traceparent 回填 / 无头时只做日志关联）、`OrderPayAmountUtilTest`、`GatewayTokenResolverTest`、`IsolatedCatalogTest`、`OrderInfoInitialPaymentTest`。
- 前端：`web/user` `citations.test.ts` 通过。
- 未跑 MySQL 集成、未起 Postgres 做 checkpointer 冒烟、未走浏览器点选整站。
- 未 commit。

不要编造 QPS / 召回率 / GMV。
