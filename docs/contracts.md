# Smartlect 业务契约

更新：2026-09-09，F3 归因门禁已通过。Java 是价格、库存、订单、支付、退款的唯一权威；Growth 只调用受控 API、维护自身任务状态和消费业务事件，不直接读写交易表。本文区分当前源码合同与已完成的 F1/F2 验证；F3 运行升级及联验进度以 [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) 为准。

## 当前 HTTP 入口

Gateway 将 `/api/assistant/**`、`/admin-api/assistant/**` 原路径转发到本项目 Growth，路由位于通用管理 BFF 之前，响应超时 95000 ms。旧 Java 公开交易接口保留；AI 写操作必须走报价/确认链。

| 方法与路径 | 当前输入与行为 |
|---|---|
| `GET /api/assistant/session` | 解析用户 cookie 或创建只读访客，返回 `actor` 与 `csrf_token`。 |
| `GET /admin-api/assistant/session` | 必须有有效管理员 cookie，返回 Java 认证过的商家主体；F1 尚无经营目标/审批业务入口。 |
| `POST /api/assistant/conversations` | JSON `{}`，有效主体＋CSRF，创建本人会话。 |
| `GET /api/assistant/conversations/{conversation_id}` | 仅本人，返回会话、最近最多100条消息、原提案、相关运行与人工状态。 |
| `POST /api/assistant/conversations/{conversation_id}/messages` | `{message_id,text}`；幂等保存消息/运行。返回 `RUNNING` 并执行有界Shopping；已接受message_id重试返回原run，同会话并发新消息拒绝且不偷偷插入上下文。GET/SSE不触发重跑。 |
| `POST /api/assistant/conversations/{conversation_id}/mcp` | MCP JSON-RPC 2.0（单次 POST，无会话恢复/无 SSE）：`initialize`（版本协商，支持 2025-06-18／2025-03-26；未知版本回已支持版本并带 `protocolVersionDowngraded` 与 `MCP-Protocol-Version-Downgraded`）、`tools/list`、`tools/call`。`search_knowledge` 与购物同一 `embed_query`。通知返回 202 无响应体。工具集、Schema、权限校验与 Agent 同一份 `REGISTRY`。**仅只读工具**；`propose_*`、`remember_preference`、`request_handoff`、`load_skill` 及 `search_skus`/`recommend_skus`（会写归因回执，外部客户端无曝光上报契约）均返回 `tool_not_available`，未知与不暴露同一答复。每次调用建独立 run 与回执，落同一审计链。 |
| `POST /api/assistant/conversations/{conversation_id}/proposals` | 登录用户＋CSRF；`{message_id,action_type,parameters}`，动作仅 `order/cancel/refund`；返回运行 `WAIT_USER` 和 `result.proposal`。 |
| `GET /api/assistant/proposals/{proposal_id}` | 仅本人，返回持久化原参数、版本、确认/执行状态和业务回执。 |
| `POST /api/assistant/proposals/{proposal_id}/confirm` | 登录用户＋CSRF；`{proposal_version,approved}`，`approved` 默认 `true`，拒绝时显式 `false`；只执行服务器保存的原参数。终态重试直接返回 `{proposal:...}`，其余返回含 `result.proposal` 的运行。 |
| `GET /api/assistant/runs/{run_id}` | 仅本人，查询运行结果，不触发执行。 |
| `GET /api/assistant/runs/{run_id}/events` | 仅本人，按非负整数 `Last-Event-ID` 回放最多 1000 条持久化 SSE 事件；鉴权/归属/游标校验先于流响应头。先回放再等待持久事件至终态/95秒；重新连接继续Last-Event-ID，不再次提交消息。 |
| `GET /health` | Growth 健康；启用消费时附 worker 状态，断开或心跳过期返回 503/degraded。 |
| `GET /internal/ledger/summary?payOrderId=...` | Growth 内部入口，要求内部 token；未指定支付单时返回全账本汇总。 |

