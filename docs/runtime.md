# Smartlect 本地运行

更新：2026-09-09，F4/F5功能已有证据，F6评测与F7交付仍在进行。从项目根目录执行 `./scripts/dev.sh bootstrap`，探测空闲端口并生成本项目随机凭证，保存在 Git 忽略的 `run/runtime.env`（权限 600）。重复执行保留已有凭证/端口，只补缺失的 demo、访客 secret、独立 `SMARTLECT_ATTRIBUTION_SECRET` 和允许 Origin 等字段；不重置已有数据库。Java/Python 应用由启动器加载此文件，不能假定默认端口空闲。源码更新不等于运行实例已升级，实际版本/进度见 [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md)。

模型配置另存于 Git 忽略的 `run/model.env`；允许缺文件以运行无 key 回归。启动器仅为两个 Python 进程读取并合并此文件，不将它合并进 Java/Compose 配置。文件必须是权限 600 的普通文件，不能是软链接；只允许白名单中的模型/embedding/rerank key、供应商 URL、型号等字段，发现业务凭证或额外字段即拒绝。按字面值解析，不执行 source/eval，不打印值。默认模型选择为用户指定的 `qwen3.7-plus`，不会继承昂贵旗舰；模式支持 `mock/live/rule-fallback`。执行 `./scripts/dev.sh model-mode live` 保存模式，再 `up` 应用变更；该命令不会输出或改动模型密钥。真实能力与纵切证据见 `artifacts/f2-provider-capabilities.json`、`f2-live-vertical-v6.json`。

`./scripts/dev.sh config` 校验 Compose，输出端口但不输出密钥。`./scripts/dev.sh infra-up` 启动独立 MySQL、Redis、RabbitMQ、Nacos 和 Seata，等待健康检查并验证 Nacos 登录。该命令只表示中间件就绪；Java 应用、增长服务和完整演示使用各自阶段门禁。

`./scripts/dev.sh infra-check` 实查 Nacos 中 Seata 健康注册地址与端口，以及 MySQL 中增长、迁移、商业应用身份的 schema 授权范围。此检查要求本项目中间件已启动。

`./scripts/dev.sh up` 在独立中间件健康检查通过后启动 **13 个应用进程：九个 Java JAR、FastAPI AI API（growth）、Growth worker（growth-worker）及两个 Vue 前端（web-user/web-admin）**。先单独等待 worker 健康，再启动并等待 API 和七个商业服务，随后启动依赖跨库视图的 Admin 与 Gateway，最后两个前端；健康检查上限 240 秒，进程退出立即报错。这个顺序保证支持v1/v2的消费者先于新Java生产者就绪。HTTP 应用仅绑定 loopback，worker 没有监听端口。重复 up 复用相同内容/配置/命令的进程，内容或配置变化时重启相应进程。

API 负责会话、严格工具参数、结构化提案、确认执行、状态查询和 SSE 回放；worker 独立运行 RabbitMQ 财务消费者，提交后 ACK，消费线程不等待模型。`/messages`立即返回持久运行并在后台执行有界Shopping图。SSE回放并等待增量事件；只显示经验证的回答与简短工具进度。Merchant同样由API持有有界任务，按新观测规划并由确定性执行器在稳定grant内执行，参见[经营合同](merchant-contract.md)。实际 API 合同见 [contracts.md](contracts.md)。

F3 API 新增自然entry、可信访客登录绑定、持久推荐列表和可见曝光/点击；每个请求由服务器解析稳定scope。
推荐策略/assignment入MySQL，HTTP列表使用规则或内容规则；只有live Shopping的treatment路径有可选模型重排，
成功/失败模式分别记录 `content_llm/content_rule_fallback`，不能用全局live开关当作每份列表实际调用模型的证据。
两种排序都执行最终SKU复验，详见 [agent-design.md](agent-design.md)。

推荐结果记录 `algorithm_version=sku-rank-paid-units-v1`：热门路使用Java订单只读
`/internal/order/commerce/popularProducts`，按历史确认付款件数排序（含0元及后续退款），不取商品`totalSale`冒充付款反馈。
五路召回通过`productIds/excludeProductIds`在SQL LIMIT前过滤scope及用户排除项；include为None时省略、空数组严格空结果。
这些新读取入口需随Order/Product服务一起更新；口径与观测时间存在`popularity_evidence`，不改变Java计价/支付/退款。
精确参数与名单上限见 [contracts.md](contracts.md)。

