# HANDOFF：node1 升配后的性能压榨与收官

> 2026-09-15 09:40 更新。**集群常驻形态已全量上线并通过门禁**（首页/API 200，RMQ 3 节点，冒烟全过）。
> 用户正在控制台对 node1 停机变配（4c16g → 更高规格，不计成本，费用走账户余额）。
> 本文件交给新会话：等 node1 重启后，填 JVM 参数、跑压测套件、更新文档收官。

## 用户需求

1. 三机**常驻集群形态**（已实现并在运行）；node2/3（2c8g ×2 ≈ ¥551/月，科创包抵扣）**不需要升配**——压测时利用率仅 15-21%。
2. node1 升配后**一步到位提 QPS**：JVM 参数已全部 env 化（勿再分档归因，用户已确认）。
3. 用 800 VU 钉死"极限 QPS"结论。

## 当前状态（全部在线，2026-09-15 09:37 门禁通过）

| 组件 | 状态 |
|---|---|
| RabbitMQ | ✅ 3 节点 quorum、59 队列（rabbit-c1/2/3，host 网络 5672/15672） |
| Redis | ✅ 1m2s + 3 sentinel（master=node1，quorum 2，down-after 5s） |
| Nacos | ✅ 3 节点 Raft（host 网络 8848/9848/7848，mysql 后端） |
| 应用 | ✅ 13 进程健康（apps-check 冒烟通过）；growth 连 rabbit-c2，Java 走 SPRING_RABBITMQ_ADDRESSES 多地址 |
| 监控 | ✅ 集群态：exporter→127.0.0.1:15672、node2/3 node-exporter 在线、prometheus 三机 node 目标 |
| runtime.env | ✅ 已含集群键（SMARTLECT_CLUSTER_FORM=cluster、多地址、sentinel）；**JVM 三键尚未填**（等升配后内存到位，当前 16g 只剩 ~1.8g 不能上 512m 堆） |
| CI/CD | ✅ 最新提交 5f8e989（JVM 参数 env 化）部署一致，流水线绿 |

**已根治的竞态**：seata 早于 nacos 仲裁启动会注册失败退出——smartlect-infra.service 已加 `Restart=on-failure` + `RestartSec=20`，重启后自愈。

**node1 变配重启后的预期**：infra 单元（含集群 override）自启 mysql/redis/seata；集群容器 restart=unless-stopped 自启；apps 单元自动走集群分支正常起。若个别服务因时序未就绪，systemd 自重启会兜底；极端情况手动 `systemctl restart smartlect-apps`。

## 三机事实表

| 机器 | 公网 | 内网 | 主机名 | 角色 |
|---|---|---|---|---|
| node1 | 39.107.102.244 | 172.21.131.151 | smartlect-node1 | **升配中**；应用 + MySQL + Redis(主) + rabbit-c1 + nacos-c1 + sentinel |
| node2 | 47.93.9.163 | 172.19.34.202 | smartlect-node2 | rabbit-c2 + nacos-c2 + redis-replica + sentinel |
| node3 | 123.56.160.31 | 172.19.34.203 | smartlect-node3 | rabbit-c3 + nacos-c3 + redis-replica + sentinel |

- SSH：本地 id_rsa 三机免密；node1→node2/3 已组 mesh（编排从 node1 发起）。
- 集群编排：服务器 `/opt/cluster/`（本地 `run/cloud/cluster/`，gitignored）；监控配置：`run/cloud/monitoring/` ↔ `/opt/monitoring/`。

## 后续任务

### 1. 验证 node1 变配生效
SSH 上去看 `nproc` / `free -h`；然后 `systemctl is-active smartlect-infra smartlect-apps smartlect-monitoring` + `curl http://127.0.0.1/api/product/loadCategory` 应 200。若有单元卡 failed，按上面竞态说明处理。