Java 内部接口使用 `ResponseVO`：成功为 `status=success,code=200,data=...`。Growth 公共 API 直接返回对象；状态冲突返回 `{error:...}`，严格 schema 错误为 HTTP 422 `invalid_request`，只包含字段位置，不回显输入。FastAPI 鉴权错误使用 `detail`：会话无效 401、权限/CSRF 拒绝 403、他人资源 404、版本/幂等冲突 409、提案过期 410、身份/交易服务不可用 503。

| Java 内部 POST 路径 | 当前合同 |
|---|---|
| `/internal/identity/introspect` | JSON 严格只有 `realm: user/merchant`；服务 token＋对应 cookie；返回 `data={subjectType,actorId,permissions,sessionId}`。 |
| `/internal/order/commerce/v2/quote` | 用户委托＋购买参数；返回 `quoteId/requestHash/totalAmountCents/expiresAt/order`。报价有效 5 分钟，不扣库、不锁券。 |
| `/internal/order/commerce/v2/createConfirmed` | 用户委托＋`Idempotency-Key`；`{quoteId,confirmedAmountCents,order,attributionContextToken?}`，Java 在最终交易检查内匹配报价后建单；可选来源凭据单独验签，不参与购买意图指纹。 |
| `/internal/order/commerce/v2/executeAction` | 用户委托＋原 `Idempotency-Key`；`{actionType,params}`，只允许 `CANCEL_ORDER/REFUND`。 |
| `/internal/order/commerce/v2/actionStatus` | 用户委托；`{actionType,idempotencyKey,params}`，查询 `CREATE_ORDER/CANCEL_ORDER/REFUND` 原命令；`PAYMENT` 使用 `params.payOrderId` 查询付款和订单同步状态。 |

取消参数为 `{orderId}`；退款为 `{orderItemId,refundAmountCents,reason?}`。退款恢复必须携带原确认金额及原理由以核对完整命令指纹；建单恢复的 `params` 可为 `{}`，按本人和原 key 恢复支付单。只有确认执行器调用写入口，模型工具不暴露确认、付款完成或任意 URL/SQL/shell。

## 身份、cookie 与 CSRF

- Gateway 先移除客户端伪造的内部 token、ops token、用户委托、用户/管理员已验标记及管理员 ID/角色/权限/签名头。AI 前缀随后由 Python 逐请求认证，避免旧 header 优先规则阻挡访客或决定 AI 主体；普通 Java 交易/管理接口仍走原登录门禁。已通过内部 token 认证的 `/internal/**` 保留合法服务委托头。
- IdentityBridge 仅转发对应的 `token` 或 `adminToken` cookie，不接受客户端主体/权限字段或同名登录 header 替代 cookie。重复目标 cookie 或访客 cookie 拒绝；已有但无效的登录 cookie 返回 401，不能降为访客。
- Java 用户会话查本项目 Redis 后再确认用户存在且启用；商家查 Redis 会话版本，再由 Java 当前管理员记录复核启用状态、版本和权限。`sessionId` 为 `SHA-256(realm + ':' + token)`，不返回 token、邮箱或密码，也不调用会轮换 token 的 `autoLogin`。
- 用户权限固定 `shopping:read/orders:read/orders:write`；访客只有 `shopping:read`。商家返回 Java 当前 `admin:manage/admin:legacy/analytics:read/analytics:export/audit:read` 的实际子集，只读指标权限不授予管理写操作。
- 无用户 cookie 时可签发 30 天 `smartlect_visitor` cookie，使用独立 secret、HttpOnly、SameSite=Lax，HTTPS 时加 Secure。访客只有自身会话，不能读用户订单或创建交易提案。
- 写请求必须带命中 `SMARTLECT_ALLOWED_ORIGINS` 精确白名单的 `Origin` 和 `X-CSRF-Token`。CSRF 签名绑定 actor、主体类型、session 摘要及 1 小时有效期；换用户/会话后不能复用。客户端先 GET session，再带回 cookie、Origin 与 CSRF。
- 四个历史缺口 `latestBrowseProductId/browseHistoryIds/listUserCoupons/estimateSingleSkuOffers` 已使用 `DelegatedUserIdentity.requireAndMatch`：缺委托 401，body.userId 与委托不一致 403，实际查询使用委托身份；订单/明细还按 Java 资源归属复核。内部 token 不是用户授权。
- F1 采用 Java introspection，没有第二套管理员签名登录。保留的 `AdminAssertionSigner` 已取消内部 token 回退，未配置独立签名 secret 时不能签名。

