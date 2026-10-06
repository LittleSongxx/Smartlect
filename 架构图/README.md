# Smartlect 架构图集

13 张 Archify 图（整体 + 各部分）加一个导航站：先用 [index.html](index.html) 看总览，
再从分组进入每个部分的说明页；每张图都能单独打开（缩放 / 主题 / 导出 PNG·SVG）。

## 目录结构

```
架构图/
├── index.html                  导航站：总览图 + 分组入口
├── pages/<name>.html           13 个说明页（图 + 职责 / 输入输出 / 机制 / 边界 + 代码证据锚点）
├── diagrams/<name>.html        13 张独立交互图（Archify 产出，showcase 四门通过）
├── diagrams/review-*/*.json     每次 finalize 的收据（含 spec/artifact 的 sha256）
├── candidates/<name>.json      图源（Archify 候选；再生成与再校验都从它出发）
├── assets/site.css             导航站样式
├── build-site.py               导航站生成器（证据清单从 candidates 派生，与图同源）
```

## 图集与校验状态

四门 = `validate` · `deliver`（含 showcase 工件检查）· `check --require-provenance` · `browser-check`（四档视口 × 双主题）。
下列 sha256 取自最后一次通过的 finalize 收据（`diagrams/review-*/<name>.finalize-summary.json`）：

| 图 | 类型 | 文件 | 验收 | spec sha256 | artifact sha256 | 路由建议 |
|---|---|---|---|---|---|---|
| 系统总览 | architecture | `diagrams/01-overview.html` | 四门通过 | `b836e522c2670ee5` | `4bd1e8792dee4ae5` | — |
| 部署拓扑 · 阿里云 ECS 三节点 | architecture | `diagrams/02-deploy.html` | 四门通过 | `58a909f40d16061f` | `4ab8df99d288c932` | inspect-route-readability |
| 前端结构 · 用户端与管理端 | architecture | `diagrams/03-web.html` | 四门通过 | `32bbf40cfdde7f6e` | `1b02d3e36d07aed6` | inspect-route-readability |
| Java 后端服务群 | architecture | `diagrams/04-backend.html` | 四门通过 | `19e3f18f9a6adfbe` | `893bc78616d97fac` | inspect-route-readability |
| 鉴权与路由链路 | sequence | `diagrams/05-auth-flow.html` | 四门通过 | `5c561128d5957745` | `9bded93d34b8fd71` | — |
| 下单主链 · 幂等到扣减补偿 | sequence | `diagrams/06-order-create.html` | 四门通过 | `44252909cd6994b2` | `37bb918945eee6ef` | — |
| 订单状态机 | lifecycle | `diagrams/07-order-lifecycle.html` | 四门通过 | `2f8a0f820684a8dc` | `88517d22a8382905` | inspect-route-readability |
| 支付成功与 Outbox 最终一致 | workflow | `diagrams/08-pay-outbox.html` | 四门通过 | `0c1bd6e46549e750` | `e4d52d45f7025579` | inspect-route-readability |
| 秒杀券 · Redis 预占到对账 | workflow | `diagrams/09-coupon-rush.html` | 四门通过 | `053cb4c460a25666` | `1e6637bf1ac81afb` | inspect-route-readability |
| 导购 Agent 有界 ReAct 循环 | workflow | `diagrams/10-agent-loop.html` | 四门通过 | `269a8a18e7070e31` | `2efd874725792574` | — |
| 知识发布与混合检索数据流 | dataflow | `diagrams/11-rag.html` | 四门通过 | `b68d23aecbe5e258` | `924bf9e19ac83255` | inspect-route-readability |
| 提案确认 · 从建议到 Java 落单 | sequence | `diagrams/12-proposal.html` | 四门通过 | `79cde93eb4fb84c4` | `f64e18a7bd5cefa8` | — |
| 子智能体派发（task_dispatch） | sequence | `diagrams/13-subagent.html` | 四门通过 | `8f6e194449788429` | `702b47d9af3642a6` | — |

路由建议是**咨询性信号**（不改变退出码）：`inspect-route-readability` 表示存在绕行或交叉，
建议在桌面视口做感知复核。本图集未做图像级感知评审（未请求），也不主张"视觉已验收"。

## 覆盖矩阵

