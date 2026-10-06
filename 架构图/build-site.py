#!/usr/bin/env python3
"""生成「架构图」图集的导航站（index.html + pages/*.html + assets/site.css）。

图表本身由 Archify 生成（见 candidates/ 与 README.md 的再生成命令）；
本脚本只负责导航与说明页，证据清单直接从 candidates/*.json 的 sources 派生，
保证页面与图内引用同源。
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "https://github.com/LittleSongxx/Smartlect"
REVISION = "77739061b59ce2854183e6d261057aa8113de8da"

GROUPS = [
    ("端与接入", ["03-web", "05-auth-flow"]),
    ("交易后端（Java）", ["04-backend", "06-order-create", "07-order-lifecycle", "08-pay-outbox", "09-coupon-rush"]),
    ("智能导购（Python）", ["10-agent-loop", "13-subagent", "12-proposal"]),
    ("检索与知识", ["11-rag"]),
    ("部署与运维", ["02-deploy"]),
]

PAGES = {
    "01-overview": {
        "title": "系统总览",
        "kind": "architecture",
        "lead": "一张图放下整个 Smartlect：浏览器两端、Nginx、网关、Java 交易服务群、Python 导购 Agent、检索栈与数据设施，以及它们之间的边界。",
        "owns": [
            "它是全图集的入口与地图：只表达「谁在哪里、谁调用谁、边界在哪」，细节下沉到各分区图。",
            "刻意画出的分界：浏览器负责呈现；Python 负责「问什么、检索什么、下一步计划什么」；真正改价格、扣库存、落订单的只有 Java。",
        ],
        "io": [
            ("入口", "用户端与管理端 SPA 经 HTTPS 进入 Nginx（smartlect.cn），/api/ 与 /admin-api/ 反代到网关。"),
            ("出口", "模型服务（阿里云百炼兼容模式：对话 / 向量 / 重排三端点）是唯一外部依赖。"),
            ("读写", "Java 服务群各写自己的 schema；导购 Agent 写 smartlect_growth；知识检索读 ES + Qdrant。"),
        ],
        "mech": [
            "网关统一入口：路由 lb://smartlect-* 到 Java 服务，导购路径 /api/assistant/** 转发到 Python（超时 95s）。",
            "导购 Agent 用有界 ReAct：模型 6 次、工具 10 次、检索 2 次、单轮 90s（policy.py 是唯一预算事实源）。",
            "知识先发布才进检索；价格与库存不进向量，每次向交易服务重新查询。",
            "跨服务一致性靠「条件 UPDATE + 业务幂等账本 + Outbox 事件」三层，而不是分布式事务。",
        ],
        "bounds": [
            "模型可以建议，不能成交：下单、退款、经营授权都要人点确认。",
            "支付是模拟的（mock 通道），没有真实资金流。",
        ],
        "related": ["02-deploy", "03-web", "04-backend", "10-agent-loop", "11-rag"],
    },
    "03-web": {
        "title": "前端结构 · 用户端与管理端",
        "kind": "architecture",
        "lead": "两个 Vue 3 SPA 与它们在网关上的两个 API 面；导购工作区的「问这件」聚焦与 SSE 事件流都在这里。",
        "owns": [
            "用户端：逛店、商品详情、购物车、结算、订单、导购浮层与独立导购页。",
            "管理端：商品、订单、用户、优惠券、知识库、人工客服与 AI 资产页（模型 / 提示词 / 知识索引 / 运行浏览器 / 工具调试台）。",
            "前端不存 token：Java 侧走 Sa-Token Cookie，导购侧写操作带 X-CSRF-Token。",
        ],
        "io": [
            ("Java 面", "axios baseURL /api（withCredentials），响应统一解包 data.data，901 触发重新握手、401 跳登录。"),
            ("导购面", "独立 fetch 客户端基址 /api/assistant，会话与 CSRF 来自 GET /session。"),
            ("事件流", "SSE over fetch，带 Last-Event-ID 游标，100s 超时、断线重连只回放已持久化事件。"),
        ],
        "mech": [
            "「问这件」：商品页写入会话级 consultProduct → 每条消息带 focus_mode=PRODUCT + product_id + sku_key → 服务端据此钉在单商品语料。",
            "管理端菜单把已退役功能保留为「已停用」占位（经营助手 / 广告投放 / 评价分析 / 增长报告）。",
            "桌面端另有浮动导购面板，与独立页共用同一个 AgentWorkspace。",
        ],
        "bounds": [
            "导购浮层默认只答当前商品与店规；「改问全店」显式切换为 GLOBAL。",
            "确认卡片单独拉取实时订单/条目展示，与事件流解耦。",
        ],
        "related": ["01-overview", "05-auth-flow", "10-agent-loop", "12-proposal"],
    },
    "05-auth-flow": {
        "title": "鉴权与路由链路",
        "kind": "sequence",
        "lead": "一次请求如何穿过 Nginx、网关与业务服务：两层校验、双账号体系、白名单与内部令牌。",
        "owns": [
            "网关的 AuthGlobalFilter：先剥离客户端伪造的身份头，再按路径白名单决定是否校验登录态。",
            "服务端 Sa-Token 拦截器：真正取身份的地方，注解（@SaCheckLogin / @SaCheckPermission）兜底。",
        ],
        "io": [
            ("用户端", "Cookie: token → 网关读 Redis 的 token 登录键 → 业务服务会话内省取 userInfo。"),
            ("管理端", "Cookie: adminToken → 网关读 adminToken 键 → 服务端用 StpAdminLogic 核对并与权限比对。"),
            ("导购", "/api/assistant/** 白名单直通，Python 侧用 IdentityBridge 自校验 actor 与 CSRF。"),
        ],
        "mech": [
            "双账号体系互不通用：用户端 StpUtil（可并发）与管理端 StpAdminLogic（非并发、uuid）两套 StpLogic。",
            "管理端登录有 IP 锁定与失败计数，验证码校验先行，密码 bcrypt 校验并支持自动升级。",
            "内部接口只认 X-Internal-Token（常量时间比较，未配置即全拒），Feign 自动带头。",
            "网关按 routeId 限流：敏感路径 30 QPS、默认 200 QPS，超限 429；GET 默认重试 2 次。",
        ],
        "bounds": [
            "网关只判断 token 是否存在，不下发身份头——身份一律由服务端会话内省得出。",
            "白名单路径不校验登录态：登录、验证码、公开商品、导购路径。",
        ],
        "related": ["01-overview", "03-web", "04-backend"],
    },
    "04-backend": {
        "title": "Java 后端服务群",
        "kind": "architecture",
        "lead": "9 个 Spring Cloud 服务、各自的独立库，以及网关如何把 16 条路由分发到它们。",
        "owns": [
            "gateway(:18080) 路由与鉴权；user/product/cart/stock/order/pay/coupon 是交易权威；admin 是管理端 BFF（跨库统计视图 + Feign 聚合）。",
            "服务间调用只走 /internal/** Feign 接口，禁止跨库直连。",
        ],
        "io": [
            ("入口", "网关按 /api/** 与 /admin-api/**（重写为 /admin/**）分发；admin-api 兜底到 admin 服务。"),
            ("库", "8 个业务库各自归属一个服务，迁移由 Flyway 管理；admin 走跨库视图。"),
            ("中间件", "Redis 承载会话、分布式锁与限流；RabbitMQ 承载 Outbox 事件与延迟队列；Nacos 负责注册发现。"),
        ],
        "mech": [
            "order 是编排者：建单时经 Feign 拉地址与商品快照、读库存真相、券预占、扣库存、清购物车、建支付单。",
            "库存唯一真相是条件 UPDATE（stock + delta >= 0），券同理；两者都以业务键去重。",
            "Outbox 与业务同库同事务，提交后投递并等发布确认；重试耗尽转 EXHAUSTED，可自动或人工重放。",
            "退款走显式 Saga 状态机（PENDING_PAYMENT → PAYMENT_CONFIRMED → STOCK_PENDING → COMPLETED，超限转 MANUAL_REVIEW）。",
        ],
        "bounds": [
            "定时任务靠 Redis 锁保证多实例安全；admin 的日结任务同样加锁。",
            "服务注册到 Nacos 时上报真实内网 IP（集群形态），网关经 lb:// 发现。",
        ],
        "related": ["01-overview", "02-deploy", "05-auth-flow", "06-order-create", "08-pay-outbox"],
    },
    "06-order-create": {
        "title": "下单主链 · 幂等到扣减补偿",
        "kind": "sequence",
        "lead": "一次 postOrder 的完整往返：幂等账本抢占、库存与券预占、本地事务、跨服务扣减、事件，以及 catch 分支的补偿。",
        "owns": [
            "order 服务是唯一落单者；stock 与 coupon 各自守护自己的条件更新；pay 提供支付单；cart 清车。",
            "幂等账本 order_request_idempotency 记录 (user_id, command_type, idempotency_key) 与请求指纹。",
        ],
        "io": [
            ("请求", "POST /api/order/postOrder 带 Idempotency-Key；响应回写 Idempotency-Replayed。"),
            ("读取", "建单前读库存可用量、校验并预占券、拉地址与商品快照（快照固化后不随商品变化）。"),
            ("写入", "订单/明细/物流信息与 Outbox 行同库同事务；随后远程扣库存并把购物车条目清掉。"),
        ],
        "mech": [
            "重复键：直接回放已存响应；同键不同参 409；PROCESSING 超时转 INCONCLUSIVE 交人工核。",
            "扣库存走 changeStockBatch，业务键 order-deduct:<payOrderId> 防重复扣减。",
            "支付超时延时消息用幂等键 payTimeout:<orderId>，到点关单并回补。",
            "catch 分支：库存回补 restoreOrderStock、券解锁 changeUserCouponStatus；再失败落 mq_compensation_log。",
        ],
        "bounds": [
            "条件 UPDATE 从 SQL 层保证不超卖；业务幂等记录表以 business_key 为主键。",
            "补偿与业务同键，重放不会重复加减。",
        ],
        "related": ["04-backend", "07-order-lifecycle", "08-pay-outbox", "09-coupon-rush"],
    },
    "07-order-lifecycle": {
        "title": "订单状态机",
        "kind": "lifecycle",
        "lead": "订单的 9 个状态与全部合法流转：主链、取消/关单、退款与终态；每一次流转都是带条件的 CAS 落库。",
        "owns": [
            "状态枚举 OrderStatusEnum（0 待支付 … 7 部分退款，-1 删除）；迁移表集中在 OrderStateMachine。",
            "取消与关单离开待支付；退款从已支付/已发货/部分退款进入；删除只允许从终态进入。",
        ],
        "io": [
            ("事件来源", "支付成功（Outbox 事件）、秒杀券直付、用户取消、支付超时/系统关单、发货、确认收货、退款审批、删除。"),
            ("落库", "每次流转都以 order_status 条件做 CAS；返回 0 行即并发竞争，幂等重入退化为读比对。"),
        ],
        "mech": [
            "延迟队列驱动支付超时关单、自动确认收货与模拟发货。",
            "退款 Saga 有自己的状态机（受理 → 支付侧 → 库存回补 → 完成），库存回补可重试 6 次后转人工复核。",
            "部分退款可继续补退至全额。",
        ],
        "bounds": [
            "非法流转直接抛异常，不做静默修正。",
            "DELETE(-1) 是软删除标记，已删除订单不再参与对账统计。",
        ],
        "related": ["04-backend", "06-order-create", "08-pay-outbox"],
    },
    "08-pay-outbox": {
        "title": "支付成功与 Outbox 最终一致",
        "kind": "workflow",
        "lead": "pay 侧完成后，事件如何可靠地到达 order 并推进状态机——以及投递失败、重试耗尽与补偿重放的完整路径。",
        "owns": [
            "pay 是支付状态的权威（intent 落库 + mock/live 通道）；order 只消费事件并按自己的状态机推进。",
            "Outbox 本地消息表与业务同事务落库，提交后才投递，断开 pay→order 的同步调用环。",
        ],
        "io": [
            ("写入", "Outbox 行（幂等键 paySuccess:<payOrderId>，可靠性 HIGH）与业务同事务。"),
            ("投递", "afterCommit 触发，带 Publisher Confirm；失败指数退避重试，定时任务兜底扫描。"),
            ("消费", "PAY_SUCCESS_QUEUE 手动 ack + Redis 租约幂等；单号粒度 Redisson 锁内 assertSettled 后 CAS。"),
        ],
        "mech": [
            "投递失败重试 5s/30s/2min；耗尽转 EXHAUSTED 并暴露 Prometheus 指标。",
            "消费侧幂等：Redis 租约 Lua + 状态机 CAS + 业务键三重保护。",
            "补偿台账 mq_compensation_log 记录四类远程失败，支持自动重放（每分钟扫）与管理端人工重放。",
        ],
        "bounds": [
            "重试与重放都以幂等键去重，重复消费不会重复推进状态。",
            "退款库存回补走独立的 REFUND_EXCHANGE 队列，与支付事件互不干扰。",
        ],
        "related": ["04-backend", "06-order-create", "07-order-lifecycle", "09-coupon-rush"],
    },
    "09-coupon-rush": {
        "title": "秒杀券 · Redis 预占到对账",
        "kind": "workflow",
        "lead": "唯一以 Redis 预占为资格来源的链路：限流 → Lua 预占 → DB 条件扣减 → 建单 → 支付激活，外加 10 分钟对账收敛。",
        "owns": [
            "coupon 服务持有券库存（remain_count），order 服务负责秒杀建单与券激活。",
            "两段式防超发：Redis Lua 预占（库存/去重/参与者集合）+ DB 条件 UPDATE 兜底。",
        ],
        "io": [
            ("入口", "POST /api/discountCoupon/rushCoupon 带 Idempotency-Key，先过用户维度（30 次/60s）与券维度（200 次/秒）限流。"),
            ("写入", "预占成功后 DB 条件扣减 remain_count-1；建单时券先落 CANT 状态，支付成功才激活。"),
        ],
        "mech": [
            "任一步失败释放预占（release/align Lua），Redis 与 DB 由每 10 分钟的对账任务以 DB 为准收敛。",
            "对账同时摘除悬空参与者集合成员，Redis 归零时从 DB 权威同步。",
            "支付超时关单会回补库存与券名额，回补带上限防止重复回补导致虚高。",
        ],
        "bounds": [
            "秒杀券的「库存」在 coupon 侧，与 sku_stock 无关。",
            "Redis 只是资格来源，最终可售份数以 DB 为准。",
        ],
        "related": ["04-backend", "06-order-create", "07-order-lifecycle"],
    },
    "10-agent-loop": {
        "title": "导购 Agent 有界 ReAct 循环",
        "kind": "workflow",
        "lead": "一轮对话从入队到答复：轮次装配、模型节点、工具节点、答案节点与守卫，全程受预算闸约束。",
        "owns": [
            "会话与运行：消息入队（带 focus 范围）、run + MySQL 租约、事件持久化后经 SSE 回放。",
            "循环：LangGraph 图只编译一次（model → tools → answer），run 作用域经 ContextVar 注入。",
        ],
        "io": [
            ("输入", "本轮消息（focus_mode / product_id / sku_key）、会话历史与任务槽、已发布知识。"),
            ("工具", "19 个工具（检索、商品与订单查询、提案、记忆、派发）经 invoke 执行：allowed 列表 + RBAC + 严格校验 + 幂等账本。"),
            ("输出", "答复与引用、澄清问题、待确认提案、SSE 事件流。"),
        ],
        "mech": [
            "预算闸是单一事实源：模型调用 6 次、工具调用 10 次、检索 2 次、单轮 90s；每次尝试前放行或拒绝。",
            "答案守卫链：证据契约、状态声明必须带本轮回执、引用在出答前复验仍可见，结构修复 1 次后强制收口。",
            "降级收口统一处理超时与预算耗尽：只说明未覆盖并给人工入口，不伪造事实。",
        ],
        "bounds": [
            "单条观察 6500 字节上限；相同调用被拒绝并给出结构化原因。",
            "来源内容里的指令被识别隔离，不引原文；ACL 拦截只露标题并编译为转人工。",
        ],
        "related": ["01-overview", "11-rag", "13-subagent", "12-proposal"],
    },
    "11-rag": {
        "title": "知识发布与混合检索数据流",
        "kind": "dataflow",
        "lead": "两条数据流在一张图里：管理端发布侧（切分 → 嵌入 → 发布门）与导购检索侧（改写 → 混检 → 融合重排 → 引用）。",
        "owns": [
            "发布侧：草稿与事实校验、512 tok / 51 重叠分块、批量嵌入（批 10，审计先于 HTTP）、索引镜像与发布门。",
            "检索侧：查询改写与多路变体、ES BM25 与 Qdrant dense 各取 top-50、RRF 融合 24、厂商重排取前 8。",
        ],
        "io": [
            ("写入", "ES 索引（smartcn）与 Qdrant 集合（1024 维 HNSW）由同一份分块镜像写入。"),
            ("可见性", "只有 PUBLISHED 且有效期内的文档参与检索；撤回后不再被新的回答引用。"),
        ],
        "mech": [
            "任一路检索不可用时按健康窗跳过并记录降级，仍可用单路结果作答。",
            "最多 4 条引用；facts 冲突显式标注，出答前复验引用仍可见（FOR SHARE）。",
            "检索预算 2 次，超限走重写拒绝或空观测；重排不可用时按 RRF 顺序并记录 rerank_backend。",
        ],
        "bounds": [
            "来源内容里的指令模式被识别并隔离，不引原文。",
            "ACL 拦截只暴露标题，编译为转人工（商家侧文档）。",
        ],
        "related": ["01-overview", "10-agent-loop", "03-web"],
    },
    "12-proposal": {
        "title": "提案确认 · 从建议到 Java 落单",
        "kind": "sequence",
        "lead": "「模型建议、人点确认、Java 落单」的完整链路：报价、待确认提案、版本校验、幂等执行与支付。",
        "owns": [
            "导购 Agent 是提案所有者：生成（先向 Java 要报价）、确认（版本校验）、执行（幂等键打到 Java）、记录结果。",
            "提案状态机：PROPOSED → CONFIRMED/REJECTED/EXPIRED → EXECUTING → SUCCEEDED/FAILED/UNKNOWN。",
        ],
        "io": [
            ("生成", "POST /internal/order/commerce/v2/quote 取 quote_id 与金额（分），写 proposal 并展示确认卡片。"),
            ("执行", "POST /commerce/v2/createConfirmed，Idempotency-Key 与 Java 侧请求幂等账本对齐。"),
            ("支付", "mock 通道直接完成；live 通道取支付链接；支付成功由 pay 的 Outbox 事件驱动 order。"),
        ],
        "mech": [
            "版本号与决策版本双重校验：重复确认不会二次执行。",
            "支付前金额不一致 → 409 RECONFIRM_REQUIRED，回卡片重确认。",
            "EXECUTING/UNKNOWN 只复核（recover_only），不重复扣款。",
        ],
        "bounds": [
            "人工客服接管中的会话拒绝确认（human_control_active）。",
            "确认端点要求用户身份 + orders:write 权限。",
        ],
        "related": ["10-agent-loop", "06-order-create", "08-pay-outbox", "03-web"],
    },
    "13-subagent": {
        "title": "子智能体派发（task_dispatch）",
        "kind": "sequence",
        "lead": "遇到可并行的独立检索任务时，主 Agent 派发 1–3 个子智能体并发执行，各自取证后合并，并如实披露未完成项。",
        "owns": [
            "派发器：关键词路由到三个档位（order-reader / comparator / retrieval-scout），并集只读。",
            "每个子代理用 create_react_agent 起图，6 步上限，25s 超时，只回文本。",
        ],
        "io": [
            ("输入", "1–3 个任务描述与理由（parallel / isolation / deep_chain），超出即拒绝。"),
            ("输出", "compose_results：✓/✗ 状态、路由档位、耗时、incomplete_tasks 披露。"),
        ],
        "mech": [
            "预算共享：子代理的模型与工具调用都记在主 run 的预算上（不是每代理一份）。",
            "单个子任务失败/超时不影响整批，失败在合并结果里标注。",
            "路由结果作为 decision 事件留痕；完整结果留在调用账本，模型只看投影。",
        ],
        "bounds": [
            "子代理工具集是只读并集：不能下单、不能改状态。",
            "未完成项必须披露，模型不得掩盖失败。",
        ],
        "related": ["10-agent-loop", "11-rag"],
    },
    "02-deploy": {
        "title": "部署拓扑 · 阿里云 ECS 三节点",
        "kind": "architecture",
        "lead": "Java 后端当前跑在阿里云 ECS 三节点上：node1 承载全量应用与主库，node2/node3 承载应用副本与中间件成员，Nginx 做网关多后端。",
        "owns": [
            "node1（8c16g）：Nginx、应用全量、MySQL 主、Redis 主、sentinel、rabbit-c1、nacos-c1。",
            "node2 / node3（2c8g）：应用副本（gateway/product/order/user|cart）、Redis 副本与 sentinel、rabbit-cN、nacos-cN。",
        ],
        "io": [
            ("入口", "Nginx upstream 三个网关后端（max_fails=3、fail_timeout=10s、keepalive），副本网关挂掉自动摘除。"),
            ("跨机", "应用经内网连 node1 的主库与 sentinel 发现的主 Redis；副本网关的 /api/assistant/** 指向 node1:18000。"),
            ("共享", "上传目录经 NFS 共享，副本节点先等挂载就绪再拉进程。"),
        ],
        "mech": [
            "RabbitMQ 是 3 节点 quorum（pause_minority、host 网络、稳定节点名），拓扑走 export/import_definitions。",
            "Redis 1 主 2 副本 + 3 Sentinel（quorum 2、down-after 5s），主漂移后应用经 Lettuce 跟随、无需重启。",
            "Nacos 3 节点 Raft 共用 node1 MySQL 的 smartlect_nacos 库；MySQL 仍单机主库 + node2 只读副本。",
            "发布走受限 SSH 网关（只放行 upload/deploy/rollback/status），13 进程健康门禁兜底，保留 3 个 release bundle 可回滚。",
        ],
        "bounds": [
            "MySQL 主从切换目前是人工步骤（改 runtime.env → 提升副本 → Nacos 数据源同步）。",
            "回退用 revert-cluster.sh 一步回到单机形态，单机期数据卷全程未动。",
        ],
        "related": ["01-overview", "04-backend"],
        "note": "本页部分依据工作区未提交的 deploy/cluster/ 编排文件与 docs/prod-hardening/ha-cluster.md 的集群记录绘制；图内证据锚点只引用 HEAD 已提交的字节。",
    },
}


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def source_links(kind: str) -> list[tuple[str, str]]:
    """从候选 JSON 派生证据清单：[(显示文本, GitHub 链接或路径)]."""
    path = ROOT / "candidates" / f"{kind}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    found: dict[tuple, set] = {}

    def walk(node):
        if isinstance(node, dict):
            if "path" in node and isinstance(node.get("path"), str):
                key = (node["path"], node.get("line"), node.get("end_line"))
                found.setdefault(key, set())
                if node.get("label"):
                    found[key].add(node["label"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    links = []
    for (p, line, end) in sorted(found, key=lambda k: (k[0], k[1] or 0)):
        label = " / ".join(sorted(found[(p, line, end)]))
        loc = f"{p}" + (f":{line}" if line else "") + (f"-{end}" if end else "")
        if p.startswith(("deploy/cluster/",)) or not line:
            links.append((f"{label} · {loc}", ""))
            continue
        anchor = f"#L{line}" + (f"-L{end}" if end else "")
        links.append((f"{label} · {loc}", f"{REPO}/blob/{REVISION}/{p}{anchor}"))
    return links


def page_shell(title: str, body: str, *, up: str = "../") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{esc(title)} · Smartlect 架构图</title>
<link rel="stylesheet" href="{up}assets/site.css" />
</head>
<body>
{body}
</body>
</html>
"""


