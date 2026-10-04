#!/usr/bin/env python3
# 生成 Smartlect 架构图集导航站：index.html + pages/*.html
# 所有图表由 archify 渲染并已通过 validate/deliver/check/browser-check 四门禁。
import os, html, json

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/LittleSongxx/Smartlect"
SHA = "2c8e46eef0b279ed3c6eee2d297b79dd2cf553db"

DIAGRAMS = [
 dict(no="01", slug="system-overview", type="architecture", title="系统总览",
  desc="四层全景：浏览器 → Nginx → 网关 → Java 交易权威 + AI 助手 → 基础设施",
  group="总览", status="pass",
  owns="整个系统的一句话地图：谁面向用户、谁做决策、谁落交易、数据落在哪。读者应先看这张图获得方位感，再进入各部分详图。",
  sections=[
   ("分层职责", [
    "入口层：Nginx 终结 TLS（Let's Encrypt），按路径分流——/ 到用户端静态站、/admin/ 到管理端、/api/ 反代网关。",
    "应用层：Spring Cloud Gateway 统一入口（Sa-Token 会话校验 + Sentinel 限流），lb:// 路由到 8 个 Java 服务；/api/assistant 反代 Python 助手。",
    "决策层：AI 助手（FastAPI + LangGraph）负责「问什么、检索什么、提议什么」，只能生成待确认提案。",
    "交易层：Java 是价格/库存/订单的唯一可写方；MySQL 按服务分库，Redis 承担会话/缓存/秒杀 Lua，RabbitMQ 驱动超时与发货。"]),
   ("关键边界", [
    "模型不可成交：下单/退款/支付都经人工确认后由 Java 执行。",
    "服务间内部接口走 X-Internal-Token；LLM 仅白名单端点（百炼/智谱）。",
    "价格与库存不进向量库，每次实时重问交易服务。"]),
  ],
  evidence=["deploy/nginx.smartlect.conf", "backend/smartlect-gateway/src/main/resources/application.yml", "README.md"],
  related=["02", "07", "11"]),

 dict(no="02", slug="backend-services", type="architecture", title="后端微服务地图",
  desc="9 个 Spring 服务的 Feign 同步调用拓扑 · 每服务独立分库",
  group="后端", status="pass",
  owns="Java 后端的完整服务地图：每个服务的端口与分库、谁同步调用谁（Feign）、AI 助手消费哪些 /internal 接口。",
  sections=[
   ("服务清单", [
    "gateway :18080（路由/鉴权/限流）· admin :18081（管理端 BFF）· user :18082 · product :18083 · stock :18084 · cart :18085 · order :18086 · pay :18087 · coupon :18088。",
    "每个服务独立 MySQL 分库：smartlect_user / product / stock / cart / order / pay / coupon / admin。"]),
   ("调用关系", [
    "order 是交易编排中心：下单时 Feign 顺序调 product（核价/快照）→ stock（锁库存）→ coupon（锁券）→ cart（清购车）→ user（地址）→ pay（支付单）。",
    "coupon 在秒杀场景反向 Feign 调 order 的 postCouponRushOrder 落秒杀单。",
    "admin 看板另经 Feign 聚合 product/order/user（图面省略，避免拥挤）。",
    "cart 加购时经 Feign 校验 product/stock（图面省略）。"]),
   ("内部信任", [
    "/internal/** 由 smartlect-common 的 InternalApiAuthFilter 校验 X-Internal-Token。",
    "AI 助手所有 Java 调用带 X-Smartlect-User-Id 与 Idempotency-Key（图 7 详述）。"]),
  ],
  evidence=["backend/smartlect-order/app/src/main/java/com/smartlect/biz/impl/OrderInfoServiceImpl.java", "backend/smartlect-common/src/main/java/com/smartlect/web/InternalApiAuthFilter.java", "assistant/src/smartlect/commerce.py"],
  related=["04", "03", "07"]),

 dict(no="03", slug="auth-boundaries", type="architecture", title="认证与信任边界",
  desc="Sa-Token 双账号体系 · 网关会话校验 · 三道防线",
  group="后端", status="pass",
  owns="「谁是谁」如何在整个系统里传递：用户端 token 与管理端 adminToken 两套 Sa-Token 账号、网关的 Redis 会话校验、内部调用的 X-Internal-Token、AI 助手的身份内省桥。",
  sections=[
   ("双账号体系", [
    "用户端：StpUtil（token-name=token），登录写 Redis token:login:token:{t}。",
    "管理端：StpAdminLogic（loginType=admin, token-name=adminToken），独立前缀 adminToken:login:token:{t}；角色权限由 SmartlectStpInterface 从 session dataMap 加载。",
    "服务端共 39 处 @SaCheckLogin/@SaCheckRole 注解做方法级校验。"]),
   ("网关防线", [
    "AuthGlobalFilter 按路径前缀查对应 Redis 键，通过后注入 X-User-Id / X-User-Token-Verified / X-Admin-Token-Verified。",
    "任何客户端伪造的身份头在网关被剥离，内部头只在信任区内流通。"]),
   ("内部与助手", [
    "InternalTokenGlobalFilter 校验 /internal/** 的 X-Internal-Token。",
    "AI 助手 IdentityBridge 把 cookie POST 到 user 服务 /internal/identity/introspect 内省，访客走签名只读证明——没有第二套登录库。",
    "写操作前端先取 CSRF nonce，后端校验 X-CSRF-Token。"]),
  ],
  evidence=["backend/smartlect-gateway/src/main/java/com/smartlect/cloud/gateway/filter/AuthGlobalFilter.java", "backend/smartlect-common/src/main/java/com/smartlect/security/StpAdminLogic.java", "assistant/src/smartlect/auth.py"],
  related=["12", "07", "02"]),

 dict(no="04", slug="order-pay-flow", type="sequence", title="下单到履约全链路",
  desc="同步 Feign 编排 + 延时/死信驱动超时取消、模拟发货、自动确认",
  group="交易流程", status="pass",
  owns="一笔普通订单的完整生命周期：下单时的同步编排、mock 支付的异步落单、时间驱动的履约与超时回滚。",
  sections=[
   ("四个阶段", [
    "① 下单：postOrder 后 order 顺序 Feign 核价/锁库存/锁券，落待支付订单并发 15 分钟 TTL 延时消息。",
    "② 支付：getPayInfo 经 order 到 pay 建支付单；用户在演示页触发 mock complete；pay 在事务提交后经 outbox 发 pay.success，order 消费后 paySuccess 落单。",
    "③ 履约：pay.logistics.delay 模拟发货；7 天 pay.confirm.delay 自动确认收货。",
    "④ 超时分支：15 分钟未付 → pay.timeout 死信 → 取消订单并释放库存与券。"]),
   ("可靠性设计", [
    "pay.success 用本地消息 outbox 取代 pay→order 的同步 Feign 回调，避免双写不一致。",
    "消费端幂等台账防重复消费；失败沿 5s/30s/120s 三级重试拓扑退避。",
    "对账任务 PayOrderTask 兜底扫描支付单状态。"]),
  ],
  evidence=["backend/smartlect-order/app/src/main/java/com/smartlect/controller/OrderController.java", "backend/smartlect-pay/app/src/main/java/com/smartlect/biz/impl/PayChannel4Mock.java", "backend/smartlect-common/src/main/java/com/smartlect/constants/RabbitMQConfig.java"],
  related=["05", "06", "02"]),

 dict(no="05", slug="refund-saga", type="sequence", title="退款 Saga",
  desc="人工审核后消息驱动：order → stock 回补 → 回执闭环",
  group="交易流程", status="pass",
  owns="退款这个跨服务流程如何保持一致：审核通过后由 REFUND_STOCK / REFUND_RESULT 两条消息串起订单与库存，幂等与重试兜底。",
  sections=[
   ("流程", [
    "用户在售后页申请退款 → 管理端 RefundReview 人工审核（金额须等于剩余可退）。",
    "审核通过后 order 在事务内发 REFUND_STOCK_KEY；stock 消费前查幂等台账，回补库存后发 REFUND_RESULT_KEY。",
    "order 消费回执标记退款完成；演示环境退款到账为模拟记账。"]),
   ("兜底", [
    "消费失败沿 5s/30s/120s 重试拓扑退避，耗尽进死信。",
    "mqCompensationLog + MqConsumeReplayRouter 支持补偿与按队列重放。"]),
  ],
  evidence=["backend/smartlect-order/app/src/main/java/com/smartlect/biz/RefundSagaTransactionService.java", "backend/smartlect-stock/app/src/main/java/com/smartlect/component/RefundStockListener.java", "backend/smartlect-order/app/src/main/java/com/smartlect/component/RefundResultListener.java"],
  related=["04", "02"]),

 dict(no="06", slug="coupon-rush", type="workflow", title="秒杀抢券流程",
  desc="Redis Lua 原子预占 → Feign 秒杀单 → 延时死信兜底释放",
  group="交易流程", status="pass",
  owns="高并发抢券为什么不会超卖：库存余量与用户限购在 Lua 脚本内原子判定，占位与落单解耦，超时由死信自动释放。",
  sections=[
   ("两条出路", [
    "预占成功 → coupon 反向 Feign 调 order postCouponRushOrder 落秒杀单 → 支付成功后 pay.success 核销。",
    "15 分钟未付 → pay.timeout 死信 → rollback_v1 释放 Redis 占位并取消订单；两个监听器解耦券释放与订单取消。"]),
   ("运营工具", [
    "warmupRushStock 活动前把库存同步进 Redis；reconcileRushStock 事后对账修正漂移；sweep_dangling 清理悬挂占位。",
    "抢购 QPS 另有 Redis 计数限流兜底。"]),
  ],
  evidence=["backend/smartlect-coupon/app/src/main/java/com/smartlect/component/CouponRushStockService.java", "backend/smartlect-common/src/main/resources/lua/coupon_rush_reserve_v1.lua", "backend/smartlect-order/app/src/main/java/com/smartlect/biz/impl/CouponRushOrderServiceImpl.java"],
  related=["04", "02"]),

 dict(no="07", slug="assistant-internals", type="architecture", title="AI 助手内部架构",
  desc="FastAPI 组合根 · LangGraph 有界会话 · 工具五层设防 · 混合检索",
  group="AI 助手", status="pass",
  owns="Python 助手（smartlect 包）的内部组成：请求如何被准入与鉴权、会话如何有界运行、工具如何设防、检索与模型如何被调用。",
  sections=[
   ("请求路径", [
    "网关 /api/assistant 反代到 uvicorn :18000；每个请求先过 IdentityBridge 内省，run 创建前过准入闸（每 actor 并发 ≤3、全局 ≤24）。",
    "会话运行时是 LangGraph 三节点图（model/tools/answer），MySQL 租约互斥 + 心跳续期，checkpointer 存图状态。"]),
   ("硬预算", [
    "模型调用 ≤6、工具 ≤10、知识检索 ≤2、单轮 90 秒；上下文裁剪 14400 token，观察投影 ≤6500 字节。",
    "非 live 模式不进图，控制器直接确定性收口。"]),
   ("工具面", [
    "15 个工具走同一 REGISTRY：allowed → RBAC → Pydantic strict → 幂等台账 → gen_ai_span 五层设防。",
    "写类工具只有 propose_*（生成提案），没有任何 approve/execute 权限。",
    "子智能体（task_dispatch）复用同一条 invoke 路径，单批 ≤3 任务并发。"]),
  ],
  evidence=["assistant/src/smartlect/app.py", "assistant/src/smartlect/tools.py", "assistant/src/smartlect/graph_runtime.py"],
  related=["08", "09", "10", "03"]),

 dict(no="08", slug="shopping-agent-turn", type="workflow", title="导购一轮对话",
  desc="准入 → 租约 → 有界 ReAct → 带引用答复或待确认提案",
  group="AI 助手", status="pass",
  owns="用户发一条消息之后助手内部发生什么：从准入到三节点 ReAct 循环，到三种终止出路。",
  sections=[
   ("主循环", [
    "model 节点流式生成；有 tool_calls 进 tools 节点执行并回填观察；finish/无调用进 answer 节点。",
    "answer 有 FinalAnswer 契约与守卫链，校验失败允许回 model 修复一轮（标注于节点上）。"]),
   ("三种终止", [
    "带引用答复（COMPLETED）；待确认提案（propose_order → WAIT_USER + SSE 事件）；转人工（request_handoff 建工单）。",
    "SSE 断线按 Last-Event-ID 重放，前端续传。"]),
  ],
  evidence=["assistant/src/smartlect/agents/shopping/session.py", "assistant/src/smartlect/agents/shopping/graph.py", "assistant/src/smartlect/app.py"],
  related=["09", "07", "12"]),

 dict(no="09", slug="proposal-hitl", type="sequence", title="提案确认（人在环上）",
  desc="模型只提议 · 人核对并确认 · Java 复核落单",
  group="AI 助手", status="pass",
  owns="「模型可以建议、不能成交」这条红线如何落地：提案的生成、人工核对、确认执行与边界分支。",
  sections=[
   ("不可绕过的确认", [
    "propose_order 先向 order 取 v2/quote 报价，提案绑定 quoteId 与确认金额。",
    "前端确认卡必须先完成 display 核对（提案快照 + 地址 + 商品快照）才放开确认按钮。",
    "确认走乐观版本：PROPOSED → CONFIRMED/REJECTED；过期提案 410，唯一出路是重新咨询。"]),
   ("执行", [
    "CONFIRMED → EXECUTING：下单走 v2/createConfirmed（Java 复核金额），取消/退款走 v2/executeAction。",
    "回执 commandStatus 映射 SUCCEEDED/FAILED/UNKNOWN；UNKNOWN 进入 actionStatus 恢复查询。",
    "支付提案 mock 即时完成；live 模式只取支付链接，服务端不代付。"]),
  ],
  evidence=["assistant/src/smartlect/app.py", "assistant/src/smartlect/state.py", "web/user/src/components/agent/AgentConfirmCard.vue"],
  related=["08", "04", "07"]),

 dict(no="10", slug="knowledge-rag", type="dataflow", title="知识库发布与混合检索",
  desc="先发布才可检索 · ES BM25 ∥ Qdrant ANN → RRF → 重排 · 带引用",
  group="AI 助手", status="pass",
  owns="店规知识从草稿到被引用的数据流：发布管线（写）与检索管线（读）两条平行流水线。",
  sections=[
   ("写管线", [
    "管理端上传 → pypdf 有界解析分块 → 发布（旧版置 WITHDRAWN 并 bump 目录 revision）。",
    "有 embedding key 时异步索引作业双写 ES（smartcn 倒排）与 Qdrant（1024 维向量），可续跑重试；无 key 同步发布，检索退化 BM25-only。"]),
   ("读管线", [
    "候选过滤只取 status=PUBLISHED 且在有效期与 ACL 内——未发布的内容不可能被检索到。",
    "ES BM25 与 Qdrant ANN 并行召回 → RRF 融合 → gte-rerank-v2 重排 → 带块级引用核验的答复。",
    "缓存键含目录 revision，发布后旧缓存自然失效；后端故障按滑动窗口降权。"]),
  ],
  evidence=["assistant/src/smartlect/knowledge.py", "assistant/src/smartlect/hybrid_search.py", "assistant/src/smartlect/indexing.py"],
  related=["07", "08"]),

 dict(no="11", slug="deployment", type="architecture", title="部署拓扑",
  desc="宿主机 systemd 进程 + Docker Compose 基础设施 · 端口仅绑定 127.0.0.1",
  group="部署与前端", status="pass",
  owns="这套系统跑在一台什么样的机器上：哪些是宿主机进程、哪些是容器、内存上限与端口暴露策略。",
  sections=[
   ("形态", [
    "Web 双应用、Java 8 服务 + 网关、Python 助手均为宿主机进程；Nginx 是唯一公网入口（HTTP 全部 301 到 HTTPS）。",
    "六个容器：MySQL 8.4.11（2G）、Redis 7.4.7（384M）、RabbitMQ 4.2.9（768M）、Nacos v2.5.3（768M）、Elasticsearch 8.19.0（1G）、Qdrant v1.15.1（512M），全部带 healthcheck 与持久卷。",
    "可选 Postgres 16 容器（compose profile）作为 LangGraph checkpointer。"]),
   ("隔离", [
    "容器端口只发布到 127.0.0.1（开发映射如 Redis 16379、Nacos 18848 由 env 决定）。",
    "数据库分账号分库（flyway / nacos / growth 专用账号）。"]),
  ],
  evidence=["deploy/compose.yaml", "deploy/nginx.smartlect.conf", "scripts/dev.sh"],
  related=["01", "12"]),

 dict(no="12", slug="frontend-apps", type="architecture", title="前端双应用",
  desc="用户端与管理端两个独立 Vue 3 应用 · 唯一共享是设计令牌",
  group="部署与前端", status="pass",
  owns="浏览器的两端：页面结构、API 层约定、导购 UI 组件，以及管理端停用功能的呈现方式。",
  sections=[
   ("用户端", [
    "Vue3+TS，:18180，history 路由；主 Tab：首页/分类/购物车/我的，子页含商品、结算、支付、订单、独立导购页。",
    "API 双通道：javaGet/javaPost 走 Java 商城接口，aiGet 走 /api/assistant；401 或业务码 901 统一清会话。",
    "导购组件：商品页「问这件」入口、PC 全局浮层（Pinia 控制）、提案确认卡（先核对再确认）。"]),
   ("管理端", [
    "Vue3+JS，:18181，/admin/ 基址 + hash 路由；覆盖看板/商品/订单/退款审核/用户/券/知识库/AI 资产。",
    "经营助手、广告投放、评价分析、增长报告菜单灰显「已停用」，对应写接口鉴权后 410。",
    "移动端管理台整体下线，旧书签重定向首页。"]),
  ],
  evidence=["web/user/src/api/client.ts", "web/admin/src/views/Layout.vue", "web/shared/design-tokens.scss"],
  related=["03", "08", "01"]),
]

