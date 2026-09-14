# 跨机集群形态：搭建、演练与单机对比（ha-cluster）

日期：2026-09-15 ｜ 状态：**已完成并切回单机**（集群形态按需可 15 分钟内重建）
证据：本目录 `cluster-evidence/`（演练时间线日志、双形态压测曲线 CSV、sentinel 探针全量记录）

## 目标与结论

用 3 台 ECS（现有 4c16g + 科创包新购 2×2c8g，同 VPC 内网互通、安全组仅内网放行业务端口）把中间件从单机提升为跨机集群，产出三类真实证据后回退单机：

1. **故障演练**：RabbitMQ leader 击杀 11 秒完成 quorum 重选举、发布端 1 秒内多地址重连、**2430 发 = 2430 收零丢失**；Redis 主库击杀 sentinel **1.06 秒完成切主**、探针 150 请求仅 1 次超时、应用零重启自动跟随；Nacos 逐节点击杀服务发现不中断。
2. **双形态压测**：同压测机、同阶梯（100/200/400 VU），集群形态 QPS **+50%~89%**、p95 **-36%~-69%**；400 VU 饱和时单机开始抛错（2.2%）而集群形态零错误优雅排队。
3. **可回退**：全程不动旧数据卷（RabbitMQ 拓扑走 defs 导入而非改卷），回退单机 10 分钟、apps-check 全绿。

## 集群拓扑

```
smartlect-node1 (4c16g, 172.21.131.151)   现有机：全部应用进程 + MySQL(主) + Redis(主*)
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

- 新购 2×2c8g 经济型按量（科创包抵扣 ¥0.383/h/台）；全程开机 ~2h，集群体验成本 <¥2。演练+压测完成后已停机（控制台可再开机，编排保留在服务器 `/opt/cluster/`）。
- 切换窗口（停应用到恢复）：首次 01:53→02:23 约 30 分钟（含 runtime.py/seata 两处热修）；回退 03:23→03:33 仅 10 分钟、apps-check 全绿。
- 坑位实录：compose override 改容器标签触发 runtime.py「外来 checkout」保护（改为允许同 checkout 叠加文件）；seata 注册地址硬编码 docker 网络名（参数化修复）；VT100 画框输出解析 quorum leader；`down --remove-orphans` 误杀同项目他目录容器（集群编排共享 project 名的教训）；单机 redis 容器缺 masterauth。

## 边界与演进

- 应用层未跨机：9 个 Java 服务仍单机部署（Spring Cloud 注册 IP 为 127.0.0.1）。本次集群化对象是中间件数据面/控制面——对应"消息零丢失、配置发现不中断、缓存热切"三类真实故障；应用层多副本需要会话/幂等键跨机化，是下一阶段。
- MySQL 未做主从：备份+PITR 已覆盖（见 backup-restore-drill.md）；补 async 复制即可演进。
- 压测负载含 3 个 HTTP 请求/迭代（首页+目录+商品页），"QPS"为 k6 请求口径；两形态口径一致，对比有效。
