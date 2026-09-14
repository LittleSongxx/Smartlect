# support-eval：客服线评测（五指标记分卡）

日期：2026-09-14。设计原则（用户拍板）：**不为生产严谨服务，为面试叙事服务**——
指标全是面试标准词汇、每个一句话说得清、数值可写进简历。参考 mewhelp 项目的
评测架构（分桶判别力、确定性优先、judge 只干两件小事、未评上不落零分），
替代此前只冒烟未首跑的 support-ragas（RAGAS 四件套方案，git 历史存证）。

## 五个指标

| 指标 | 判分 | 一句话定义 |
|---|---|---|
| **Recall@5** | 确定性 | 该题金标文档进入最后一次真实检索前 5 的比例（多金标部分分） |
| **MRR** | 确定性 | 金标文档排名倒数的平均（多金标先平均、缺席记 0） |
| **答案覆盖率** | judge | 标准答案要点被客服答案正确覆盖的比例（judge 逐条数个数） |
| **Faithfulness** | judge | 答案事实主张全部有检索证据支撑的比例（二值，只查编造） |
| **拒答率** | 确定性 | 库外问题诚实拒答（answer_status ∈ {insufficient, needs_human}）的比例 |

judge = `SMARTLECT_JUDGE_*`（DeepSeek，温度 0，与主对话模型 qwen 异源）；
检索面（Recall/MRR/拒答率）纯确定性计算，零 judge 成本、可复算。

## 结构

- `corpus/`：47 篇共享语料（12 主题域 + 5 篇旧版干扰 + 1 篇近似干扰），
  每题面对整库检索。
- `questions.jsonl`：77 题六层——L1 单跳事实×18、L2 条件判断×17、L3 数值清单×11、
  L4 跨文档×11、L5 边界干扰×10（旧版政策陷阱）、**L6 库外拒答×10**（语料无对应
  政策的真缺席题，金标为空、应拒答）。每题字段：`question` / `points`（要点清单，
  覆盖度分母）/ `gold_docs` / `reference_answer` / L6 加 `should_refuse`。

## 用法

```bash
# 门禁（离线零依赖）
python3 scripts/check_support_eval.py

# 采集（需活栈）
python3 scripts/eval_support_eval.py collect --output artifacts/support-eval/collect-<日期>

# 判分（需 judge 密钥；系统 python3，无 venv）
python3 scripts/eval_support_eval.py score --input artifacts/support-eval/collect-<日期>
```

产物：`scorecard.md`（层×指标矩阵 + 总体 + 该拒没拒/不忠实个案带理由）、
`per-question.csv`（逐题）、`scorecard.json`。

## 面试叙事映射

- 一句话体系："客服线五指标记分卡——检索面确定性算 Recall@5/MRR，生成面异源
  judge 判覆盖度与忠实度，库外桶测拒答诚实；77 题六层、47 篇含干扰语料。"
- 优化弧线：首跑出基线 → 按层归因（哪层弱修哪层）→ 复跑对比。L5 边界层与
  L6 拒答层是最可能出故事的两个桶（旧版政策引用、编造规则）。

## 已知边界

- judge 有噪声：温度 0 缓解；覆盖度计数可能保守（冒烟中出现过逐条可对照却少计
  1 条），读数看层均值而非单题。
- 不做多试验重复与置信区间（设计决定：不追求生产严谨）；若需粗方差感，同批
  重跑 score 即可（collect 的答案不重采样，只看 judge 漂移）。
- 检索指标上限受 FINAL_DEPTH=8 截断（candidates ≤8），@5 在其内。

## 与旧线关系

- quality-v2 客服线（Recall@8/Faithfulness 判级版/Pass@1/建单 F1）：退役，
  数字归档不引用。
- support-ragas（RAGAS 四件套）：只冒烟未首跑即被本方案替代，git 历史存证
  （`f8976c1`）。判分不再依赖 ragas/langchain，系统 python3 直连 judge。
- 导购/广告两线：维持 quality-v2（与本线无关）。
