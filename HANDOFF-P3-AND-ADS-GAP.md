# Handoff：P3 标注复标与广告状态缝（quality-v2 下一程）

日期：2026-09-13。仓库：`/home/song/code/Smartlect`，分支 `main`，HEAD `1a81d6d`。
本文给**新开的 AI 对话**接手用。取代已删除的 `HANDOFF-EVAL-EXPANSION.md`（其阶段已完成）。
先读本文，再速读 `IMPLEMENTATION_STATUS.md`（本地、唯一现状来源，含完整调优史）与 `docs/quality-eval-v2.md`（体系索引）。

一句话：**测量体系已硬化并扩容（65/62/11 题、k=3 试验、Wilson CI、judge 校准 κ=1.0、冻结报告），v11 暴露的类级缺陷已修五项+方案 A（v12：导购 0.944/客服 0.934/广告 1.0），holdout-2 终测导购满分、客服检索满分。剩两件事：P3 标注复标（主任务）、广告状态缝补覆盖（等用户决定）。不是调系统，是校准尺子本身。**

## 1. 已锁定决定（不要重开、不要推翻）

1. **quality-v2 是唯一评测体系**；旧评测仅存 git 历史，数字不可比。
2. **合同 v6/v6.1 公开表头**（`evals/quality-v2/metrics-contract.md`）：导购 `Pass@1`+`Precision@4/ceiling`；客服 `Recall@8`+`Faithfulness`（DeepSeek judge、quote 门控、只算 essential）；广告 `Attribution_integrity`（断言级分母，v6.1 增 rank/reject/status 机制断言）。每指标印分母+Wilson 95% CI；不合成总分。
3. **有界窗口 14400 token / 43200 字节**、skill `shopping_advice` 1.13.0 / `support_policy` 1.8.0、检索策略 `shopping-constraint-v2`——勿再调。
4. **方案 A 已落地**（用户拍板）：服务请求类问句 + 答案让步（第一人称转交提议直接编译；必要性陈述须引用政策含"人工"）→ 控制器开工单。`growth/src/smartlect/agents/shopping.py` 的 `answer_offers_human_transfer`/`answer_states_human_necessity` 与 `looks_like_service_request` 扩展。
5. **P5 跨模型对比已放弃**（用户决定）；GLM 密钥不再需要。
6. **holdout-1 与 holdout-2 均已烧毁**（首测即终测），文件与 manifest 只存证不改动、不得据此调系统。当前无独立留出；下次密封出题待 P3 后。
7. 不为单题打补丁；改系统前问用户；改任何提示文本前先跑悬崖探针（§5-2）。

## 2. 现状快照

### 成绩基线（官方）

| 线 | 基线 run | 数字 |
|---|---|---|
| 导购 65 题 | `official-v12-20260913` | `Pass@1=0.944`、`P@4/ceiling=0.921`、pass^3=0.934、翻转仅 shop-d-34 |
| 客服 61 live | `official-v12-20260913` | `Recall@8=0.863`、`Faithfulness=0.726`（n=120 试验，±4pt 噪声带内波动）、`Pass@1=0.934` |
| 广告 11 本 | `official-v12-20260913` | `Attribution_integrity=1.0` |
| holdout-2 终测 | `official-holdout2-20260913` | **导购 8/8 满分（24/24 试验）、客服 Recall@8=1.0 / F=0.833 / 7/8、广告 6/7（integrity 0.988）** |

每条 run 都有 `report.md`（P6 生成器：`eval_quality_v2.py report-frozen --output <run目录>`，含指标↔设计↔归因映射表）。

### 本程修复链（提交 40e766c→1a81d6d，全部类级、零提示改动）

购买帧数量短语回流（d-58 七连败真凶）/ 价格口语缺口（以下·裸数·中文数字·区间）/ 类目中文词表桥 / 同参拒收拦截闸 + 拒收理由人话化 + no_business_claim offer 豁免 / 方案 A 开单编译 / 裸数金额溯源（d-50 回归修复）。细节与证据见 IMPLEMENTATION_STATUS 对应条目。

### 观察项（v12 数据，未修）

shop-d-19 回退授权 0/3、shop-d-34 1/3、shop-d-26 双峰 1/3——概率性纪律，修需动 skill 提示（悬崖探针先行 + 用户批准）。

## 3. 剩下的两件事（按序）

### T-A 广告状态缝（等用户决定是否补 dev 覆盖，先问）

holdout-2 的 ads-h2-02 发现：双活动小额预算耗尽时，**投放门行为全对**（后续点击/曝光 409 `ads_not_active`、活动从推荐候选消失），但活动**状态列未转 `EXHAUSTED`**（读为 ACTIVE/pause null）——`status:0.a` 断言失败。单活动形状（dev ads-d-09）同断言通过；"双活动 + probe_status"组合 dev 无覆盖。机制代码：`growth/src/smartlect/ads/store.py` 的 click 事务尾部 exhaustion UPDATE。
接手动作：先问用户"补不补 dev 剧本"。补则在 `evals/quality-v2/ads/playbooks.json` 加一本（镜像 h2-02 形状但换数字/槽位，script 计数由校验器推导，AnnotationError 强制），随 v13 一起测；不补则留档。**不许直接按 holdout 题目改系统**——若要查根因，先在 dev 侧复现（新建 dev 剧本），再按"改系统前先问"走。

### T-B P3 标注复标（主任务，等用户开工指令）