## 严格参数与工具边界

Growth JSON 请求体和工具参数使用 Pydantic `strict=True,extra=forbid`：拒绝额外字段，不将布尔、字符串或浮点数量转换成整数。GET 推荐入口的数字来自 URL query，由 FastAPI 解析后校验，不能用 JSON 类型规则描述 URL 编码。消息 ID 长度 1–128，文本 1–8000，确认版本为正整数。提案的 `parameters` 再由对应工具 schema 校验；Java v2 同样拒绝未知字段及标量类型强制转换。

| 提案 | F1 参数约束 |
|---|---|
| `order` | `payMethod` 仅 `mock`（默认）；`addressId` 1–64 字符；`orderFrom` 为 0/1（默认 0）；`orderList` 1–20 项，每项 `productId` 1–64、`propertyValueIds` 1–256、整数 `buyCount` 1–999、可选 `remark` 最长 500；可选 `userCouponId` 最长 64。Java 最终数量上限及可售校验仍有效。 |
| `cancel` | `orderId` 1–64 字符，先查本人订单再生成提案。 |
| `refund` | `orderItemId` 1–64 字符；整数 `refundAmountCents` 为 0 至有符号 64 位整数上限；`reason` 最长 500。当前针对该明细全部剩余可退金额，预查和 Java 执行时均要求金额匹配，未增加任意部分金额退款接口。 |

注册工具为 `load_skill/request_handoff/search_knowledge/recommend_skus/search_skus/compare_skus/get_my_addresses/get_payment_status/get_conversation_memory/remember_preference/get_product_offer/get_my_orders/get_order_status/get_refund_status/propose_order/propose_cancel/propose_refund`，同时受 actor 权限和本次任务白名单限制。`shopping_advice` 开放 `recommend_skus` 与 `compare_skus`；`search_skus` 保留导购检索兼容入口。模型参数无主体、凭证或批准字段；Java 服务/路径由程序固定，委托来自 ActorContext。推荐最终逐 SKU 复验，商品合计 `totalStocks` 不作为可售依据。

`request_handoff` 是用户/访客本人会话的终止工具，仅接受转交说明及本轮知识引用；纯转交无需先检索或加载Skill。必须独占工具批次，混合交易/转交在任何动作前拒绝；原租约与主体在建单事务内复核，真实OPEN工单产生`command_accepted`回执后终止，不继续调用模型，也不表示人工已经接管。普通`finish_answer`不创建工单；无依据/冲突/模型失败的控制器升级另标`controller_safety/controller_fallback`，与`model_tool`区分。建单、工具回执和最终回答目前分属事务，崩溃后若已有工单，只返回原工单并取消续跑，标`recovered_existing_ticket`，不虚称丢失的回执已经完成；同一消息ID和请求指纹的HTTP重放可恢复原run，原调用计数保持；新消息及异参在会话锁内拒绝，恢复不会启动模型。人工接管撤销原租约，禁止迟到回答。

广告展示接口 `GET /api/assistant/ads/recommendations?limit=1..4` 只返回可投候选（真实SKU、价格/库存、活动/素材版本、推广标识）；无有效授权或可售候选返回空列表。它不创建触点。广告曝光请求可附 `expected_campaign_version/expected_creative_version`，服务端在写入前复核页面所见版本；曝光成功回执后才能提交点击/CPC，版本变化拒绝旧曝光。

工具回执通过严格Pydantic `ToolReceipt`校验，schema_version=`tool-receipt-v1`，data为对应工具的结构化观测；记录校验后参数、回执、时间、evidence ID；查询成功与业务终态分开。`get_refund_status` 只有非空且全部为 Java `COMPLETED` 才标记 `business_completed`。网络超时/连接错误为 unknown；重放先读取已存回执，不重复完成过的工具。当前 `resource_version` 可为 null，不宣称所有事实都具有资源版本。

## 报价、确认与恢复

