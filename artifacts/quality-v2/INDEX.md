# 评测资产索引

更新：2026-10-05。全部官方 run 含 provenance（git_head + scorer sha256）。

## 官方基线（不可删改）

| 目录 | 版本 | 说明 |
|---|---|---|
| official-v5~v15 | v5-v15 | 65+63 旧集基线（v15 = 修复前最终基线） |
| official-v16-20261004 | v16 | 87+83 扩容后首轮（检索/抽取多缺陷暴露） |
| official-v17-20261005 | v17 | 第一轮系统修复后（终答三机制+抽取净化） |
| official-v18-shopping-20261005 | v18 | 导购线：词表惰性过滤后 0.904 |
| official-holdout1-20260912 | — | 密封留出首测（已烧毁） |
| official-holdout2-20260913 | — | 密封留出首测（已烧毁） |
| official-holdout3-20261004 | — | 密封留出首测（已烧毁，驱动第一轮修复） |
| judge-calibrate-20261004 | — | 双 judge κ=1.000 校准（最新） |

## 归档（archive/）

### diagnostics/
诊断与验证 run（复跑台账参照物、非基线）：含 holdout-4 部分数据（BURNED 标注）、v16 中止 run、旧 judge 校准。

### repair-runs/
修复验证 run（旧版缺陷的对照证据）。

## 纪律

- rerun-ledger.jsonl：复跑台账，禁止重采样刷绿
- 官方 run 产物不可删改（provenance 溯源链）
- 冒烟/自检 run 已清理（无存档价值）
