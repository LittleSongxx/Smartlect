# 2026-10-05 改动索引

本日主题：Agent 架构评审落地的优化改造（P0–P3 全量）。背景：同日完成 AI Agent 部分的全面架构评估（runtime/多智能体/入口设计/行业对标/残留排查）后，按评审建议实施全部优化项；守卫链按用户决策走零行为变更的结构化治理，checkpointer 保留机制仅修 env 写入。

| 功能点 | 状态 |
| --- | --- |
| [子智能体预算审计修复.md](子智能体预算审计修复.md) | 已完成（dispatch 14/14 绿） |
| [demo死分支与ledger文档收尾.md](demo死分支与ledger文档收尾.md) | 已完成（`make demo` 全栈回归未跑） |
| [评测manifest重物出库.md](评测manifest重物出库.md) | 已完成（12 个 manifest 出库，本地保留） |
| [postgres-env门控.md](postgres-env门控.md) | 已完成（同日决策变更，被下项取代） |
| [checkpointer移除.md](checkpointer移除.md) | 已完成（决策变更：彻底移除；无 PG 依赖环境 292 + MySQL 63 真机回归绿） |
| [死模块删除与文档数字修正.md](死模块删除与文档数字修正.md) | 已完成 |
| [守卫链分层治理.md](守卫链分层治理.md) | 已完成（ADR-0013；逐条降级为后续评测驱动事项） |
| [退役命名与跨栈残留清理.md](退役命名与跨栈残留清理.md) | 已完成（三栈定向验证绿） |
| [架构图图集.md](架构图图集.md) | 已完成（13 张图四门通过；引用巡检 111 条 0 越界；站点自检含窄屏） |
| [三节点应用集群与性能压测.md](三节点应用集群与性能压测.md) | 已完成（中间件集群重建 + 应用多副本；**顺便修掉订单不下单的真 bug**；单机峰值 803.66 req/s、集群峰值 832.32 req/s；库存与限流已还原） |
| [悬空调用清理与Flyway校验和修复.md](悬空调用清理与Flyway校验和修复.md) | 已完成（**发现并修复 V3 迁移注释导致的重启即失败，影响全部存量环境**；product-projection 悬空调用链整体退役；12 进程重启 + 端到端冒烟通过） |

验证汇总（本机，2026-10-05）：assistant 非 MySQL 套件 292 用例 OK（64 skip，checkpointer 移除后于**无 psycopg 环境**复跑）、MySQL 套件 63 用例 OK（9 skip，含 `test_shopping_mysql` 改名点与无 checkpointer 图的真机回归）；`test_dispatch_subagent` 14/14（含 3 个新增预算用例）；web user vitest 79/79；Java order/coupon 模块编译成功、`OrderCommerceV2ControllerTest` 3/3。**后端全量 `mvn test` BUILD SUCCESS**（集群改造的 runtime.py/定时任务/映射修复后于本机复跑）；`runtime.py self-test` 与 `check_independence.py` 绿。全栈 `make demo`/`dev.sh check` 与 live 评测未执行（见各记录页「未完成项」）。

另：本日新增 [架构图图集.md](架构图图集.md)——用 archify 技能产出 13 张架构/流程/状态/数据流图与导航站（`架构图/`，含 ECS 三节点部署视图），逐图通过 showcase 四门；原始证据见 `eval/verification/atlas-20261005/`。

另：本日新增 [三节点应用集群与性能压测.md](三节点应用集群与性能压测.md)——在阿里云三台 ECS 上把中间件集群按当前配置重建、把应用层做成多副本（product/order/gateway ×3、user/cart ×2），并用 k6 测出极限吞吐与拐点。压测证据见 `eval/verification/cluster-loadtest-20261005/`。该记录**同时修掉一个线上真 bug**：`OrderItemMapper` 的批量插入 SQL 带硬编码尾逗号，下单从未成功过（`order_info` 长期 0 行），单元测试因 mock 掉 mapper 而全绿。

另：本日新增 [悬空调用清理与Flyway校验和修复.md](悬空调用清理与Flyway校验和修复.md)——承接架构评审做全仓「悬空调用/退役残留」专项排查。清理工作中重启服务时**暴露一个仓库级故障**：`14cbee9` 给已应用的 `V3__baseline.sql` 加了 2 行注释，Flyway 校验和不匹配，导致所有在 `14cbee9` 之前应用过 V3 的环境（含线上）重启即启动失败。处置是让文件回到与已应用版本逐字节一致（`diff -q` 对 `25ef508` 验证），把说明迁到同目录新建的 `README.md`，而不是改数据库校验和。同批退役 `product-projection` 悬空调用链（Java→Python 死端点 + 重试 + 补偿重放的自循环噪声）、三处死配置、29 个变量的旧栈 `.env.example`、孤儿构建产物；并记录一个**环境串扰陷阱**：MySQL 套件在载入 `run/runtime.env` 时会把 `SMARTLECT_MODEL_CALL_LIMIT=16` 注入 policy，使一条硬编码默认预算 6 的用例误报失败（显式钉回 6 即通过，非回归）。

本日全部改动基于 `7773906` 工作树，**未提交**（由作者审阅后决定提交切分）。
