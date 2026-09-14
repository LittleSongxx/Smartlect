# T0-2 备份与 PITR 恢复演练

日期：2026-09-14 ｜ 状态：**已完成**（全量备份 cron 上线 + PITR 恢复实测闭环，RTO/RPO 见下） ｜ 组件：MySQL 8.4.11（compose 容器 `smartlect-mysql-1`，数据卷 `smartlect_mysql`）

## 做了什么

### 1. 每日备份管道（已上线）

- 脚本：服务器 `/opt/backups/bin/backup.sh`（本地副本 `run/cloud/backup.sh`，gitignored），cron `/etc/cron.d/smartlect-backup` **每日 03:30**。
- 全量：`mysqldump --single-transaction --set-gtid-purged=OFF --source-data=2 --databases <11 schema>` → gzip 到 `/opt/backups/mysql/full-<时间戳>.sql.gz`。
  - `--single-transaction`：InnoDB 一致性快照，不锁业务；`--source-data=2` 把 binlog 文件+位点以注释写进 dump 头（PITR 锚点）；GTID 未启用故 `--set-gtid-purged=OFF` 避免恢复端报错。
  - 11 schema = smartlect_{user,product,stock,cart,order,pay,coupon,admin,growth,nacos,seata}。
- 增量（binlog 副本）：binlog 默认开启（ROW 格式，验证 `@@log_bin=1`，**无需重启**）；每次备份把 `binlog.[0-9]*` 与 `binlog.index` 副本带到 `/opt/backups/mysql/`（按文件名增量，非覆盖）。
- 保留 7 天（full 与 binlog.index 按时间清理；binlog 文件仅删「已不在最新 index 中引用且超期」的）。
- 凭证：root 密码运行时从 `/opt/smartlect/run/runtime.env` 读，经 `MYSQL_PWD` 环境变量注入 `docker exec`（不进 ps 参数、不进脚本、不入库）。
- 首跑实测：**2.8 秒**完成（dump 124K + binlog 副本 81M，演示数据量小）。

### 2. PITR 恢复演练（核心交付，2026-09-14 17:41-17:45 实测）

时间线：

```text
17:41:01  全量备份完成（dump 头锚点: binlog.000003, POS=28352731）
17:41:33  写入标记 A（smartlect_growth._drill_marker，binlog 实际事件）
17:41:45  T_cut（人为指定恢复时刻）
17:41:58  写入标记 B
—— 模拟「数据全损，要求恢复到 17:41:45」——
17:43:04  临时容器 smartlect-restore-drill 就绪（mysql:8.4.11，127.0.0.1:13307，独立卷）   16.0s
17:43:11  gunzip 全量 | docker exec -i mysql 恢复完成                                       +7.1s
17:44:47  mysqlbinlog --start-position=28352731 --stop-datetime='2026-09-14 17:41:45'      +2.4s
          （宿主机直读 /var/lib/docker/volumes/smartlect_mysql/_data/binlog.000003）
17:44:50  验证完成
```

**验证结果**（全绿）：

```text
标记表：1  marker-A-before-cut  17:41:33   ← 在（切割点前，binlog 回放恢复）
        （marker-B 不存在）                 ← 切割点后写入被正确排除
业务行数：pay_trade_record 5=5、product_info 67=67、conversation 8=8、agent_run 9=9 全 OK
金额 checksum：SUM(pay_amount)=182.80 / COUNT=5，live 与恢复端完全一致
11 个 schema 表数：全部一致（21/11/5/4/16/6/5/14/45/13/5）
演练后清理：容器删除、标记表 DROP、无残留
```

### RTO / RPO 结论

- **RTO ≈ 30 秒**（容器就绪 16s + 全量恢复 7s + binlog 回放 2.4s + 验证 3s）。
  诚实标注：当前数据集极小（dump 124K），RTO 被容器初始化的固定成本主导；数据增长后 dump 恢复与回放时间线性上升，届时应关注 gzip 解压与回放带宽。
- **RPO（PITR 粒度）≈ 秒级**：binlog 事件按秒时间戳回放，本演练在相隔 12 秒的两个事件之间精确切割。
- **RPO（磁盘/卷全损场景）= 最近一次 binlog 外带副本年龄（最坏 ~1h）+ 每日全量**：binlog 与数据在同一卷同一盘，盘损同灭；自 2026-09-15 起每小时第 7 分由 `/opt/backups/bin/binlog-sync.sh` 经 binlog-dump 协议外带增量（`mysqlbinlog --read-from-remote-server --raw`，不直接拷正在写的活跃文件；每次重拉上一档保证截断副本自愈；`/opt/backups/binlog/` 保留 7 天，cron `/etc/cron.d/smartlect-binlog-sync`）。改进选项（未做，按需启用）：ossutil 传阿里云 OSS 异地一份（分币级成本，需控制台建 bucket+AK）。

## 遇到的坑

1. **mysql:8.4.11 镜像不带 mysqlbinlog**（有 mysql/mysqldump/mysqladmin，唯独没有它）；而 Ubuntu 24.04 把 mysqlbinlog 打在 `mysql-server-core-8.0` 包而非 mysql-client。解法：`apt-get download mysql-server-core-8.0` → `dpkg-deb -x` 抽出二进制装到宿主机 `/usr/local/bin`（不装服务、不进容器）。8.0.46 客户端读 8.4 binlog 实测无警告。
2. **`mysqladmin ping` 在容器初始化窗口假就绪**（临时 server 阶段也回 alive），就绪判定必须 `SELECT 1` 真查询。
3. **mysqlbinlog 的 `--stop-datetime` 按「运行 mysqlbinlog 的机器的本地时区」解释**——容器内默认 UTC 会把切割点偏 8 小时。在宿主机（CST）跑并显式 `TZ=Asia/Shanghai`。
4. `set -o pipefail` 下 `gunzip | grep -m1` 的 SIGPIPE 会杀脚本（演练脚本第一版就这么死的）；取证类管道要么容忍退出码，要么 `|| true`。
5. 恢复端容器自身 binlog 也默认开启，回放事件被再次记入其 binlog——无害，但要知道。
6. 对账前先 `SHOW TABLES` 拿真实表名（order 库没有 `orders` 表，是 `order_comment` 等；`pay_trade_record` 的金额列叫 `pay_amount`），别按直觉猜。

## 面试一句话

为单机 MySQL 设计并实测了三段式灾备：每日 mysqldump 一致性快照（--source-data=2 记 binlog 锚点）+ binlog 副本外带 + 临时容器 PITR 演练——在相隔 12 秒的两个写入之间精确切割恢复，标记验证 + 11 schema 行数/金额 checksum 全对齐，RTO 30 秒、PITR 粒度秒级；同时诚实量化了「binlog 与数据同盘」场景下 RPO 退化到日备年龄的风险并给出每小时 binlog 外带/OSS 的改进路径。
