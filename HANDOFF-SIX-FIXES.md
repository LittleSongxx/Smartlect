# Handoff：六个修复优化项（质量指标收尾战役）

日期：2026-09-15。仓库：`/home/song/code/Smartlect`，分支 `main`，HEAD `d1d8e94`（本文提交；其间 `035e0f7…d1d8e94` 有生产加固战役的并行提交，与本战役无关，勿动 `run/`、`docs/prod-hardening/` 相关）。
本文给**新开的 AI 对话**接手用。先读本文，再速读 `IMPLEMENTATION_STATUS.md`（本地、唯一现状来源，含完整战役史；评测条目集中在"2026-09-14 评测体系转向"及其后续条目）。

一句话：**客服线 support-eval 五指标已官方定稿（fix3：Recall@5 0.949 / MRR 0.865 / 覆盖率 0.848 / Faithfulness 0.9605 / 库外诚实率 1.0），导购/广告维持 quality-v2 v15 基线（0.974 / 0.962 / 1.0）。用户已委托六个修复优化项（本文 §3），按 T3→T1→T5→T2→T4 顺序执行，T6 明确不修。**

## 1. 已锁定决定（不要重开、不要推翻）

1. **客服评测 = `evals/support-eval/` 五指标记分卡**（77 题六层 × 47 篇含干扰共享语料），设计原则用户拍板："不为生产严谨服务，为面试叙事服务"——指标全用面试标准词汇、标注面最小（question/reference_answer/points/gold_docs）。RAGAS 方案（`f8976c1`）只冒烟即退役；quality-v2 客服线全套指标退役，**数字不得再引用**。
2. **holdout-3 整卷作废**（manifest 存证保留、永不运行）；holdout-1/2 已烧毁。`--split holdout3` 通道永不再触发。
3. **导购/广告线维持 quality-v2**（合同 v6/v6.1/v6.2 现状）；行为面（客服建单/ACL/注入）已放弃测量，不要试图恢复。
4. 官方终态=fix3 系统态：**skill `support_policy` 1.9.0 已部署且与官方记分卡一致**（1.9.1 完整性实验净值持平已回退存证）。改 skill 前先想清楚是否会打破"部署态=官方数字态"，改完必须全量复测定稿。
5. 提示词迭代纪律：**每类最多两轮**，不为单题打补丁；judge 指标 ±2–4pt MoE 带内波动不下结论。
6. 提交不用审批（用户已授权沿用）；状态文档每完成一项更新。

## 2. 现状快照

- **栈**：活栈运行中（growth :18001 健康）。growth 375 测试全绿基线（`growth/.venv/bin/python -m unittest discover -s growth/tests`，非 MySQL 全量）。
- **系统改动现状**：`smartlect/answer_guards.py`（状态声明守卫，已接线 shopping.py answer_node）+ support_policy 1.9.0（答案纪律硬约束）。均在提交 `f0ea881`。
- **评测资产**：`scripts/eval_support_eval.py`（collect/score）、`scripts/check_support_eval.py`（题库门禁）、`artifacts/support-eval/`（collect-20260914{,-fix1,-fix2,-fix3,-fix4} + 各 probe；**官方数字=collect-20260914-fix3**，注意 fix3 的 scorecard 是要素重裁+逐点判定后的重判版）。
- **导购侧资产**：quality-v2 全套（`scripts/eval_quality_v2.py`，`--line shopping` 可单线跑）；Tier-1 诊断列已在 scorer（提交 5bbb3b3）。
- **工作树**：用户自己的未提交文件 `HANDOFF-PROD-HARDENING.md`、`docs/prod-hardening/monitoring.md`——**不要动、不要提交**。本文 HANDOFF-SIX-FIXES.md 接手后由接手者处置。

## 3. 六个任务（用户已委托；推荐顺序 T3→T1→T5→T2→T4，T6 不修）

### T3（P3，先做：小修）r-049 守卫预算耗尽通道失败

