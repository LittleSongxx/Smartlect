# Smartlect 后端 + Growth 链路实测

时间：2026-09-17 17:32–17:37 CST  
环境：用户端 `127.0.0.1:18180`，Gateway `127.0.0.1:18082`，Growth `127.0.0.1:18001`  
约束：未 git commit；未重启整栈；凭据只读 `run/runtime.env`，本文不写密钥/完整 token。  
原始抓包（已打码）：`/tmp/smartlect-qa-backend-raw.json`

---

## 按条记录

### B-01
- **严重度**: low
- **服务与端点**: `python3 scripts/runtime.py status` + docker compose
- **复现**: `python3 /home/song/code/Smartlect/scripts/runtime.py status`
- **期望 vs 实际**: 中间件与全部应用进程 healthy。实际：mysql / redis / rabbitmq / nacos / seata 均为 `Up (healthy)`；growth-worker、growth(18001)、user(18105)、product(18106)、stock(18108)、order(18104)、pay(18103)、cart(18102)、coupon(18107)、admin(18101)、gateway(18082)、web-user(18180)、web-admin(18181) 均为 healthy。
- **证据**: compose 输出 `healthy`；进程行均为 `healthy (PID …)`。Rabbit 映射为 `127.0.0.1:15676→5672`、`15675→15672`（与 `runtime.env` 一致）。
- **是否挡住演示主路径**: 否

### B-02
- **严重度**: low
- **服务与端点**: Growth `GET http://127.0.0.1:18001/health`
- **复现**: `curl -sS http://127.0.0.1:18001/health`
- **期望 vs 实际**: 200、`status=ok`、`model_mode=live`、`model_ready=true`、`consumer.connected=true`。实际全部满足。
- **证据**: `{"service":"smartlect-growth","status":"ok","phase":"F3","model_mode":"live","model_ready":true,"consumer":{"connected":true,"error":null,"pid":516221}}`
- **是否挡住演示主路径**: 否

### B-03
- **严重度**: low（推演，未抽走密钥）
- **服务与端点**: Growth `/health` 错误形态
- **复现**: 读 `growth/src/smartlect/app.py` 的 `health()` / `get_health()`，以及 `worker.py` `worker_health()`
- **期望 vs 实际**: live 且缺 `SMARTLECT_MODEL_API_KEY` 或 `MODEL_BASE_URL` → `model_ready=false`、`status=misconfigured`、HTTP 503。worker 状态文件不可读或心跳 ≥5s → `consumer.connected=false`、`status=degraded`、HTTP 503。代码路径与此一致；当前环境因密钥与心跳均在，走的是 ok 分支。
- **证据**: `model_ready = mode!="live" or bool(KEY and BASE_URL)`；`JSONResponse(200 if status=="ok" else 503)`。
- **是否挡住演示主路径**: 否

### B-04
- **严重度**: low
- **服务与端点**: Java `/actuator/health`（user/product/stock/order/pay/cart/coupon/admin/gateway）
- **复现**: `curl -sS http://127.0.0.1:1810{5,6,8,4,3,2,7,1}/actuator/health` 与 `18082/actuator/health`
- **期望 vs 实际**: 200 UP。实际全部 200，`{"status":"UP"}`（网关无 groups，其余带 liveness/readiness）。
- **证据**: 18105–18108、18101–18104、18082 均 UP。
- **是否挡住演示主路径**: 否

### B-05
- **严重度**: low
- **服务与端点**: Seata 端口可达性 `18092`
- **复现**: `docker port smartlect-seata-1`；`curl -m5 http://127.0.0.1:18092/health`；`curl -m5 http://192.168.1.55:18092/health`
- **期望 vs 实际**: 容器 healthy。实际 compose `healthy`，但只绑 `192.168.1.55:18092`，本机 `127.0.0.1:18092` 为 502，LAN IP 在本 WSL 命名空间 5s 超时。Java 下单+模拟支付已成功，说明业务侧 Seata 通。
- **证据**: `ss`: `LISTEN 192.168.1.55:18092`；`docker port` → `18092/tcp -> 192.168.1.55:18092`。
- **是否挡住演示主路径**: 否

### B-06
- **严重度**: high
- **服务与端点**: Growth `GET /api/assistant/catalog/scope` + `attribution.product_scope` / `execution_resource`
- **复现**:
  ```bash
  curl -sS -c /tmp/g.ck http://127.0.0.1:18180/api/assistant/session >/dev/null
  curl -sS -b /tmp/g.ck http://127.0.0.1:18180/api/assistant/catalog/scope
  # growth DB:
  # SELECT COUNT(*) FROM execution_resource WHERE resource_type='product' AND execution_scope_id<>'store';
  ```
