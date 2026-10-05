# 2026-10-06 改动索引

本日主题：从节点扩容（2c8g → 4c8g）后的运行排查、缺陷修复与参数调优。承接 [2026-10-05](../2026-10-05/README.md) 的集群搭建与首次压测。

| 功能点 | 状态 |
| --- | --- |
| [扩容后排查与参数调优.md](扩容后排查与参数调优.md) | 排查 6 项（修 5）；后续 5 项全部实施；**postOrder 长耗时定位并修复（p95 6835→249ms）** |

## 本日修复的缺陷（按影响排序）

1. 副本节点开机不自愈（`wait-cluster` 前置依赖）
2. 死信恢复路径全废（`AopContext` → 自注入；投真实死信消息端到端验证通过）
3. Feign-在-事务反模式（全仓 4 处清零，根治连接池被长事务抽干）
4. 副本节点 JVM 参数停留在 2 核时代（`apply-sizing.sh` 按规格推导）
5. 压测脚本与接口契约不符（`loadProduct` 的 `pageNo`、`add2Cart` 的表单绑定）+ 判定口径漏业务错误
6. `defaultSku` 空 productId 刷日志；`runtime.py` 的 Seata 文案残留

## 验证汇总（2026-10-06 凌晨）

- 后端全量 `mvn test` **BUILD SUCCESS**；`runtime.py self-test` 与 `check_independence.py` 绿
- 死信路径：同一测试消息，修复前抛 AOP 异常 → 修复后成功处理且部署后失败计数为 0
- 交易闭环：补库存 + 单量封顶后**业务错误归零**
- 站点 200、门禁 12 进程 / 9 注册全绿；集群三组件健康
- 证据见 [eval/verification/cluster-tuning-20261006/](../../../eval/verification/cluster-tuning-20261006/)

另：postOrder 长耗时已定位到两个阻塞点并修复——① 发布确认占着请求线程（改异步试投）② node2 商品副本因 Redis 地址指向不存在的端口而全端点慢 90-240 倍。客户端 p95 6835ms → 249ms。
