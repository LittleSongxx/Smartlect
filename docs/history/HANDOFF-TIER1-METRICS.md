# Handoff：Tier-1 诊断指标实施 + holdout-3 首测窗口（quality-v2 下一程）

日期：2026-09-14。仓库：`/home/song/code/Smartlect`，分支 `main`，HEAD `85791ef`。
本文给**新开的 AI 对话**接手用。先读本文，再速读 `IMPLEMENTATION_STATUS.md`（本地、唯一现状来源，含完整战役史）与 `docs/quality-eval-v2.md`（体系索引）。

一句话：**四场类级修复后 v15 全线历史最好（导购 Pass@1=0.974、客服 Recall@8=1.0/Pass@1=0.978、广告 integrity=1.0），holdout-3 已盖章待首测（等用户指令，不得自跑）。主任务是实施用户已认可的六项 Tier-1 诊断指标（MRR@8、Recall@1、Context Precision@8、首位合规率、空集诚实率、建单 F1）并用 v13-v15 历史证据回填对比；Tier-2（公开表头变更）等用户看完回填数字再定。**

## 1. 已锁定决定（不要重开、不要推翻）

1. **quality-v2 是唯一评测体系**；旧评测仅存 git 历史，数字不可比。
2. **合同 v6/v6.1/v6.2 公开表头**：导购 `Pass@1`+`Precision@4/ceiling`；客服 `Recall@8`+`Faithfulness`（DeepSeek judge、quote 门控、只算 essential）；广告 `Attribution_integrity`。每指标印分母+Wilson 95% CI；不合成总分。**claims 判级原则 v6.2 已成文**（essential=删去后被问出的问题落空或被误导性部分回答；两条操作款见合同）。
3. **方案 A 及其扩展已落地**（服务请求+让步→工单；推诿话术第三析取；许可问句分类；ACL 分流仅 MERCHANT 建单；访客引导登录）。
4. **四场类级修复已入系统**（提交 20b7179/9df119f）：状态自答强制政策取证闸门、建单边界四件套、必含词头词收获帧、回退授权替换闸门。勿再调窗口/skill/检索策略。
5. **holdout-1/2 已烧毁**（文件存证不动）；**holdout-3 已盖章**（85791ef，三线 manifest 8+8+8，首测即终测）：**等用户指令才跑（建议 `--trials 3`），不得自跑、跑后不调题不调系统**。
6. 不为单题打补丁；改系统前问用户；改提示前跑悬崖探针（§5-2）；P3 教训：改 dev.jsonl 只按仲裁结论。
7. **Tier-1 指标方案已经用户认可方向**（本轮对话结论）：六项诊断列（详见 §3），确定性计算、零 judge 成本；NDCG 否决（金标无序）、Answer Relevancy 公开化否决（无分离样本+judge 噪声）、micro-F1 单报否决（要加 macro）。

## 2. 现状快照

### v15 官方基线（`official-v15-20260914`，393 试验，report.md 已生成）

| 线 | v15 | v14 |
|---|---|---|
| 导购 65 题 | `Pass@1=0.974`（CI 0.940–0.989）、`P@4/ceiling=0.962`、翻转仅 shop-d-65 | 0.954 / 0.936 |
| 客服 63 题 | **`Recall@8=1.0`**（151 试验）、`Pass@1=0.978`、`Faithfulness=0.829`（回落 8pt=通过题表达面单试验翻转，无 Pass 回归，已拆账见状态文档） | 0.987 / 0.914 / 0.911 |
| 广告 12 本 | `Attribution_integrity=1.0` | 维持 |

**Recall 深度曲线（从 v15 证据逐排名实测，Tier-1 的动机）**：Recall@1=0.833 / @2=0.960 / @4=1.0 / @8=1.0；金标从未掉出前三位。即 @8 饱和（语料仅 32 篇文档），判别力在 @1/MRR。金标大小分布：单金标 126/150、双金标 18、三金标 6。

### 剩余失败/观察项（都有证据，勿单题修补）

- 客服 fail 仅 sup-d-63（软问法判别性设计题，预期内）+ sup-d-43 单试验翻转；shop-d-65 翻转、shop-d-19/34 已修复。
- setup_failed 台账 5 题（shop-d-10/26/49、sup-d-38/50——通道类 `Run retains its actual requested model mode`，v15 未补跑）。
- sup-d-60 维持 2/3（推诿措辞概率方差）；Faithfulness 表达面 8 题单试验翻转（judge MoE ±4pt 噪声带）。

### 工作树状态

用户自己改了三个文档未提交（README.md、docs/quality-eval-v2.md、docs/runtime.md——demo 命令与数字同步）——**不要动、不要提交它们**，由用户处理。其余干净。

## 3. T-A 主任务：六项 Tier-1 诊断指标（用户已认可方向）

全部为**诊断列**（不进公开表头、不改分母、不改判分）——scorer 改动+合同测试即可，无数据集变更（**不需要** manifest/freeze 重盖；注意 metrics-contract.json 在 manifest 里有哈希，若往 json 加字段则需三线 manifest 刷新+freeze 重盖——建议只在 metrics-contract.md 文档化，json 不动即可完全避免）。

