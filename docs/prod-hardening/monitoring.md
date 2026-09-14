# T0-1 监控告警体系（Prometheus + Grafana + Alertmanager）

日期：2026-09-14 ｜ 状态：**主体完成，2 个开口项**（SMTP 投递凭证、Growth FastAPI 指标） ｜ 部署：`/opt/monitoring`（compose project `monitoring`，独立于 smartlect 主栈）

## 做了什么

### 架构

```
9×Java /actuator/prometheus (18080-18108, loopback)
node-exporter :9100 (含 textfile: 容器内存水位 + growth 进程心跳)
mysqld-exporter :9104 ──┐
redis-exporter :9121    ├─→ Prometheus :9090 (15s/30s 采集, 30d 保留)
rabbitmq-exporter :9419 ┘        │ 告警规则 7 条
                                  ↓
                        Alertmanager :9093 → 邮件 SMTP（凭证待接线）
                        Grafana :3000 (127.0.0.1, 匿名 Viewer + admin 密码在 env)
```

- 全部容器 `network_mode: host` + 显式 loopback 监听（必须 host 网络：Java/MySQL/Redis/Rabbit 都只绑 127.0.0.1，桥接网络触达不了宿主 loopback）。rabbitmq-exporter 镜像无监听地址参数（绑 0.0.0.0:9419），靠安全组只放行 22/80/443 兜底。
- systemd 单元 `smartlect-monitoring.service`（对齐 smartlect-infra 模式，`up -d --wait` + 开机自启）。
- 凭证全部在 `/opt/monitoring/env`（600）与 `mysql-mon.cnf`（400, owner=nobody）：MySQL `mon` 账号（PROCESS/REPLICATION CLIENT/SELECT）、RabbitMQ `mon` 账号（monitoring 标签 + 业务 vhost 空权限，仅 API 只读）、Grafana admin 随机密码。均不入库不入图。
- textfile 采集：cron 每分钟 `docker stats` → `smartlect_container_mem_bytes/limit_bytes`；`pgrep` → `smartlect_process_up{growth-worker,growth-api}`。这是「MySQL 超 limit 90%」「growth worker 心跳丢失」两条告警的数据源，也是目前容器级内存唯一采集手段（未上 cAdvisor，避免 gcr.io 拉不动）。

### 大盘（Grafana `Smartlect 全栈总览`，13 面板）

顶部 stat：Java 目标在线(9) / 5xx 比例 / growth worker 心跳 / 最小 uptime / 死信总数。时序：HTTP QPS 按服务、JVM 堆 used/max、GC 暂停速率、MySQL 连接+慢查询、Redis 命中率、RabbitMQ 队列深度 Top10（含 `smartlect.growth.commerce.queue` 与 dead 队列）、容器内存/limit（红线 90%）、主机 CPU/磁盘（红线 80%）。
截图：`figures/monitoring-dashboard.png`。业务面板（LLM 成本/质量）属 T1-5，不在本大盘。

### 告警规则（alerts.yml，7 条起步）

| 规则 | 条件 | for | 依据 |
|---|---|---|---|
| SmartlectServiceDown | 任意采集目标 up==0 | 1m | 依赖 15s/30s 采集周期 |
| SmartlectGateway5xxRateHigh | 5xx 占比>1% | 5m | 单机演示站的合理噪声门限 |
| SmartletQueueBacklog | 任一队列 ready>100 | 5m | growth worker 单进程消费能力 |
| SmartlectDeadLetter | 任一 dead 队列>0 | 5m | 死信=需要人工介入 |
| SmartlectMySQLNearMemLimit | 容器内存>limit 90% | 5m | P0-0 事故前置量 |
| SmartlectGrowthWorkerDown | worker 心跳==0 | 2m | textfile 1min 粒度×2 |
| SmartlectDiskUsageHigh | 根盘>80% | 10m | 40G 盘、备份将占空间（T0-2） |

## 怎么验证的

