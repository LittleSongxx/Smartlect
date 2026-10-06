# 悬空调用清理与 Flyway 校验和故障修复

## 需求

承接本日 AI Agent 侧的架构评审，对全仓做一次「悬空调用与退役残留」专项排查并清理。触发点是
评审中发现：Java 侧 `ProductProjectionClient` 仍在向 Python 的
`/internal/product-projection/enqueue` 发请求，而该路由已随 ADR-0008 退役——这是一条**会真实
产生 404 的死调用**，且带 3 次重试 + 补偿日志 + 自动重放，形成自我循环的噪声源。

排查范围：Java↔Python 双向调用面、退役功能残留（代码/配置/迁移/构建产物）、配置死开关、
孤儿文件、测试引用、文档漂移。

清理过程中**额外发现并修复了一个仓库级故障**（见下节），它不属于悬空调用，但同批处理。

## 具体变更

### 一、P0：「悬空调用」本身就是线上故障（不是死代码）

`ProductProjectionClient` 的调用链是完整的**正反馈**：404 → 3 次即时重试 → 落
`mq_compensation_log`（routing key `product.projection`）→ `MqCompensationAutoReplayTask`
带退避自动重放 → 再 404。每次商品保存/上架都会走一遍，并污染指标
`smartlect.product.projection.enqueue.exhausted`。

删除清单（整条通道，不只客户端）：

- `backend/smartlect-product/app/src/main/java/com/smartlect/integration/ProductProjectionClient.java`（删文件）
- `backend/smartlect-common/src/main/java/com/smartlect/compensation/ProductProjectionCompensatePort.java`（删文件）
- `ProductInfoServiceImpl.java`：移除字段与两个调用点（`saveProduct` 尾部、`updateProductStatus` 上架分支）
- `MqCompensationLogServiceImpl.java`：移除 `REMOTE_PRODUCT_PROJECTION` 重放分支与 `ObjectProvider` 字段
- `RemoteCompensateRecorder.java`：移除 `recordProjectionEnqueue`
- `InternalApiHeaders.java`：移除 `REMOTE_PRODUCT_PROJECTION` 常量
- `SaveProductGalleryTest.java`：移除对该客户端的 mock 与 `verify`（原断言把死调用锁成了契约，mock 恒真所以测试一直绿）

**兼容性说明**：若某个存量环境的 `mq_compensation_log` 里还有 `routing_key='product.projection'`
的历史行，重放会落到 `未知远程补偿类型` 分支并报错。本机四个相关库实测均为 0 行（见验证），
存量环境需在升级前自查该表。

### 二、P0：给已应用的 Flyway 迁移加注释，会让所有环境重启即失败

**这是本次最重要的发现，且与本批清理无因果关系——它是清理时重启服务才暴露的。**

`14cbee9`（chore: 死代码清理）给 `smartlect-order` 已应用的 `V3__baseline.sql` 加了 2 行注释。
Flyway 对迁移文件做 CRC32 校验并与 `flyway_schema_history` 比对，**内容变一个字节即启动失败**：

```
Migration checksum mismatch for migration version 3
-> Applied to database : -827808042
-> Resolved locally    : 1806845664
```

时间线（`git show -s --format=%ci` + 文件 mtime + 进程状态）：

| 时刻 | 事件 |
| --- | --- |
| 10-04 06:36 | `25ef508` 引入当前 V3，order 应用该版本，DB 记录校验和 `-827808042` |
| 10-04 21:00 | order 进程启动（此后一直健康，Flyway 只在启动时校验） |
| 10-04 23:51 | V3 被追加 2 行注释（文件 mtime） |
| 10-04 23:54 | `14cbee9` 提交该注释 |
| 10-05 23:11 | 本批清理重启 order → **首次触发校验，启动失败** |

影响面是**部署级**的：任何在 `14cbee9` 之前应用过 V3 的环境（含线上）重启都会挂，
不只是本机。所有 Java→Python 与 Python→Java 的调用面在故障前都是好的。

处置选择：**让文件回到字节一致状态，而不是去改数据库校验和**。后者只修一台机器，
前者修所有环境。校验：

