# ADR-0006: 移除 Seata，统一为本地事务 + Outbox 最终一致

日期：2026-10-04
状态：已接受（2026-10 收敛重构）

## 背景

下单链路此前同时存在两套回滚机制：`@GlobalTransactional`（Seata AT，覆盖 order/coupon 两库）与显式补偿（库存幂等回补、券解锁、远程补偿台账）。两者叠加导致真正的回滚边界无法推理——Seata 的全局回滚会连带回滚 coupon 侧 `deductStock`，而代码里同一失败路径又手写 `releaseRushCouponReserve`（内含 addStock 回补）做同样的事。

## 决定

移除 Seata 全套（server/undo_log/pom/yml/注解），事务策略收敛为一条主线：

- **单库原子性**：订单+明细+物流+幂等账本在一个本地事务。
- **跨服务一致性**：库存/券用**条件更新 + 幂等键 + 失败显式回补**（`restoreOrderStock` / `releaseRushCouponReserve`，已有远程补偿台账兜底）。
- **跨服务事件**：统一走本地消息表 Outbox（`TransactionalMqSender` + 租约重试 + 补偿审查表）。
- **库存一步化**：删除「先 lockAndVerify 后扣减」两阶段（FOR UPDATE 预检存在"只锁未扣"中间态），直接条件 UPDATE 扣减——失败即库存不足上抛，无中间态可悬挂。

## 后果

- 少一个中间件（seata-server 容器、5 张全局表、每库 undo_log）。
- 事务叙事单一可讲：「不超卖=条件更新；跨服务=Outbox+幂等消费+对账」——正是行业主流（mall/lilishop 系）做法。
- 秒杀链路经核验：`releaseRushCouponReserve` → `releaseStockAfterDbRefund` 已含 DB 库存回补（addStock 带上限保护），Seata 删除后补偿自洽，无需新增代码。