- **证据**：`artifacts/support-eval/collect-20260914-fix3/r-049.json`（fix2/fix3/fix4 连续同点 FAILED，error=`AssertionError: Run retains its actual requested model mode`）。根因高置信：守卫的 ValueError 拒绝消耗了**唯一的** `answer_repairs` 预算（shopping.py:454 初始化 `min(1, len(answer_rejections))`），后续任何校验失败直接 `BudgetExceeded('answer_contract_failed')` → 通道断言。
- **修法**：守卫拒绝与 schema 拒绝分账（如 `context['guard_repairs']` 独立一次机会），或守卫触发路径不升级 BudgetExceeded（对齐 state_claim_residual 的放行哲学）。
- **验证**：单测（guard 拒绝后仍可 schema 修复一次）→ growth 全量绿 → `collect --case r-049` 连跑 3 次全 COLLECTED → 全量复测恢复 77/77。
- **预期**：分母恢复 77；半小时级。

### T1（P1，性价比最高的真修复）导购空集诚实率 0.783 → 0.92+

- **证据**：v15 `artifacts/quality-v2/official-v15-20260914/`：不诚实试验 = shop-d-56 全 3 试验（**rule-fallback 以 support 风格 `insufficient` 收口，从未经过选品面、retrieve_diagnostics 为空、无合法 empty_reason**——注入题把模型预算烧光后走 closeout 路径）+ shop-d-65 两试验（USB 线空集题拿鼠标键盘凑数）。
- **修法**（两处，均在 growth）：(a) closeout/编译层：购物面问题在 rule-fallback 收口时生成选品面合法空集（empty_reason=hard_constraint_unsatisfied、selected 空），而不是 support 式 insufficient 文本；(b) shop-d-65 类凑数=空集纪律，可借回退授权闸门同类手法（force 一轮"按约束收口"修复）。注意 (a) 是编译层修复，先例=建单边界四件套（`9df119f`）。
- **验证**：growth 全量绿 → 悬崖探针（shop-d-05,22,25,35,37 ×1 不回归）→ 空集 9 题 ×3 试验（`eval_quality_v2.py run --line shopping --case shop-d-03,04,06,09,13,16,17,35,38,56,64,65 --trials 3 --output artifacts/quality-v2/empty-honesty-verify`，注意其中 compare 题不进该指标分母）→ empty_set_honesty 列回 0.92+。
- **风险**：动编译层，悬崖探针必跑；shop-d-65 概率纪律可能需要二轮，止于两轮。

### T5（P5，评测基建）judge 指标官方数字改双跑均值

- **证据**：四轮覆盖率 0.860/0.879/0.841/0.843、faith 0.884/0.899/0.960/0.934——单试验 ±2–4pt 方差吞过真实改进的读数。
- **修法**：`eval_support_eval.py` 加 `--repeat 2`（collect 跑两份独立目录，score 各判后取逐题均值再聚合；报告注明 n=2×77）。或者最简版：官方流程约定跑两次 collect、手动对比取均值并在 scorecard 标注。
- **验证**：一次双跑，两轮差值应落 ±4pt 带内；报告模板更新。
- **预期**：不提分，让 T1/T2 的效果可判读。

### T2（P2，冲覆盖率 0.9 的唯一剩余路径）finish_answer 参数模板

- **证据**：四轮平台期 0.84–0.88；fix4 要素完整性条款只把 L3 数值层 0.727→0.955，整体净值持平——**提示词层已到顶，缺口是多参数复述无强制机制**（问退货漏时限、问积分漏到账天数）。
- **修法**：`FinalAnswer` schema（shopping.py）加可选参数字段组（如 `policy_facts: [{kind: 金额|时限|数量|条件, text}]`），模型 finish_answer 时对政策题必须逐项填；编译时对"引用了政策文档但零 policy_facts"触发一轮定向修复（复用 answer_rejections 机制，注意与 T3 的预算分账联动）。**只填证据里写明的内容**——模板化复述天然低 faith 风险，这是它优于提示词的原因。
- **验证**：单测 → growth 全量 → 悬崖探针（客服面无既定探针集，用 fix3 低分题 r-033/034/047/021 + 守卫题 r-016/017 + 库外 q-live-01/07 做 8 题探针）→ T5 双跑全量 → 覆盖率 ≥0.90 且 faith ≥0.94 判成功。
- **风险**：schema 改动牵动旧拒答路径与 evidence 结构；两小时级战役；失败判据=净值仍持平则回退（同 1.9.1 处置）。

### T4（P4，可选）L4 跨文档检索 Recall@5 0.850

- **证据**：多金标题系统性弱于单金标（L1=1.0）；fix3 层表。
- **修法方向**：检索侧多查询分解或复合问句改写强化（growth 检索管线）。收益不确定（+3–5pt），风险收益比最差，**建议做完 T2 后再评估是否值得**。

