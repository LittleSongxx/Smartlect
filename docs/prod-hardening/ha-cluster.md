# 跨机集群形态：搭建、演练、单机对比与常驻收官（ha-cluster）

日期：2026-09-15 ｜ 状态：**常驻集群已全量上线**（node1 升配 8c32g、JVM 调优、800 VU 钉板，见文末「常驻收官」节）
证据：本目录 `cluster-evidence/`（演练时间线日志、双形态压测曲线 CSV、sentinel 探针全量记录）；收官压测在服务器 `/opt/cluster/evidence/loadtest-20260915-1049/`（8 份 k6 日志 + 曲线 CSV + 窗口戳）

## 目标与结论

用 3 台 ECS（现有 4c16g + 科创包新购 2×2c8g，同 VPC 内网互通、安全组仅内网放行业务端口）把中间件从单机提升为跨机集群，产出三类真实证据后回退单机：

1. **故障演练**：RabbitMQ leader 击杀 11 秒完成 quorum 重选举、发布端 1 秒内多地址重连、**2430 发 = 2430 收零丢失**；Redis 主库击杀 sentinel **1.06 秒完成切主**、探针 150 请求仅 1 次超时、应用零重启自动跟随；Nacos 逐节点击杀服务发现不中断。
2. **双形态压测**：同压测机、同阶梯（100/200/400 VU），集群形态 QPS **+50%~89%**、p95 **-36%~-69%**；400 VU 饱和时单机开始抛错（2.2%）而集群形态零错误优雅排队。
3. **可回退**：全程不动旧数据卷（RabbitMQ 拓扑走 defs 导入而非改卷），回退单机 10 分钟、apps-check 全绿。

## 集群拓扑

```
smartlect-node1 (8c16g, 172.21.131.151)   现有机：全部应用进程 + MySQL(主) + Redis(主*)
                                            + rabbit-c1 + nacos-c1 + sentinel ×1
smartlect-node2 (2c8g, 172.19.34.202)     新购：rabbit-c2 + nacos-c2 + Redis 副本 + sentinel
smartlect-node3 (2c8g, 172.19.34.203)     新购：rabbit-c3 + nacos-c3 + Redis 副本 + sentinel
```

- **RabbitMQ 3 节点 quorum 集群**（rabbitmq:4.2.9，host 网络）：58 个业务队列全部 `x-queue-type: quorum`，Raft 3 副本跨三机；`pause_minority` 分区策略。
- **Redis 1 主 2 副本 + 3 Sentinel**（quorum 2，down-after 5s）：演练后主漂移到 node3，拓扑自动收敛回 1m2s。
- **Nacos 3 节点集群**（v2.5.3，host 网络 8848/9848/7848，Raft）：共用 node1 MySQL 的 `smartlect_nacos` 库，配置零迁移。
- MySQL 保持单机（binlog + PITR 已覆盖；主从列为演进项）。

## 零代码切换设计（关键决策）

应用全是宿主机进程经 `runtime.env` 注入连接串，因此切集群**不改一行业务代码**：

| 组件 | 单机 | 集群 | 机制 |
|---|---|---|---|
| Java → RabbitMQ | `spring.rabbitmq.host/port` | `SPRING_RABBITMQ_ADDRESSES=a:5672,b:5672,c:5672` | Spring 属性优先级：addresses 覆盖 host/port |
| Java → Redis | `spring.data.redis.host/port` | `SPRING_DATA_REDIS_SENTINEL_MASTER/NODES` | Lettuce sentinel 感知，切主自动跟随 |
| Java/Seata → Nacos | 单地址 | `SMARTLECT_NACOS_ADDR=a,b,c` 逗号列表 | Nacos 客户端原生多地址 |
| Growth(pika) → RabbitMQ | 单地址 | 指向 c2 | pika 单端点 + 已有重连循环 |

支撑改动仅两处仓库文件：`scripts/runtime.py`（`verify_project` 允许同 checkout 的 compose override；`infra_check` 增加集群形态分支：AMQP 端点探活替代单容器健康、Nacos 取首个成员发请求——改动后 `./scripts/dev.sh check` 全绿再上线）；`deploy/seata/application.yml`（registry 地址参数化 `${SMARTLECT_NACOS_SEATA_ADDR:nacos:8848}`，默认值即单机形态）。服务器端用 `deploy/compose.cluster.yaml` override：mysql/redis 加内网绑定、旧 rabbit/nacos 挂 inactive profile（**数据卷原样保留，回退即恢复**）。

