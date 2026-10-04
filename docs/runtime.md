# Smartlect 本地运行

更新：2026-10-04（收敛重构后）。从项目根目录执行 `./scripts/dev.sh bootstrap`，探测空闲端口并生成本项目随机凭证，保存在 Git 忽略的 `run/runtime.env`（权限 600）。

## 基础设施（7 个容器）

| 服务 | 默认端口 | 说明 |
|---|---|---|
| MySQL 8.4 | 13306 | 10 个业务库（无 Seata） |
| Redis 7.4 | 16379 | Sa-Token 会话 + Redisson 锁/限流 |
| RabbitMQ 4.2 | 15672/15674 | Outbox 可靠消息 + 延迟队列 |
| Nacos v2.5 | 18848 | 服务发现（无配置中心） |
| Elasticsearch 8.19 | 9200 | smartcn 中文分词（需 build Dockerfile） |
| Qdrant 1.15 | 6333 | 1024 维 HNSW 向量检索 |
| PostgreSQL 16 | 15432 | LangGraph checkpointer（profile `postgres`） |

```bash
./scripts/dev.sh infra-up   # 启动上述全部容器并等待健康
./scripts/dev.sh infra-check
```

## 应用进程（12 个）

| 进程 | 端口 | 说明 |
|---|---|---|
| assistant | 18000 | FastAPI（Python，无 worker 进程） |
| user | 18105 | 账户/地址/RBAC/Sa-Token 登录 |
| product | 18106 | 商品/SKU/分类 |
| stock | 18108 | 库存（条件更新） |
| order | 18104 | 订单/退款 Saga/Outbox |
| pay | 18103 | mock 支付（intent 权威） |
| cart | 18102 | 购物车 |
| coupon | 18107 | 优惠券/秒杀 Lua |
| admin | 18101 | 管理端 BFF |
| gateway | 18080 | SCG 网关（Sa-Token 校验） |
| web-user | 18180 | Vue 3 用户端 |
| web-admin | 18181 | Vue 3 管理端 |

```bash
./scripts/dev.sh build   # 编译 Java + assistant venv + 前端
./scripts/dev.sh up      # 按顺序启动 12 进程（Java 先声明队列 → assistant → 前端）
./scripts/dev.sh check   # 三栈全量测试
./scripts/dev.sh status
./scripts/dev.sh down
```

## sa-token 配置

`smartlect-common.yml` 全局共享 `sa-token.token-name: token`——所有业务服务自动继承，各服务不得覆写 token-name（Redis 键前缀会不一致导致互读不到会话）。管理端 StpAdminLogic 的 `tokenName: adminToken` 在 `StpAdminLogic.java` 注册。

## 常用操作

```bash
./scripts/dev.sh seed-store     # 示例货架 + 知识灌入
./scripts/dev.sh reset-demo     # 重置演示数据
./scripts/dev.sh model-mode     # 切换 mock/live
./scripts/dev.sh catalog        # 安装商品目录
```
