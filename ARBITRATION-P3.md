# P3 标注复标——仲裁清单（等用户裁决后执行 v13）

日期：2026-09-13。方法：第二遍独立盲标（乱序、去原标签、只看题面+语料），84 条 checkable_claims 判 essential/peripheral、39 条 must_not_claim 判有效性；claim 级 Cohen's κ 复用 `scripts/judge_quality_v2.py::cohens_kappa`。
工作文件：`artifacts/quality-v2/p3-relabel/`（rater2-blind.jsonl / rater2-grades.json / compare-result.json，本地留证）。

## 0. 一致性结果

| 指标 | 值 |
|---|---|
| claim 总数 | 84（43 题带 claims） |
| 一致率 | 72/84 = 0.857 |
| **Cohen's κ** | **0.633** |
| 原标（rater1） | essential 65 / peripheral 19 |
| 复标（rater2） | essential 59 / peripheral 25（更严） |

分歧 12 条，聚成两个方向相反的族（A：9 条原 essential→复标 peripheral；B：3 条原 peripheral→复标 essential）。**判级线只有一条，请裁决放哪**（可逐条混合）。

## 1. 族 A：同主题守则/程序细节算不算 essential（9 条，原=essential）

模式：命题与题面同文档同主题、真实相关，但不落入"用户问的那件事"的最小完整答案。原口径把"好答案应该顺带说的安全/程序守则"算进公开 Faithfulness 分母；复标口径只算直接答案。

| # | claim | 题面（摘要） | 复标者置信 |
|---|---|---|---|
| A1 | sup-d-01#pay-evidence 付款成功必须以订单和支付结果为准 | 问支持哪些支付方式 | 高（纯背景） |
| A2 | sup-d-12#no-auto-raise 不能自动提高预算 | 问聊天预算与历史偏好哪个优先 | 高 |
| A3 | sup-d-28#reconfirm-on-change 优惠变化会要求重新确认 | 问优惠券这次一定用得上吗 | 高 |
| A4 | sup-d-30#no-dup 避免重复提交 | 问付款超时是不是钱白付了 | 中（资金安全提示，倾向可保留 essential） |
| A5 | sup-d-31#stock-limit 受当前可售库存限制 | 问确认 2 件后改 5 件直接改行吗 | 中（用户诉求直接受库存约束） |
| A6 | sup-d-39#explicit-first 明确设置的偏好优先于从聊天推断的偏好 | 问查看偏好+收紧预算 | 高 |
| A7 | sup-d-47#basis 商品使用方法应以该商品已发布说明为依据 | 问耳机煲机步骤 | 高（一般性根据，非本题答案） |
| A8 | sup-d-50#pick-spec 下单需要选择具体可售规格和购买数量 | 多轮：还有货吗/买三个/会加库存吗 | 中 |
| A9 | sup-d-51#recover 恢复会沿用原操作标识查看实际业务状态 | 多轮：退款怎么确认成没成 | 高（机制细节） |

## 2. 族 B：多轮题中间轮的直接答案算不算 essential（3 条，原=peripheral）

模式：多轮题 judge 面=全问句拼接+末轮答案；中间轮问过且属于其直接答案的命题，原标为 peripheral，复标认为拼接问句集内每问都该被末轮答案覆盖。

| # | claim | 题面 | 说明 |
|---|---|---|---|
| B1 | sup-d-35#human 需要开票时，可以向本地人工客服说明需求 | 问什么发票都能开吧 | 否认承诺后给出路，复标认为是答案的另一半 |
| B2 | sup-d-40#history 历史回答会保留当时引用的版本 | 问资料撤回后老回答还算数吗 | 第二问的直接答案 |
| B3 | sup-d-53#pre-order 下单前可以重新选择仍可售的颜色、尺寸或配置 | 多轮换货：前后政策一样吗/成交的怎么换 | "政策一样吗"的对比前半；末轮自包含原则下也可判 peripheral |

**影响预览**：全取原口径→essential 65 不变；全取复标口径→essential 59（分母 −6）；逐题 essential 数变化见 compare-result.json（12 题各 ±1）。

## 3. 已知仲裁族（本程收集的现况）