Java 实际运行 `run/apps/{service}/{sha256}.jar` 的只读副本。复制检查来源修改时间/大小/文件身份和 ZIP CRC，拒绝正在变化或尚未完成打包的 JAR；同一 hash 的副本不会覆盖。进程记录保留来源路径、SHA-256 和修改时间，后续 Maven 重建 `target/` 不会破坏现有 JVM 的延迟类加载或退出流程。旧 hash 副本保留，当前没有自动清理。

两个 Python 进程分别使用 `growth/.venv/bin/python -I -m smartlect.app` 和 `... -I -m smartlect.worker`，来自同一个已安装 `smartlect` 包。更新判定按包内全部文件的相对路径与 SHA-256 计算内容指纹，包含 `.py`、打包的 SQL 迁移及其他资源，只排除 `__pycache__`/`.pyc`；SQL 改动也会触发更新。非 editable 安装需先重装包。`-I` 隔离当前目录、PYTHONPATH 和用户 site-packages 的导入影响，业务配置仍由进程环境显式传入。

worker 每 0.5 秒原子更新 `run/worker-status.json`（权限 600），记录 PID、连接状态和时间。运行管理器核对 worker 进程归属、文件 PID 及 5 秒内心跳；API `/health` 同样检查消费者连接和心跳新鲜度，缺失/过期返回 degraded/503。单独重启 API 不会停止财务 worker。

`./scripts/dev.sh apps-check` 重验13个进程归属与健康，核对九个Java服务在Smartlect Nacos group中注册的loopback地址与配置端口，以及八个商业库的Seata元数据表；`up`结束前也会执行。两个Python进程不注册为Nacos Java服务。

Gateway 的 `/api/assistant/**` 和 `/admin-api/assistant/**` 保留原路径转发到 `SMARTLECT_GROWTH_BASE_URL`，响应超时 95000 ms。请求先清洗伪造内部/主体头，再交给 API 逐请求通过 Java cookie bridge 认证；访客可咨询，管理入口仍强制有效管理员 cookie。bootstrap 的 `SMARTLECT_ALLOWED_ORIGINS` 包含实际 Gateway 和用户端 loopback URL；写请求先 GET session 获取 CSRF，再带同 cookie、Origin 与 `X-CSRF-Token`。用户端通过 Vite preview 代理同源请求；Node进程环境只给PATH/语言/时区/前端端口与Gateway地址，无业务或模型凭证。

`./scripts/dev.sh status`列出容器和应用健康状态。`./scripts/dev.sh apps-down`停止本项目应用，保留中间件；`./scripts/dev.sh down`再停止/移除经Compose项目标签和配置文件路径核对的本项目容器及网络，保留数据卷。没有自动清库或重置。从`down`恢复或首次运行先`infra-up`，再`up`；`up`自身不启动中间件。`reset-demo --run-id`仅退役Java已登记的本项目演示并创建独立replacement资源，保留旧交易/事件/累计账本；实际隔离和重投证据见[安全重置合同](reset-contract.md)及实施状态。

`./scripts/dev.sh demo --seed 42` 保留已有真实 Java 交易场景（固定为 purchase_stockout，无 `--scenario` 参数）。Java 仅在本地 demo 开关及 mock 支付模式下初始化 100 用户/20 商品/40 SKU，使用生成密码签发正常 Redis 会话；重复初始化不改已有库存。场景覆盖下单/重放/支付/退款/售罄/取消及对账，事件消费启用时等待账本收齐。该入口本轮11项交易回归已通过，仍不是推荐投放效果实验。

新增 F1 专项入口：应用 up 后执行 `growth/.venv/bin/python scripts/check_f1.py`。它只使用 Smartlect 合成用户/SKU、Java 报价及模拟支付，验证伪造头、归属/CSRF、变更金额拒绝、提案持久化、重复确认、SSE 回放和账本；中途核验进程身份后实际重启 **API 一个进程**，保持 worker 运行。已通过的结果见 [f1-live-confirmation.json](../artifacts/f1-live-confirmation.json)：实付/退款/净额 1000/1000/0 分，库存 5→5，`live_model_called=false`。这不是完整自然语言演示，也未使用真实资金。

新 bootstrap 默认 `SMARTLECT_GROWTH_EVENTS_ENABLED=true`；增长身份只访问独立增长库，worker 先提交事实/账本再 ACK。`growth/.venv/bin/python scripts/check_event_replay.py` 使用已有 Java 事实检查未 ACK 重投、实际 **growth-worker** 重启及 Broker ACK，要求前置队列已消费完毕，不造新金额。本轮 AMQP 重投26事实/原账本不变已通过，结果见 `artifacts/f1-amqp-replay.json`；新 `--output` 参数可指定产物，默认 `artifacts/amqp-replay.json` 不再覆盖历史P2证据；[growth/LEDGER.md](../growth/LEDGER.md) 保留原 v1 协议和历史证据，其中旧“app 内消费者”的进程说明由本节的 API/worker 分离结构取代。

