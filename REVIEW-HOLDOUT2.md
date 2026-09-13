# Holdout-2 草案审核交接（给新开的 AI 对话）

日期：2026-09-13。仓库：`/home/song/code/Smartlect`，分支 `main`，HEAD `c27194e`。
你是**独立审核者**：代用户审核 quality-v2 评测体系的 holdout-2 留出题草案，在盖章（密封）前把关。
背景文档（可选阅读）：`HANDOFF-EVAL-EXPANSION.md`（本阶段总交接）、`evals/quality-v2/metrics-contract.md`（指标合同 v6/v6.1）、`IMPLEMENTATION_STATUS.md`（本地状态）。

## 审核对象与流程位置

holdout-2 是新的独立留出集（holdout-1 已于 09-12 首测烧毁）。当前处于**草案阶段**：
题目已出、离线校验全绿，但三线 manifest 未盖章。盖章后**首测即终测**——跑一次就烧毁，
不得再改题、不得按结果调系统。所以你的审核是盖章前最后一道闸，标准要严。

## 铁律（违反会烧毁留出或污染评测）

1. **只读**：不得修改、移动、删除任何 `holdout2*` 文件；也不得改 dev/holdout-1/manifest/脚本。
2. **不得运行留出题**：任何 `--split holdout2` 的 `run` 命令都被门禁拒绝（`holdout2_seal_pending_user_approval`），也不要试图绕过。允许的命令只有（用绝对路径的 venv，`cd scripts` 后相对路径 `growth/` 不存在）：
   - `cd scripts && /home/song/code/Smartlect/growth/.venv/bin/python eval_quality_v2.py validate --split holdout2`（离线标注自洽）
   - `cd scripts && /home/song/code/Smartlect/growth/.venv/bin/python test_quality_v2.py`（合同测试）
3. **不得据题意调整系统/提示/开发集**——审核结论只交回给用户。
4. holdout-1 的文件（`*/holdout.jsonl`、`holdout-manifest.json`、`extra/holdout-*.md`）可读不可动。

## 审核对象文件

| 线 | 题目 | 素材 |
|---|---|---|
| 导购 | `evals/quality-v2/shopping/holdout2.jsonl`（8 题 `shop-h2-01…08`） | 目录快照 `shopping/catalog-snapshot.json`（20 SKU，冻结） |
| 客服 | `evals/quality-v2/support/holdout2.jsonl`（8 题 `sup-h2-01…08`） | `fixtures/knowledge/*.md` + 新 extra `support/extra/holdout2-*.md`（4 份） |
| 广告 | `evals/quality-v2/ads/holdout2-playbooks.json`（7 本 `ads-h2-01…07`） | 排序公式见下 |

对照面（查重用）：`shopping/dev.jsonl`（65 题）、`support/dev.jsonl`（62 题）、`ads/playbooks.json`（11 本）、
`shopping/holdout.jsonl`/`support/holdout.jsonl`/`ads/holdout-playbooks.json`（holdout-1）。

## 逐线核查清单

### 导购（8 题）
1. **金标正确性（最重要）**：每题 `satisfaction_set` 必须等于 `hard_constraints` 用评分器同款逻辑推导的结果。
   复核方法（离线，安全）：
   ```python
   import sys; sys.path.insert(0, 'scripts')
   from quality_v2 import catalog_index, sku_satisfies
   skus = catalog_index()
   for case in [json.loads(l) for l in open('evals/quality-v2/shopping/holdout2.jsonl')]:
       if case['kind'] == 'compare': continue  # compare 金标为空是惯例
       derived = sorted(k for k, s in skus.items() if sku_satisfies(s, case['hard_constraints']))
       assert derived == case['satisfaction_set'], case['case_id']
   ```
2. **题意↔约束一致**：读 `user_turns`，确认约束集合忠实反映用户最后一轮的累积语义（多轮题取末轮存活约束）；金标为空必须是"合法空集"（约束冲突/超库存），不是标注错误。
3. **分/元换算**：所有 `budget_max_cents`/`min_price_cents` 必须 = 用户说的元数×100（历史上踩过 3000元≠300000分 的坑）。
4. **compare 题**：`comparison_targets`/`allowed_target_terms`/`expected_comparison_complete` 三件套齐全且目标词在目录中可命中。
5. **查重**：问句措辞、coverage 形状与 dev 65 题不重复（同形状不同词是加分——留出要测泛化）。