Java 报价绑定主体、规范化购买参数、选中 SKU/数量/明细金额、最终总额以及收件人/电话/地址内容摘要；同一 addressId 下地址内容变化也需重确认。优惠预估和执行锁券复用计价逻辑。建单在最终优惠和库存锁检查之后、订单/付款意图持久化之前重验报价；参数、金额、SKU、数量、地址或有效期不匹配返回 `RECONFIRM_REQUIRED`，相关锁券/交易变更整体回滚。报价不永久锁价、不预占库存。

Growth 保存原参数和 `parameters_hash/proposal_hash/quote_id/quote_total_cents/expires_at/action_id/idempotency_key`；确认接口不能替换金额/SKU/地址。首次确认使用所见提案 `version`，同一决定重试继续发送其 `decision_version` 与相同 `approved`，不能把执行过程中递增的新 `version` 当成新批准。

AgentRun 状态为 `CREATED/RUNNING/WAIT_USER/WAIT_OUTCOME/COMPLETED/FAILED/CANCELLED`；Proposal 使用 `PROPOSED/CONFIRMED/EXECUTING/UNKNOWN/SUCCEEDED/FAILED/REJECTED/EXPIRED`。MySQL 唯一键、版本和会话租约限制并发；每个运行首次领取后有 90 秒期限，HTTP 确认执行租约 30 秒。

每次非终态 confirm HTTP 调用创建新的有界运行，原提案/action/idempotency key 保持不变；重启后不复用过期 AgentRun。EXECUTING/UNKNOWN 先查 Java 原命令回执，退款保留完整确认参数。查询失败保持 UNKNOWN；只有未找到已提交原命令记录时，才使用同一个 key 重送原参数。新 run 不是新交易，也不能重置后续经营授权累计预算。

Java 幂等恢复先于报价过期/消费检查，已完成请求返回原支付单，参数指纹变化拒绝。Growth 终态重试返回原提案。刷新、GET 查询和 SSE 重连不触发交易。SSE 事件类型为 `message_delta/tool_started/tool_result/proposal_required/operation_pending/completed/error`，携带运行、会话和序号；F2保存工具进度和验证后的整段answer增量，不保存隐藏推理或流式输出尚未校验的JSON。

| Java `commandStatus` / 工具 `command_status` | 含义 |
|---|---|
| `command_accepted` | 已受理，不能据此声称付款/退款完成。 |
| `business_pending` | 业务处理中，继续查原回执。 |
| `business_completed` | 当前动作的 Java 终态已确认；建单完成仍可能 `paymentStatus=PENDING`，付款另行确认。 |
| `rejected` | 确定性拒绝；状态查询失败不代表原写入被拒绝。 |
| `unknown` | 结果未定，保留原 key 核对，不另造交易。 |

付款核对支付意图和订单同步；模拟渠道已付款但订单未同步仍 pending。取消核对订单及库存恢复。退款只有 Java `COMPLETED` 才完成，`PENDING_PAYMENT/PAYMENT_CONFIRMED/STOCK_PENDING` 等仍待处理。模拟支付 complete 由用户在页面单独点击，或验收驱动器显式扮演用户调用，不是模型工具，没有真实扣款。


## F2 新增接口与知识/记忆边界