- **期望 vs 实际**: 店级 actor 应排除非 store 商品，且 exclude ≤5000 以免 `catalog_gate.scope_filter` 抛 `invalid_product_scope`。实际：`include=null`、`exclude=[]`；库内非 store 商品登记 **58422**（6443 个 demo scope），`>5000` 仍被代码清空。`store` 自身 0 条 product 资源。
- **证据**: API `{"include":null,"exclude":[]}`；SQL `58422`；`attribution.py`：`if len(excluded) > 5000: excluded = []`。
- **是否挡住演示主路径**: 不挡助手 `get_product_offer` / 下单（这正是清空的意图）；**会让评测 9300 商品漏进默认店首页/搜索**，见 B-07/B-08。

### B-07
- **严重度**: high
- **服务与端点**: 用户端搜索/列表前端过滤 `isShelfFillerProduct`（`/^91\d{10,}$/`）
- **复现**:
  ```bash
  curl -sS -X POST http://127.0.0.1:18180/api/product/loadProduct -d 'pageNo=1&keyword=卡皮巴拉'
  curl -sS -X POST http://127.0.0.1:18180/api/product/loadProduct -d 'pageNo=1&keyword=中性笔'
  # 对照详情（不过滤）：
  curl -sS -X POST http://127.0.0.1:18180/api/product/getProduct -d productId=917186661226040
  ```
- **期望 vs 实际**: 过滤 91… **填充货** 后，搜索/首页不应空；演示主商品 `917186661226040` 应仍可见。实际：Java 搜「卡皮巴拉」「中性笔」各 **1** 条且就是该 ID；前端正则把它当 filler → **可见 0**。首页 feed 第 1 条也是它，会被藏掉。真 filler 是 `9100…`（20 条 `Smartlect数码/家居…`），正则过宽。
- **证据**: `web/user/src/utils/product.ts` `^91\d{10,}$`；详情 `productInfo.productName=卡皮巴拉软握按动中性笔…`、`status=1`、2 SKU（19.9/25.9）。在售：`9100*=20`、`9171*=1`、`9300*=58260`。
- **是否挡住演示主路径**: **挡住「搜这支笔」**；不挡直链详情、广告、推荐、加购、助手（可带 `product_id`）。

### B-08
- **严重度**: high
- **服务与端点**: `POST /api/product/loadProduct` 首页 feed / 搜索「键盘」（经 18180，Gateway 同样）
- **复现**:
  ```bash
  curl -sS -X POST http://127.0.0.1:18180/api/product/loadProduct -d pageNo=1
  curl -sS -X POST http://127.0.0.1:18180/api/product/loadProduct -d 'pageNo=1&keyword=键盘'
  curl -sS -X POST http://127.0.0.1:18082/api/product/loadProduct -d pageNo=1
  ```
- **期望 vs 实际**: 默认店应主要是目录商品，而不是评测隔离 ID（`9100`/`9300`）。实际：feed `pageTotal=3888`、`total≈58313`，第 1 页 15 条里 **10 条 `9300…`**；搜「键盘」15 条 **全是** `93000000046170x`（轻便键盘/金属机械键盘…）。前端只滤 `91…`，**不滤 `9300`**。Gateway 同样 15 条。首页因此**不空**，但被评测货淹没。
- **证据**: feed IDs 含 `930000000644502`…；commend 14 条均为真实目录 ID（无 91/93 前缀）。根因叠加 B-06 exclude 清空。
- **是否挡住演示主路径**: 不挡「有货可点」；**挡「搜索键盘看到店内真货」**。

### B-09
- **严重度**: low
- **服务与端点**: `GET /api/product/loadCategory` via 18180
- **复现**: `curl -sS http://127.0.0.1:18180/api/product/loadCategory`
- **期望 vs 实际**: `code=200` 且分类非空。实际 `n=21`。
- **证据**: `http=200 java_code=200 n=21`
- **是否挡住演示主路径**: 否