## 故障演练（真实击杀 + 时间线取证）

### ① RabbitMQ：leader 击杀 → quorum 重选举（drill-rabbit.log）

```
[02:46:21] leader of smartlect.rushing.order.queue: rabbit@smartlect-node2
[02:46:23] KILL rabbit-c2（docker stop）
[02:46:34] t+2s 采样：running_nodes=2，new_leader=rabbit@smartlect-node1   ← 含 docker stop 耗时，重选举实际 <2s
[02:46:42] 重启被杀节点，集群自愈回 3 节点
```

零丢失对账（drill-zeroloss.log，向 c1 持续发布 quorum 消息中途击杀 c1）：

```
[02:56:34] publish error (StreamLostError), reconnecting...
[02:56:34] reconnected -> 172.19.34.202        ← 1 秒内客户端多地址切换
TOTAL_SENT=2430 / TOTAL_RECEIVED=2430 / ZERO_LOSS=PASS
```

### ② Redis：主库击杀 → sentinel 故障转移（drill-redis.log）

```
02:58:12.259 # +sdown master mymaster 172.21.131.151 6379     ← kill 后 5s 判定（配置 down-after=5000）
02:58:12.337 # +odown master ... #quorum 3/2                   ← 3 个 sentinel 仲裁达成
02:58:13.321 # +switch-master mymaster ... 172.19.34.203 6379  ← sdown→新主全程 1.06s
```

应用侧：nginx→gateway 探针每 300ms 一次走 Redis 限流链路，**150 请求仅 1 次超时**（发生在 5s 探测窗口内），Lettuce 经 sentinel 自动跟随新主、**应用零重启**。旧主重启后被 sentinel 自动降级为副本，终态 1 主 2 副本收敛（node1 副本需 `--masterauth`，已随 override 固化）。途中补了一课：单机设计的 master 容器没有 masterauth，降级后连不上新主——跨机主从要求所有成员互为认证。

### ③ Nacos：逐节点击杀 → 发现不中断（drill-nacos.log）

```
杀 c2(follower)：c1 readiness 10/10，发现服务持续
杀 c1（客户端地址表首位）：gateway 经 nginx 仍 HTTP 200/0.06s（客户端多地址自动切换）
干净窗口单杀 c3：c1/c2 readiness 各 10/10
```

## 双形态阶梯压测（A/B）

方法：压测机独立于被测机（k6 部署在 node2/node3 双发、走内网打 node1 nginx，排除 T0-4 中"压测机抢应用 CPU"的干扰）；场景同为 browse 全链路（nginx→gateway→Java→MySQL/Redis）；阶梯 100→200→400 VU，每档 100s；同一晚背靠背执行。

| 并发 | 形态 | QPS（k6 口径） | p95 | p99 | 错误率 | node1 CPU |
|---|---|---|---|---|---|---|
| 100 VU | 集群 | **85** | **1.41s** | 2.24s | 0% | ~99% |
| 100 VU | 单机 | 45 | 4.58s | — | 0% | ~99% |
| 200 VU | 集群 | **103** | **4.38s** | 5.92s | 0% | 97-98% |
| 200 VU | 单机 | 62 | 8.76s | — | ≈0% | ~99% |
| 400 VU | 集群 | **109** | **8.64s** | — | **0%** | 97-98% |
| 400 VU | 单机 | 73 | 13.4s | — | **2.2%** | ~99% |

- **拐点**：集群形态 ~100 VU（85 req/s，p95 破 1s）；单机形态 100 VU 即 p95 4.6s。
- **平台**：集群 QPS 平台 ~109，比单机（~73）高 50%；两形态 node1 CPU 都在 99% 打满——**瓶颈都在应用机的 4 核**，集群的增益来自把 Redis 主/Rabbit 仲裁/Nacos 仲裁与消息收发移出应用机、以及中间件端口直连（去掉 docker-proxy 跳数）。
- **饱和行为差异最有说服力**：400 VU 下单机开始 2.2% 报错（连接积压垮掉），集群形态零错误纯排队——过载时先变慢、不变错。
- Prometheus 曲线（cluster-ramp.csv / single-ramp.csv）：集群形态 200/400 VU 档内部请求速率 144-147/s vs 单机 113/s；集群形态下 node2/3 CPU 仅 15-21%（读写链路本来就不重、扩的是可用性与隔离性，不是浏览吞吐——这是本次实测对"集群为什么"最诚实的回答）。