| 部分 | 职责 | 图 | 主要证据 |
|---|---|---|---|
| 全系统 | 端到端边界与主链路 | 01 系统总览 | 网关路由表、前端代理、policy 预算常量、hybrid_search |
| 前端两端 | 双 API 面、导购工作区与 SSE | 03 前端结构 | vite 配置、http.ts、useAgentSession/useAgentFocus、Layout 菜单 |
| 网关与鉴权 | 两层校验、双账号、白名单、限流 | 05 鉴权与路由链路 | AuthGlobalFilter、application.yml 白名单、SaTokenInterceptorConfig |
| Java 服务群 | 8 服务 + BFF、独立库、内部接口 | 04 Java 后端服务群 | 根 pom、网关路由、各服务端口配置 |
| 下单链路 | 幂等、预占、扣减、补偿 | 06 下单主链 | OrderController、OrderInfoServiceImpl.createOrder、幂等账本、SkuStockMapper |
| 订单状态 | 9 状态全部合法流转 | 07 订单状态机 | OrderStatusEnum、OrderStateMachine 迁移表 |
| 支付与一致性 | pay→order 事件、Outbox、补偿 | 08 支付与 Outbox | PayChannel4Mock、TransactionalMqSender、OutboxDispatchTask、补偿台账 |
| 秒杀券 | Redis 预占 + DB 条件扣减 + 对账 | 09 秒杀券 | CouponRushRateLimitService、CouponRushRedisComponent、CouponRushOrderServiceImpl |
| 导购 Agent | 有界 ReAct、工具、守卫、预算 | 10 导购循环、13 子智能体派发 | policy.py、session.py、tools.py、dispatch.py、profiles.py |
| 提议与成交 | 人点确认 → Java 落单 → 支付 | 12 提案确认 | state.py、app.py（confirm/execute_proposal）、commerce.py |
| 检索与知识 | 发布门 + 混检 + 引用契约 | 11 RAG 数据流 | knowledge.py、hybrid_search.py、indexing.py |
| 部署与运维 | 阿里云三节点、网关 LB、中间件集群 | 02 部署拓扑 | ha-cluster.md、deploy/nginx.smartlect.conf、CI workflow；集群编排见下方口径说明 |

未被单独成图的部分（有证据缺失或属于上述部件的从属关系）：账号/地址与 RBAC 细节、商品目录的确定性排序、
管理端运营工具页、评测资产（`evals/`、`eval/verification/`）。它们分别在 04/03 图内以卡片或说明页覆盖入口，
但没有独立的图。

## 证据口径（重要）

- 库标识：`https://github.com/LittleSongxx/Smartlect`，提交 `77739061b59ce2854183e6d261057aa8113de8da`。
- 图内 `sources` 与说明页的"代码溯源"清单由 Archify 在提交字节上校验（路径存在、行号在范围内）；
  说明页清单直接从 `candidates/*.json` 派生，两者同源。全部引用做过一次脚本巡检（HEAD 字节逐条核对）。
- 工作区当前有未提交改动。因此：
  - 涉及**尚未提交**的事实（三节点部署编排 `deploy/cluster/`、checkpointer 移除等），部署页在正文里单独标注，
    图内引用只锚定 HEAD 已提交的字节（`docs/prod-hardening/ha-cluster.md`、`deploy/nginx.smartlect.conf`、CI workflow）。
  - 图的描述口径是"当前工作区形态"，凡与 HEAD 不一致处以上述标注为准，不把未提交字节当作已提交证据。
- 四门通过 ≠ 线上正确：本任务没有验证真实外部链路（线上服务、模型供应商、生产流量）。

## 再生成 / 再校验

```bash
export ARCHIFY_CHROME="$HOME/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"   # 本机 Chrome/Chromium 路径
node "$HOME/.zcode/skills/archify/bin/archify.mjs" finalize <type> \
  架构图/candidates/<name>.json 架构图/diagrams/<name>.html \
  --repo-root . --quality showcase --json --out-dir 架构图/diagrams/review-<n>
python3 架构图/build-site.py     # 重新生成 index.html 与说明页
```

改动候选后请用新的 `--out-dir review-<n>`（旧目录已有浏览器证据，不要覆盖）；
`<type>` 取 architecture / sequence / workflow / dataflow / lifecycle，与候选里的 `diagram_type` 一致。

## 已知限制

1. 07 订单状态机有 4 处路由交叉、02/03/04/08/09/11 有少量绕行——均为咨询性信号，未再迭代布局；
   已在各图收据 `visualReviewRecommendation` 中留档。
2. 部署图的部分事实来自工作区未提交编排，HEAD 中尚无对应文件（见上"证据口径"）。
3. 未做感知评审（`visual-check` 未请求），导航站的浏览器自检为截图目视 + 链接存在性检查。
4. 图集与 `docs/assets/architecture.png` 等既有示意图并存：既有图是产品向的概览图，本图集是工程向的可交互版本。
