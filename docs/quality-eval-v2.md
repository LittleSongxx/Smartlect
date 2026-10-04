# quality-v2 质量评测索引

更新：2026-10-04。**两条主线**（导购选品 / 政策客服）的公开指标评测体系。广告投放线已于 v7 退役（ADR-0008），代码与剧本已删除。

## 位置与跑法

- 评测集：`evals/quality-v2/{shopping,support}/dev.jsonl`
- 合同：`evals/quality-v2/metrics-contract.md`（v7+）
- 跑法：`scripts/eval_quality_v2.py`（validate / run / judge / report）
- 被测 assistant 需已由 `dev.sh up` 启动（健康检查通过）

```bash
cd scripts && python3 eval_quality_v2.py run --official
```

## 公开指标

| 线 | 指标 | 说明 |
|---|---|---|
| 导购 | `Pass@1` | 一题通过率 |
| 导购 | `Precision@4/ceiling` | 贴满率（NDCG 式正规化） |
| 客服 | `Recall@8` | 最后一次真实检索的去重 candidates |
| 客服 | `Faithfulness` | DeepSeek judge 异源判分 |

所有指标带分母、Wilson 95% CI、`pass^k` 多试验（`--trials N`），不合成总分。

## 纪律

- 一题三结局：pass / unscored / setup_failed（复跑台账禁止重采样刷绿）
- holdout 首测即烧毁（holdout-1/2 已烧毁，holdout-3 密封待测）
- judge 失败记 `null`，绝不回退规则分
- 标注自洽错误（AnnotationError）直接中止 run

## 产物

`artifacts/quality-v2/` 下 40+ run 目录（official-v5 到 v15、judge-calibrate、holdout 烧毁记录、修复验证等），含 provenance（git_head、scorer sha256）。

另有 `evals/support-eval/`（客服线补充评测：47 篇干扰语料 + 77 题六层），产物在 `artifacts/support-eval/`。
