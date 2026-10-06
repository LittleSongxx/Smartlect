# README 重写、架构图重绘与截图更新

日期：2026-10-07 ｜ 状态：已完成（截图取自本地实跑环境，功能链路已走通）

## 需求

参考仓库里另外两个项目的 README 写法（[NewsClaw](https://github.com/LittleSongxx/NewsClaw)、
[MindCart](https://github.com/LittleSongxx/MindCart)），全面重写 Smartlect 的 README；按当前真实情况重新绘制架构图；
重新到浏览器里截图，过程中确认对应功能正常；顺带重写 GitHub 仓库的 About。

## 参考到的写法（两个项目共同点）

- 开头：一句话定位 + 一句边界声明，紧跟 shields.io 扁平徽章，再一张整宽截图
- 正文：场景化小节（①②③）+ 配图，图下短句说明，不用折叠块
- 架构：Mermaid 流程图 + 文末指向 `docs/adr/`
- 后半段：技术栈分组表、项目结构、快速开始（含账号表）、验证入口、运维排查入口表、
  决策记录、**「这个仓库里没有的东西」**（主动划边界）
- 语调：工程化、口语化，强调「能本地跑通」，不吹不藏

## 具体变更

### 1. README 全面重写（`README.md`）

保留原有的诚实边界（模型可以建议、不能成交；支付是模拟的；演示账号权限在服务端裁剪），
按上述骨架重组，并补齐此前缺失的三块：

- **导购现场**独立成节：带引用作答、子智能体派发、提案待确认
- **运维与排查入口**表：站点/网关健康/调度中心/配置中心/指标/日志/MQ 补偿/Outbox 水位，
  附「服务起不来时的排查顺序」
- **这个仓库里没有的东西**：没有真实资金、没有公开超管密码、没有分布式事务框架、
  没有第二个 Agent、没把模型当事实源、已退役的四个管理端模块

技术栈表按真实组件更新：补 Canal（变更捕获）、xxl-job（调度）、Nacos（发现 + 配置中心）、
Caffeine+Redis 多级缓存；基础设施标明 9 个容器。

### 2. 架构图重绘（`docs/assets/architecture.png`）

按当前拓扑重画（HTML→浏览器渲染→PNG，2× 缩放）：

- 分层：浏览器双端 → nginx → Gateway(Sa-Token/Sentinel) → 应用层（Assistant + 9 个 Java 服务）→ 数据面 → 支撑面
- 支撑面显式画出 **Canal**（binlog→MQ→ES）、**xxl-job**（9 任务调度）、**Nacos**（发现 + 配置中心）、LiteLLM
- 底部两条主链路（一条浏览、一条导购）说明缓存层级与「价格库存回问 Java」
- README 另附等价 Mermaid 流程图，便于 GitHub 内直接渲染

### 3. 截图全部重拍（`docs/assets/screenshots/`）

旧图摄于 2026-09-18，且含已退役模块（广告投放、经营助手）的界面。本次用 Chromium 走真实交互重拍：

| 文件 | 场景 |
|---|---|
| `home.png` | 用户端首页 |
| `product-guide.png` | 商品页「问这件」导购浮层（范围钉在当前商品） |
| `cart.png` / `orders.png` | 加购结果 / 订单列表（含实付款与操作） |
| `product-sku.png` | 规格选择面板（选规格时才向库存服务取数） |
| `assistant.png` | 智能客服：带引用 [1] 的完整回答 + 反馈入口 |
| `checkout.png` | 结算页（地址、券、支付方式、付款明细） |
| `admin-product.png` | 管理端商品管理（检索过滤后） |
| `admin-order.png` | 管理端订单管理（买家信息隐藏） |
| `admin-knowledge.png` | 管理端知识库（草稿/发布分离、索引失败重试） |

清理了 11 张不再引用的旧图（含 browse/search/admin-ads/admin-merchant/admin-home 等），
`docs/assets/` 从 5.4 MB 降到 3.4 MB，且每张图都被 README 引用。

### 4. GitHub About 重写

原 description 与 topics 停留在已废弃的技术线（AgentScope、React/AG-UI、SQLite、长期记忆、
K=3 门禁），与当前仓库完全不符。改为：

- **Description**：AI 导购电商系统：Vue 3 双端商城 + 九个 Spring Cloud 微服务，店里的导购是
  LangGraph 有界 ReAct Agent——范围钉在当前商品、回答带引用、下单必须人点确认。ES+Qdrant 混检、
  Canal 同步商品索引、Outbox 最终一致，九容器 Docker Compose 一键起。演示 https://smartlect.cn
- **Homepage**：https://smartlect.cn
- **Topics**：`ai-agent` `langgraph` `rag` `vue3` `spring-cloud` `spring-boot` `java`
  `microservices` `shopping-mall` `ecommerce` `elasticsearch` `qdrant` `rabbitmq` `redis`
  `mysql` `nacos` `docker-compose` `portfolio`（替换全部旧标签）

## 验证方式与证据

截图不是摆拍：整个过程在本地实跑环境（12 个应用进程 + 9 个容器）里用 Chromium 走真实交互，
每一步收集 console 错误与请求失败，**全部为 0**。同时顺带跑通并确认了这几条链路：

1. **浏览**：首页 → 分类 → 商品详情（数据来自 Java 目录）
2. **导购**：商品页「问这件」浮层打开、智能客服提问「退换货政策」→ 得到带引用 [1] 的完整回答
3. **交易**：加购（规格弹层）→ 购物车 → 结算 → 提交订单（确认对话框）→ 模拟支付
   → 订单状态从「待付款」变「已付款,待发货」
4. **后台**：管理端 gallery 账号登录 → 商品检索、订单管理（看到刚支付的订单）、知识库

支付成功后订单状态自动同步，这条链路同时验证了 xxl-job 的 `payOrderPoll` 调度任务在跑
（该批任务此前从未执行过，见[部署前缺陷修复](部署前缺陷修复.md)）。

**没有编造任何界面状态**：截图里看到的数据都是真实交互产生的（购物车里的商品、订单号
`20261007044306504…`、实付款 ¥33.90）。此前截到的两处不理想画面（客服回复尚未生成、
管理端看板当日统计为 0）已通过「等回复完成再拍」和「该页不入镜」处理，未用修图掩盖。

## 未完成项

- 管理端看板页未入镜：当日销售额/订单为 0（统计任务 cron 在凌晨，且演示环境当天只有一笔订单），
  数据本身正确，只是作为展示素材信息量不足。
- `figures/smartlect-final-architecture.md` 引用同一张 `architecture.png`，图已换成新版，
  该文档的文字描述仍是旧架构，未同步。
- GitHub About 的 Topics 上限 20，本次用了 18 个，未收录 `sa-token`、`xxl-job` 等。

## 关联代码版本

本文件改动：`README.md`、`docs/assets/architecture.png`、`docs/assets/screenshots/*`（新增 11 张、
删除 11 张）；GitHub 仓库 About（description/homepage/topics，经 `gh` CLI 设置，不入仓库）。
未改动任何业务代码。
