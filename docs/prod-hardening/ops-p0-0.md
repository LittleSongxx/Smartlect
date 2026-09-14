# P0-0 运维小修：MySQL mem_limit 提升与应用日志轮转

日期：2026-09-14 ｜ 状态：**已完成** ｜ 环境：阿里云 ECS 北京 4c16g（39.107.102.244），compose project `smartlect`

## 做了什么

### 1. MySQL 容器 mem_limit 768m → 1g

- **背景**：实测 `smartlect-mysql-1: 621.8MiB / 768MiB (80.96%)`，逼近 cgroup 上限。MySQL 触发 cgroup OOM kill 后需要 crash recovery，事务恢复期间整站不可用——单机演示环境最现实的可靠性风险之一。
- **改动**：`deploy/compose.yaml` mysql 服务 `mem_limit: 1g`（commit `1c764e5`）。本地与服务器经 git bundle 同步（服务器 `git pull /root/deploy/s-p00.bundle main`），双端配置一致。
- **生效**：`systemctl restart smartlect-infra`。compose 检测到配置变化仅重建 mysql 容器；数据在命名卷 `mysql` 中，不受重建影响（RabbitMQ 卷同理未动）。

### 2. 应用日志轮转（此前完全无轮转）

- 新增 `/etc/logrotate.d/smartlect`：
  - 覆盖 `/opt/smartlect/run/logs/*.log`（13 个主日志：9 Java + growth API/worker + 2 前端）与 `/opt/smartlect/run/logs/*/nacos/*.log`（9 个服务的 nacos 客户端日志，同样无限增长）；
  - 参数：`weekly`、`rotate 8`、`compress`、`delaycompress`、`missingok`、`notifempty`、`copytruncate`；
  - **copytruncate 的原因**：日志句柄被运行中的 Java/Python 进程持有，rename 式轮转会让进程继续写入已改名文件（新文件永远为空）；copytruncate 先复制再原地清空，进程无感知。
- **nginx 日志**：发行版自带 `/etc/logrotate.d/nginx`（daily × 14、compress、postrotate reload）已覆盖 `/var/log/nginx/*.log`，保留发行版默认、不重复配置（原计划 weekly×8，实际已有更强配置）。
- sentinel 目录日志自带按日期滚动（`.2026-09-14` 后缀），不纳入。

## 怎么验证的（命令 + 实际输出）

```text
# 改动前（15:11）
$ docker stats --no-stream
smartlect-mysql-1: 621.8MiB / 768MiB 80.96%

# 重启 infra 生效后（15:30，buffer pool 预热中）
$ docker stats --no-stream | grep mysql
smartlect-mysql-1: 535.9MiB / 1GiB 52.33%        # 稳态 ~620MiB -> 约 62%，低于 75% 验收线

# 全栈健康门禁（runtime.py 自带：进程身份 + Nacos 注册 + Seata undo 表）
$ /usr/bin/python3 scripts/runtime.py apps-check
Application checks passed: thirteen owned healthy processes, nine Nacos registrations, eight Seata undo tables.

# logrotate 配置校验（dry-run）
$ logrotate -d /etc/logrotate.d/smartlect
rotating pattern: /opt/smartlect/run/logs/*.log /opt/smartlect/run/logs/*/nacos/*.log  weekly (8 rotations)
considering log /opt/smartlect/run/logs/smartlect-admin.log   ...（13 个主日志 + 36 个 nacos 日志全部识别）

# 强制轮转一次（验证真实行为）
$ logrotate -f /etc/logrotate.d/smartlect ; echo rc=$?
rc=0
$ ls -lh run/logs/smartlect-order.log*
-rw-r--r-- smartlect-order.log.1  291K  (轮出的旧内容)
-rw-r--r-- smartlect-order.log      0   (原地清空，进程继续写入同一 inode)

# 前端入口
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18180/
200
```

## 遇到的坑

1. **`systemctl restart smartlect-infra` 会联动重启 smartlect-apps**（systemd 依赖传播），整体恢复约 5 分钟（15:16 下令 → 15:21 apps active → apps-check 全绿）。中间件维护要预留这个窗口，不是「只动容器不动应用」。
2. 重启后立即跑 apps-check 会得到 `not registered` / `HTTP 000`——那是恢复途中的正常现象，等单元 active 后再验，以免误判故障。
3. 一次长轮询 SSH 会话（40×10s 等待循环）无输出挂起，新开连接重跑立即正常——远程验证类命令应自带 `timeout`，别裸等。
4. mem_limit 变更后 docker stats 立即读数是冷缓存值（458MiB），会随 buffer pool 预热回升；判断余量要看稳态值对照新 limit。

## 面试一句话

巡检发现 MySQL 容器内存达 cgroup limit 的 81%（OOM 即 crash recovery），将 mem_limit 提至 1g 并补齐缺失的日志轮转（copytruncate 处理持有句柄的 Java 进程），以 docker stats 水位、强制轮转、全栈健康门禁三重验证收口，配置经 git bundle 双端同步保持一致。