### T6（P6）Faithfulness 残余 3 例——**明确不修**

0.961 超业界线（0.85–0.95），残余全是推断类，提示已两轮边际递减。同理 L5 的 MRR 0.775 降级处理（旧版文档偶尔排前但 L5 faith=1.0，排序瑕疵未造成答案后果）。**不要重开。**

## 4. 陷阱与经验（本程真踩过，前车之鉴）

1. **解释器分工**：collect 必须用 `growth/.venv/bin/python`（scenario_client 依赖 smartlect/pika）；score 用系统 `python3`（openai 直连）。bash cwd 会在调用间漂移——**一律绝对路径**。
2. **改 growth/src 后**：`growth/.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation /home/song/code/Smartlect/growth`（绝对路径！）→ `kill $(pgrep -f "smartlect\.worker" | head -1) $(pgrep -f "smartlect\.app" | head -1)` → `./scripts/dev.sh up`。**测试/运行结果诡异时第一怀疑旧包**（本程三次：新模块 ImportError、守卫"未触发"排查走弯路——先 `grep` venv site-packages 确认装的是新码）。
3. **collect 的 evidence 必备字段**：`line/scenario/seed/documents` 必须预置（ScenarioClient 要求）；`json.dumps` 必须带 `default=str`（Java 快照含 Decimal）。
4. **长跑纪律**：`setsid nohup ... < /dev/null &` 脱离进程组；判活用日志 mtime/grep 不用 pgrep（会匹配自身）。速率 ~30s/题（47 篇整库灌入/题），77 题 ≈ 41 分钟。
5. **通道类失败** `Run retains its actual requested model mode`：偶发=重试一次即可；**连续同点失败=真 bug**（见 T3），不要无限重试。
6. **judge MoE ±2–4pt**：带内波动不下结论；读层均值不读单题；逐点判定是全对制（一条要点多事实须全中），2–3 要点题没有中间态。
7. **诊断先看留痕**：上一程把"真实 get_my_orders 观测"误诊为编造，根因是 collect 没存工具留痕（现已存 `tool_names`/`tool_receipts`）。判"编造"前先查 `tool_receipts`。
8. **状态文档插入**：新条目插在锚点条目之前、保留旧条目完整，别拿旧条目首行当锚点替换（历史教训连犯六次）。
9. **题库改动**必过 `python3 scripts/check_support_eval.py`（金标/近重复/溯源度/覆盖）；要点裁剪只按"问题所问"，不许看系统答案迁就（essential/peripheral 教训）。
10. 评测全景与简历数字映射见 `evals/support-eval/README.md` 与状态文档"全部质量指标"条目；不要引用任何退役数字（旧客服线全套、holdout 全系、RAGAS 冒烟值）。

## 5. 关键路径速查

- 客服评测：`evals/support-eval/`（corpus/ questions.jsonl README）+ `scripts/eval_support_eval.py` + `scripts/check_support_eval.py`；产物 `artifacts/support-eval/`
- 导购/广告：`evals/quality-v2/`（合同 v6.2）+ `scripts/eval_quality_v2.py`（run/validate/self-check/report-frozen）+ `scripts/test_quality_v2.py`（78 项，系统 python）
- 系统：`growth/src/smartlect/`（`agents/shopping.py` answer_node 校验链/`answer_guards.py` 守卫/`skills/support_policy.json` 1.9.0）
- 栈：`./scripts/dev.sh infra-up` → `up`；growth 健康 `:18001/health`；judge/embedding 密钥 `run/model.env`（走 `runtime.model_env()`）
- 状态文档：`IMPLEMENTATION_STATUS.md`（gitignore、本地）——每完成一项更新，提交不用审批

## 6. 第一小时建议路径

1. 读本文+状态文档 → 2. 查栈健康（growth :18001）与 `git log --oneline -6` 对上 HEAD → 3. **T3**（守卫预算分账：单测+重装+重启+r-049 三连测）→ 4. **T1**（空集 closeout 修复：探针+9 题×3 验证）→ 5. **T5**（双跑均值接线）→ 6. **T2**（参数模板战役，独立提交）→ 7. 每项完成即入档状态文档+提交；T4 做不做等 T2 结果再议。
