# ADR-0008: 推荐/归因/worker 线整体退役

日期：2026-10-04
状态：已接受（2026-10 收敛重构）

## 背景

assistant 曾承载四条线：Shopping Agent、RAG 客服、确定性推荐（五路召回+语义重排+曝光点击归因+commerce ledger）。后两条线的存在稀释了项目主线（Agent runtime + 交易边界），且与 Java 侧形成三处反向耦合（attribution validateBatch / product-projection enqueue / commerce MQ）。

## 决定

- **整体退役**：`/recommendations` 全家、traffic landing/bind、attribution、commerce ledger、product-projection、worker 消费进程（约 -4300 行，13 进程 → 12）。
- **首页滚动位改走 Java 确定性精选**：`GET /product/loadCommendProduct`（管理端配置的 commend 商品）——符合「浏览器只画状态，推荐是交易侧确定性数据」的边界。
- **保留三个拆出件**（均为存活契约）：
  - `db.py`：线程本地 MySQL 连接 + canonical JSON（全库共用）。
  - `catalog_scope.py`：商品可售范围 include/exclude（前端商品过滤在用）。
  - `scenario_scope.py`：评测场景 scope 注册/退役/reset 水位（eval 与 Java demo scenario 依赖）。
- **save_recommendation 保留**：这是检索回执（Recall@8 评测的分子分母来源），不是归因——它随 ScenarioScopeStore 留存。

## 后果

- assistant 的故事收敛为三件事：**Agent（有界 ReAct + 持久化提案 HITL）、RAG（ES+Qdrant 混检）、提案确认闭环**。
- 9 个 MySQL 契约测试随 ledger 水位语义退役/挂起（标注 TODO），eval 场景隔离不受影响。