**数据源**：证据文件 `artifacts/quality-v2/<run>/support|shopping/<case>.t<k>.json`；检索面=`model_runs[].tool_receipts` 中 `tool_calls` 名为 `search_knowledge` 的 `receipt_json`（解析后取 `data.candidates` 或顶层 `candidates`，**只有最后一次真实检索计分**——同名先例 `quality_v2.last_real_search` 已有判别逻辑可参考）；导购选品面=`model_runs[-1].run.result.selected_sku_keys`（顺序即展示序）与 `result.products`。逐题金标：`evals/quality-v2/support/dev.jsonl` 的 `relevant_doc_ids`、`evals/quality-v2/shopping/dev.jsonl` 的 `hard_constraints`+`satisfaction_set`（由 `sku_satisfies` 可再推导）。

1. **MRR@8（客服检索）**：每有效试验（金标非空且发生过真实检索），对每个金标 doc_id 取其在最后一次检索 candidates 去重序中的排名 r，试验得分=1/min(r)；多金标取平均（先平均后除）。line 级=按试验宏平均。null 条件与 Recall@8 相同。
2. **Recall@1（客服检索）**：全部金标均排名 ≤1 的试验占比。与现有 `Recall@4_diagnostic` 并列。
3. **Context Precision@8（客服检索，RAGAS 同义）**：binary 金标下的 rank-weighted precision：对去重 candidates 前 8 位，第 i 位命中金标则计 precision@i=(截至 i 的金标命中数)/i，总分=Σ(precision@i×hit_i)/|金标集|（无命中记 0）。
4. **首位合规率 violation_free@1（导购）**：分母=选择列表非空的计分试验；分子=`selected_sku_keys[0]` 满足该题全部硬约束（`sku_satisfies(case['hard_constraints'])`）。空集题不计入分母。
5. **空集诚实率 empty_set_honesty（导购）**：分母=`satisfaction_set` 为空的题的计分试验；分子=该试验 L 为空 ∧ `empty_reason∈{hard_constraint_unsatisfied,no_eligible_sku}` ∧ 未走热销补位（即空集题里的 pass 贡献）。若分母为 0 记 null。
6. **建单 F1 handoff_f1（客服）**：金标=`expected_handoff`；预测=终态"开了持久工单"（`handoff` 字段）。**关键口径**：`allow_handoff=true` 的题（sup-d-04/05/57/59）两种行为都算对——**从 F1 分母中剔除**并单独报剔除数（它们不是可判定的负例）。输出 precision/recall/F1 三数+分母。必须用**编译后终态**（result['handoff']），不是模型原始声明。

**实现位置**：`scripts/quality_v2.py`——`score_support`/`score_shopping` 已在 row 里填诊断字段（先例 `Recall@4_diagnostic`、`Faithfulness_rule`）；`aggregate_line` 的指标集合与 `denominators`；`write_report` 的线表与合同摘要；`scripts/test_quality_v2.py` 加已知值用例（构造小夹具：可控 candidates 序/选择序，断言各指标精确值——MRR/CP 的手工期望值先算好）。report-frozen（P6 生成器）同步纳入新列。
**回填脚本**：写一个离线脚本（放 `artifacts/quality-v2/tier1-backfill/`，用绝对路径 venv）扫 v13/v14/v15 三个 run 的证据直接计算六指标，产出历史对比表交用户——**不需要栈、不需要改历史 run 目录**。v15 的深度曲线已验：MRR≈(0.833+次位修正)、CP 等数字应与 §2 曲线自洽（0.833 的 @1 是你校验回填脚本正确性的锚点）。
**验证序列**：合同测试全绿 → self-check 完美轨迹满分不变量保持 → `validate` 绿 → 回填表交用户。Tier-2（公开表头：检索线 MRR、导购首位合规率、意图 F1 入公开）**等用户看完回填数字拍板**，届时走合同 v6.3 修订（md+json+manifest 刷新+freeze 重盖+合同测试）。

**可选延伸（用户提过，Tier-2 时再议）**：request_kind 五类意图 micro/macro-F1 需先给每题标 expected_kind（case `kind` 字段半自动映射+人工校）——若用户要，先出映射草案交确认，勿自裁。

## 4. T-B/C/D：其余任务

- **T-B holdout-3 首测**：等用户指令。命令：`scripts/` 下 `--official --trials 3 --split holdout3 --output artifacts/quality-v2/official-holdout3-<日期>`；后台+仓内日志+setsid；跑完 `report-frozen`。**跑前不碰题目文件；跑后不按结果调任何东西**，读数归因入状态文档即可。
- **T-C 台账补跑**（可随时）：`--case shop-d-10,shop-d-26,shop-d-49,sup-d-38,sup-d-50 --trials 3 --output artifacts/quality-v2/v15-repair-pending`，通道类留痕。
- **T-D 观察项维持**：不动系统；若用户要修 sup-d-60 推诿措辞方差/检索首位错位（Recall@1=0.833 的 25 试验），按"类级+悬崖探针+先问用户"纪律走。

