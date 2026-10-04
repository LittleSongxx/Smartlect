# quality-v2 质量评测索引

更新：2026-10-04。**两条主线**（导购选品 / 政策客服）的公开指标评测体系。广告投放线已于 v7 退役（ADR-0008），代码与剧本已删除。

**v16 扩容（2026-10-04）**：导购 dev 65→87 题（新维度：灰色空集/RGB/网布/无线/头戴/`excluded_sku_keys` 首用/双边价格窗/类目排除/多数量；新多轮 4；新对抗 3：角色扮演注入/分隔符注入/工具参数伪造，金标全部由 `sku_satisfies` 脚本推导）；客服 dev 63→83 题（大可见池判别 8：visible 6-10 篇 fixtures + 3-5 篇难负例注入，恢复 Recall@K/@1/MRR 判别力；负向陷阱 5；多文档合成 3；ACL/生命周期 2；多轮 2）；新增难负例语料 `evals/quality-v2/support/extra/eval-hn-*.md` 40 篇（邻主题干扰/限定范围变体/数字近邻冲突对/时段渠道对立/生命周期 ACL）。指标定义全部不变（metrics-contract v8 修订只记录扩容与深度链正名）；**v15→v16 口径变严，公开分预期下降，两版不可直接混比**。

## 位置与跑法

- 评测集：`evals/quality-v2/{shopping,support}/dev.jsonl`
- 合同：`evals/quality-v2/metrics-contract.md`（v8）
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
- holdout 首测即烧毁（holdout-1/2 已烧毁；**holdout-3 于 2026-10-04 与 v16 同批首测烧毁**；holdout-4 为 v16 扩容后新密封留出，12+12 题、独立 AI 审核修订后盖章，见 `docs/history/REVIEW-HOLDOUT4.md`）
- judge 失败记 `null`，绝不回退规则分
- 标注自洽错误（AnnotationError）直接中止 run

## 产物

`artifacts/quality-v2/` 下 40+ run 目录（official-v5 到 v16、judge-calibrate、holdout 烧毁记录、修复验证等），含 provenance（git_head、scorer sha256）。

另有 `evals/support-eval/`（客服线补充评测：47 篇干扰语料 + 77 题六层），产物在 `artifacts/support-eval/`。
