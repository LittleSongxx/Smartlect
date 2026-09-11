# Java P0 裁剪记录

日期：2026-09-09。范围：`smartlect-admin`、`smartlect-user`、`smartlect-product`，以及共同模块 `MiddlewareIT` 的运营视图依赖和断言。输入是本交接包冻结源码；未访问或运行原项目。

## 依调用关系删除

| 原功能 | 删除内容 | 原因与保留边界 |
|---|---|---|
| 管理端旧 AI 对话/客服/分析/学习 | AgentMessage 控制器、服务、实体、查询类；AgentLearningController；仅服务这些 HTTP 调用的 AdminRestClientConfig | 所有远端都指向旧 Agent。普通运营、发货设置、统计、订单延迟队列维护、管理员身份与审计保留 |
| 提示词编辑和 search 同步 | SettingController 的提示词四接口；ToolController 的 productData/ragData；SearchTool Feign 三件套 | 对应旧 prompt 缓存和未迁入的 search 服务。没有通过关闭启动检查保留空接口 |
| 商品 RAG 索引 | ProductRagIndex/Property/SkuVO；Feign/controller/support/fallback 的 getRagIndex；ProductInternalService 组装；ProductInfoServiceImpl 的 RAG MQ 投递和调用 | 商品保存、上下架、推荐标志、销量更新仍执行原数据库逻辑；价格、SKU、库存快照、目录查询与文本清洗保留 |
| 商品 DTO 的 Elasticsearch 绑定 | ProductInfoDTO ES 注解、es-settings.json、product-api 的 spring-data-elasticsearch 依赖 | DTO 保留普通商品字段；`getSearchIndex` 是不访问 ES 的商品事实投影，保留以复用文本清洗覆盖，不构成运行服务依赖 |
| 旧 AI 隐私工作流 | PrivacyAgentClient、UserPrivacyController、PrivacyConfirmRequest | 客户端请求明确限定 `scope=AI_DOMAIN_V1`，全部代理旧 Python 的任务/下载，并无本地用户数据清理。用户资料/地址删除、浏览历史清理、通知及评论审核清理保留 |
| 旧客服查询图像 | AgentImageAssetRequestDTO、VerifiedImageAssetDTO；内部验证/读取/留证接口；FileController 的 getAgentImage；上传 AGENT 场景及仅此场景的元数据、30 天保留/清理、ImageAssetStore 抽象 | 保留头像、评论上传、百度审核开关、频控、违规封禁、人工复核、隔离评论图片校验与清理。移除仅此场景的 SQL 字段/迁移和 mapper 方法 |
| 旧 Agent 通知桥 | NotifyPushPublisher 向 WS_MESSAGE_TOPIC_AGENT 的副本发布 | 普通站内通知持久化和原 WS_MESSAGE_TOPIC 广播继续保留 |
| 旧 AI 权限 seed | AI_OPERATOR、SUPPORT_AGENT 及其 ai:*、support:* 权限和绑定 | 对应代理业务已经删除；SUPER_ADMIN、DATA_ANALYST、AUDITOR、普通管理/统计/审计权限保留 |

## 保留的中性内部契约

- `ProductCommerceInternalController`：`/internal/product/commerce`，保留上架商品搜索、详情、权威 SKU offer 和已有事实读取。商品测试随类名/路由更名。
- `UserCommerceInternalController`：`/internal/user/commerce`，保留最近浏览商品和去重浏览历史，只裁去查询图片接口。
- 商品快照、SKU 价格、库存读取继续使用本项目 Java 的 mapper/Feign 边界。

## 运营视图

保留 `analytics_sales_daily`、`analytics_product_sales_daily`、`analytics_inventory_risk`、`analytics_fulfillment_after_sales_daily`。它们只依赖本项目 order/product/stock 域。

删除依赖旧 Agent 库的 `analytics_agent_quality_daily`、`analytics_tool_quality_daily`、`analytics_recommendation_funnel_daily`、`analytics_recommendation_quality_daily`、`analytics_offer_quality_daily` 和 `analytics_inventory_forecast`。增长效果视图待新的增长账本建立后按真实契约实现，当前不把旧表改名冒充新闭环。

