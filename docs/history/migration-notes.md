# Smartlect 迁移决策

日期：2026-09-09。源码来自校验通过的三个冻结 ZIP；交接材料的版本、SHA-256 与许可证见 `handoff/manifest.json`。没有访问、修改或运行原三个项目，未复制其运行凭证、数据库或业务 JAR。

## Java

保留 common、gateway、admin、user、product、stock、cart、order、pay、coupon，共 25 个 Maven reactor 项目（含聚合/API 模块）。包、源码/测试/资源路径为 `com.smartlect`，根 group/artifact 为 `com.smartlect:smartlect`，版本 `0.1.0-SNAPSHOT`，应用类 `Smartlect*Application`。保留 Java 17 编译目标及来源框架版本。

更名同步覆盖 Feign、LoadBalancer 自动注册、MyBatis、SQL、Maven、服务发现、Redis、RabbitMQ 和推荐归因字段。保留通用业务类名及第三方协议名。旧来源许可证原样存于 `backend/LICENSE.md`。

旧 search 模块未迁入，common 的 ES starter 和根 Spring AI BOM 已移除。公共 RAG DTO/VO/enum、RAG 交换机/队列/重放分支、旧提示词资源及缓存、会话取消/consult/pending 缓存、仅客服使用的图片入口与旧 AI 权限已按调用关系删除。正常浏览、用户隐私业务处理、订单、库存、退款、通知、Outbox 和补偿逻辑保留。

网关移除旧 Agent HTTP/WebSocket 和 search 路由及其专用熔断/限流。普通业务路由、鉴权、管理员签名和交易限流保留。内部委托用户改为 `X-Smartlect-User-Id`，同一信任校验逻辑继续执行。

推荐归因和成交事件继续使用现有业务边界，改接 `smartlect.growth.*`。归因验证 URL 由公共配置统一读取 `SMARTLECT_GROWTH_BASE_URL`，避免购物车和订单使用不同地址。增长不可用不能阻断普通购物。

公共测试只移除专属于已删除 RAG 类型/向量服务的测试。RBAC 测试矩阵改为实际保留权限并保留拒绝/失效会话/any-of 断言。各业务模块具体删除清单、运营视图与测试变化见 `docs/java-pruning.md`。

## 数据和资源

不迁入来源的外部商品镜像导入脚本及预置交易演示种子：它们含外部资源路径、历史用户口令、预制交易/看板统计、search/RAG 写入和清库行为，不适合作为新闭环结果。仅保留静态类目定义；后续场景生成本项目独立合成用户、商品、SKU，再实际执行交易。

Compose project 为 `smartlect`，生成新库、网络、卷、用户、密码与端口；来源运行实例不可作为验证依赖。源码默认端口仅是候选，启动必须加载 `run/runtime.env` 中经冲突检测分配的端口。凭证仅保存在 Git 忽略的 `run/`。

`handoff/migrate_java.py` 及后续一次性裁剪脚本是可核对的迁移记录；常规构建、检查和运行不调用它们，也不使用解包目录。

Python 复用/裁剪及安装证据见 `docs/growth-migration.md`。各阶段完成与未完成情况以 `IMPLEMENTATION_STATUS.md` 为准。