进程管理固定使用系统 `/usr/bin/python3`（可由支持pidfd的SMARTLECT_RUNTIME_PYTHON覆盖），增长使用独立venv。已发现本机Miniconda Python不提供pidfd接口，因此不能用它替代管理进程的系统解释器。

应用归属记录在 `run/processes.json`，日志位于 `run/logs/smartlect-*.log`。停止前逐项核对 `/proc` 的 PID、启动时间、可执行文件、完整命令行和本项目工作目录；通过 Linux pidfd 发送信号，避免 PID 复用时误杀。身份变化直接报错。正常退出等待最多 40 秒，必要时仅强制结束已经核验的本项目进程。Java 默认堆上限 256 MiB，可用 `SMARTLECT_JAVA_XMX` 调整；不共享来源工程的 JVM 配置、类路径或 Python 导入路径。

初始 `/proc` 读取可能短暂返回空命令行；身份读取最多重试 1 秒，并检查前后启动时间与可执行文件一致。启动时额外核对身份与实际 `Popen` 参数完全相符，之后继续严格核验，空值或不稳定身份不会作为可发送信号的依据。

每个 Java 服务设置 `csp.sentinel.log.dir` 到 `run/logs/sentinel/{service}`；Nacos `JM.LOG.PATH` 到 `run/logs/{service}`（实际日志在其 `nacos/` 下），`JM.SNAPSHOT.PATH` 到 `run/cache/{service}`。这些键已从实际 Sentinel 1.8.9 `LogBase`、Nacos 3.0.3 `CacheDirUtil`/`LocalConfigInfoProcessor` 和 logback-adapter 1.1.4 的 `nacos-logback14.xml` 核验。

| 资源 | 默认宿主端口 | 身份与隔离 |
|---|---:|---|
| MySQL | 13306 | `smartlect_app` 仅商业库 DML；`smartlect_flyway` 商业库迁移 |
| Redis | 16379 | 独立容器/卷、随机密码、DB 0、业务 key 前缀 `smartlect:` |
| RabbitMQ | AMQP 15672；管理 15674 | 用户/vhost 均 `smartlect`，随机密码 |
| Nacos | HTTP 18848；gRPC HTTP+1000 | 独立数据库/实例；内置 `nacos` 管理员使用新密码，group `SMARTLECT_GROUP` |
| Seata | 18092 | `smartlect_seata` 数据库/用户；注册 `smartlect-seata`，group `SMARTLECT_SEATA_GROUP` |
| Gateway / Growth API | 18080 / 18000 | 实际值以 `run/runtime.env` 为准；AI 路由指向同一 Growth API |
| Growth worker | 无 | 独立进程，使用状态文件和进程身份检查，无第二套 HTTP 服务 |

用户端由 `SMARTLECT_WEB_USER_PORT` 指定（默认18180）；构建产物、配置和lock hash决定重启。管理端由 `SMARTLECT_WEB_ADMIN_PORT` 指定（默认18181），入口 `/admin/`。两端都只获得端口/Gateway URL和少量系统环境字段，不获得业务或模型密钥；加入管理端端口的既有run配置用 `./scripts/dev.sh bootstrap`，保留原凭证/端口并增补同源列表。旧DASHBOARD字段不是运行工作台。

Compose project 固定为 `smartlect`。卷为 `smartlect_mysql`、`smartlect_redis`、`smartlect_rabbit`；网络为 `smartlect_default`。除 Seata 注册要求使用可达本机地址外，发布端口仅绑定 loopback。端口被占用时 bootstrap 顺延选取，不停止占用方。Nacos 使用空 namespace 保持不同版本客户端兼容，靠独立实例和 Smartlect group 隔离。Seata 事务组为 `smartlect_tx_group`。

MySQL 首次初始化创建八个商业库以及独立的 `smartlect_growth`、`smartlect_nacos`、`smartlect_seata`。增长身份只得到增长库权限，无法直接写商业库。商业表由新 Java reactor 内的 Flyway migration 创建。Nacos/Seata 官方兼容 schema 从冻结快照取材后独立保存于 `deploy/sql/`；没有导入来源数据库内容或固定密码。MySQL JDBC 驱动固定版本并检查 SHA-256 后加入 Smartlect Seata 镜像。