## 5. 陷阱与经验（本程真踩过，前车之鉴）

1. **growth 跑 venv 安装包**：改 `growth/src` 后必须 `growth/.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation /home/song/code/Smartlect/growth`（绝对路径！），再按 PID 重启 worker：`kill $(pgrep -f "smartlect\.worker" | head -1) $(pgrep -f "smartlect\.app" | head -1)` → `./scripts/dev.sh up`。**测试/验证结果诡异时第一怀疑旧包**（本程两次假警报）。
2. **悬崖探针**：动任何 prompt/skill/schema/mission 抽取前必跑 `run --case shop-d-05,shop-d-22,shop-d-25,shop-d-35,shop-d-37 --trials 1`。
3. **长跑必须** `setsid nohup ... < /dev/null &` **脱离进程组**——本程一次 zcode 更新把 nohup 进程杀成挂起僵尸（日志停更但进程活着，误判已死导致双写风险）。判活用日志 mtime 而非 pgrep（pgrep 会匹配自身命令行）。
4. **WSL/Docker 事故处置**：docker CLI 全线 SIGBUS=loop0（docker-wsl-cli.iso）I/O 损坏，需用户重启电脑；恢复后 `processes.json` 有陈旧 PID 复用陷阱——`dev.sh up` 报 "PID xxx identity changed" 时，按 `/proc/<pid>/stat` 的 start_ticks（第 22 字段）与记录比对清理死条目再 up。
5. **MySQL 门控测试套件（SMARTLECT_RUN_MYSQL_TESTS=1，自起 docker）预存 14 红**（套件腐化，非新近改动引入；闸门开/关失败集逐字相同验证过）——**maintained 基线是非 MySQL 的 discover 全量**（当前 369+，全绿为过关线）；MySQL 套件勿混入功能战役，待专项。
6. **judge MoE ±4pt**：指标级波动在带内不构成回归结论，逐题分解再下判断；Faithfulness 分母 null 先查是不是 sup-d-16（无 essential 的合同性 null）。
7. **改 IMPLEMENTATION_STATUS.md 插入新条目时**，用"新条目+还原旧条目标题行"的方式，别拿旧条目首行当锚点替换——本程连犯六次把旧条目搞成孤儿段落。
8. bash cwd 调用间持久；统一 `cd /home/song/code/Smartlect/scripts` 后用绝对路径 venv。
9. 评分器/合同改动顺序：合同测试→self-check→validate；数据集改动才需要 manifest 重生成→删旧 freeze→freeze。
10. 官方 run 后自动生成 20 条 judge 人审清单（`judge/human-review.*`）——新指标若涉 judge 面才需关注，Tier-1 六项全部确定性。

## 6. 关键路径速查

- 合同/数据集/留出：`evals/quality-v2/`（`metrics-contract.md` v6.2；shopping|support|ads 各自 dev+holdout+holdout2+holdout3 与 manifest；support/extra 的 eval-*（dev 用）与 holdout*-*（存证勿动）与 holdout3-*（已盖章勿动））
- 评分/runner/judge/报告：`scripts/quality_v2.py`（Tier-1 主战场）、`eval_quality_v2.py`（run/validate/self-check/freeze/judge/judge-calibrate/report-frozen，`--split holdout3` 已接线）、`judge_quality_v2.py`（judge+人审清单+cohens_kappa）
- 证据：`artifacts/quality-v2/official-v5…v15` + holdout1/2 终测 + `rerun-ledger.jsonl`（append-only 永不删）+ 各验证 run（gate-verify/boundary-verify/b2-verify/v14-repair-pending）
- 状态文档：`IMPLEMENTATION_STATUS.md`（gitignore、本地）——**每完成一项更新它，用户已授权"提交不用审批"，沿用**（注意用户自己的三个未提交文档别碰）
- 架构：`docs/adr/0001–0004`；体系索引 `docs/quality-eval-v2.md`
- 栈：`./scripts/dev.sh infra-up` → `up`；健康检查 growth `/health`（`run/runtime.env` 的 `SMARTLECT_GROWTH_PORT`，当前 18001）；judge 密钥 `run/model.env`
- 回归底线：合同测试（当前 70 项，`scripts/test_quality_v2.py`，系统 python 可跑）+ 增长全量（`growth/.venv/bin/python -m unittest discover -s growth/tests`，当前 369+）+ self-check 完美轨迹=满分不变量
- v15 证据锚点：Recall@1=0.833（125/150）、@2=0.960、@4=@8=1.0——回填脚本的正确性校准值

## 7. 第一小时建议路径

1. 读本文+状态文档 → 2. 查栈健康（§5-4 恢复术）→ 3. 实施六项指标（§3：scorer→测试→self-check/validate→回填脚本）→ 4. 回填表交用户定 Tier-2 → 5. 期间若用户下 holdout-3 首测指令，暂停 Tier-1 先跑密封卷（T-B 优先级最高且不可逆）。