| 方法与路径 | 已实现行为 |
|---|---|
| `GET /api/assistant/conversations` | 本人最近会话，隐藏内部付款专用会话。 |
| `GET /api/assistant/proposals/{id}/display` | 先验原提案归属，再由Java按原目标返回已购商品/规格；不改原确认参数或金额。 |
| `GET /api/assistant/payments/{id}` | 本人支付意图与订单同步状态；不是模型批准。 |
| `POST /api/assistant/payments/{id}/complete` | `{expected_amount_cents}`；登录＋同源CSRF，匹配实际金额，持久原提案/key后走F1执行/恢复，仅模拟渠道。 |
| `GET /api/assistant/preferences` | 本人有效偏好及source/evidence/期限/版本。 |
| `PUT /api/assistant/preferences/{key}` | `{value}` 显式更正；只允许用途、预算、likes/avoid/categories。 |
| `DELETE /api/assistant/preferences/{key}`、`DELETE /api/assistant/memory` | 删除/清理、撤销摘要引用、取消执行租约，保留交易审计。 |
| `POST /api/assistant/conversations/{id}/handoff` | `{reason}` 持久人工工单并取消自动运行；人工期拒绝回复及新确认执行。 |
| `GET /api/assistant/knowledge/{doc}/{version}` | 返回当前可见发布原文；ACL/有效期/撤回不满足返回404，历史答案仍保留引用版本与摘录。 |
| `GET /admin-api/assistant/knowledge`、`POST .../knowledge` | 已认证管理员列版本/建草稿；草稿含source、ACL、商品/类目、有效期。 |
| `POST /admin-api/assistant/knowledge/parse?filename=...` | 原始MD/TXT/文本PDF字节；2MiB、40页、30万字符及解压上限；不接受任意URL，不执行OCR。 |
| `POST /admin-api/assistant/knowledge/{doc}/{version}/publish`、`.../withdraw` | `{}`；管理员＋CSRF，配置embedding时真实索引、版本化发布/撤回。同步索引≤40切片，HTTP尝试独立审计。 |
| `GET /admin-api/assistant/support`、`PATCH .../support/{ticket}` | 管理员列工单，`{action,version,reply?}`接管/回复/结束；CAS版本控制。管理UI留待F4/F6。 |

检索先筛ACL/状态/时效，再BM25；真实embedding模型/维度/索引版本匹配才启用稠密RRF。结果保留doc/version/chunk/checksum与行/字符定位。回答入库与引用当前有效性在同一事务校验；撤回并发不会生成新的过期引用答案。可疑指令或知识冲突立即停止后续工具并转人工。

偏好推断必须引用当前本人消息原文，最多30天，不能覆盖显式修改或删除墓碑；价格和交易状态永不来自偏好。最近8轮与摘要纳入12k保守上下文预算，工具调用/结果成对保留。每轮6实际模型请求、10工具、2检索，原90秒deadline跨恢复保持；重试、embedding、格式修复均计数。详见[agent-design.md](agent-design.md)、[model-provider.md](model-provider.md)。

## F3 推荐、触点与可信范围（源码已实现，联验待完成）

实际路由位于 [app.py](../growth/src/smartlect/app.py)，全部公共写入口沿用身份＋同源 CSRF。相较 HANDOFF 的拟议路径，已统一到 `/api/assistant` 前缀，未另开 `/api/traffic/touches` 或任意来源写入入口。

| 方法与路径 | 输入与行为 |
|---|---|
| `POST /api/assistant/traffic/landing` | `{entry_id}`，1–64 字符；只生成 `NATURAL_VISIT/NATURAL`，身份、scope、发生时间和 touch ID 来自服务端。同一主体/scope/entry 幂等。 |
| `POST /api/assistant/traffic/bind` | `{}`，登录用户＋当前签名访客 cookie；返回 `bound/conversation_ids/assignment_conflict`。没有访客凭据时 `bound=false`；已绑定其他账号或 scope 时 409 并清除该访客 cookie。 |
| `GET /api/assistant/recommendations` | query 参数 `query`（≤200）、`max_price_cents`（0–100000000，可省略）、`category_id`（1–64，可省略）、`limit`（1–8，默认4）。返回持久 `recommendation_id/items/assignment/strategy_version/algorithm_version/ranking_mode/diagnostics`；`algorithm_version` 为排序器内容哈希。treatment 走 `semantic_rerank`，失败回落规则排序，不 500。生成列表不等于已曝光。 |
| `POST /api/assistant/recommendations/{id}/exposures` | `{positions:[1,…]}`，1–8 个位置，每项1–8；核对本人/绑定访客、scope、24小时内原列表后生成 `REC_IMPRESSION`。 |
| `POST /api/assistant/recommendations/{id}/clicks` | `{position}`，1–8；同上核验后生成 `REC_CLICK`。原列表决定 product/SKU/assignment/策略，客户端不能替换。 |
| `POST /internal/attribution/validateBatch` | 内部 token；`{userId,items:[{requestId,productId,skuKey?,position}]}`，1–100项、位置1–20；返回 Java `ResponseVO`。只返回当前24小时内同 scope、可信归属、匹配 SKU 的有效推荐点击，缺 `skuKey` 的旧商品级载体返回空。 |
| `GET /admin-api/assistant/attribution?payOrderId=...` | Java 管理员身份＋`admin:legacy`；按当前 scope 返回归因类别/计算状态的金额汇总和最多1000条事件、`events_truncated`。广告与推荐维度不可相加，尚无广告费用/ROAS报表。 |