GROUPS = ["总览", "后端", "交易流程", "AI 助手", "部署与前端"]
TYPE_LABEL = {"architecture": "架构图", "sequence": "时序图", "workflow": "流程图", "dataflow": "数据流图"}

CSS = """
:root{--bg:#f7f8fa;--card:#fff;--ink:#1a2233;--muted:#5b6472;--line:#e3e7ee;--accent:#2f6fed;--chip:#eaf1fe;
--ok:#0e9f6e;--okbg:#e6f7f0}
*{box-sizing:border-box}body{margin:0;font:15px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 64px}
header h1{font-size:26px;margin:6px 0 2px}header p{color:var(--muted);margin:0 0 4px}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.chip{background:var(--chip);color:var(--accent);border-radius:999px;padding:2px 12px;font-size:12.5px}
.chip.ok{background:var(--okbg);color:var(--ok)}
h2{font-size:19px;margin:34px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
a.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;text-decoration:none;color:inherit;transition:box-shadow .15s,transform .15s}
a.card:hover{box-shadow:0 6px 18px rgba(31,45,80,.10);transform:translateY(-1px)}
.card .no{font-size:12px;color:var(--accent);font-weight:600;letter-spacing:.5px}
.card .t{font-size:16.5px;font-weight:650;margin:2px 0}
.card .d{font-size:13px;color:var(--muted);line-height:1.6}
.badge{display:inline-block;font-size:11.5px;background:var(--chip);color:var(--accent);border-radius:6px;padding:1px 8px;margin-top:8px}
.frame{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:16px 0}
.frame iframe{display:block;width:100%;height:860px;border:0}
.frame.tall iframe{height:1180px}
section.doc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 20px 14px;margin:14px 0}
section.doc h3{font-size:15.5px;margin:16px 0 6px;color:var(--accent)}
section.doc ul{padding-left:20px;margin:4px 0}section.doc li{margin:4px 0}
.ev{font-size:13px;color:var(--muted)} .ev code{background:var(--chip);border-radius:5px;padding:1px 7px;font-size:12px;color:var(--accent);font-family:ui-monospace,Consolas,monospace}
.nav{display:flex;justify-content:space-between;gap:10px;margin-top:18px;flex-wrap:wrap}
.nav a{color:var(--accent);text-decoration:none;font-size:14px;background:var(--card);border:1px solid var(--line);border-radius:9px;padding:7px 14px}
.crumb{font-size:13.5px;color:var(--muted)}.crumb a{color:var(--accent);text-decoration:none}
footer{margin-top:44px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);padding-top:14px}
@media (max-width:720px){.frame iframe{height:560px}}
@media (prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#161d27;--ink:#e7ecf3;--muted:#98a3b3;--line:#253044;--chip:#1c2a44;--accent:#7aa7ff}}
"""