`MiddlewareIT` 移除旧 Agent 数据库、七个模拟源表及相应 GRANT；保留并对齐四个普通视图创建及受限读者权限测试。MySQL 并发扣库/幂等、回滚 Outbox、Redis Lua、RabbitMQ 和八域 schema 首次/重复迁移检查保持存在。

## 测试变化与当前证据

- 删除 `AgentMessageServiceImplDataAnalystTest` 和 `AgentMessageControllerDataAnalystTest`：仅验证已删除的旧 Agent HTTP 代理功能；原管理模块没有独立普通运营测试被删除。
- 删除 `UserPrivacyControllerTest` 三项：只验证旧 AI 隐私任务代理的身份/口令/任务边界。原普通用户鉴权、地址/资料删除和数据清理不属于这三个测试。
- 原 `ProductAgentOfferConstraintTest` 更名为 `ProductCommerceOfferConstraintTest`，保留其 SKU 限制断言。
- 新增 `ImageModerationServiceImplTest`：头像成功上传、拒绝旧查询图像场景、评论疑似内容进入审核及原用户/订单归属、孤立评论重复清理只删除一次。
- 新增 `UserCommerceInternalControllerTest`：浏览事实按用户范围读取、去重后限量、无用户条件不查数据。
- 已运行 Python 标准库 XML 检查：三个模块的 26 个源码 XML 全部解析通过，图像 mapper 投影尾逗号检查通过。此检查不代表 SQL 已在 MySQL 执行。
- 静态扫描：三个模块源码（排除 application.yml 和 target）无旧 Agent/RAG/ES 运行依赖；HTTP `User-Agent` 为协议名，测试中的旧 `agent` 字符串只用于拒绝场景断言。
- 实际运行 `mvn -B -f backend/pom.xml -pl smartlect-user/app -am test`：BUILD SUCCESS、退出码 0；user 模块 33 项，0 失败、0 错误、1 跳过（未启用独立 RabbitMQ 集成环境）。两个新增测试通过。日志：`artifacts/local/java-user-tests.log`。此前首次完整构建暴露新增测试 mock 方法签名错误，已经修为 `censorImage(byte[])` 后重跑通过。
- `OrderGrowthRabbitIntegrationTest` 改用 SMARTLECT_RUN_RABBIT_INTEGRATION/SMARTLECT_RABBIT_*、本项目端口/vhost和随机专用资源；未执行该外部中间件测试，不把跳过视作通过。
- 完整 Maven clean verify 由主实施流程统一执行并写入 `IMPLEMENTATION_STATUS.md`；本文不把未执行的 Java 测试视为通过。

## 已知原业务边界

评论人工审核后跨 order 域的自动评论发布/拒绝仍是原实现记录日志的路径，本次没有把它作为新验证成功项。后续业务验收若覆盖评论发布，应补齐该跨域契约；此次保留其本域记录和清理行为。

## 2026-09-10：第三方 SDK 依赖归属收紧

支付宝 SDK 从 `smartlect-common` 下沉到唯一直接使用它的 `smartlect-pay/app`；阿里云邮件 SDK 下沉到 `smartlect-user/app`。全仓 Java 源码核查确认，两者分别只在 `PayChannel4AliPay`、`AliEmailServiceImpl` 中导入，公共 API 没有暴露 SDK 类型。两段依赖声明连同原有 exclusions 原样移动，父 POM 版本管理以及 common 中的 `bcprov-jdk18on`、`org.dom4j:dom4j` 替代依赖保留，避免改变支付/邮件运行功能。其他模块不再经 common 获得这两个 SDK；具体包体和内存收益尚未测量。

静态检查：25 个 POM XML 解析通过，声明与原 exclusions 一致，模块依赖图中 SDK 分别只由 pay/app、user/app 可达。Maven 构建和运行检查由主流程串行执行，本条不把静态检查写成编译通过；待运行 `mvn -B -f backend/pom.xml test`，并用 `mvn -B -f backend/pom.xml dependency:tree -Dincludes=com.alipay.sdk:alipay-sdk-java,com.aliyun:aliyun-java-sdk-core` 核查实际解析结果。