[attribution.py](../growth/src/smartlect/attribution.py) 从服务端 `execution_resource` 解析已注册用户的 scope；未注册用户和访客使用 `store`。场景 scope 的商品必须在 include 白名单内，`store` 也排除归属其他 scope 的商品；空白名单表示无可用商品，缺少/非法范围拒绝。推荐候选、最终复验，以及共享工具的 `get_product_offer/propose_order` 都检查该范围。用户请求和模型参数不能指定 scope；本地 `register_scope` 没有公共 HTTP 路由。

五路召回均由Growth在Java查询前注入 `productIds/excludeProductIds`：scope.include为None时省略 `productIds`，空数组严格返回空；exclude为scope排除与本次 `excluded_product_ids` 的并集。两个名单各最多5000个非空商品ID（每项≤64字符），不接受显式null；Growth合并后超限返回422。名单在Java SQL的WHERE中先过滤再LIMIT，不能先截断其他分支商品再靠Growth过滤补救。返回后仍再次核对scope和具体SKU硬约束。

| Java 内部只读 POST 路径 | 召回合同 |
|---|---|
| `/internal/product/commerce/searchOnSale` | 内容/类目/新品三路使用；保留 `keyword/categoryId/limit` 并增加上述名单，limit沿原逻辑限制1–50。 |
| `/internal/order/commerce/coPurchaseProductIds` | `{productId,limit?,productIds?,excludeProductIds?}`；scope先于LIMIT筛共购结果，limit保留默认5、限制1–20的兼容逻辑。 |
| `/internal/order/commerce/popularProducts` | `{limit?,productIds?,excludeProductIds?}`，limit严格整数1–20、默认20；`ResponseVO.data=[{productId,paidUnits,basis,observedAt}]`，`paidUnits`为整数件数，`basis=confirmed_payment_units_excluding_refunds`，`observedAt`为UTC时间。订单接口不接受类目作为筛选条件，显式 `category_id` 仍由推荐最终SKU复验执行。 |

上述接口要求内部服务认证，定义见 [OrderCommerceInternalController.java](../backend/smartlect-order/app/src/main/java/com/smartlect/controller/internal/OrderCommerceInternalController.java) 和 [ProductCommerceInternalController.java](../backend/smartlect-product/app/src/main/java/com/smartlect/controller/internal/ProductCommerceInternalController.java)。热门依据是历史已确认付款件数，包含0元付款及后来退款的订单；它不是净销量，也不再使用商品 `totalSale` 作为付款热门证据。推荐卡保留 `popularity_evidence={paidUnits,basis,observedAt}`；缺少或无效付款证据为null、没有销售理由。这些读取和排序不改变Java计价、库存、报价绑定、支付或退款合同。

[auth.py](../growth/src/smartlect/auth.py) 只从当前已验签 cookie 提取 visitor ID。绑定不接受 body 中的 visitor/user ID；同一访客不能转移账号或 scope。每次持当前双方凭据绑定记录 `bound_at` 水位，仅纳入发生/创建时间不晚于该水位的访客触点/推荐列表；随后匿名新增事实需再次可信绑定才能纳入。绑定迁移同 scope 访客会话归属并撤销旧运行租约，原访客不再能读该会话；跨设备不做概率拼接。当前浏览器沿用访客 assignment；已有账号与其他浏览器分组冲突保留原记录并标记 `assignment_conflict`，不覆盖历史分组。

触点按 `recommendation_id + position + kind` 去重，重复回调不制造第二次点击；相同幂等身份但来源参数/元数据/指纹变化返回409。列表过期返回410，越权/不存在返回404。[traffic.ts](../web/user/src/api/traffic.ts) 每次页面加载生成一个 entry；[AgentProductList.vue](../web/user/src/components/agent/AgentProductList.vue) 在可见页面中卡片至少50%进入视口才报曝光，用户点击才报点击。生成答案、刷新会话或仅生成列表都不算曝光。

