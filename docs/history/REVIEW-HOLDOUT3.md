# 任务：独立审核 holdout-3 密封留出草案（只读，输出审核结论）

仓库：`/home/song/code/Smartlect`。你是**独立审核人**：未参与 holdout-3 的起草，也不参与系统开发。holdout-3 是第三份密封留出（首测即终测），你的任务是**在盖章前找出题目缺陷**——克隆、金标错误、覆盖失衡、禁句误报面。只输出结论，不改任何文件。

## 背景

- quality-v2 唯一评测体系；导购 65 dev 题、客服 63、广告 12 本；holdout-1/2 均已烧毁（文件只存证）。
- 本轮系统在 v14/v15 间做了四场类级修复（状态自答强制政策取证、建单边界四件套、必含词头词收获帧、回退授权替换闸门）；holdout-3 在 v15 基线上密封，用于测未见泛化。
- 草案：**导购 8（shop-h3-01…08）+ 客服 8（sup-h3-01…08）+ 广告 7（ads-h3-01…07）**，新 extra 文档 6 份（`evals/quality-v2/support/extra/holdout3-*.md`）。

## 必读（按序，只读）

1. `evals/quality-v2/shopping/holdout3.jsonl` / `support/holdout3.jsonl` / `ads/holdout3-playbooks.json` —— 被审草案本体。
2. `evals/quality-v2/metrics-contract.md` —— 操作定义（重点：claims 分级 v6.2 判级原则与操作款、禁句否定窗口、转人工 Pass、allow_handoff、广告 script 剧本约束）。
3. 对照全集（克隆审计的对象）：`shopping|support` 的 `dev.jsonl`、`holdout.jsonl`、`holdout2.jsonl`；`ads` 的 `playbooks.json`、`holdout*-playbooks.json`。
4. `evals/quality-v2/shopping/catalog-snapshot.json` —— 20 SKU 快照（导购金标由 `sku_satisfies` 从硬约束推导，你可自行重推导）。
5. `fixtures/knowledge/*.md` —— 客服语料（claims 必须是可见文档正文连续子串）。
6. `artifacts/quality-v2/holdout3-draft/generate.py` —— 生成与自检脚本（金标现算 + 跨集查重逻辑在此）。
7. `docs/quality-eval-v2.md` 与 `IMPLEMENTATION_STATUS.md`（扫 v13-v15 条目即可）。

## 审核维度（逐项给结论）

**A. 克隆审计（阻塞级）**：每道题与 dev/holdout-1/holdout-2 的题面、主题、金标形状逐条比对。同族不同题可接受（holdout-2 审核先例：h2-03 与 d-26 同形被明示可接受），但**近似克隆**（同主题+同文档+同问法变体）是阻塞项。已知设计意图（不算克隆，但请复核度）：h3-04 MERCHANT 软问法与 d-63 同哲学不同主题（直播 vs 上新）；广告 h3-01/02 与 dev d-06/d-07 同机制不同数字形状，h3-03（双耗尽）最近亲是 d-12；导购 h3-07（粉色→黑色回退）与已烧毁 h2-06 同族但产品族/措辞不同（回退授权族的未见泛化探针是有意覆盖，审核建议 5 采纳项）。
**审核后修订记录（2026-09-14，独立审核结论已落实）**：阻塞 1（h3-08 lifecycle 改 publish_with_future_valid_from+86400）；阻塞 2（h3-01 补 no-cash essential）；建议 1（h3-03 题面改写拉开与 d-57 表面距离）；建议 2（h3-05 no-other-read 降 peripheral）；建议 3/4（note 写明区分点与类目复用意图）；建议 5（shop-h3-07 换为回退授权探针、ads-h3-01 改疲劳翻转断言、新增 ads-h3-08 organic unknown 正例——同 SKU 归因面由 h3-06 的归因族覆盖，明示接受不复测）；建议 6（note 措辞、sup-h3-04 补 actor、生成器增 2-gram Jaccard≥0.6 模糊查重告警、本文件 d-09→d-12 更正）。修订后复核：validate --split holdout3 全绿、字面与模糊查重均零命中。
**B. 金标正确性（阻塞级）**：导购——按 catalog 快照与硬约束独立重推导 satisfaction_set（含空集题的 empty_reason 语义）；客服——claims 是否可见语料连续子串、essential/peripheral 是否符合合同 v6.2 判级原则（删去后被问出的问题是否落空）、needle 是否有诚实答案误报面（否定窗口 ±8 字符）；广告——script 计数推导、双活动 same_sku、status/reject 断言语义。
**C. 覆盖与难度（建议级）**：三线机制覆盖是否均衡；是否有题对当前系统结构性不可过（金标正确但面不公平）或结构性白给。
**D. 出题纪律（建议级）**：多轮题末轮是否自包含；复合命题是否保持单命题；新 extra 文档的 sha256 与 body 是否一致。

## 输出格式（直接输出 markdown）

```
## 审核结论：通过 / 需修改
## 阻塞项（逐条：题号、问题、证据、建议修法）
## 建议项（同结构）
## 覆盖评估（三线各一句）
```

## 纪律

- **只读**：不得修改/移动/删除任何文件；不跑评测、不起栈、不装依赖（离线审计足够；如需跑 `validate --split holdout3`，允许只读执行 `growth/.venv/bin/python scripts/eval_quality_v2.py validate --split holdout3`——注意工作目录在 scripts/，用绝对路径 venv）。
- 不重开已锁定事项（合同公开表头、方案 A、判级原则 v6.2、holdout-1/2 存证不动）。
- 全程简体中文。