## 成本与运维事实

- 新购 2×2c8g 经济型按量（科创包抵扣 ¥0.383/h/台）；演练期成本 <¥2。集群后转**常驻**（node2/3 保持开机，编排保留在服务器 `/opt/cluster/`，含已验证一次的 `revert.sh` 全套回退）。
- 切换窗口（停应用到恢复）：首次 01:53→02:23 约 30 分钟（含 runtime.py/seata 两处热修）；回退 03:23→03:33 仅 10 分钟、apps-check 全绿。
- 坑位实录：compose override 改容器标签触发 runtime.py「外来 checkout」保护（改为允许同 checkout 叠加文件）；seata 注册地址硬编码 docker 网络名（参数化修复）；VT100 画框输出解析 quorum leader；`down --remove-orphans` 误杀同项目他目录容器（集群编排共享 project 名的教训）；单机 redis 容器缺 masterauth。

## 常驻收官（2026-09-15）：升配、JVM 调优与 800 VU 钉板

集群转常驻后对 node1 停机变配 **4c16g → 8c32g**，重启后三组件全部自愈（RMQ 3 节点/59 队列无分区、quorum 3/3 voter；Nacos 3/3 readiness；Redis 经定向 failover 主回 node1、1m2s+3 sentinel 收敛；apps-check 13 进程全绿）。随后一步到位注入 JVM 三键（`SMARTLECT_JAVA_XMS=512m / XMX=512m / PROCESSORS=4`，runtime.env，无代码改动），`ps` 验证 9 个 JVM 全部 `-XX:ActiveProcessorCount=4 -Xms512m -Xmx512m`。

### 升配后四档压测（node2/3 双发 k6 打 node1，HOLD=100s/档）

| 总并发 | 尝试 req/s | 实际服务 req/s | p95 | 错误率 | node1 CPU | node2/3 CPU |
|---|---|---|---|---|---|---|
| 100 VU | 124 | 124 | **24ms** | 0% | 26-44% | 15-19% |
| 200 VU | 248 | 245 | **21ms** | 1.3%（429） | 38-42% | 17-23% |
| 400 VU | 497 | 349 | **40ms** | 29.9%（429） | 42-48% | 22-30% |
| 800 VU | 972 | 515 | **190ms** | 47.0%（429） | 52-57% | 26-38% |

与升配前（4c16g + 默认 JVM，同为集群形态）对比：

| 并发 | 旧 QPS / p95 / node1 CPU | 新 QPS / p95 / node1 CPU |
|---|---|---|
| 100 VU | 85 / 1.41s / ~99% | **124（+46%）** / 24ms（-98%）/ ~35% |
| 200 VU | 103 / 4.38s / 97-98% | **245（+137%）** / 21ms / ~40% |
| 400 VU | 109 / 8.64s / 97-98% | **349（+220%）** / 40ms / ~45% |

### 极限结论：瓶颈已从 4 核 CPU 移到网关限流器（配置值）

- **极限不再上移的机制**：400/800 VU 的全部"错误"都是网关 Sentinel 限流的 **429**（`SentinelGatewayConfig`：`web-api` 分组与每服务路由均 `default-qps=200`）。800 VU 峰值分钟 nginx 口径 API 成功量 **恰为 12000/分钟 = 200.0 req/s 整**，多出的 570 req/s 被干净甩载，**零 5xx、无级联、压后 apps-check 立即全绿**。
- **拐点**：约 150-200 req/s（API 口径）——低于它零错误、p95≤24ms；高于它过载请求被 429 而非排队。旧形态是"全放进来然后爬到 8.6s"，新形态是"顶格 200 放行 + 秒拒超出"，保护性严格更优。
- **表观吞吐**（含不过网关的静态首页，nginx 直接服务）：800 VU 下 ~585 req/s，node1 CPU 仅 57%——**8c32g 远未饱和，资源天花板未探到**。下一步扩容杠杆是把 `smartlect.gateway.rate-limit.default-qps` 上调（Spring 属性，env 可覆盖、无需改码）后复测；按 CPU 曲线外推，当前硬件 API 上限约在 350-400 QPS。
- node2/3（压测机兼集群成员）峰值 CPU 38% < 60% 阈值，**无需扩容**。