```text
# 13 个采集目标全部 up（9 Java + node/mysqld/redis/rabbitmq）
$ curl -s :9090/api/v1/targets   → 13×up
mysql_up 1 ; redis_up 1 ; rabbitmq_up 1
redis_keyspace_hits_total/(hits+misses) = 0.972 ; mysql_global_status_threads_connected = 15
rabbitmq_queue_messages_ready 59 个队列标签（含 commerce/dead 队列）

# 故障注入闭环（验收项）
16:26:11 docker pause smartlect-rabbitmq-1
16:28:46 Alertmanager API: alert count:1
         active SmartlectServiceDown | 采集目标失联: 127.0.0.1:9419 (job=rabbitmq)
16:28:46 docker unpause
16:30:06 Alertmanager API: alert count: 0（恢复）；应用 curl 200（Java 自动重连，无需重启）

# 大盘：headless Chromium 经 SSH 隧道截图，13 面板有数据（figures/monitoring-dashboard.png）
```

## 遇到的坑（按耗时排序）

1. **端口映射反直觉**：宿主 15672→容器 5672(AMQP)，管理 API 在宿主 **15674**；MySQL 宿主端口 **13306**、Redis **16379**。exporter 全按默认端口配的全军覆没，`docker port <c>` 才是真相。
2. **kbudde/rabbitmq-exporter 的三连坑**：① `RABBIT_URI` 是老约定，RC12 要 `RABBIT_URL/RABBIT_USER/RABBIT_PASSWORD`（密码变量不是 `RABBIT_PASS`）；② 默认 bert 二进制协议在 RabbitMQ 4.2 上解析失败（每队列指标全丢、只留全局聚合），`RABBIT_CAPABILITIES=no_sort` 强制 JSON 才好；③ monitoring 标签不够列队列——还需在业务 vhost `set_permissions`（空正则=可访问不可读写）。该 exporter 已归档 EOL，长期方案是 RabbitMQ 4 原生 `rabbitmq_prometheus` 插件（15692），记入迁移项。
3. **mysqld-exporter v0.15.1 删掉了 DSN 环境变量**（`DATA_SOURCE_NAME` 和 `MYSQLD_EXPORTER_DATA_SOURCE_NAME` 都无效），凭证只认 `--config.my-cnf`；且 `.my.cnf` 是 root:600 时镜像内 nobody 用户读不了（permission denied），需 chown 65534。
4. **redis_exporter v1.66 不认 `redis://` scheme**（`dial redis: unknown network redis`），裸 `host:port` 即可。
5. **shell 提取密码的 sed 锚点错误**：`^mon:` 匹配不到 `MYSQL_MON_DSN=mon:...` 整行，导致整行被当密码写进凭证文件（cnf 121 字节露馅）。密码处理要么 `cut -d= -f2-` 先剥变量名，要么直接重置。
6. SSH 长会话会挂死（compose 拉镜像期间 transport timeout）——重负载操作交给 systemd 单元跑，SSH 只查询。
7. 首次 `up -d --wait` 因两个 exporter 失败把单元判 failed，但 restart:unless-stopped 的容器仍在——先修容器再 `systemctl restart` 清状态。

## 开口项（下回接续）

- [ ] **SMTP 投递**：Alertmanager email_configs 已预留占位（smtp.qq.com:465），等用户提供邮箱+授权码后替换 `/opt/monitoring/alertmanager.yml` 并 `systemctl restart smartlect-monitoring`；然后补一次 pause 演练验证「收到邮件」+ send_resolved。
- [ ] **Growth FastAPI 指标**：`prometheus-fastapi-instrumentator` 接入 growth API（growth 代码改动 → 本地 `./scripts/dev.sh check` 全绿 → bundle 同步 → 重启 apps）。growth-worker 已有 textfile 心跳兜底。
- [ ] Alertmanager 静默/路由分档（warning vs critical）暂未做，规则起来后再按实际噪声调整。
- [ ] kbudde exporter 归档风险：迁移到原生 rabbitmq_prometheus 插件（需给 rabbit 容器发布 15692 端口，动 deploy/compose.yaml，放 T1-6/T2-9 一并考虑）。

## 面试一句话

从零搭起单机全栈监控：Prometheus 采集 13 个目标（9 Java actuator + 中间件 4 exporter + 自研 textfile 心跳），Grafana 13 面板大盘，7 条告警规则用「docker pause rabbitmq → Alertmanager 告警 → unpause → 自动恢复」完成故障注入闭环验收；过程中排掉 RabbitMQ 4 管理端口映射反转、kbudde exporter 三处版本坑、mysqld-exporter 移除环境变量等连环问题，全部以实捕获的告警与截图留证。