def rel_links(cur):
    m = {d["no"]: d for d in DIAGRAMS}
    return [(m[n]["no"], m[n]["title"], f'{m[n]["no"]}-{m[n]["slug"]}.html') for n in cur["related"]]

def build_index():
    cards = ""
    for g in GROUPS:
        items = [d for d in DIAGRAMS if d["group"] == g]
        cards += f'<h2>{html.escape(g)}</h2><div class="grid">'
        for d in items:
            cards += (f'<a class="card" href="pages/{d["no"]}-{d["slug"]}.html">'
                      f'<div class="no">图 {d["no"]}</div><div class="t">{html.escape(d["title"])}</div>'
                      f'<div class="d">{html.escape(d["desc"])}</div>'
                      f'<span class="badge">{TYPE_LABEL[d["type"]]}</span></a>')
        cards += "</div>"
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Smartlect 架构图集</title><style>{CSS}</style></head><body><div class="wrap">
<header><h1>Smartlect 架构图集</h1>
<p>一家会按商品回答的店——C 端商城 + 商家后台，中间只放两个领域 Agent。本图集覆盖系统总览、后端微服务、认证边界、交易流程、AI 助手、部署与前端共 12 张交互式图示。</p>
<div class="meta"><span class="chip">12 张图 · 5 个部分</span><span class="chip ok">全部通过 validate / deliver / check / browser-check</span>
<span class="chip">证据锚定 <a href="{REPO}/tree/{SHA}" style="color:inherit">{SHA[:9]}</a></span></div></header>
<h2>先看总览</h2>
<div class="frame"><iframe src="diagrams/01-system-overview.html" title="系统总览"></iframe></div>
{cards}
<footer>图表由 <b>archify</b> 渲染（含暗色主题与导出），点击任一卡片查看该部分的说明页与全屏交互图 · 生成于 2026-10-04 · 仓库 <a href="{REPO}">{REPO.replace("https://","")}</a></footer>
</div></body></html>"""
    open(os.path.join(ROOT, "index.html"), "w").write(page)

def build_page(d):
    rels = rel_links(d)
    rel_html = "".join(f'<a href="{u}">图 {n} · {t} →</a>' for n, t, u in rels)
    ev = " · ".join(f'<code>{html.escape(e)}</code>' for e in d["evidence"])
    secs = ""
    for t, items in d["sections"]:
        secs += f"<h3>{html.escape(t)}</h3><ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>图 {d["no"]} · {d["title"]} — Smartlect 架构图集</title><style>{CSS}</style></head><body><div class="wrap">
<header><div class="crumb"><a href="../index.html">← 架构图集</a> / {html.escape(d["group"])}</div>
<h1>图 {d["no"]} · {d["title"]}</h1><p>{html.escape(d["desc"])}</p>
<div class="meta"><span class="chip">{TYPE_LABEL[d["type"]]}</span><span class="chip ok">四项门禁通过</span>
<span class="chip">全屏：<a href="../diagrams/{d["no"]}-{d["slug"]}.html" style="color:inherit" target="_blank">在新窗口打开交互图</a></span></div></header>
<section class="doc"><h3>这一部分负责什么</h3><p>{html.escape(d["owns"])}</p>{secs}
<p class="ev" style="margin-top:14px">关键证据：{ev}</p></section>
<div class="frame{' tall' if d['type'] == 'sequence' else ''}"><iframe src="../diagrams/{d["no"]}-{d["slug"]}.html" title="{d["title"]}"></iframe></div>
<div class="nav"><a href="../index.html">← 返回图集</a>{rel_html}</div>
<footer>锚定仓库修订 <a href="{REPO}/tree/{SHA}">{SHA}</a> · 图内每个节点均带源码位置引用，可在交互图中点击查看。</footer>
</div></body></html>"""
    os.makedirs(os.path.join(ROOT, "pages"), exist_ok=True)
    open(os.path.join(ROOT, "pages", f'{d["no"]}-{d["slug"]}.html'), "w").write(page)

build_index()
for d in DIAGRAMS:
    build_page(d)
print("index +", len(DIAGRAMS), "pages written")