### 解除限流复测（同日）：真实极限 ~600 req/s，真炸弹在监控栈

方法：`runtime.env` 注入 `SMARTLECT_GATEWAY_RATELIMIT_DEFAULTQPS=2000`（Spring 宽松绑定，零代码改动），300 VU 探针确认解除（0 失败，旧限流下必出 429）后复跑同款压测 + 600/1600 VU 补档；测毕删除键恢复 200 限流（探针 429 重现 14.6% 确认）。

| 并发 | req/s（k6 全档均值） | p95 | p99 | 错误 | node1 CPU（hold 段） |
|---|---|---|---|---|---|
| 100 VU | 124 | 20ms | 26ms | 0 | 22-30% |
| 200 VU | 249 | 22ms | 36ms | 0 | 38-46% |
| 400 VU | 486 | 93ms | 344ms | 0 | 66-69% |
| 600 VU | **605** | 858ms | 1.25s | 0 | 72-78% |
| 800 VU | 582 | 1.67s | 2.13s | 0 | 74-80% |
| 1600 VU | 501* | 3.67s* | 4.24s | ~0 | 崩溃窗口* |

\* 1600 VU 档后期宿主被 Jaeger OOM 拖入假死（见下），吞吐/延迟数字含污染，仅作崩溃实证。

- **真实极限 = 600 VU / 605 req/s（零错误）**；400 VU（486 req/s、p95 93ms、CPU<70%）是"健康顶格"。800 VU 起吞吐回落、延迟陡升——过峰**纯排队劣化，全程零 5xx**。
- node1 CPU 峰值 80% 未打满：约束在应用层内部（9 JVM × processors=4 的线程预算、池与 GC），不是机器核数；node2/3 全程 ≤35%。
- **真系统级瓶颈在监控栈**：Jaeger all-in-one 的 `SPAN_STORAGE_TYPE=memory` 无上界，600 req/s 级持续追踪下 RSS 涨到 **19.4GB** 触发 node OOM——宿主用户态假死 12 分钟（ICMP 通、TCP 握手通、banner/HTTP 全超时），且在压测结束**数分钟后**才引爆（延迟引爆，极易误诊为压测后遗症之外的问题）。修复：`MEMORY_MAX_TRACES=200000` + `mem_limit: 4g` 双保险（超限只杀容器自身）。
- 意外实测了一次"node1 应用栈不可用"集群自愈：sentinel 5s 判定切主到 node3；RMQ/Nacos 进程未退出、拓扑不变（用户态饿死而非宕机）；事后定向 failover 零丢失切回。
- 与限流态同档对比（800 VU）：限流态服务 515 req/s / p95 190ms vs 解除态 582 req/s / p95 1.67s——**限流器用 12% 吞吐换 9 倍尾延迟与过载保护**，200 QPS 出厂值合理；若业务需要更高容量，上调 `default-qps` 的同时应同步关注 400-600 req/s 区间的池与 GC 调优。



### 瓶颈归因与第二轮优化（连接池 4→12）：真极限 ~815 req/s，CPU 打满

第一轮的 605 req/s"极限"其实是**假墙**。用 Micrometer/Prometheus 回查压测窗口（actuator 暴露 prometheus 端点，历史数据零成本取证），饱和点铁证：

| 档位 | product Hikari active | 等连接排队数 | 最长等连接 | k6 p95 |
|---|---|---|---|---|
| 200 VU | 3/4 | 0 | 28ms | 22ms |
| 400 VU | **4/4 钉满** | 12 | 462ms | 93ms |
| 600 VU | 4/4 | **176** | **859ms** | 858ms |
| 800 VU | 4/4 | 195 | 987ms | 1.67s |