### 2. 填 JVM 参数（一步到位）并重启应用
```bash
RT=/opt/smartlect/run/runtime.env
cat >> "$RT" <<'EOF'
SMARTLECT_JAVA_XMS=512m
SMARTLECT_JAVA_XMX=512m
SMARTLECT_JAVA_PROCESSORS=4
EOF
chmod 600 "$RT" && systemctl restart smartlect-apps
# 等 ~8 分钟起完，验证生效（任一 java 进程）：
ps -ef | grep -oE "\-XX:ActiveProcessorCount=[0-9]+" | sort | uniq -c
```
取值：8c → 4；16c → 8 且 XMX 可 768m（32g 内存下 9 个 JVM 富余）。内存不够再降，别 OOM。

### 3. 压测套件（node2/3 双发，node1 只做被测机）
```bash
# 在 node1 上发起（k6 三机已装，脚本 /root/loadtest/browse.js）：
for VUS_PER in 50 100 200 400; do
  ssh root@172.19.34.202 "k6 run --summary-trend-stats=\"avg,med,p(90),p(95),p(99),max\" -e BASE=http://172.21.131.151:80 -e VUS=$VUS_PER -e HOLD=100s /root/browse.js >/tmp/k6.log 2>&1" &
  ssh root@172.19.34.203 "k6 run --summary-trend-stats=\"avg,med,p(90),p(95),p(99),max\" -e BASE=http://172.21.131.151:80 -e VUS=$VUS_PER -e HOLD=100s /root/browse.js >/tmp/k6.log 2>&1" &
  wait; for n in 202 203; do ssh root@172.19.34.$n "grep -E 'http_reqs\.\.\.' /tmp/k6.log; grep -oE 'p.95.=[0-9.]+m?s' /tmp/k6.log|head -1; grep -E '✓ .rate|✗ .rate' /tmp/k6.log|head -1"; done; uptime
done
```
- 旧平台基线（4c16g + 默认 JVM）：100/200/400 VU = 85/103/109 req/s，p95 1.41/4.38/8.64s，零错误。
- 曲线导出：`python3 /opt/cluster/scripts/export-ramp-csv.py <out.csv> <start-Z> <end-Z>`（Prometheus）。
- 预期（8c + 512m 堆 + processors=4）：平台 ~180-220 req/s。800 VU（每台 400）确认平台不再上移。

### 4. 文档收官
- `docs/prod-hardening/ha-cluster.md`：状态改"常驻集群"，追加变配规格 + 新旧压测对比表 + 800 VU 平台结论。
- `README.md`：部署形态行（"单台 ECS…"）改为三机集群描述；证据表数字更新。
- `IMPLEMENTATION_STATUS.md`（本地 gitignored）追加台账；**只 stage 显式路径提交推送**。

## 红线（全部有效）

1. **绝不 `git add -A`**：工作区有未提交的 eval-track 文件（`evals/support-eval/questions.jsonl`、`scripts/eval_support_eval.py`、`assistant/src/smartlect/answer_guards.py`、`assistant/tests/test_answer_guards.py`）。
2. 不碰 evals/holdout 与评测基线。
3. `run/runtime.env`、`run/model.env` 永不入库；文档不得含密钥（163 SMTP 授权码与新机 root 密码曾出现在聊天中，勿写入文件）。
4. 改 `scripts/runtime.py` 或 growth 代码：本地 `./scripts/dev.sh check` 全绿再同步（runtime.py 当前版本 5f8e989 已在服务器，无需再动）。
5. 不绕开 runtime.py 手拉应用进程；RabbitMQ 旧单机卷不动。
6. push 已获授权（本轨道常规操作）。

## 坑位（实测踩过）

- `docker compose down --remove-orphans` 误杀共享 project 名 `cluster` 的他目录容器。
- 旧单机 rabbitmq 容器必须保持停止（占 127.0.0.1:15672，rabbit-c1 绑 0.0.0.0:15672 会 eaddrinuse 循环崩溃）；infra override 已保证不会被拉起。
- 集群期回退单机用 `/opt/cluster/scripts/revert.sh`（含 infra 单元、监控、override 全套回滚，已验证一次）。
- 嵌套 ssh + heredoc 引号易炸：复杂逻辑写脚本文件 scp 执行；`set -o pipefail` 下 `| head` 会 SIGPIPE 杀脚本，用 `sed -n 1p`。