```bash
diff -q <(git show 25ef508:.../V3__baseline.sql) .../V3__baseline.sql   # 逐字节一致
git diff 25ef508 14cbee9 -- .../V3__baseline.sql                       # 差异仅 2 行注释，无 DDL
```

那条版本号说明（V2 为何跳号）迁到新增的
`backend/smartlect-order/app/src/main/resources/db/migration/README.md`，并写入「已应用的迁移
一个字都不能改」的操作规约与故障判别方法。该目录下只有 `V*__*.sql` 会被 Flyway 扫描，
README 不参与校验。

**回滚**：本条无回滚必要（恢复到 HEAD 之前的历史内容）；若需回退整批，见文末。

### 三、脚本层的悬空端点

- `scripts/loadtest/assistant-control.js`：压测目标 `/api/assistant/recommendations?limit=4`
  已退役，k6 阈值 `http_req_failed<1%` 必然失败 → 换成现役 `/api/assistant/catalog/scope`
  （同样经过 nginx → gateway → assistant → Java introspect → MySQL 全链）。
- `scripts/eval_quality_v2.py`：删除两个零调用点的死函数 `campaign_metrics_from_growth`
  （查已退役的 `ad_interaction`/`ad_spend`/`commerce_attribution*` 表）与
  `wait_attribution_settled`（打已退役的 `/admin-api/assistant/attribution`）。

### 四、死配置

三处 `smartlect.assistant.*` 块无人读取（`@Value("${smartlect.assistant` 全仓唯一读取方就是
被删的 `ProductProjectionClient`）：

- `backend/smartlect-common/src/main/resources/smartlect-common.yml`
- `backend/smartlect-cart/app/src/main/resources/application.yml`
- `backend/smartlect-order/app/src/main/resources/application.yml`

均整块移除（含 `base-url` 与两个 `attribution-*-timeout-ms`；归因线已退役，环境变量
`SMARTLECT_GROWTH_ATTRIBUTION_*` 同批失效）。**网关不受影响**——它的 assistant 路由直接读
`${SMARTLECT_GROWTH_BASE_URL}`，不经过这个属性。

根 `.env.example` 重写：原文件 29 个变量（`LLM_*`/`EMBEDDING_*`/`QDRANT_COLLECTION=smartlect_products`/
`RERANKER_MODE`/`HYBRID_*`/`VOICE_*` 等）属已退役的旧推荐栈，**逐变量核实无任何代码读取**
（真实配置走 `./scripts/dev.sh bootstrap` 生成的 `run/runtime.env` 与 `run/model.env`）。
现改为「现役环境变量对照清单 + 指向真实生成入口」，并显式声明本文件不是运行入口。

`assistant/pyproject.toml` 移除直接依赖 `python-dotenv`（源码零 `import`）；它是
`uvicorn[standard]` 的传递依赖，故在 `requirements.lock` 中保留并加注说明（lock 是完整闭包，
与既有的 `websockets`/`PyYAML` 同样处理）。

### 五、孤儿产物

- 删除 `assistant/build/`（872K）：源码已删的 `knowledge_import.py`/`postgres.py`/`execution_scope.py`
  仍留在旧构建副本里，且 src 布局决定它不会被 import——纯垃圾，只会误导排查。
- 删除全部 941 个 `__pycache__` 目录与 `*.pyc`（含 `assistant/src/smartlect/` 下 12 个、
  `assistant/tests/` 下 21 个对应源码已删的孤儿 pyc）。
- 重建 venv 内安装副本：`pip uninstall` + `pip install --no-index --no-deps --no-build-isolation ./assistant`。
  关键点——**`pip install` 不会删除旧文件**，此前 venv 里 `smartlect.execution_scope` /
  `knowledge_import` / `postgres` 三个已删模块仍可 `import`，即「源码已删但仍能跑通」，会掩盖回归。
  实测重建后三者均 `ModuleNotFoundError`，`pip check` 无破损依赖。

以上全部在 `.gitignore` 覆盖范围内（`**/build/`、`**/__pycache__/`），未跟踪，纯本地磁盘清理。

### 六、文档与命名漂移