**k6 尾延迟 ≈ Hikari 等连接时间**（859ms≈858ms 对到毫秒）。因果链：browse 流量全压 product → `SMARTLECT_DB_POOL_MAX_SIZE` 默认 4 条 MySQL 连接串行服务 → 池满排队 → Tomcat 200 线程被等连接的请求塞满（800 VU 时恰好 active=200）→ 吞吐封顶 4 连接×(1000/6ms)≈605。

修复=一行 env：`SMARTLECT_DB_POOL_MAX_SIZE=12`（配置注释本就预留此杠杆；预算核对：10 服务×12=120 + nacos/growth/exporter≈20 < MySQL max_connections 200（compose 已从 160 提到 200），池 min-idle=1 空闲自动回缩）。第二轮结果：

| 负载档 | req/s | p95 | 备注 |
|---|---|---|---|
| browse 400 VU | 488 | 63ms | 需求受限（思考时间），健康 |
| browse 600 VU | 664 | 465ms | 进入拐点区 |
| browse 800 VU | 753 | 1.15s | 贴墙 |
| **hot 400 VU**（无思考时间变体） | **822** | 1.65s | 硬墙 |
| hot 800 VU | **810** | 2.43s | **2× VU 吞吐不增=钉死** |

- **真极限 ≈ 810-820 req/s（k6 口径）**：第二轮取证 node1 CPU **87-90%**——终于打到算力本身；product Hikari 11/12、排队≈0（池不再约束）；MySQL CPU 2%、gateway 在飞 488（反应式无压）；全程零失败，过载仍是纯排队劣化。**假墙 605 → 真墙 815（+35%），生产限流同步定格 `DEFAULTQPS=400`**（旧值 2 倍；位于拐点 443 API req/s 下沿、健康区 325 上方，p95 全程 ≤~90ms）。
- 墙后的下一排杠杆（按性价比）：给 gateway/product 更高 JVM 处理器预算（现 9 JVM 统一 processors=4，需 runtime.py 支持每服务覆盖——小改，未做）；nginx→gateway 加 upstream keepalive（省每请求握手）；product 查询与缓存效率（热路径直查 MySQL）；Jaeger 已限 4g 内存（本轮 hot 压测吃满 3.34g 未再威胁宿主）。

### 收官期运维实录（四条新教训）


1. **手动 `REPLICAOF` 会和 sentinel 打架**：node1 重启期间 sentinel 自动把 Redis 主漂到 node3；手动 REPLICAOF 回切被 sentinel 判定为主失效、触发自己的 failover（主落到 node2）。正确做法是**定向 failover**：非目标副本 `CONFIG SET replica-priority 0` → `SENTINEL FAILOVER mymaster` → 目标副本当选 → 恢复 priority=100。本次按此法一次成功，主回 node1、1m2s 收敛。
2. **RabbitMQ 4.2 无 `rabbitmqctl quorum_status`**：命令在 `rabbitmq-queues` CLI 且必须带 `--vhost smartlect`（verify-cluster.sh 的旧调用会 `not found` 退出）。
3. **重启竞态的 nacos 变体**：apps 的 runtime.py 预检在 nacos-c1 重组 Raft 期间拿到 503 而失败——等 readiness 200 后 `systemctl restart smartlect-apps` 即愈（seata 变体此前已用 `Restart=on-failure` 根治，nacos 变体目前手动恢复）。
4. **打极限前先给旁路系统设上界**：压测打爆的第一台"服务"是旁路的 Jaeger（memory 存储 19.4GB → node OOM、宿主假死 12 分钟、压测结束数分钟后才引爆）。任何全链路压测前，追踪/日志/指标栈的内存上限是前置条件；症状识别口诀——ICMP 通 + TCP 握手通 + banner 超时 = 用户态饿死（内存），而非网络或 conntrack 问题。

### 规格回调附记（2026-09-16）：8c32g → 8c16g

科创包仅覆盖 ≤8c16g 档，node1 回到 8c16g（8c32g 时期数据全部保留为历史基线）。同步回调：全局堆 512m→256m（gateway/product 保持 512m/6 处理器，其余 256m/4）、Jaeger 上限 4g→2g（max-traces 20 万→10 万）、MySQL 容器维持 512M 池/2g 上限。**复测（池 12 + 限流 400 不变）：400 VU = 495 req/s、p95 23ms、1% 网关 429、内存 10/14Gi 余 3.8Gi——限流 400 在半内存下依然安全**。另录两个重启坑：变配重启后 PID 复用会撞 runtime.py 进程台账（`run/processes.json` 清空即愈，备份 .stale-bak）；nacos 503 竞态照旧等 readiness 后 restart。