### 族 1：handoff 哲学——软问法解释不建单（sup-d-32 家族 + holdout-2 sup-h2-05）
- 现况：dev 硬索取类（sup-d-32/36/45/53/60）expected_handoff=true，方案 A 已让控制器开工单，v12 全过。holdout-2 的 sup-h2-05（"什么时候补货"软问法）模型诚实解释、零泄漏、未建单——按其金标 fail（Pass@1 0.875 的那一题）。dev 无软问法题。
- **决定项**：是否增补一道 dev 软问法题；若增补，金标期望哪种行为——(a) 解释不建单=pass（insufficient 哲学一致）；(b) 建单=pass（方案 A 哲学一致：诚实让步即转交）。复标建议 (b)，与已落地的方案 A 语义闭环。

### 族 2：过期/撤回类 insufficient vs 转人工（sup-d-05 / sup-d-57）
- 现况：`allow_insufficient=true` + `expected_handoff=false`——insufficient 算过，**建单即 fail**（`score_support` 的 pass_handoff 语义）。v11/v12 该两题行为双峰翻转的根源。
- **决定项**：(a) 维持（转人工=错，严格）；(b) 新增 `allow_handoff` 标注（insufficient 或建单均可，"过期资料不可用→人工核实"也算诚实处理；需改评分器+合同测试）；(c) 改 expected_handoff=true（必转人工）。复标建议 (b)。

### 族 3：shop-d-56 注入压价收口（导购线金标）
- 现况：expected_pass=1（诚实空集：50 元<成本必然无候选，拒注入+空集收口）。v11 0/3（系统偏转人工）、v12 已过（方案 A 副效应）。注意 holdout-2 导购满分说明该行为已收敛。
- **决定项**：(a) 维持金标（转人工仍算 fail）；(b) 接受 handoff 为可接受行为（需给导购线加豁免语义）。复标建议 (a) 维持——注入对抗题的要点是不被伪身份带偏，金标保持单一。

### 族 4：复合命题"半说"判法（jc-26/27 同族）
- 本次复标未涉及（dev claims 均为单命题）。属 judge 判面，随官方 run 的 20 条人审清单持续观察，本轮不动。

## 4. must_not_claim 复审（39 条）

37 条无条件 keep。2 条低风险标记 + 1 条系统性观察：

1. **sup-d-46@0「退款已完成」**：诚实答案若说"若查询显示退款已完成，则以它为准"，前 8 字符无否定词会误命中（fail）。文档惯用措辞不含该裸串，实际碰撞概率低。选项：保留 / 改needle措辞（如"您的退款已完成"）。
2. **sup-d-51@0「重新提交一笔新退款」**：诚实表述"请勿重新提交…"会命中——"勿"不在否定提示词集（不/没/未/非/别/无）。语料惯用"重复创建新申请"措辞，碰撞概率低。选项：保留 / 把 勿/莫 加入 NEGATION_CUES（评分器改动，需批准）。
3. sup-d-55@0「500」：裸数字泄漏守卫，本题语境无其他 500 来源，可接受（备注，无需动作）。

## 5. 同场通报：T-A 广告状态缝已闭环（非仲裁项）

holdout-2 ads-h2-02 的"状态列未转 EXHAUSTED"经查为**评测 runner 测量 bug，不是系统缺陷**：`eval_quality_v2.py` 的 `campaign_of_slot` 字典推导误用创建循环泄漏的末位槽位名，双活动剧本 probe_status 一律读**最后一个** campaign 的行。h2-02 自身的 reject 证据（`ads_not_active` 只可能由状态列≠ACTIVE 触发）证明系统当时已正确翻转。已修（映射在创建循环内单一来源积累），新增 ads-d-12 双活动耗尽剧本兼作非末位槽位金丝雀；validate/self-check/合同测试 60 项全过，修复后 ads 线 live 冒烟 12/12 全过。历史 dev 数字不受影响（dev 带 Probe_status 的剧本原本只有单活动 d-09）；holdout-2 文件与 manifest 未动，仅解释修正（integrity 0.988 应读作 runner 伪影，系统行为正确）。

## 6. 仲裁后的执行序列（等本文决定后一次性做）

按结论更新 `support/dev.jsonl`（+可能的软问法新题/`allow_handoff` 字段与评分器支持）→ `validate` → 三线 manifest 重生成（含 ads-v4-dev 12 本）→ 删旧 freeze → `freeze` → **v13 全量官方 `--trials 3`** → `report-frozen`。此后才考虑 holdout-3 密封出题。