### 客服（8 题）
1. **claims 子串**：每条 `checkable_claims[].text` 必须是该题可见语料（`visible_doc_ids` 正文 + `knowledge_setup` 文档正文）的**连续子串**（NFKC casefold）。复核：
   ```python
   from quality_v2 import _corpus_for, _fold
   # 构造 {'visible_doc_ids': [...], 'knowledge_setup': {...}} 后 _fold(claim) in _fold(_corpus_for(case))
   ```
2. **essential/peripheral 恰当性**：essential 应是"不说即答案错误/不完整"的核心命题；判卷只算 essential——分级过严会把诚实答案误伤，过松会放水。
3. **expected_handoff/allow_insufficient 语义**：claims 题一般 `false`；冲突/例外/ACL 题 `true`；过期/撤回题沿用 `false + allow_insufficient` 惯例（注意 dev 里 sup-d-04/05 同类先例；该哲学本身在 v11 有争议记录，草案沿惯例即可）。
4. **must_not_claim 防误伤**：每条 needle 不得是本题任何金标 claim 文本的子串（或前 8 字内有否定词）；也不得出现在问句里。误伤会把正确答案误判违规。
5. **extra 文档**：`checksum_sha256` = 文件内容 sha256；冲突对两份确属不可调和的冲突；MERCHANT/生命周期字段与 dev 同类题（sup-d-05/06）形状一致。
6. **查重**：claims 句与 dev 62 题的全部 claims 零重复（生成器声称已查，独立复核）。

### 广告（7 本）
排序公式（`growth/src/smartlect/ads/service.py::rank_ads`）：
`score = relevance × fatigue × (.5 + .5 × pacing)`，其中
`fatigue = 1.0（点过）else 1/(1+该观众在该素材上的曝光数)`；`pacing = (budget-spent)/budget`；
平手按 campaign_id/creative_id 字典序破（剧本槽位前缀 a<b、a1<a2 保证方向）。
耗尽语义：最后一击扣满时 click 事务自动把活动转 `EXHAUSTED/budget_exhausted`，后续点击/曝光 409
`ads_not_active`，且活动从推荐候选消失（`remaining < cpc` 即被过滤）。
1. **每个 probe_rank 的期望可由公式手工推出**（同 SKU 双活动 relevance 打平是前提——`same_sku: true` 必须在）。
2. **计数一致性**：`expected.counts` 的 impressions/clicks = 脚本 expose/click 之和；payments 恒 0；
   `CTR`/`CVR` 与计数算术一致（含 null 语义：clicks=0 → CVR=null）。
3. **拒绝/状态断言**：`reject` 的 error 只允许 `ads_not_active`（耗尽后）或 `ads_budget_exhausted`；
   `probe_status` 期望与耗尽语义一致。
4. **基础三本**（impressions_only/clicks_no_payment/attributed_payment）流量形状与 dev 不同但结构合法。

### 全局
1. 独立性：三线草案与 dev/holdout-1 的题面、金标、claims、coverage/kind 形状零复制。
2. 规模与结构：导购 8 / 客服 8（essential 5）/ 广告 7（机制 4 + 基础 3）——比例与覆盖面是否合理（holdout-1 是 7/6/4）。
3. 悖论检查：没有任何题依赖系统当前的已知缺陷才能通过（d-58 类通道失败除外——shop-h2-07 家具 browse 是有意复测该路径，属设计内）。

## 裁决回传格式（交给用户转给主对话）

```
## 审核结论：通过 / 需修改 / 拒绝
### 必改项（阻塞盖章）
- <题号>: <问题> / <建议>
### 建议项（不阻塞）
- ...
### 复核记录
- 金标重推导：8/8 一致（或差异清单）
- claims 子串：全部通过（或违规清单）
- must_not_claim 误伤检查：通过/…
- 计数一致性：7/7（或差异）
- 查重：无重叠（或重叠清单）
```

注意：审核者只给结论与修改建议，**不执行修改**（修改由主对话在盖章前统一落实并重新 validate）。
