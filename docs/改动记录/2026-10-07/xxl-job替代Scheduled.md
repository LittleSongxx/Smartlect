# xxl-job 替代 @Scheduled 自研锁调度（批次三）

日期：2026-10-07 ｜ 状态：已完成，全仓 BUILD SUCCESS

## 需求

对标主流（中小规模 90% 团队选 xxl-job），替代 @Scheduled + Redis setIfAbsent 自研锁。
控制台统一管理任务、失败重试、告警、手动触发，替代代码级调度开关。

## 具体变更

### 基础设施

1. `deploy/sql/16-xxljob.sql`（v2.5.0 官方 8 表，去建库改 `USE smartlect_xxljob`）
2. `deploy/mysql-init.sh` 加 `xxljob` 域与账号（GRANT ALL）
3. `deploy/compose.yaml` 新增 `xuxueli/xxl-job-admin:2.5.0` 容器
   （`smartlect_xxljob` 库 + accessToken 鉴权 + 18090 端口）
4. `scripts/runtime.py` PORTS/bootstrap/infra_up/infra_check 四处纳管

### Java 侧

5. `smartlect-common pom` 加 `xxl-job-core:2.5.0`
6. `smartlect-common.yml` 加 xxl.job 公共配置
   （admin 地址/appname 按服务名自动派生/executor 端口/日志路径）
7. `XxlJobConfig`（common config）：XxlJobSpringExecutor bean
8. **九个 @Scheduled 任务迁移为 @XxlJob handler**：

| 服务 | 任务 | @XxlJob value | 原调度 |
|---|---|---|---|
| common | OutboxDispatchTask | outboxDispatch | 5s |
| common | MqCompensationAutoReplayTask | mqCompensationReplay | 60s |
| admin | AutoDataTask | autoDataTask | cron 0 0 1 |
| order | PayOrderTask | payOrderPoll | 5s |
| order | OrderAutoReceiptReconcileTask | orderAutoReceiptReconcile | 600s |
| order | RefundSagaService.reconcile | refundSagaReconcile | 30s |
| user | ImageModerationCleanupTask | imageModerationCleanup | cron 0 15 * |
| user | UserTempBanReconcileTask | userTempBanReconcile | 60s |
| coupon | CouponRushReconcileTask | couponRushReconcile | cron 0 */10 |

## 验证

- xxl-job-admin 容器 healthy（18090 可访问）
- 8 张系统表正确导入 smartlect_xxljob 库
- 全仓 `mvn test` BUILD SUCCESS（CouponRushReconcileTaskTest 已改断言 @XxlJob）

## 未完成项

- xxl-job 控制台首次部署需手动注册执行器与任务（admin 地址 + appname + cron）；
  可写 `scripts/xxljob_setup.py` 通过 OpenAPI 自动注册（后续补充）
- Redis setIfAbsent 锁代码暂保留（xxl-job 路由策略 FIRST 已保证单实例执行，
  锁作为纵深防御不删除；后续评估是否清理）

## 关联代码版本

基于批次一/二工作树。本批次文件：deploy/（compose+sql+mysql-init）、
scripts/runtime.py、smartlect-common（pom+yml+XxlJobConfig）、
九个任务类 @Scheduled → @XxlJob + CouponRushReconcileTaskTest
