# Smartlect 业务契约

更新：2026-10-04（收敛重构后）。Java 是价格、库存、订单、支付、退款的唯一权威；assistant 只调用受控 API、维护自身会话状态，不直接读写交易表。

## Java ↔ assistant 双向调用

### assistant → Java（SmartlectCommerceClient）

| 端点 | 用途 | 身份头 |
|---|---|---|
| `POST /internal/identity/introspect` | Cookie 内省（user / merchant 双 realm） | `X-Internal-Token` + cookie |
| `POST /internal/product/snapshotBatch` | 商品快照（含价格） | 同上 + `X-Smartlect-User-Id` |
| `POST /internal/stock/getBatch` | 实时库存查询 | 同上 |
| `POST /internal/order/commerce/v2/quote` | 下单报价 | 同上 + `Idempotency-Key` |
| `POST /internal/order/commerce/v2/createConfirmed` | 确认下单 | 同上 |
| `POST /internal/order/commerce/v2/executeAction` | 取消 / 退款执行 | 同上 |
| `POST /internal/order/commerce/v2/actionStatus` | 幂等核对 | 同上 |
| `POST /internal/order/commerce/*` | 订单/退款/支付状态查询 | 同上 |
| `POST /internal/pay/mock/complete` | 模拟支付完成 | 同上 |
| `POST /internal/pay/channel/getPayUrl` | 支付表单获取 | 同上 |

### Java → assistant

无。推荐/归因/worker 线已于 2026-10 退役（ADR-0008）。

## assistant 对外端点

### 用户面 `/api/assistant`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/session` | 当前 actor + CSRF token |
| GET | `/catalog/scope` | 商品可售范围 include/exclude |
| POST/GET | `/conversations[/{id}]` | 会话创建/列表/详情 |
| POST | `/conversations/{id}/messages` | 发消息（启动 Agent run） |
| POST | `/conversations/{id}/handoff` | 转人工工单 |
| POST | `/conversations/{id}/proposals` | 规则通道直接生成提案 |
| GET | `/proposals/{id}` · `/display` · POST `/confirm` | 提案读取/回显/确认 |
| GET | `/payments/{id}` · POST `/complete` | 支付状态/模拟完成 |
| GET/PUT/DELETE | `/preferences[/{key}]` | 偏好 CRUD |
| DELETE | `/memory` | 清除全部记忆 |
| GET | `/knowledge/{doc}/{ver}` | 已发布文档只读 |
| GET | `/runs/{id}` · `/runs/{id}/events` | Run 快照 / SSE 事件流 |

### 管理面 `/admin-api/assistant`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/session` · `/scopes` · POST `/scopes/select` | 商家身份/scope |
| CRUD | `/knowledge[/{doc}/{ver}[/publish|/withdraw]]` | 知识管理 |
| GET | `/knowledgeOps/summary` · `/knowledgeIndex/jobs/*` | 索引运维 |
| GET/POST | `/models/*` | 模型热切换 |
| CRUD | `/prompts/*` | 提示词版本管理 |
| GET | `/tools/catalog` · POST `/tools/invoke` | 工具调试 |
| GET | `/runs[/{id}]` | Run 审计浏览器 |
| GET/PATCH | `/support/*` | 工单管理 |

## 身份与鉴权

- **Java 侧**：Sa-Token 1.39 双账号体系（用户端 `StpUtil` + 管理端 `StpAdminLogic`），网关统一校验 + 服务端 `@SaCheckLogin` / `@SaCheckPermission`
- **assistant 侧**：Java Cookie 内省（`/internal/identity/introspect`）+ 访客 JWT + CSRF jti 一次性消费
- **内部 API**：`/internal/**` 统一 `X-Internal-Token` HMAC 校验（fail-closed），网关不路由此前缀