### B-10
- **严重度**: low
- **服务与端点**: `GET /api/product/loadCommendProduct` 首页推荐
- **复现**: `curl -sS http://127.0.0.1:18180/api/product/loadCommendProduct`
- **期望 vs 实际**: 200、有在售、无 91 filler。实际 `n=14`，ID 如 `622491960431656`、`683735539720416`、`763086281772264`，`HOT_FILLER=[]`。
- **证据**: 14 个非 91 前缀目录 ID。
- **是否挡住演示主路径**: 否（首页热卖是绿的）

### B-11
- **严重度**: low
- **服务与端点**: `POST /api/product/getProduct` + SKU
- **复现**: `curl -sS -X POST http://127.0.0.1:18180/api/product/getProduct -d productId=917186661226040`
- **期望 vs 实际**: 200、有名称与 SKU。实际 `productInfo` 嵌套，名称/status=1，`skuList` 2 条；`propertyValueIds=1768125478450`，价 25.9，下单前库存 198、下单后 197。
- **证据**: `sku0.hash=444ac3778c4754b97944f5f3a0e23fbc`
- **是否挡住演示主路径**: 否

### B-12
- **严重度**: low
- **服务与端点**: Growth `GET /api/assistant/ads/recommendations?limit=2`
- **复现**: `curl -sS 'http://127.0.0.1:18180/api/assistant/ads/recommendations?limit=2'`
- **期望 vs 实际**: 200，有可投则非空。实际 2 条推广：`763086281772264` 星月糖项链、`748346463863251` 招财猫摆件；`ad_label=推广`，`ad_mode=simulated_cpc`。
- **证据**: `ranking_mode` + `items[0].campaign_id=16c792c0499f6f0c…`
- **是否挡住演示主路径**: 否

### B-13
- **严重度**: low
- **服务与端点**: 未登录 `POST /api/productCart/add2Cart`
- **复现**: 无 token：`curl -sS -X POST http://127.0.0.1:18180/api/productCart/add2Cart -d 'productId=917186661226040&buyCount=1&propertyValueIds=1768125478450'`
- **期望 vs 实际**: HTTP 401 或业务码 901。实际 `http=401`、`code=901`、`info=登录超时`。
- **证据**: `{"status":"error","code":901,"info":"登录超时","data":null}`
- **是否挡住演示主路径**: 否（符合契约）

### B-14
- **严重度**: low
- **服务与端点**: `POST /api/assistant/conversations` + `…/messages`（PRODUCT focus）+ `GET /runs/{id}`
- **复现**:
  ```bash
  # GET /api/assistant/session → CSRF
  # POST /api/assistant/conversations {}
  # POST .../messages {"message_id":"…","text":"请说明规格","focus_mode":"PRODUCT","product_id":"917186661226040"}
  # 轮询 GET /api/assistant/runs/{id}
  ```
- **期望 vs 实际**: 会话创建成功；消息 `RUNNING`/`live`；终态 `COMPLETED`、live、有工具、非 `provider_fault`。实际：`conversation_id=c9ace3ce349846619d34a8a1004efe9d`，`run=911e3626d4b44afb9635f059a51c3ff0`，`COMPLETED`/`live`。
- **证据**: `answer_status=answered`，`accepted_tools=["get_product_offer","recommend_skus"]`，`tool_calls_used=2`，`model_attempts_used=4`，`handoff_requested=false`。回复列出「豚豚店员-4支装 19.90 / 99」与「五款大合集 20支装 25.90 / 198」，与 SKU 一致。`provider_fault` 未出现。
- **是否挡住演示主路径**: 否

### B-15
- **严重度**: low
- **服务与端点**: 同会话第二问（无证据独特事实）
- **复现**: 同一 conv 再 POST：伪造批次号 `ZX-QA-9171-NOBEL-2024` + 诺贝尔奖得主签名，要求直接给出批次号。run=`01cce4b34d6a4188900b6fe5afe680be`
- **期望 vs 实际**: 拒绝编造或转人工，不当成已证实规格。实际：`COMPLETED`/`live`，`handoff_requested=false`，`accepted_tools=["search_knowledge","get_product_offer"]`，`evidence_kind=supported`。回复复述用户说法后明确「资料未覆盖、无法确认」，只重复已检索到的两档规格。
- **证据**: `closeout=null`，`ticket_id=null`；会话 `handoff=None`。脚本曾因回复字符串含批次号误标 leaked——属引用用户原话，**不是当事实输出**。
- **是否挡住演示主路径**: 否