def render_page(kind: str, meta: dict) -> str:
    diagram = f"../diagrams/{kind}.html"
    parts = [
        '<header class="topbar">',
        f'<a class="back" href="../index.html">← 返回总览</a>',
        f'<span class="badge">{esc(meta["kind"])}</span>',
        "</header>",
        f'<main class="wrap">',
        f'<h1>{esc(meta["title"])}</h1>',
        f'<p class="lead">{esc(meta["lead"])}</p>',
    ]
    if meta.get("note"):
        parts.append(f'<p class="note">{esc(meta["note"])}</p>')
    parts += [
        '<section class="diagram">',
        f'<iframe src="{diagram}" title="{esc(meta["title"])} 交互图" loading="lazy"></iframe>',
        f'<p class="open"><a href="{diagram}" target="_blank" rel="noopener">在新标签打开交互版（缩放 / 主题 / 导出）</a></p>',
        "</section>",
        '<section><h2>它负责什么</h2><ul>',
    ]
    parts += [f"<li>{esc(item)}</li>" for item in meta["owns"]]
    parts.append("</ul></section>")
    parts.append('<section><h2>输入与输出</h2><dl>')
    for key, value in meta["io"]:
        parts.append(f"<dt>{esc(key)}</dt><dd>{esc(value)}</dd>")
    parts.append("</dl></section>")
    parts.append('<section><h2>关键机制</h2><ul>')
    parts += [f"<li>{esc(item)}</li>" for item in meta["mech"]]
    parts.append("</ul></section>")
    parts.append('<section><h2>边界与失败路径</h2><ul>')
    parts += [f"<li>{esc(item)}</li>" for item in meta["bounds"]]
    parts.append("</ul></section>")

    links = source_links(kind)
    parts.append('<section><h2>代码溯源（证据锚点）</h2><ul class="src">')
    for label, url in links:
        if url:
            parts.append(f'<li><a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a></li>')
        else:
            parts.append(f"<li><code>{esc(label)}</code></li>")
    parts.append("</ul>")
    parts.append(
        f'<p class="hint">以上锚点与图内 <code>sources</code> 同源（由 candidates/{kind}.json 派生）；'
        f"链接指向提交 <code>{REVISION[:12]}</code> 的字节。</p></section>"
    )

    related = [(rk, PAGES[rk]["title"]) for rk in meta.get("related", []) if rk in PAGES]
    if related:
        parts.append('<section><h2>相关页面</h2><ul class="rel">')
        for rk, rtitle in related:
            parts.append(f'<li><a href="{rk}.html">{esc(rtitle)}</a></li>')
        parts.append("</ul></section>")

    spec = json.loads((ROOT / "candidates" / f"{kind}.json").read_text(encoding="utf-8"))
    parts.append(
        f'<footer class="meta">候选：<code>candidates/{kind}.json</code> · 图：<code>diagrams/{kind}.html</code> · '
        f"标题：{esc(spec['meta']['title'])}</footer>"
    )
    parts.append("</main>")
    return page_shell(meta["title"], "\n".join(parts))


