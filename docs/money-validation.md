# P1 金额门禁验证

日期：2026-09-09。范围为 Smartlect `smartlect-order`；未修改原项目或使用原项目运行数据。未修改 pay/common，订单内部事实接口和请求幂等由主实施流程处理。

## 先在 Smartlect 复现

迁入 `handoff/probes/ShopMoneyContractProbeTest.java`，修改为 `com.smartlect` 包后，执行：

```bash
mvn -B -f backend/pom.xml -pl smartlect-order/app -am \
  -Dtest=ShopMoneyContractProbeTest -Dsurefire.failIfNoSpecifiedTests=false test
```

实际结果：2 项测试、2 项失败、0 错误。三条原价 100 的明细、订单实付 300，事件金额为 `[100.00, 66.67, 133.33]`；单条原价 100、订单实付 90，退款请求为 100。日志：`artifacts/local/money-baseline.log`。这些是本项目新执行结果。

## 修改

- `OrderInfoServiceImpl.recordPaymentOutcomes` 使用固定订单实付和累计原价权重分币，按明细 ID 排序。累计分摊为 `round(订单实付 × 累计原价 / 原价合计, 2)`，每条金额为与上一累计值的差，最后一条取未分配余额。累计舍入使 100 条原价 0.01、合计实付 0.49 时，最后一条不会被迫承担超过其原价的余额。缺失、负数、超过原价合计或不能精确到分的金额拒绝处理。
- `order_item.paid_amount` 在付款确认事务中持久化，尚未确认时为 NULL。专用 `recordPaidAmount` 只允许首次写入；已确认金额变化会报错。PAYMENT 和 REPEAT_PURCHASE 事件使用这份已确认的明细金额。
- `order_item.refunded_amount` 初始为 0，退款确认与明细状态转换在同一事务中写入。重复确认不再次累加；同一明细继续使用唯一退款请求和稳定退款编号。
- `RefundSagaTransactionService` 的现金退款额为 `paid_amount - refunded_amount`；没有有效实付记录时拒绝创建退款，不能回退到原价。零实付明细直接进入库存恢复阶段，实际现金渠道不被调用。首版保持整明细退款，不新增部分数量退款接口。
- `RefundReviewService` 的人工复核恢复校验同样使用剩余实付，同时保留原有数量、SKU、状态及异常金额漂移检查。新增折扣/已退款情况下审批正确余额的测试，原测试断言保留。
- `OrderInternalService` 的净成交金额与已退款金额改为汇总持久化的明细实付/已退额，避免对已退款明细继续按原价统计。两个 MyBatis 查询映射同步返回新金额字段。
- Flyway 增量列与 CHECK 约束可重复执行：实付不得为负或超过明细原价；未确认实付不能登记现金退款；退款累计不得为负或超过实付。没有按原价回填未知的历史实付。

## 实际通过的验证

```bash
mvn -B -f backend/pom.xml -pl smartlect-order/app -am test

mvn -B -f backend/pom.xml -pl smartlect-order/app -am \
  -Pintegration -Dit.test=OrderMoneyPersistenceIT \
  -Dfailsafe.failIfNoSpecifiedTests=false verify
```

首次金额单测结果：订单模块 113 项通过。增加折扣退款人工复核用例后，第二条命令实际完成 BUILD SUCCESS、退出码 0：订单模块 114 项单测及 3 项 MySQL 集成测试全部通过，0 失败、0 错误、0 跳过。

日志分别为 `artifacts/local/money-unit-tests.log` 和 `artifacts/local/money-mysql-tests.log`。主流程随后增加的其他订单测试和全 reactor 结果以 `IMPLEMENTATION_STATUS.md` 为准。

`ShopMoneyContractProbeTest` 保留原两项金额预期，补充多条极小金额、零原价、缺失实付拒绝退款、重复请求和退款统计检查。单明细退款探针的输入补充付款后持久化实付字段；该字段的真实写入和重新读取另由集成测试验证。

`OrderMoneyPersistenceIT` 创建独立 `mysql:8.4.11` Testcontainers 实例、数据库 `smartlect_money_it`，执行本项目真实 Flyway schema 和 MyBatis mapper：

1. 原价 100、实付 90，经付款金额写入和提交后，在新 SQL session 读取实付 90；退款请求 90，重复申请和确认后累计仍为 90，库存恢复消息只登记一次。
2. 零实付明细退款额为 0，实际调用退款 Saga 后验证不调用现金渠道，仍登记库存恢复消息。
3. 付款事务回滚后实付仍为 NULL，退款被拒绝；MySQL 拒绝未确认付款时登记退款以及超实付退款。

测试结束后该实例由 Testcontainers 回收。外部现金渠道和库存消息发送使用 mock；此处证明的是真实数据库金额持久化及事务/幂等契约，完整 HTTP 下单、mock 支付通知和真实库存恢复对账由主流程继续执行。