对开发集客服线做第二遍独立标注并报一致性：
- 范围：`evals/quality-v2/support/dev.jsonl` 全部 `checkable_claims` 的 **essential/peripheral 分级** + 全部 `must_not_claim`（约 64 essential + 11 peripheral + ~40 needle）；
- 方法：独立重标（不看原标注），逐题判级；然后算 claim 级 Cohen's κ（复用 `scripts/judge_quality_v2.py::cohens_kappa`）；
- 仲裁清单交用户，**已知仲裁族**（提前收集好）：
  1. sup-d-32 / sup-h2-05 / sup-d-56——"解释对但不建单/建单了但标注说不用"的 handoff 哲学（方案 A 已收编服务请求类，残余是软问法）；
  2. sup-d-05 / sup-d-57 过期撤回类 insufficient vs 转人工的行为方差（v11/v12 均翻转）；
  3. shop-d-56 注入压价收口（金标期望诚实空集，系统偏转人工）；
  4. 复合命题 claim 的"半说"判法（T2 校准 jc-26/27 同族）。
- 仲裁后更新 dev.jsonl → `validate` → manifest 重生成 → 删旧 freeze → `freeze` → **v13 全量官方 `--trials 3`** → `report-frozen`。此后才可考虑 holdout-3 密封出题（须全新题、独立审核、用户盖章，流程照抄 holdout-2：草稿→REVIEW 文档→独立 AI 审核→修→盖章→等首测指令）。

## 4. 不要做的事

- 不碰 holdout-1/holdout-2 任何文件与 manifest；不按已烧毁留出调任何东西。
- 不再调窗口/skill/检索策略；不动合同公开表头。
- 不为单 badcase 加词表/特例/改金标；不把 `setup_failed` 当垃圾桶。
- 不在共享栈上 `dev.sh down/build`；不主动 push；回复用户用简体中文。
- P3 改 dev.jsonl 属于数据集维护（允许），但它改变金标——**只按仲裁结论改，不自裁**。

## 5. 陷阱与经验（本程真踩过/验证过）

1. **growth 跑的是 venv 安装包**：改 `growth/src` 后必须 `growth/.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation ./growth`，再按 PID 重启：`kill $(pgrep -f "smartlect\.worker" | head -1) $(pgrep -f "smartlect\.app" | head -1)` → `./scripts/dev.sh up`。**测试报错先怀疑旧包**（本程两次假警报）。绝不 `pkill -f` 匹配含自身命令行的模式。
2. **悬崖探针**：动任何 prompt/skill/schema 前跑 `run --case shop-d-05,shop-d-22,shop-d-25,shop-d-35,shop-d-37 --trials 1`。
3. bash cwd 在调用间持久，统一 `cd scripts/` 后用绝对路径 venv（`/home/song/code/Smartlect/growth/.venv/bin/python`）。
4. **WSL 可能重启**（本程踩过：栈全灭、/tmp 清空、后台任务被杀）——恢复：`./scripts/dev.sh infra-up` → `up`；官方 run 后台跑（nohup + 仓内日志），定期轮询。
5. `campaign_id` 是全局主键：固定 id 跨 run 撞 `draft_idempotency_conflict`（用槽位前缀+run 哈希）。
6. DeepSeek judge 空返回/JSON 截断按陷阱#5 先例补判（从已存证据、留痕 `judge_repair`；补判脚本别把通道失败试验也判了——本程踩过并回滚）。
7. judge 有 MoE 方差（指标级 ±4pt@n=120 属噪声带）；单试验翻转分散 ≠ 回归，逐题分解再下结论。
8. 数据集改动顺序：`validate` → manifest 重生成 → 删旧 freeze → `freeze`；官方 run 后自动生成 20 条 judge 人审清单（`judge/human-review.*`）。
9. 标注正则三坑（都有单测守着）：购买帧数量短语、价格裸数（量词阻断）、疑问词尾巴——改 `shopping_mission.py` 前先跑 `growth/.venv/bin/python -m unittest growth.tests.test_shopping_mission`。

## 6. 关键路径速查

- 合同/数据集/冻结：`evals/quality-v2/`（`metrics-contract.md` v6/v6.1；`shopping|support|ads` 的 dev+holdout+holdout2+manifest；support/extra 的 eval-*（dev 用）与 holdout*-*（留出存证，勿动））
- 评分/runner/judge/报告：`scripts/quality_v2.py`、`eval_quality_v2.py`（run/validate/self-check/freeze/judge/judge-calibrate/report-frozen）、`judge_quality_v2.py`（含 `cohens_kappa`，P3 直接复用）
- 校准集：`evals/quality-v2/support/judge-calibration.jsonl`（32 对，金标由构造决定）
- 状态文档：`IMPLEMENTATION_STATUS.md`（gitignore、本地）——**每完成一项更新它，用户确认后提交**（本程用户已授权"提交不用审批"，沿用除非用户另说）
- 官方证据：`artifacts/quality-v2/official-v5…v12` + holdout1/2 终测 + `rerun-ledger.jsonl`（append-only）+ ADR 引用探针（atrisk/window/sup21/fixverify3/v8-repair-d26/holdout1-repair，勿删）
- 架构决策：`docs/adr/0001–0004`；体系索引：`docs/quality-eval-v2.md`
- 栈：`./scripts/dev.sh infra-up` → `up`；健康检查 growth `/health`（`run/runtime.env` 的 `SMARTLECT_GROWTH_PORT`）；judge 密钥在 `run/model.env`
- 回归底线：合同测试 60 项（`scripts/test_quality_v2.py`）+ 增长 364 项（`growth/.venv/bin/python -m unittest discover -s growth/tests`）+ self-check 完美轨迹=满分不变量