## F3 冻结上下文与独立归因

确认建单前 Growth 以持久 `action_id` 为 context key，最多等待0.5秒冻结不可变快照：本人及截至绑定水位的访客主体、近7天触点 ID/指纹、scope、captured/expires 时间；最多1000触点，超限或失败放弃可选来源。相同 key 永远取回同一快照，不在重试时纳入新点击或延长有效期。

凭据为 `base64url(canonical_JSON，无padding) + '.' + lowercase_hex_HMAC_SHA256`；HMAC 输入是 `smartlect-attribution-v1:` 加编码后的 payload，使用独立 `SMARTLECT_ATTRIBUTION_SECRET`，不回退内部认证 key。payload 严格仅含 `v=1/context_id/snapshot_version=1/snapshot_hash/user_id/execution_scope_id/issued_at/expires_at`，时间为 UTC epoch 秒，有效期300秒。访客绑定和触点集合保存在快照中，由 `snapshot_hash` 绑定，不把可修改 campaign 或 visitor 字段交给客户端。

[OrderAttributionService.java](../backend/smartlect-order/app/src/main/java/com/smartlect/biz/OrderAttributionService.java) 本地验签、拒绝重复/额外 JSON 字段和错误类型，核对下单用户以及 `issued_at ≤ orderCreatedAt < expires_at`。建单事务在幂等接纳新订单后通过主键唯一的普通 INSERT 冻结 `order_attribution_context`；不调用 Growth HTTP、不等待模型。缺失/非法/过期凭据或独立 key 不可用均保存 `UNKNOWN_CONTEXT`，合法交易继续。该可选凭据不进入购买意图指纹；重放不能改写既有订单来源。

归因规则字段为内容哈希（窗口与“广告必须匹配商品或 SKU”写入配置，默认 7 天广告 / 24 小时推荐），只使用订单已冻结引用集合内且指纹复核通过的事实：

- 广告取窗口内最后一次匹配该商品或 SKU 的 `AD_CLICK`，同时间按 touch ID 排序；匹配可信主体与稳定 scope，可以跨会话/round/run，不再把广告 A 记到商品 B。
- 推荐独立取窗口内同 product 和 SKU 的最后有效 `REC_CLICK`；曝光仅记录 `recommendation_assist_id`。迟付款仍用原订单时间；退款继承原已付款明细归因，不查退款时新点击。
- 有广告为 `AD_ATTRIBUTED`；无广告但存在可信来访记录为 `NATURAL_VERIFIED`；只有空快照或推荐互动不能证明自然，仍是 `UNKNOWN_CONTEXT`。v1 付款为 `LEGACY_UNKNOWN`，退款继承付款类别。`traffic_channel` 保留最近来访渠道，可与早先广告点击同时存在；未知不得并入自然。
- 类别与 `PENDING/FINAL` 计算状态分开。有已验证 context 引用但快照或触点尚未到齐为PENDING；晚到事实仅可补齐原冻结集合。快照哈希、触点实际内容、用户或 scope 不符为未知，不能以同用户/窗口内的新点击补归因。

## 账本兼容与 F4 待实施范围

[events.py](../growth/src/smartlect/events.py) 同时接受批次 `schema_version=1/2`。Java 提交事件经事务 Outbox 发往 `smartlect.commerce.outcome.exchange`，路由 `smartlect.commerce.outcome`，队列 `smartlect.growth.commerce.queue`；Growth 同一事务提交事实、异常、幂等、金额及归因投影后才 ACK。PAYMENT 计明细实付，REFUND 只回冲 `COMPLETED` 退款（可为0分）；VIEW/REPEAT_PURCHASE 等不加收入，转化按支付单去重。金额仍用 BigDecimal/Decimal 和整数分；乱序退款先待定再对账。