def render_index() -> str:
    cards = []
    for group, kinds in GROUPS:
        items = "\n".join(
            f'<li><a href="pages/{k}.html"><span class="t">{esc(PAGES[k]["title"])}</span>'
            f'<span class="k">{esc(PAGES[k]["kind"])}</span></a></li>'
            for k in kinds
        )
        cards.append(f'<section class="group"><h2>{esc(group)}</h2><ul class="cards">{items}</ul></section>')
    overview = PAGES["01-overview"]
    return page_shell(
        "Smartlect 架构图集",
        f"""<header class="hero">
  <h1>Smartlect 架构图集</h1>
  <p>整体与各部分的架构图、流程图：端与接入、Java 交易后端、Python 导购 Agent、检索与知识、部署与运维。</p>
  <p class="hero-meta">13 张图，全部通过 Archify showcase 四门（validate · deliver · check · browser-check）；
     证据锚点指向提交 <code>{REVISION[:12]}</code>。</p>
</header>
<main class="wrap">
  <section class="overview">
    <div class="overview-head">
      <h2>{esc(overview["title"])}</h2>
      <a href="pages/01-overview.html">打开说明页 →</a>
    </div>
    <iframe src="diagrams/01-overview.html" title="Smartlect 系统总览"></iframe>
    <p class="open"><a href="diagrams/01-overview.html" target="_blank" rel="noopener">在新标签打开交互版</a></p>
  </section>
  {"".join(cards)}
  <section class="notes">
    <h2>怎么读这套图</h2>
    <ul>
      <li>每张图都能单独打开：左上角切换主题，右下角可导出 PNG/SVG。</li>
      <li>图与说明页都标了「它负责什么 / 输入输出 / 关键机制 / 边界」，页末是代码证据锚点。</li>
      <li>部署一页注明：部分事实来自工作区未提交的 <code>deploy/cluster/</code> 编排，图内锚点只引用已提交字节。</li>
    </ul>
  </section>
</main>""",
        up="",
    )


