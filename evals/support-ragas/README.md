# support-ragas：客服线 RAGAS 评测（quality-v2 客服线的继任）

日期：2026-09-14。用户拍板：客服线定位为"分层简单的基础 RAG"，弃自研指标，
改用 RAGAS 经典四件套；行为面（转人工/ACL/注入/多轮）不再测量。导购/广告
两线仍走 `evals/quality-v2/`，与本线无关。旧客服评测数字归档不引用。

## 结构

- `corpus/`：47 篇共享语料库（12 个主题域：支付/订单/物流/退换货/保修/会员/
  优惠券/发票/账户安全/库存预售/门店）。其中 6 篇是刻意干扰项：
  - 5 篇 `*-old.md`：已废止旧版政策（旧支付/旧取消/旧运费/旧退货 15 天/旧积分
    永不过期）——测试系统是否引用过期资料；
  - 1 篇 `cpn-04-store.md`：近似措辞陷阱（门店现金券 vs 线上优惠券）。
  每题面对**整库 47 篇**检索（不再按题裁剪池子），根治旧线"每题 1-3 篇、
  指标饱和"的根源问题。
- `questions.jsonl`：67 题，五层：
  - L1 单跳事实 ×18；L2 条件判断 ×17；L3 数值/清单 ×11；L4 跨文档双跳 ×11；
    L5 边界/干扰 ×10。
  - 每题字段：`question` / `reference_answer`（人工参考答案，context_recall
    与正确性面的锚）/ `gold_docs`（金标文档，仅供归因分析，不进 RAGAS 判分）。
- `requirements.txt`：判分环境钉版（`run/venv-ragas`）。

## 判分配置

- 指标：`faithfulness` / `answer_relevancy` / `context_precision` /
  `context_recall`（RAGAS 0.2.15 经典四件套）。
- judge：`SMARTLECT_JUDGE_*`（DeepSeek deepseek-flash，温度 0）——与主对话
  模型（qwen）异源，沿用旧线的反自评纪律。
- embedding：`SMARTLECT_EMBEDDING_*`（text-embedding-v4，中文优化）——
  answer_relevancy 的反向问题相似度依赖它。
- contexts 取材：最后一次真实 `search_knowledge` 回执的候选 doc_id 序（去重、
  终答深度），按 doc_id 映射回语料全文——与旧线 Recall 的打分面同源。

## 用法

```bash
# 1) 采集（需要活栈：./scripts/dev.sh infra-up && up；用系统 python3）
python3 scripts/eval_support_ragas.py collect --output artifacts/support-ragas/collect-<日期>

# 2) 判分（需要 judge/embedding 密钥；用专用 venv）
run/venv-ragas/bin/python scripts/eval_support_ragas.py score --input artifacts/support-ragas/collect-<日期>

# 3) MoE 校准（首次必跑：同批双跑量四指标漂移带，此后所有读数带内判读）
run/venv-ragas/bin/python scripts/eval_support_ragas.py moe --input artifacts/support-ragas/collect-<日期>
```

产物：`ragas-run*.csv`（逐题）+ `scores.json` + `report.md`（指标总表，
moe 模式附漂移表）。

## 质量门禁

```bash
python3 scripts/check_support_ragas.py
```

检查金标存在性、题目近重复（字符 2-gram Jaccard≥0.6，holdout-3 同标准）、
参考答案溯源度（与金标正文 2-gram Jaccard≥0.15）、非干扰文档全覆盖。

## 已知边界

- RAGAS 为 LLM-judge/embedding 判分，四指标均含噪声——**首跑前先 `moe`**，
  漂移带之内的差异不下结论（旧线 judge ±4pt 教训的延续）。
- ragas 版本钉死 0.2.15：0.4.x 与 langchain 1.x 组合存在导入断裂，
  升级需回归验证后再动。
- 出题改题改判分配置时重跑门禁；语料改动会使历史 collect 的 corpus_sha256
  失配（score 时会因 doc_id 映射缺失而暴露）。
