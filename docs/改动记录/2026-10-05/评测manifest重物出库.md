# 评测 manifest 重物出库（P1）

## 需求

`eval/verification/agent-release-gate-20261004/agent-release-report-20261004-042118-339805.manifest.json`（20.6MB，全仓最大跟踪文件，内容为 407 个文件的逐文件 sha256 指纹，且指纹对象是 src 布局重构前的旧代码树）随 20261004 批次整体入库，与 `.gitignore` 既定的「重物不入库」政策（20260930 批次先例：逐目录显式忽略 `*.manifest.json`、同目录 `.md` 报告照常入库）不一致。error-rerun 目录 10 个 manifest（100KB–884KB）与 retrieval-dev-calibration 的 375KB manifest 同理。

## 具体变更

- `.gitignore`：删除 `rerun-20260930/` 三条死规则（该目录已不在工作树与 git 历史）；新增三条规则——`agent-release-gate-20261004/`、`agent-release-gate-20261004-error-rerun/` 下 `agent-release-report-*.manifest.json` 与 `retrieval-dev-calibration-20261004/recall-dev-report-*.manifest.json`。
- `git rm --cached` 移出 12 个 manifest（主 1 + error-rerun 10 + retrieval-dev 1）；**本地文件全部保留**（原始证据政策），可再生指纹不再膨胀仓库。
- 同目录 `.md` 报告照常入库；全仓 grep 确认无文档链接引用被移出文件名，无需修链。
- 保留入库的小 manifest（category-gate 138KB、retrieval-release 204/210KB、memory extraction 等）不受影响。

## 验证

- `git status --short` 显示 12 个 `D`（仅索引删除）；`git check-ignore` 对主 manifest 返回命中（规则生效）；`ls` 确认本地文件仍在（20.6MB 原样）。

## 启用与回滚

- 回滚：`git add` 对应文件并删 .gitignore 三条规则即可（本地文件从未删除）。

## 关联代码版本

基于 `7773906` 工作树（本批未单独提交）。