Growth SQL 将版本化的 ledger、agent_state、knowledge_memory、knowledge_index_attempt 迁移打包，API/worker 启动都调用同一迁移器。MySQL `GET_LOCK('smartlect_growth_schema',10)` 串行迁移，`schema_migration` 记录名称与 SHA-256；已应用版本缺失、哈希改变或补插较旧版本时失败。0001 保留既有账本，0002 新增会话/消息/运行/提案/工具/事件表，不覆盖 Java 交易成果。MySQL DDL 隐式提交，当前建表迁移可重放；未来 ALTER 需独立定义恢复，不能把普通事务 rollback 当成 DDL 回滚。

F3另打包 [0005_attribution.sql](../growth/src/smartlect/migrations/0005_attribution.sql)（scope/资源、访客绑定、触点、不可变context、事件元数据与归因投影）和
[0006_recommendation.sql](../growth/src/smartlect/migrations/0006_recommendation.sql)（策略/实验/分桶）。Java Order的
[V2迁移](../backend/smartlect-order/app/src/main/resources/db/migration/V2__order_attribution_context.sql)增加订单来源侧表。
这些新增表不覆盖既有交易或v1账本；已应用迁移禁止改哈希。v1 `raw_json/fingerprint`保留原文，来源缺失按`LEGACY_UNKNOWN`单列。

F3版本升级按以下顺序执行；本轮已按此顺序上线，验收证据另列于文末：

1. `./scripts/dev.sh bootstrap` 补齐独立归因secret，`./scripts/dev.sh build` 完成Java/Python/用户端构建。构建期间旧JAR不可变副本可继续运行；只重建target不算已部署。
2. `./scripts/dev.sh up` 先更新worker，完成增长迁移、v1/v2解析与待定投影重放，并等待消费者连接/新鲜心跳；失败立即停止本次后续启动，不放行新v2生产者。
3. 启动新版API与Java生产者，Java在建单事务本地验证共享的独立归因secret；`apps-check`检查全部应用身份/健康及注册。API `phase=F3`只标识代码阶段，不能代表归因场景通过。
4. 使用本阶段新Java订单/付款/退款与VIEW事实完成归因联验，复核金额总账、v1原始指纹、未知覆盖、重复与乱序结果，再保存证据。队列可能已有v2时回退生产者仍保留兼容消费者，不直接换回只接受v1的worker。

Growth冻结来源最多等待0.5秒，Java验签没有Growth网络依赖；来源缺失/错误/过期降为`UNKNOWN_CONTEXT`并继续合法交易。
兼容`validateBatch`客户端另使用200ms连接/500ms读取超时且不重试，只能丢弃可选推荐来源，不能阻断交易。
归因secret不能由`run/model.env`覆盖；禁止以内部认证secret代替或打印密钥。真实广告预算和CPC扣费仍待F4，F3合成点击不能写成投放收益。

Seata 的 AT DataSource 代理在 Flyway 之前检查 `undo_log`；因此初始化/应用 up 使用迁移身份幂等创建八个商业库的 Seata 元数据表。首次启动发现的缺表错误由这个部署前置条件修复，保持 Seata 事务功能启用。

构建入口 `./scripts/dev.sh build` 先执行独立性扫描，再构建整个 Java reactor，按 `growth/requirements.lock` 安装依赖，以 `--no-deps --no-build-isolation -e growth` 安装包并执行 pip check。Python 需要 3.11+；已有 `growth/.venv` 优先复用，否则依次探测 `SMARTLECT_PYTHON`、已安装版本、用户 Miniconda 和系统 Python。`./scripts/dev.sh check` 执行独立性扫描、运行脚本自测、Java 测试、Growth unittest 与用户端 Node contract tests；需要真实 MySQL 的用例仍须显式开启，不能把默认跳过当作已通过。

命名检查 `python3 scripts/check_independence.py` 扫描业务、部署和脚本，排除冻结交接包、许可证/来源记录、迁移取材工具和构建产物；发现旧品牌、旧归因字段、旧路径依赖或越界软链接即失败。`python3 scripts/check_independence.py --self-test` 和 `python3 scripts/runtime.py self-test` 可独立验证扫描器、端口冲突选择、配置读取、SQL 权限隔离与非法凭证拒绝。

本轮 F1 已完成检查点为 25 reactor/349 项 Java 单元、6 项状态 MySQL、1 项 HTTP＋mock Java 及上述真实 Java 确认链。此外原 demo 11项、Java金额/报价MySQL 4项、AMQP重投本轮通过；最终运行环境27项轻量通过，另12项MySQL曾实跑通过，详见 [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md)；不引用历史支付/共购测试充当本轮成绩。未实现 `eval`、完整三场景或 `reset-demo`，未对外发布、推送仓库、真实投放或真实付款。

