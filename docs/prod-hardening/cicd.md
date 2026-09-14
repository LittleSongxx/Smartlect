# T0-3 CI/CD（GitHub Actions）

日期：2026-09-14 ｜ 状态：**已完成**（绿色流水线 + 真实部署 + 回滚演示均验收；一次真实的红色失败与修复迭代留档） ｜ 流水线：`.github/workflows/ci.yml`（commit `0faff21`）

## 做了什么

### 流水线结构

```
push/PR ──┬─ backend：mvn test（testcontainers 自带 MySQL，无需服务容器）
          ├─ growth：pip 按锁文件装依赖 + 装本包 + unittest（369 项）
          └─ web(user/admin)：npm ci + vitest（并行矩阵）

workflow_dispatch ── 全部测试通过后 ── deploy job：
  git bundle create deploy.bundle HEAD
  → ssh upload（bundle 经 stdin 进服务器）
  → ssh deploy（网关执行 ci-deploy.sh）
     git reset --hard FETCH_HEAD（前滚/回滚通用）
     → 按改动范围条件重建（web→npm build / backend→mvn package / growth→venv 重装）
     → systemctl restart smartlect-apps
     → runtime.py apps-check 健康门禁，失败即 exit 1
  workflow_dispatch?rollback=true → ssh rollback（回到 /opt/releases 上一个 bundle）
```

### 安全设计：deploy key 只是一个网关，不是 shell

- 专用 ed25519 密钥对，私钥入 GitHub Secrets（`SMARTLECT_DEPLOY_KEY`），公钥以 `command="/root/deploy/ci-gateway.sh",restrict` 挂进服务器 authorized_keys。
- 网关只认 4 个动词：`upload`（stdin 收 bundle）/ `deploy` / `rollback` / `status`，其余一律 `exit 64`——密钥即使泄漏也拿不到 shell。
- 实测：`status` 返回单元状态+HEAD；`ls /etc` 被拒（rc=64）。
- 主机指纹固定在 Secrets（`ECS_HOST_KEY`，ssh-keyscan 的完整行），runner 端 StrictHostChecking 生效。
- 服务器保留最近 3 个 release bundle 于 `/opt/releases/`，回滚=重放上一个 bundle（同一条部署路径，不是另写的脚本）。

### 部署语义

- `git fetch bundle HEAD && git reset --hard FETCH_HEAD`：前滚/回滚同一语义；服务器工作树保持干净（runtime.env 等均为 gitignored）。
- 条件重建对齐人工手册（§5.1）：只有对应目录变了才重建对应产物，无变更时纯重启。
- GitHub 从 ECS 不可达的限制不参与 CI（runner 在 GitHub 侧，bundle 经 SSH 进入），保持既有 bundle 流不破坏。

## 怎么验证的（三次运行，一次真实的红）

| run | 内容 | 结果 |
|---|---|---|
| `34831125576`（push） | 首次流水线 | ✅ backend/growth/web 全绿（2m22s） |
| `34831838510`（dispatch） | 首次部署 | ❌ `Host key verification failed` → 定位：ECS_HOST_KEY secret 已含整行，workflow 又拼了一次主机名 → 修 workflow |
| `34831614514`（dispatch） | 修复后部署 | ❌ 部署实际成功但 SSH 在 4m19s 无输出后 `Broken pipe` 误报红 → 加 `ServerAliveInterval=30` keepalive |
| `34832783435`（dispatch） | 完整验收 | ✅ 测试全绿 → `DEPLOY-OK f5d7028 -> 0faff21`，apps-check 13 进程/9 注册/8 undo 表通过，job 绿 |
| `34833778568`（dispatch rollback=true） | 回滚演示 | ✅ 服务器回到上一 release bundle，健康门禁复验通过 |

关键日志（验收 run）：

```text
gateway: uploaded 4.2M
deploy: bundle archived as /opt/releases/20260914-182353.bundle（保留最近 3 个）
HEAD is now at 0faff21 T0-3 fix: SSH keepalives survive the ~4min app restart during deploy
deploy: restarting apps（健康门禁内置）
Application checks passed: thirteen owned healthy processes, nine Nacos registrations, eight Seata undo tables.
DEPLOY-OK f5d70289db647fc76ef5e43dbf752b19a15760de -> 0faff21715c8f7222ca5702fa3562274a0687729
```

误报红那次的服务器侧事实（证明 systemd 托管的部署不受 SSH 断连影响）：

```text
$ systemctl is-active smartlect-apps     → active
$ git log --oneline -1                   → f5d7028（已切换）
$ runtime.py apps-check                  → passed（13/9/8）
```

## 遇到的坑

1. **known_hosts 拼接重复主机名**：secret 里存的是 ssh-keyscan 的完整行（含 host 前缀），workflow 再拼 `echo "host $SECRET"` 变成 `host host key` 畸形行——直接整行 echo。
2. **GitHub runner→ECS 的 SSH 撑不过 4 分钟无输出**（app 重启期间）：`systemctl restart` 本身交给 systemd 不受断连影响，但 job 会误报红。客户端 keepalive（`ServerAliveInterval=30`）解决。
3. **scp 与 forced command 不兼容**（现代 scp 走 SFTP 子系统，command= 会劫持）：所以 bundle 上传用 `ssh upload < bundle`（stdin 流）而不是 scp。
4. workflow 的 `needs:` 在测试失败时会 **skip**（而非 fail）deploy job——门禁语义是"测试不绿不部署"，真正的部署级失败由 apps-check 兜底。

## 遗留说明

- 安全组若在 T1-8 收紧 22 端口为源 IP 白名单，需同时给 GitHub runner 的 IP 段放行（meta.githubusercontent.com 的 actions IP ranges，可用 hook 自动更新）或改走其他通道——已在 T1-8 待办里登记。
- bundle 每次 4.2M 全量（不做增量基线跟踪），换取"任意 ref 可部署、前后滚同一语义"的简单性；仓库显著变大后再优化。

## 面试一句话

为"GitHub 不可达的境内服务器"搭了 CI/CD：Actions 跑全量测试（testcontainers 自带 MySQL），手动触发的部署经一把"只会四个动词"的受限 SSH 网关把 git bundle 送进服务器、按目录条件重建、重启后以 13 进程健康门禁兜底，失败即红；保留 3 个 release bundle 一键回滚——并用三次真实运行（两次红：known_hosts 拼接错误、4 分钟重启期的 SSH 断连误报）展示了闭环的调试与收敛过程。