- `assistant/README.md`：更正「Recommendations and immutable attribution are implemented」这句
  与 ADR-0008 自相矛盾的表述；修 4 个失效链接（`../artifacts/f2-*.json` 两个不存在、
  `integration-reuse.md`/`growth-migration.md` 实际在 `docs/history/`）。
- `docs/prod-hardening/monitoring.md`：加失效追记——其记录的 growth worker 心跳与
  `SmartlectGrowthWorkerDown` 告警已随 ADR-0008 退役，现役 `run/cloud/monitoring/alerts.yml`
  已无该规则。**正文保持原样**（该文是 2026-09-14 时点的历史记录，改写有违证据政策）。
- `assistant/tests/test_shopping_mysql.py`：fixture `catalog_attribution` → `catalog_scenario_scope_store`。
  「退役命名与跨栈残留清理.md」声称已改此项，实际只改了调用点变量名、定义名未改，此处补齐。
- `web/admin/src/api/client.js`：删除零引用的 `actionLabels`（全为已退役的 campaign/creative 动作名）。
- `web/admin/src/utils/growthDisplay.js`：删除 6 个零引用导出（`diagnosisLabels`/`periodText`/
  `campaignStatusText`/`grantStatusText`/`productLabel`/`observationMetrics`）。
- 前端测试 fixture 从退役端点换成现役端点（沿用同日「退役命名与跨栈残留清理.md」的既定做法）：
  `web/admin/tests/admin.test.js` 的 `/ads/campaigns`、`/ads/actions` → `/knowledge`；
  `web/user/tests/home-promotions.test.ts` 删除失效的 `/recommendations?` mock 分支。

### 明确不改的项（附理由）

| 项 | 理由 |
| --- | --- |
| 退役表对应的迁移文件（`0006_recommendation.sql` 等） | 加注释即破坏校验和，与上述 Flyway 故障同源；只能靠文件校验和存续 |
| `assistant/LEDGER.md` 正文历史命令 | 文件已有退役抬头且声明「以下为历史记录」，改写违反「不整理历史证据」 |
| `TRIAL_MENU_PATHS` 里的 `/ads` 等 | 与 `Layout.vue` 的 `disabled: true` 占位菜单**有意一致**，删了反而让展厅账号看不到占位说明 |
| `X-Admin-*` 9 个常量 | 网关 `AuthGlobalFilter` 用它剥离伪造头，是声明性契约，不是悬空 |
| `CommerceV2Service.status` 未加 `requireNonTrial` | 只读口且只查本人（`require()` + 归属校验），非缺陷 |
| `SMARTLECT_ATTRIBUTION_SECRET` | 名为 attribution，实际仍服务 `ScenarioScopeStore`（`privacy.py`），不可删 |

## 关键源码

- `backend/smartlect-product/.../integration/ProductProjectionClient.java`（删除）
- `backend/smartlect-common/.../compensation/ProductProjectionCompensatePort.java`（删除）
- `backend/smartlect-order/app/src/main/resources/db/migration/V3__baseline.sql`（恢复字节一致）
- `backend/smartlect-order/app/src/main/resources/db/migration/README.md`（新增，迁移操作规约）
- `scripts/loadtest/assistant-control.js`、`scripts/eval_quality_v2.py`

## 验证方式与证据

**静态**

- 悬空引用清零：`grep -rn "ProductProjection|product-projection|REMOTE_PRODUCT_PROJECTION|recordProjectionEnqueue"` 在 Java 主源码与 yml 中零命中。
- 死配置读取方核实：`grep -rn 'smartlect\.assistant' --include=*.java` 在删除前唯一命中 `ProductProjectionClient`。
- 迁移文件字节一致：`diff -q` 与 `git show 25ef508:...` 逐字节相同；`git diff 25ef508 14cbee9 -- V3__baseline.sql` 显示差异仅 2 行注释。
- `python3 -c ast.parse` 校验 `eval_quality_v2.py` 语法；`node --check` 校验 `assistant-control.js`。

**测试（本机，2026-10-05）**