CSS = """\
:root { color-scheme: light dark; --fg:#1c1f23; --muted:#5b6470; --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --accent:#0b6bcb; }
@media (prefers-color-scheme: dark) { :root { --fg:#e8eaed; --muted:#9aa4b2; --bg:#14171b; --card:#1b1f24; --line:#2a3037; --accent:#6cb0ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.7 -apple-system, "Segoe UI", "PingFang SC", "Noto Sans CJK SC", sans-serif; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
code { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:.9em; }
.wrap { max-width:1180px; margin:0 auto; padding:0 20px 64px; }
.hero { padding:56px 20px 28px; text-align:center; }
.hero h1 { margin:0 0 12px; font-size:34px; }
.hero p { margin:6px auto; max-width:820px; color:var(--muted); }
.hero-meta { font-size:13px; }
.topbar { display:flex; align-items:center; gap:12px; padding:14px 20px; border-bottom:1px solid var(--line); background:var(--card); position:sticky; top:0; z-index:5; }
.topbar .back { font-weight:600; }
.badge { margin-left:auto; font-size:12px; color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:2px 10px; }
h1 { font-size:28px; margin:28px 0 10px; }
.lead { color:var(--fg); max-width:900px; }
.note { color:var(--muted); background:rgba(255,196,0,.12); border-left:3px solid #e0a800; padding:8px 12px; max-width:900px; }
section { margin:28px 0 0; }
section h2 { font-size:18px; margin:0 0 10px; border-left:3px solid var(--accent); padding-left:10px; }
ul, dl { margin:0; padding:0; }
li { margin:4px 0; overflow-wrap:anywhere; }
ul { list-style:none; }
ul > li { padding-left:16px; position:relative; }
ul > li::before { content:"·"; position:absolute; left:4px; color:var(--muted); }
dl dt { font-weight:600; margin-top:10px; }
dl dd { margin:2px 0 0 0; color:var(--muted); overflow-wrap:anywhere; }
.diagram { margin-top:20px; }
iframe { width:100%; height:min(84vh, 1040px); border:1px solid var(--line); border-radius:10px; background:var(--card); }
.open { font-size:13px; color:var(--muted); margin-top:8px; }
.src a, .src code { font-size:13px; overflow-wrap:anywhere; }
.hint { font-size:12.5px; color:var(--muted); }
.group { margin-top:26px; }
.cards { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:12px; }
.cards li::before { content:none; }
.cards li { padding:0; }
.cards a { overflow-wrap:anywhere; display:flex; justify-content:space-between; gap:10px; align-items:baseline; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; color:var(--fg); }
.cards a:hover { border-color:var(--accent); text-decoration:none; }
.cards .k { font-size:12px; color:var(--muted); }
.overview-head { display:flex; align-items:baseline; gap:12px; justify-content:space-between; }
.notes ul { margin-top:6px; }
.rel { display:flex; flex-wrap:wrap; gap:10px; }
.rel li::before { content:none; }
.rel li { padding:0; }
.rel a { background:var(--card); border:1px solid var(--line); border-radius:999px; padding:4px 12px; font-size:13.5px; }
footer.meta { margin-top:34px; padding-top:14px; border-top:1px solid var(--line); color:var(--muted); font-size:12.5px; }
@media (max-width:720px) { iframe { height:70vh; } .hero h1 { font-size:26px; } }
"""


def main() -> None:
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "site.css").write_text(CSS, encoding="utf-8")

    pages = ROOT / "pages"
    pages.mkdir(exist_ok=True)
    for kind, meta in PAGES.items():
        if not (ROOT / "diagrams" / f"{kind}.html").exists():
            raise SystemExit(f"缺少图表：diagrams/{kind}.html")
        (pages / f"{kind}.html").write_text(render_page(kind, meta), encoding="utf-8")

    (ROOT / "index.html").write_text(render_index(), encoding="utf-8")
    print(f"已生成 index.html 与 {len(PAGES)} 个说明页")


if __name__ == "__main__":
    main()