F2 知识初始化：`growth/.venv/bin/python scripts/seed_knowledge.py --live-embeddings` 发布32份仓库合成资料并记录真实索引元数据；不带参数只建词法索引。已有发布版本跳过，不重新消耗模型。`scripts/check_model.py` 为真实协议smoke，`scripts/check_f2.py` 为真实模型＋Java模拟资金纵切；二者不是完整质量评测，44例冻结RAG集留待F6。worker另在线程中每日清理30天前的聊天/trace，不删除交易提案与账本事实。

F3命令已实跑：`scripts/check_f3.py`（真实Java交易＋合成广告触点）、`scripts/check_f3_model.py`（真实语义重排）、`scripts/check_event_replay.py --schema-version 2 --output artifacts/f3-amqp-replay.json`。重投脚本按原schema版本选择最多100条原事实，不把v2改成v1；不动其他项目。自动续行期间本项目中间件退出255、应用停止，经状态核验后只恢复本项目，原34条账本原文和指纹保留。完整结果见 [f3-validation.json](../artifacts/f3-validation.json)。


## 共享 WSL 下的资源控制

三个项目并行时，构建、临时MySQL测试和全链路验收仍串行。暂不需要运行界面/API时可先 `./scripts/dev.sh apps-down`，保留中间件及卷；之后 `up` 逐个启动并等待健康，避免多个JVM同时预热。仅管理Smartlect已校验归属的进程，不能重启WSL/Docker或停其他项目。

## 部署前的两道门（2026-09-17 起）

`ci-deploy.sh` 在 `systemctl restart smartlect-apps` **之前**跑两步，目的是让"坏了就别下线"：

1. `python3 scripts/runtime.py check-apps`（秒级，每次部署都跑）：为 13 个服务各拼一遍启动计划，
   确认可执行文件与产物（JAR / Python 包 / 前端 dist）都在。2026-09-17 一次 `runtime.py` 重构
   漏绑定产物路径，直接导致重启失败、整站不可用——这一步就是那次事故的对策。
2. `python3 scripts/runtime.py smoke`（约 5 分钟，backend/ 或 scripts/ 有改动时跑）：用同一份 JAR、
   同一份 env 让 Spring 上下文真刷新一次。普通服务用 `--spring.main.web-application-type=none`
   （不监听端口、不注册 Nacos），gateway 是 WebFlux 应用，改用 reactive + `--server.port=0`
   + 关注册；判定以启动日志为准（看到 `Started ... in ... seconds` 通过，看到
   `APPLICATION FAILED TO START` 失败），结束后主动回收进程。

前端产物改由 CI 构建并下发：`web` job 上传 dist artifact，`deploy` job 打 tar.gz 经网关
`upload-dist` 动词送到 `/root/deploy/incoming-dist.tar.gz`，服务器解包到 `web/*/dist` 并跳过本机
npm 构建；文件缺失或比 bundle 旧时自动回退本机构建（回滚路径同样适用）。

## 前端样式约定：单一 token 源

`web/shared/design-tokens.scss` 是两个前端的**唯一**颜色/圆角/阴影/字号来源，取值对齐参考项目 Smartore（动作蓝 `#2563eb`、页面底 `#f5f7fa`、白卡 + 1px `#e5e7eb` + 8px 圆角、无阴影）。两端各自只做两件事：用 vite `resolve.alias` 的 `@tokens` 引入本文件，并各在一个入口 include 一次 `tokens-root`（生成 `:root` CSS 变量）；页面里不再出现裸 hex，历史变量名（`$color-gold`、`--gold`、`--accent` 等）保留为指向新调色板的别名。

Element Plus 的 CSS 必须先于应用主题加载（`main.js`/`main.ts` 里 `element-plus/dist/index.css` 在最前），否则主题层的覆盖会失效。管理端只有一层主题（`theme.scss` + `ai-page.scss`）；用户端只有一层（`styles/element-theme.scss` + `styles/variables.scss`）。移动皮肤与 PC 皮肤共用同一套 token，不再各建平行色板。

本轮Java检查使用限定本次命令的 `JAVA_TOOL_OPTIONS='-Xmx512m -XX:ActiveProcessorCount=2'` 与 `nice -n 10`；不改变其他项目设置，也不覆盖JaCoCo的argLine。Python合同测试的独立MySQL限制512MB/1CPU并由测试回收。前端测试可用 `npm --prefix web/admin run test -- --maxWorkers=1` 串行运行测试worker。资源不足时继续源码工作，按当前进程/健康事实判断，不能仅因一次超时就重启。