- Java 后端全量：`mvn -B -o -f backend/pom.xml test` → **BUILD SUCCESS**（25 个模块全绿，含 `smartlect-common` 118、`smartlect-product/app`、`smartlect-order/app`、`smartlect-cart/app`）。
- assistant 非 MySQL 套件：292 用例 OK（64 skip）。
- assistant MySQL 套件（真机）：63 用例 OK（9 skip）。
  见下方「已知陷阱」——首次以 `run/runtime.env` 直跑时 1 例失败。
- 前端：`web/admin` vitest 31/31、`web/user` vitest 79/79。

**运行态（本机 12 进程）**

- `mvn package` 后 `./scripts/dev.sh up` → `Application checks passed: 12 owned healthy processes,
  9 Nacos registrations`，启动冒烟通过。
- 按 PID 过滤日志，**所有新进程 `ERROR` 计数为 0**（日志文件是追加累积，历史 ERROR 来自本次之前的运行与一次失败启动）。
- 端到端冒烟（经网关 `127.0.0.1:18082`，非直连）：`session` → 建会话 → 发消息 → 轮询 run → 取回答。
  带 `product_id` 焦点的一轮返回了**来自 Java 的实时规格/价格/库存**：

  ```
  豚豚店员-4支装 (升级新款)，¥19.90，库存 99
  【五款大合集】20支装 (超高价值)，¥25.90，库存 199
  ```

  这同时验证了 Python→Java 的 `searchOnSale` / `snapshotBatch` / `stock/getBatch` 检索链在改动后完好。
- 补偿表污染自查：`smartlect_product`/`smartlect_order` 等库 `routing_key='product.projection'` 均为 0 行。

## 已知陷阱（本次踩到，值得沉淀）

`assistant/tests/test_shopping_mysql.py` 的
`test_six_actual_attempts_include_retries_and_fallback_does_not_reset_budget` 硬编码默认预算 6。
若以 `set -a; . run/runtime.env; set +a` 直跑，`run/runtime.env:67` 的
`SMARTLECT_MODEL_CALL_LIMIT=16` 会注入 policy，该用例报 `10 != 6`。
**这是环境串扰，不是代码缺陷**：显式 `SMARTLECT_MODEL_CALL_LIMIT=6` 后同用例通过（已实测）。
本次未改测试——它锁的是默认预算语义，改测试会削弱断言；但拉起 MySQL 套件时需注意把该变量
显式钉住，否则会误判为回归。

## 未完成项

- 存量环境的 `mq_compensation_log` 中 `product.projection` 历史行未清（本机为 0；线上环境需自查后再升级）。
- `test_shopping_mysql.py` 对 `SMARTLECT_MODEL_CALL_LIMIT` 的环境敏感未加隔离（可用
  `mock.patch.dict` 钉住默认值），本次只记录未改。
- 线上/集群环境是否也受 V3 校验和影响未实测（推论上受影响，判定依据是 `git diff` 与时间线，非线上复现）。
- `docs/qa-live-pass/*`、`docs/prod-hardening/ai-agent-ha.md` 等处仍有把 growth worker 描述为
  现役的历史表述，本次未逐处加追记（属历史快照，非运行依据）。

## 启用与回滚

- **配置**：三处 `smartlect.assistant.*` 为死键，删除后无启用语义；`.env.example` 不是运行入口，
  重写不影响任何进程。若需恢复旧行为，从 git 取回对应 yml 段落即可。
- **补偿通道**：`product.projection` 分支删除后若需临时恢复，回滚
  `MqCompensationLogServiceImpl` / `RemoteCompensateRecorder` / `InternalApiHeaders` 三个文件，
  并同时恢复 Python 侧路由（ADR-0008 已退役该投影线，恢复等于撤销该 ADR）。
- **Flyway**：`V3__baseline.sql` 已回到与 DB 记录一致的字节状态，order 可正常启动；
  若未来确需改已应用迁移，须 `flyway repair` 且先用 `git diff` 确认差异不含 DDL。

## 关联代码版本

基于 `7773906` 工作树（本批未单独提交，与本日其余改动同处工作区）。新增文件
`backend/smartlect-order/app/src/main/resources/db/migration/README.md`。
