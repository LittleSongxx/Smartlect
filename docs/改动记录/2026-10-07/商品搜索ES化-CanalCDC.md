# 商品搜索 ES 化：Canal CDC 标准链路（批次一）

日期：2026-10-07 ｜ 状态：已完成并端到端验证通过

## 需求

对标行业主流（Canal → MQ → ES），替代原 SQL LIKE 商品检索。原方案 87k 商品全表扫描，
且[苏三说技术等](https://www.cnblogs.com)确认 Canal→MQ→ES 是电商商品搜索的行业标准方案。

## 具体变更

### 基础设施

1. **MySQL binlog**：`deploy/compose.yaml` mysql command 显式
   `--server-id=1 --log-bin=binlog --binlog-format=ROW --binlog-row-image=FULL`
2. **Canal 容器**：`deploy/compose.yaml` 新增 `canal/canal-server:v1.1.8`
   （v1.1.6/7 在本环境 segfault，v1.1.8 稳定）；rabbitMQ 直投模式；
   `deploy/canal/canal.properties` + `instance.properties` 模板（凭据由
   `deploy/canal/startup.sh` 用 sed 注入 CANAL_* 环境变量，解决镜像无 envsubst）；
   startup.sh 同时预声明 smartlect-canal 交换机（解决首次部署鸡蛋顺序）
3. **复制账号**：`deploy/mysql-init.sh` 新增 `smartlect_canal` 用户
   （GRANT REPLICATION SLAVE + SELECT ON smartlect_product.*，
   密码截为 24 hex 避开 MySQL 8.4 report-password 长度限制）
4. **runtime.py 纳管**：PORTS["CANAL"]=11111、bootstrap password_keys、
   infra_up 名单、infra_check healthy 集合

### Java 侧

5. **product 服务 pom** 新增 `elasticsearch-java:8.19.0`（与 deploy 容器同版本）
6. **`ElasticsearchConfig`**：RestClient + ElasticsearchClient bean，
   从 `smartlect.es.url` 读连接（默认 `http://127.0.0.1:9200`）
7. **`ProductIndexService`**（search 包）：
   - `ensureIndex()`：显式 Java API mapping（productName 双字段：standard 分析 +
     `raw` keyword 子字段供短语 wildcard；status/price/sale/category/scope 等）
   - `upsert/delete`：按 productId 增删文档
   - `searchIdsByKeyword()`：`wildcard` on `productName.raw`（case-insensitive，
     wildcard 元字符转义，与 `LIKE '%kw%'` 语义逐字等价）；filter status=1 +
     catalog_scope≠eval + 排除 productIds；sort createTimeMillis desc
   - `rebuildAll()`：分页遍历 DB + bulk upsert（幂等，不清索引）
   - ES 不可达返回 null → 调用方回退 SQL LIKE（检索永不因索引故障中断）
8. **`ProductIndexConsumer`**（MQ 消费者）：监听 `smartlect.canal.product-index.queue`
   （手动 ACK），解析 Canal flat JSON，仅处理 `product_info` 表的 INSERT/UPDATE/DELETE；
   DELETE 用消息内 `data` 行的 `product_id` 删索引；失败走既有延迟重试→死信拓扑
9. **`ProductIndexInitializer`**：启动异步全量重建（87k 商品约 5 分钟，
   不阻塞健康检查——曾因阻塞导致启动超时被杀后改为 ThreadPoolTaskExecutor 异步）
10. **查询切换**（`searchOnSale` + `loadProduct`）：关键词非空且非 category: 前缀时
    走 ES 检索（searchIdsByKeyword），空结果短路返回；ES null（不可达）回退 SQL LIKE

### 旧代码清理（完全清除）

- `ProductInternalService.getSearchIndex()` 方法 + Controller `/searchIndex` 端点 +
  `ProductFeignClient.getSearchIndex()` + `ProductFeignSupport.getSearchIndex()` +
  Fallback 分支 + `ProductSearchIndexVO.java`（整文件删除，全仓零引用）
- `ProductIndexTextSanitizer` import 清理（ProductInternalService 侧已无引用）

## 验证方式与证据

1. **单元测试**：`ProductIndexServiceTest`（4 个用例：wildcard 转义、canal 行解析、
   分币换算、忽略非目标表）；`PublicProductSearchTest` 补 ES 路径用例 +
   既有用例改用 ES null stub 保回退契约；`ProductCommerceSearchScopeTest` 同；
   product 模块 35/35 全绿
2. **端到端**（live 栈验证，2026-10-07 01:09）：
   - 索引创建成功（含 raw 子字段 + custom analyzer settings）
   - 全量重建 87,469 条（约 5 分钟，异步不阻塞服务启动）
   - ES 搜索「键盘」返回 3 件金属/轻便键盘（与 SQL 结果同集）
   - Canal 增量：MySQL UPDATE product_name → Canal→RabbitMQ→Consumer→ES 文档更新
   - Canal 日志确认 binlog dump 正常、subscription 正常
3. **全仓后端 BUILD SUCCESS**（`mvn -f backend/pom.xml test`）

## 未完成项 / 已知限制

- ES 容器为 stock 镜像（无 smartcn 插件），分析器暂用 standard；
  后续切 custom build 镜像后改回 smartcn（wildcard 搜索不依赖分析器）
- Canal 位点存于容器内（无持久卷），容器重建后从 MySQL binlog 尾部重新订阅；
  首次部署靠初始化器全量重建兜底
- canal.properties / instance.properties 的模板注入依赖 bash + printenv + sed，
  镜像升级需验证这些工具仍可用

## 关联代码版本

基于 `899ed91` 工作树 + 未提交消融改动。本批次文件：
deploy/compose.yaml、deploy/canal/、deploy/mysql-init.sh、scripts/runtime.py、
backend/smartlect-product/（pom.xml + 7 个 Java 文件 + 3 个测试文件）、
backend/smartlect-common/constants/RabbitMQConfig.java

## 批次二追加：商品详情多级缓存（同日）

### 新增

1. **`ProductCacheService`**（component）：Caffeine L1（W-TinyLFU，10k 容量/60s 过期）
   + Redis L2（TTL 300s ± 10% 抖动防雪崩）；`get/put/invalidate` + `onInvalidationMessage`
   （pub/sub 广播失效）；库存清零后入缓存（静态快照），命中后实时 Feign 补库存
2. **`ProductCacheListenerConfig`**：RedisMessageListenerContainer 订阅
   `smartlect:product:invalidate` 频道 → 清本进程 L1
3. **`getProduct4VOByProductId`** 改 Cache-Aside 读路径（L1→L2→DB），
   miss 后回填；新增 `replenishRealtimeStock` 补库存方法
4. **写路径失效**：`saveProduct`/`updateProductStatus` afterCommit 调 invalidate；
   Canal 消费者 `touched.forEach(cacheService::invalidate)` 兜底
5. application.yml 加 `smartlect.cache.*` 三参数

### 验证

- product 35/35 全绿（ProductDetailGalleryTest/ProductIndexServiceTest 补 cacheService mock）
- 全仓 `mvn test` BUILD SUCCESS