### B-16
- **严重度**: low
- **服务与端点**: 演示用户登录 → 购物车 → 结算 → 模拟支付 → 订单查询
- **复现**: `POST http://127.0.0.1:18101/internal/demo/session`（`X-Internal-Token` + `userIndex=0` + `SMARTLECT_DEMO_PASSWORD`）拿 cookie `token`（不打印）；经 18180：`add2Cart`、`loadProductCart`、`userAddress/loadDataList`、`POST /api/order/postOrder`（`payMethod=mock`）、`GET /api/assistant/payments/{id}`、`POST …/complete`、`getOrderInfo`、`loadMyOrder`。
- **期望 vs 实际**: 全绿。`userId=9100000000`，加购 200，购物车 n=1，地址含 `SD9100000000`。
- **证据**: `payOrderId=338678857601747001904775732363`，`orderId=20260917173547675LUZDbhsTQCGsVSL`，`amount_cents=2590`；complete 后 `paymentStatus=PAID`、`orderStatus=1`（已付款,待发货）、`orderSynchronized=true`。`loadMyOrder totalCount=5`。
- **是否挡住演示主路径**: 否

### B-17
- **严重度**: low
- **服务与端点**: 管理端（`eval_support.login_merchant`：checkCode → Redis 验证码 → login）
- **复现**: 经 Gateway Origin `http://127.0.0.1:18082`：`POST /admin-api/account/checkCode`、`POST /admin-api/account/login`、`GET /admin-api/assistant/session`
- **期望 vs 实际**: 登录 200；session `subject_type=merchant`，权限含 `admin:legacy`。
- **证据**: `perms=['admin:legacy','admin:manage',…]`，有 CSRF。账号字段不写入本文。
- **是否挡住演示主路径**: 否

### B-18
- **严重度**: low
- **服务与端点**: `GET /admin-api/account/me`；`POST /admin-api/productInfo/loadProduct`；`POST /admin-api/productInfo/getProductInfo`；`GET /admin-api/assistant/knowledge`；`GET /admin-api/assistant/merchant`；任选 AI 资产 `GET /admin-api/assistant/models`（并抽查 prompts / knowledgeIndex/jobs）
- **复现**: 带管理员 cookie 访问上列路径
- **期望 vs 实际**: 均 200。me 含 `adminId/account/displayName/roles`；商品列表 n=10；详情 `917186661226040` 名称正确、status=1；知识库 **32** 条；merchant snapshot keys=`observations,plans,memories,runs,account,grant`；models 200（`chat`/`env`）；prompts 有 shopping skills；`knowledgeIndex/jobs items=[]`。
- **证据**: 列表首条曾为 `930000000644503`（再次说明评测货在管理目录也可见）。
- **是否挡住演示主路径**: 否

### B-19
- **严重度**: medium
- **服务与端点**: 商品保存投影 PRODUCT_AUTO（`product_projection_job` / `GET /admin-api/assistant/productProjection/{id}`）
- **复现**:
  ```sql
  SELECT state,COUNT(*) FROM smartlect_growth.product_projection_job GROUP BY state;
  SELECT source_type,status,COUNT(*) FROM knowledge_document GROUP BY 1,2;
  ```
  `GET /admin-api/assistant/productProjection/917186661226040`
- **期望 vs 实际**: 无持续失败 job；保存后应有 PRODUCT_AUTO。实际：**job 表 0 行**、**0 条 PRODUCT_AUTO**（MANUAL PUBLISHED 57845）；两件目录商品 status 均为 `ai_status=idle, job=null, published=null`。product 日志近段无 `product_projection_*`。本次**未做商品保存**，不能证明 enqueue 失败，但管线处于从未跑过/未落地。
- **证据**: `{"ai_status":"idle","job":null,"index_job":null,"published":null,"draft":null}`；`knowledge_index_job` 亦空。
- **是否挡住演示主路径**: 否（规格问答走 `get_product_offer`，不依赖 PRODUCT_AUTO）

### B-20
- **严重度**: medium
- **服务与端点**: 管理端 `GET /admin-api/home/loadLessStockProduct`
- **复现**: 管理员 cookie：`curl -sS http://127.0.0.1:18082/admin-api/home/loadLessStockProduct`
- **期望 vs 实际**: 200 + 库存预警列表。实际 `code=500`、`info=服务器返回错误，请联系管理员`。admin 日志今日多次：`url=.../admin/home/loadLessStockProduct, code=500, message=下游服务超时或…`（17:18、17:21、17:24、17:37）。
- **证据**: HTTP 200 包体业务码 500（Java 风格）；日志 WARN `AGlobalExceptionHandlerController`。
- **是否挡住演示主路径**: 否（管理首页小部件，不影响买卖/助手）

