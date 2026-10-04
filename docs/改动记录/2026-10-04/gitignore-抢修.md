# .gitignore 抢修：清除已提交的合并冲突标记，恢复 docs/ 入库

## 需求

合并提交 `b29d254`（Merge remote-tracking branch 'origin/main'）把两段带未解决冲突标记的 `.gitignore` 原样提交进了 HEAD：第 39 行 `=======`、第 104 行 `>>>>>>> origin/main`。冲突段中的 `/docs/` 规则导致所有新增 docs 文件被静默忽略（实证：`git check-ignore -v docs/newfile-test.md` 命中 `.gitignore:93:/docs/`），`docs/quality-eval-v2.md` 新引用的 `docs/history/REVIEW-HOLDOUT4.md` 若提交将成为克隆者不可见的死链。

## 具体变更

重写 `.gitignore`（105 行 → 63 行）：

1. 删除两处冲突标记及其引发的分段重复（`.venv/`、`__pycache__/`、`*.pyc`、`.env`、`.pytest_cache/`、`node_modules/`、`.cache/`、`.zcode/` 等重复条目）。
2. 删除 `/docs/` 整目录忽略——docs 恢复入库（AGENTS.md 的改动记录流程依赖 docs 可提交）。
3. 删除课程仓库时代的死规则：根目录 `/*.md`、`/*.json`、`/*.html`、`/案例与源码-*/`、`/repo-auth-service/` 等所指路径已不存在于仓库或磁盘。
4. 删除指向已消失本地文件的规则（`IMPLEMENTATION_STATUS.md`、`HANDOFF.md`、`handoff/*`、`秋招/`）。
5. 保留并分组注释：环境凭据、Python 缓存、构建产物、运行态目录、`data/*` 三个白名单、eval 报告产物忽略、`eval/verification/` 向量重物忽略、`*.log`。

## 验证

- `git check-ignore -v docs/new-file-test.md` 不再命中（exit=1）；`git check-ignore .env` 仍命中。
- `git status` 未暴露任何敏感文件（.env 等仍被忽略）。
- 新暴露 5 个此前被旧规则隐藏的本地未跟踪文档：`docs/architecture-interview.md`、`docs/history/REVIEW-HOLDOUT4.md`、`docs/history/ai-ops-plan.md`、`docs/history/implementation-log-2026-09.md`、`web/admin/BROWSER_CHECK.md`——属作者本地维护内容，本次不代为提交，留待作者决定。

## 回滚

`git revert` 本提交即可恢复旧版 .gitignore（旧版存在于父提交中）。

## 关联版本

基于 `da76f8e`（main），与同日 [工作区拆分提交.md](工作区拆分提交.md) 同期执行。