新 Java PAYMENT/REFUND 的 v2 `payload.attribution` 携带 `contextStatus/contextId/snapshotVersion/snapshotHash/executionScopeId/orderCreatedAt`；无可信来源的可选元数据不会阻断合法金额入账。新增事实/投影存在侧表；历史 v1 的 `raw_json/fingerprint` 不重写，未知来源不混入已归因金额。必须先部署支持v1/v2的消费者，再升级v2生产者；具体步骤见 [runtime.md](runtime.md)。

Java 已落库浏览通过事务 Outbox 生成 v2 VIEW，事件 ID 按用户/商品/原生产时间稳定生成；缺少原时间的旧浏览消息只更新历史，不凭接收时间补造 VIEW。Java VIEW payload 默认声明 `store`；Growth 接收v2非金额事实时按可信 `event.userId → execution_resource` 解析 scope（无映射为store），保存到 `commerce_attribution_meta.execution_scope_id`，元数据保留 `scopeSource/producerDeclaredScope`。按分支统计应使用服务端scope列，不信任生产者默认声明，也不修改原始事件。

F3 广告点击只允许内部 `ads_executor` 或明确 `f3_fixture` 来源，没有公共广告点击写入口。**F4 有状态活动、授权启用/恢复、CPC扣费、并发预算与已观察售罄保护尚未交付**；合成归因触点不是实际投放成绩。净成交ROAS/CPO/CAC及经营收益对照待该阶段提供真实可核对的模拟费用后实现，不预设调整一定增收。

## 已存档证据与当前门禁

F1 检查点：25 reactor、349 项 Java 单元测试无失败/错误/跳过；6 项状态 MySQL 检查和 1 项 HTTP＋mock Java 检查通过。真实 [`scripts/check_f1.py`](../scripts/check_f1.py) 经本项目 Gateway/Java/MySQL/worker 验证提案、确认、变更金额拒绝、API 实际重启、SSE 回放和付款退款对账：1000 分实付、1000 分确认退款、净额 0、库存 5→5。证据见 [`f1-live-confirmation.json`](../artifacts/f1-live-confirmation.json)，标记 `rule-fallback`、`live_model_called=false`。

原 purchase_stockout 本轮11项通过；Java OrderMoneyPersistenceIT 4项通过；AMQP实际重投及worker重启通过，26条事实与金额不变；原16条raw_json/fingerprint保持。最终结果见 `artifacts/f1-validation.json`，没有重用历史支付/共购测试成绩。F1 不包含真实模型能力、RAG 引用质量、Vue 接入或经营收益验收。

以上为F1当时运行记录；F2真实模型与Java确认纵切见 [agent-design.md](agent-design.md)。F3另有当前版本的独立运行与合同测试，记录于 [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md)。

F3实测见 [f3-validation.json](../artifacts/f3-validation.json)：109项Python（含44项MySQL）、最终Java范围/付款SQL、真实Gateway两条归因链、真实模型重排及浏览器曝光/点击。此前“仍须验收”的条目已在实施状态记录；F4–F7仍待实施，专用支付失败尝试事实须在F5观察前补齐。


## F4 当前投放接口

SQL0007与当前API合同见 [ads-contract.md](ads-contract.md)。此节替代上文历史“F4尚无源码”描述；验收状态单独见 IMPLEMENTATION_STATUS.md。

## F6补充

推荐请求增加可选`product_id`（HTTP列表与模型共用服务），仅将候选进一步限制为该商品与服务端
授权范围的交集；所有Java召回和最终SKU校验均沿此范围。商品ID不是名称/规格的required_terms，
未知类目不得猜测。具体Sku与报价/确认仍由Java权威校验。

Shopping使用原生`finish_answer`输出通道及`tool_choice=required`，继续校验引用、SKU和状态，
不新增业务执行工具或Agent。商品级介绍只给必要字段，不把聚合库存或空SKU库存当作可售规格。
缺少明确功能资料时，只能说明预算/可售等已核对条件，不能把这些事实写成用途适配保证。

人工工单的原会话/引用/提案详情见[support-contract.md](support-contract.md)，有界重置和旧消息
隔离见[reset-contract.md](reset-contract.md)，非金融scope与独立推荐指标见[merchant-contract.md](merchant-contract.md)。