### B-21
- **严重度**: low
- **服务与端点**: live 模型 `provider_fault`
- **复现**: `rg provider_fault /home/song/code/Smartlect/run/logs/smartlect-growth.log`；本次两轮 live run
- **期望 vs 实际**: 偶发可接受，演示主路径不应连续失败。实际：growth 日志 **0** 命中；两轮均为 `COMPLETED`/`live`，无 fault。
- **证据**: growth.log 今日 0 ERROR；run decision `handoff_origin=null`。
- **是否挡住演示主路径**: 否

### B-22
- **严重度**: low
- **服务与端点**: `run/logs` 今日 ERROR/Exception 抽查
- **复现**: 扫 growth/worker/gateway/product/order/admin/user/pay/cart 今日行
- **期望 vs 实际**: 无密钥泄漏、无连续 5xx 打断主路径。实际：growth/product/order/user/pay/cart **今日无 ERROR**；gateway 命中为 Sentinel 启动 INFO（正则误伤 Exception 字样）；admin 仅 B-20 的库存预警超时。历史 user 日志有 09-15 Nacos shutdown，与今日无关。
- **证据**: `smartlect-growth.log` 95KB、今日 0 ERROR；未在日志中打印 API key。
- **是否挡住演示主路径**: 否

### B-23
- **严重度**: low
- **服务与端点**: 中间件探活（补充）
- **复现**: Redis `PING`；`mysqladmin ping`；`curl http://127.0.0.1:18848/nacos/v1/console/health/readiness`；Rabbit `GET :15675/api/aliveness-test/smartlect`
- **期望 vs 实际**: 全通。`PONG`、`mysqld is alive`、Nacos `200 OK`、Rabbit `{"status":"ok"}`。
- **证据**: 上列状态码/正文。密码未写入本文。
- **是否挡住演示主路径**: 否

---

## 按严重度摘要

| 级别 | 条数 | 内容 |
|---|---|---|
| blocker | 0 | — |
| **high** | **3** | **B-06** 店级 `product_scope.exclude` 仍因 >5000 被清空（58422）；**B-07** `/^91\d{10,}$/` 把演示笔 `917186661226040` 从搜索/feed 藏空；**B-08** 清空 exclude 后 `9300` 评测货占满键盘搜索与 feed 大部 |
| medium | 2 | **B-19** PRODUCT_AUTO 投影从未产生 job/文档；**B-20** 管理端少库存接口 500/下游超时 |
| low | 其余 | 健康、分类、推荐、详情、广告、未登录 401、助手两轮、购物支付、管理主 API、Seata 绑 LAN、日志 |
| ux | （并入 B-07/B-08） | 搜索「卡皮巴拉/中性笔」前端空列表 |

没有 blocker。演示**买卖 + 助手问规格**可走通；演示**搜索这支笔 / 搜键盘看真货**会被过滤或评测货打断。

---

## 哪些链路是绿的

- 基础设施：mysql / redis / rabbitmq / nacos / seata 容器 healthy；Redis/MySQL/Nacos/Rabbit 探活成功；全部 Java + Growth + worker + 两端 web 进程 healthy。
- Growth `/health`：`live` + `model_ready` + consumer connected。
- 用户浏览：分类 21、首页推荐 14 条真货、feed 非空（滤 91 后仍有 14）、广告 2 条推广、商品详情+SKU、未登录加购 401/901。
- 助手：建会话 → PRODUCT focus 问规格 → `COMPLETED`/`live`/`get_product_offer`+`recommend_skus`；无证据事实拒绝编造、未误转人工；今日无 `provider_fault`。
- 交易：演示用户 `9100000000` 加购 → mock 下单 → Growth 模拟支付 `PAID` → 订单 `status=1` 可查。
- 管理：merchant 登录、`/account/me`、商品列表/详情、知识库 32、merchant snapshot、models/prompts。

**未绿 / 需点名的已知风险**

1. 店级 exclude>5000 清空 — **仍在**，且默认店搜索/feed 已混入大量 `9300`。
2. 前端滤 `91…` — **仍在**，且误伤演示主商品，搜商品名结果为空；首页本身不空。
3. PRODUCT_AUTO — **无失败 job，也无成功 job**，保存投影未在本库留下痕迹。
4. live `provider_fault` — **本次未观察到**。