## MySQL 主从与全栈 HA 演进（2026-09-15 傍晚补齐）

### MySQL 异步主从：node1（源）→ node2（只读副本）

- **形态**：node2 `/opt/cluster/mysql-replica/`（compose 项目 `cluster`，host 网络，`mysql-replica` 容器 server-id=2，绑 172.19.34.202:13307，`read_only+super_read_only` 持久化开启）；源库零改动（binlog ROW 本就为 PITR 开着，`repl@172.19.34.%` 复制账号，经典 file+position 位点，GTID 关闭）。
- **验证**：IO/SQL 双线程 Yes、`Seconds_Behind_Source=0`；写入探针（源建表插入）3 秒内副本可见，删除同步同验。
- **踩坑实录**（搭建过程全部踩过）：① 复制通道密码上限 32 字符（账号本身可更长，通道不行）；② `caching_sha2_password` 非 TLS 通道必须 `GET_SOURCE_PUBLIC_KEY=1` 做 RSA 交换；③ 在源库 `ALTER USER` 会随 binlog 复制到副本，副本没有该用户则应用线程停摆——副本要预建复制账号；④ 副本绑内网地址后健康探针要带 `-h <内网IP> -P <端口>`。

### 故障切换手册（手动，无自动切换组件）

```bash
# 常态巡检（延迟应恒为 0）：
ssh root@47.93.9.163 "printf 'show replica status\\G\n' | docker exec -i mysql-replica \
  sh -c 'MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -uroot'" | grep -E 'Replica_.*Running:|Seconds_Behind'
# 切换（node1 MySQL 不可恢复时）：
#  1) node2: STOP REPLICA; RESET REPLICA ALL; SET GLOBAL super_read_only=OFF; （副本转正）
#  2) 改 runtime.env 的 SMARTLECT_MYSQL_HOST/PORT → 172.19.34.202/13307；
#     ★ 最大重定向面是 Nacos：nacos-c1/2/3 的 spring.datasource 都指向 node1 MySQL，需同步改
#     （/opt/cluster/nacos*/conf 或环境注入）——这就是"依赖链"的代价
#  3) systemctl restart smartlect-infra smartlect-apps；apps-check 验证
#  4) node1 恢复后作为新副本对称挂回（重做快照或反向克隆）
```

RPO = 复制延迟（常态 0 秒）；RTO = 手动切换时长（分钟级，演练待做）。

### 全栈 HA（应用多副本）设计稿——下一阶段的施工图

前置改造（按序）：① **上传共享化**：`run/uploads` 挪 NFS（node2 导出）或对象存储，`SMARTLECT_PROJECT_FOLDER` 已参数化；② **注册真实 IP**：Spring 注册 Nacos 的 IP 现为 127.0.0.1，集群形态需暴露内网 IP；③ runtime.py 支持 node2 侧 launch（或 node2 独立 systemd 单元拉同一 JAR）。

实施顺序（风险从低到高）：growth 第二实例（node2:18001 进 nginx upstream；DB 租约已防双跑，admission 闸按实例计数=上限×N）→ web-user/admin + gateway 多后端（无状态）→ Java 服务第二副本（定时任务已有 Redis 锁，双实例安全）→ 全链路演练。中间件（RMQ/Redis/Nacos/MySQL）已全部跨机，就差应用层这一块。




- 应用层未跨机：9 个 Java 服务仍单机部署（Spring Cloud 注册 IP 为 127.0.0.1）。本次集群化对象是中间件数据面/控制面——对应"消息零丢失、配置发现不中断、缓存热切"三类真实故障；应用层多副本需要会话/幂等键跨机化，是下一阶段。
- MySQL 主从已于 2026-09-15 补齐（node2 只读副本，见上节）；备份+PITR 继续作为第一恢复手段（见 backup-restore-drill.md）。
- 压测负载含 3 个 HTTP 请求/迭代（首页+目录+商品页），"QPS"为 k6 请求口径；两形态口径一致，对比有效。
