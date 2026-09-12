# quality-v2 质量评测索引

更新 2026-09-13（v5：合同 v6 公开表头名实对齐——导购 `Precision@4/ceiling` 贴满率（NDCG 式正规化，raw P@4 与 ceiling 留诊断列）、广告单指标 `Attribution_integrity` 归因完整性（断言级分母，CTR/CVR 降诊断）；v4：合同 v5 的 `--trials N` 多次试验、`pass^k` 与 Wilson 95% CI）。三条主线（导购选品 / 政策客服 / 广告投放）的公开指标评测体系。旧 `evals/rag_cases.jsonl`、`tool_tasks.jsonl` 与 F6/F7 产物不是本轮基线。

## 位置

| 内容 | 路径 |
|---|---|
| 指标合同（操作定义，v6） | `evals/quality-v2/metrics-contract.md` / `.json` |
| 导购开发集 / 商品快照 | `evals/quality-v2/shopping/dev.jsonl`（29 例）/ `catalog-snapshot.json`（20 SKU） |
| 客服开发集 | `evals/quality-v2/support/dev.jsonl`（24 例，1 例 replay-only） |
| 广告剧本 | `evals/quality-v2/ads/playbooks.json`（5 剧本） |
| 评分库 / runner | `scripts/quality_v2.py` / `scripts/eval_quality_v2.py` |
| LLM judge（DeepSeek） | `scripts/judge_quality_v2.py`（判 Faithfulness 公开分 + CLI 抽检） |
| 合同测试 | `scripts/test_quality_v2.py`（38 项）+ growth 全量 352 项 |
| 产物 | `artifacts/quality-v2/<run-id>/`，复跑台账 `artifacts/quality-v2/rerun-ledger.jsonl` |

## 公开表头（合同 v6，只用这些，不合成总分）

- 导购：`Pass@1`、`Precision@4/ceiling`（贴满率 = min(P@4 ÷ min(4,|金标|)/4, 1.0) 按题宏平均，NDCG/IDCG 式对可达上限正规化；raw `Precision@4` 与 `Precision@4_ceiling` 为并排诊断列）
- 客服：`Recall@8`（k=生产检索面 FINAL_DEPTH=8，`Recall@4` 为伴读诊断）、`Faithfulness`（v3 起为 judge 判分：DeepSeek `deepseek-flash`，与主模型 qwen 不同源，quote 门控；v4 起只算 essential 命题）
- 广告：`Attribution_integrity`（归因完整性，v6 起唯一公开分：断言级分母，每剧本 8 条确定性断言=四桶计数+两率算术+禁捷径；`Pass@1` 为剧本级门；模拟 `CTR`/`CVR` 降诊断列，恒标「模拟、非因果」）

禁句（`must_not_claim` 否定窗口豁免 / `forbidden_claims` 原样命中）与禁文档（`forbidden_doc_ids`）仍是**确定性规则门**，不交给 judge。judge 失败该题 Faithfulness 记 null（分母缺失），不借用规则分。judge 有 MoE 运行方差（实测 ±0.08），官方数字以 run 内单次判定为准并记录 judge 模型与 prompt 版本。

汇总每指标旁印分母；`setup_failed` 只限 provider/预算/基础设施，进台账；题目标注自洽错误（`AnnotationError`）中止整个 run。

## 常用命令（scripts/ 目录，用 growth/.venv/bin/python）

```bash
python test_quality_v2.py                        # 合同测试（系统 python 即可）
python eval_quality_v2.py validate               # 开发集标注自洽性校验（离线）
python eval_quality_v2.py self-check             # 合成观测全链路自检（无 judge）
python eval_quality_v2.py run --official         # live 全量（含 judge 判分，需栈健康 + JUDGE env）
python eval_quality_v2.py run --official --trials 3 --line shopping
                                                 # 每题独立 3 次试验：逐题通过率、pass^k、
                                                 # Wilson 95% CI（v5；ads 确定性模拟只跑单次）
python eval_quality_v2.py run --case shop-d-01   # 复跑单例（报告标 partial）
python eval_quality_v2.py judge --output <run目录> # judge 抽检报告（默认全量 claims 题）
python eval_quality_v2.py freeze                 # 冻结开发集摘要；出题仍需人工
```

## 留出状态

未出题。`freeze` 只盖开发集摘要（`evals/quality-v2/holdout/freeze-manifest.json`）并解锁 `--split holdout` 的加载资格；留出题目必须人工另写，禁止用留出调系统。

## v3 修订要点（相对 v2）

1. Faithfulness 公开分换 judge（DeepSeek 独立判分，防自评），规则分降为诊断列。
2. 导购检索两道类级防线：买/购闭合帧 harvest（品名进资格门不依赖模型自觉）+ 硬约束溯源守卫（模型声明的 terms/类目/价格必须可回溯用户原话或 mission，否则降级；商品/规格 ID 豁免）。
3. `support_policy` 1.7.0 / `shopping_advice` 1.12.0。
4. 预算耗尽的业务收口（`rule-fallback` 且非 provider_fault，含 `WAIT_USER`）从 setup_failed 改为正常计分——更严格，不掩盖。
5. `product_scope` 对已限定 include 的场景 actor 不再枚举其他场景商品（修 5000 上限撞顶）。
