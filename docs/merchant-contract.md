# F5 Merchant 源码合同

本文件描述当前本地源码的接口和执行边界，阶段验收以
[IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) 及对应运行证据为准。
当前推进 F6，完整门禁及 F7 独立交付仍未完成；各阶段的已验证功能、失败与剩余项以实施状态为准。
F4 投放细节沿用 [ads-contract.md](ads-contract.md)，交易与独立归因沿用
[contracts.md](contracts.md)。金额都是整数分，广告与付款均为本地模拟。

## 可信身份、稳定 scope 与 HTTP

管理入口通过 [IdentityBridge](../growth/src/smartlect/auth.py) 把 `adminToken` 交给 Java
会话校验，再检查 `subject_type=merchant` 和 `admin:legacy`。浏览器不能填写 actor、角色或批准人来替代认证。
所有下列 POST 同时校验允许的 `Origin` 和 `X-CSRF-Token`；CSRF 绑定商家、Java 会话和当前 scope。

`merchant_scope_access` 由本地场景注册代码授予具体商家访问权，没有公开的任意授权入口。
`merchant_scope_selection` 以 Java session ID 的 SHA-256 保存选择；每次请求重新核验访问映射，默认 `store`。
切换范围先使用旧范围的有效 CSRF，返回新 actor 和新 CSRF；旧 token 不能写入新范围。
scope 跨 plan、Agent run 和 round 保持稳定；scope 选择不创建资源、不重置账户或库存。

| 方法与路径 | 请求 / 返回语义 |
|---|---|
| `GET /admin-api/assistant/session` | 可信 actor 与当前 scope 的 `csrf_token` |
| `GET /admin-api/assistant/scopes` | 默认店铺及本商家获准的场景范围 |
| `POST /admin-api/assistant/scopes/select` | `{execution_scope_id}`；只接受已授权范围，返回新 actor/CSRF |
| `GET /admin-api/assistant/ads/catalog` | Java 在售商品、实际 SKU/价格及库存展示；`stock_display_only=true`，不能作为执行时的库存凭据 |
| `GET /admin-api/assistant/merchant` | 当前商家/scope 最近各 30 条 observations、plans、memories、runs，以及账户和当前 grant |
| `POST /admin-api/assistant/merchant/runs` | `{request_id, objective, mode?, product_scope?, planned_budget_cents?}`；接纳后异步运行，返回 run 或明确等待状态 |
| `GET /admin-api/assistant/merchant/runs/{run_id}` | 查本商家、当前 scope 的持久运行；不重新执行 |
| `POST /admin-api/assistant/merchant/plans/{plan_id}/execute` | `{expected_version}`；批准后执行或按原计划/动作键恢复，返回计划状态和真实回执 |
| `POST /admin-api/assistant/merchant/memories/{memory_id}/approve` | `{expected_version, reviewed_content?}`；人工核对并批准具体 DRAFT 经验 |

`request_id` 最长 128 字符，`objective` 最长 1,000 字符；`product_scope` 若提供为 1–100 个不同的合法商品 ID。
`planned_budget_cents` 为 0–1,000,000,000,000 的整数，作为计划总预算约束；省略时采用所选商品现有活动预算之和。
省略商品范围时取本商家的现有活动商品。上述约束是意图，不能代替稳定 grant 的授权。
同一 actor/scope/request ID 的相同规范化请求返回原 run，异参为 `merchant_request_conflict`；
API 使用严格参数模型，额外字段或非法类型返回 422，不以字符串转数值绕过金额校验。

`mode` 接受 `live / rule / mock`，默认 live。live 必须实际配置 live Provider；mock 只在 mock 配置下可请求。
显式 rule 使用保守规则候选并保存 `model_mode=rule-fallback`，原请求仍保留 mode，供区分主动规则基线和模型失败降级。
后台任务由 API 进程持有，业务事实消费由独立 worker 执行；没有把经营模型放进消息 ACK 路径。
管理端通过上述快照/轮询接口展示计划，Merchant 当前没有逐 token SSE 接口。

## 独立场景资源

[DemoScenarioController](../backend/smartlect-admin/src/main/java/com/smartlect/controller/internal/DemoScenarioController.java)
仅在 demo 开启且付款模式为 mock 时提供受保护的内部入口：
`POST /internal/demo/scenario/seed` 接受 `scenarioRunId/branchId` 及可选
`userCount/productCount/initialStock`，`/read` 按 `executionScopeId` 查已保存 manifest，
`/session` 校验本项目 demo 凭据后为 manifest 中指定用户创建真实 Java 会话。
这些是本地验收基础设施，不是模型工具或任意用户身份切换入口。

seed 默认 100 用户、20 商品、每商品 2 SKU、每 SKU 库存 10；允许范围分别为
1–100 用户、1–20 商品及 1–100 初始库存。稳定 scope 由 scenarioRunId/branchId 派生，
Java registry 保存请求指纹和 `demo-scenario-v1` manifest。
首次创建在 Java 事务内分配本场景独立用户/地址/商品/SKU/库存；同范围同参数只返回原 manifest，
异参/资源碰撞拒绝，不能借重跑 seed 重置库存或交易。
类目是经值核验的共享常量，不是共用的分支库存。
本地驱动器还须把 manifest 资源注册到 Growth `execution_resource` 并授予商家 scope 访问权；
仅在请求或产物里写 branch 标签不构成隔离。已实施的退役/替代场景边界见
[reset-contract.md](reset-contract.md)，实际 reset 与旧消息隔离证据以实施状态为准，不由本文代替验收。

## 已提交观测与新一轮条件

[MerchantService.prepare_run](../growth/src/smartlect/merchant/service.py) 先检查原请求回执，
再读取本商家现有活动；无草稿返回 `merchant_campaign_draft_required`。
对活动的商品/SKU 向 Java 查询库存，每批最多 8 个并发查询，网络期间不持 Growth 事务锁。
库存观察独立提交，包括售罄保护；随后在 scope 锁内生成不可变 `merchant_observation`。

观测包含活动/素材版本与状态、库存、曝光、点击、花费、确认付款/退款、去重付款单数、
明确支付失败尝试、取消、空推荐和投放库存拒绝。活动财务指标取广告归因到该活动的事实，
scope 汇总取该范围 APPLIED 事件；广告和推荐的独立报表仍通过原归因接口查询，不能相加成为两份收入。
观测保留 `paid_cents` 与 `refunded_cents`，净成交应相减；不能用曾付款次数替代净额。
取消独立计数，空推荐来自实际空 `recommendation_receipt`。
`stock_rejections` 当前是已观察零库存导致曝光/点击拒绝的 `AD_INVENTORY_REJECTED`，不是所有 Java 下单拒绝的总数。

每条 fact 保存 `evidence_id/kind/metric/value/source_ids/observed_at/occurred_at`；来源 ID 最多保留最近 20 个，
同时给出总数和截断标记，原业务表保留完整事实。支付失败附最近 20 个权威尝试摘要。
Java 库存 DTO 没有权威发生时间或版本，库存 fact 的 `occurred_at` 为 null，另保存查询开始/完成、耗时和
Growth generation；不能把响应时间或本地 generation 写成 Java 版本。

当前水位对以下实际内容计算 SHA-256：曝光 ID、收费点击 ID、APPLIED Java 事件 ID、空推荐 ID、
库存拒绝 signal ID、活动/素材 ID 集合以及活动 SKU 的库存值。
仅轮询时间、库存查询 generation、成功预算/素材修改或新 Agent run 不推进该水位。
新资源或库存值变化也可推进观测，不必伪造一次新流量；效果验证仍须实际下一轮曝光/点击/成交。
一般动作拒绝回执保留在计划历史，目前不单独进入水位。

同水位复用原 observation/round；最新计划已经使用该 observation 时返回
`WAIT_OUTCOME + unchanged_observation=true`，不调用模型或创建新计划。
存在 `EXECUTING` 计划时先返回 `plan_recovery_required=true`；必须查询/恢复旧动作结果，不能换 run 猜测结果。
数据库唯一键同时限制每个 actor/scope/observation 只有一份有效计划。
`financial_event_watermark` 是当前快照的事件数和最后事件 ID，其中查询含非财务事实；它不是 Broker 已排空的证明。
演示/评测驱动器仍须等待预期业务事件真正到达。

## Java 权威支付失败事实

[PayAttemptService](../backend/smartlect-pay/app/src/main/java/com/smartlect/biz/PayAttemptService.java)
只在 `smartlect.payment.mode=mock` 时加载。
受内部认证和委托用户身份保护的 `POST /internal/pay/mock/decline` 接受恰好
`{attemptId, payOrderId}`，`POST /internal/pay/mock/attempt` 用同样请求查询原回执。
这些入口不属于 Merchant 模型工具，也不允许商家给任意用户订单贴失败标签。

Java 锁定付款意图并校验本人、mock 渠道、待付款状态和正数整分金额，保存
`pay_payment_attempt` 及原回执，再沿现有事务 Outbox 发布 v2 `PAYMENT_ATTEMPT`。
结果为 `attemptStatus=DECLINED`、`reasonCode=MOCK_CHANNEL_DECLINED`、`paymentMode=mock`，
记录原金额、币种 CNY、Java 发生时间、订单/付款单/用户和由 attempt ID 派生的稳定事件 ID。
同尝试重放返回原时间和结果；同 ID 改付款单/主体拒绝，不产生第二条尝试或另一份事件。
尝试拒付本身不付款、不取消订单、不释放库存，也不更改财务终态。

Growth 消费器核对事件版本、来源 `PAYMENT_PROVIDER`、严格 payload、稳定事件/幂等 ID、
DECLINED 原因与 mock 标记；该事件的账本 `amount_cents` 为 null，尝试金额不增加收入或退款。
经营诊断的 `payment_failures` 只计这些已 APPLIED 的 DECLINED 事实。
用户取消、未付款、支付超时、请求超时或 UNKNOWN 均不能增加此计数。
这是经过真实 Java 持久链的模拟渠道拒付，不是实付资金或真实支付渠道质量测量。

## 一份有限计划与 Skills

[agents/merchant.py](../growth/src/smartlect/agents/merchant.py) 是一个 Merchant Agent：
固定阶段读取可信上下文，LangGraph 的 `plan → validate` 生成并校验严格 JSON，
确定性代码保存计划和执行动作。当前 prompt 为 `merchant-plan-v18`，模型输出 schema 为 `merchant-proposal-v2`；
编译后的计划继续使用 `merchant-plan-v2`，另存 `proposal_schema_version` 与 `evidence_binding_version=selected-observation-v1`。
没有总 Supervisor、库存/广告/诊断子 Agent 或 MCP 必经层；Shopping 的有界 ReAct 保持原入口。

| Skill | 当前版本与实际加载条件 |
|---|---|
| `campaign_plan` | 1.9.0；每轮加载，约束计划、依赖、稳定预算和授权边界 |
| `performance_review` | 1.8.0；有 facts 时加载，区分库存/素材/支付失败/退款/证据不足及不同动作的样本门槛 |
| `creative_copy` | 1.4.0；足量曝光且当前低CTR、存在不同通用文案选项时加载 |

Skills 是 Git 版本化业务 JSON，不是另一个模型或可由聊天安装的插件。
其中 `get_merchant_context/save_merchant_plan` 表示控制器固定阶段调用，模型本身没有任意工具调用能力；
Provider 返回 `tool_calls` 会被拒绝。经验草稿和商品/文档内容不能覆写程序性 Skills。

模型只输出 `summary/diagnosis/actions/expected_signals/experience_draft`。
actor、scope、plan ID/version、parent plan、run ID、目标、商品范围、稳定 period、observation/watermark
由服务端绑定并在持久化时再次核对，不能来自模型自报。计划 spec 不可变。
在动作中模型只选择动作类型、资源、预算、文案变体ID或策略配置，不生成/计算 `expected_version`。
控制器从规划输入的资源快照或实验 revision 绑定预期版本；模型即使附带该字段也不能决定其值。
活动/素材版本来自不可变 observation；新 run 的推荐实验视图在首次准备时固定到已有 run context，
模型与编译器均使用该 revision/配置，恢复时不以实时策略版本覆盖。保存时再次检查策略动作的预期版本。
旧已保存 spec 不回填、不重编译；原审批快照、动作 ID、执行/恢复和 CAS 拒绝保持。
公共 Ads HTTP 仍要求调用者提交其实际所见 `expected_version`，执行器不会以最新版本替换冲突版本。
模型诊断只输出 `code/explanation/evidence_ids`，不能提交 `observed_facts`。
编译器仅按主动选择的 ID 复制当前不可变观察的完整原事实至 `observed_facts`，包括数值、来源、时间及源 ID截断标记。
不补选遗漏指标、不扩充事实组，不自动生成诊断。重复/未知/旧观测/商品范围外 ID被拒绝；
新绑定合同保存前由同一纯函数对照持久 observation 再次核对事实及顶层 ID并集。
正文解释选择与不确定性，权威数值由系统绑定展示。删除诊断正文“出现数字就拒绝”的正则；
它只限制表达形式，不验证真伪。正文数字、因果及效果声明仍须独立逐句审查，不因结构校验通过而算语义正确。
原 observation 和完整事实输入保留，模型负责相关证据选择、解释和动作选择，系统准确复制数值不等于模型已经理解。
解释统一标记 `candidate_not_causal`，不把候选原因或预期信号当作实际收益。

计划最多 8 个动作，支持 F4 八类启停/预算/素材动作及 `set_recommendation_policy`。
每个非策略动作必须在 diagnosis 引用所属 campaign 的证据，scope 汇总不能代替活动引用；
资源须有正确归属/版本/关联。只有零库存证据支持 stockout，
正的权威拒付计数支持 payment_failures，正的已确认退款支持 refunds。
已投放活动的预算优化门槛为至少 10 次广告点击，推荐策略另需至少 10 次真实推荐点击；自动素材试验须至少 100 次广告曝光且本轮低CTR，
不要求同时达到预算调整的点击门槛，也不能反过来用 10 广告点击替代曝光门槛。单笔退款不能解锁素材试验。
`creative_underperforming` 须主动选择该 campaign 的广告曝光或点击证据，
校验器直接用权威观察检查素材样本成熟且 `clicks * 1000 < impressions * creative_low_ctr_per_mille`。
无需模型在两个输出列表重复抄数；选择不相关领域或另一未达筛查条件的活动仍拒绝。
`creative_low_ctr_per_mille=5` 来自广告分析的共享常量，对应严格低于 0.5%，等于阈值不触发；
新观测 maturity 和模型输入均显式提供该门槛。200 曝光/1 点击不触发，250 曝光/1 点击可触发。
模型输入的 `campaign.screening` 同时给出预算/素材样本成熟度和 `low_ctr_sample`；
预算使用 `_mature`，素材使用 `_creative_sample_mature/_weak_creative`；模型提示、规则候选、候选校验与Skill加载共用素材资格函数，
依据当前原始事实计算，不能沿用上一轮的筛查判断。`creative_sample_mature`只表示曝光量门槛，不代表财务成熟或素材原因已被证实。
执行素材试验还须主动选择同一campaign的impressions和clicks事实；可分布在不同诊断中，不强制某个标签或诊断拆法，不由系统补齐。
模型直接采用筛查结果并引用同活动原始证据；筛查不证明统计显著性、因果或替换收益。
`insufficient_evidence` 可以表示样本或原因证据不足；确认事实与原因未知可在同一诊断说明，无需按类别名称拆项。
任何类别都不能绕过权威观察的动作成熟度、库存、范围或预算门禁。

样本未成熟时可保留判断。尚未花费的 DRAFT 可在用户总预算约束内安排初始预算，
不局限于原预算为零；执行仍须有效 grant 批准，有货且预算允许时才可启用。
恢复须处于 PAUSED/EXHAUSTED，规划及执行时均检查库存与预算；仅观测到正库存不自动恢复。
启用/恢复活动还须已有 ACTIVE 素材或同一计划包含对应素材的启用/恢复，否则无法产生流量。
自动素材替换须加载相应 Skill，模型直接提交 `copy_text`。
固定 `copy_options`/`copy_variant` 选项协议与服务端 `COPY_VARIANTS` 已在 v19 移除：
把模型限制在两条通用候选里既测不出文案能力，也让任何"模型优于规则"的结论只反映选项编号。
替换须确实产生实质变更（归一化后仍与现文案相同即拒绝），广告标识由展示端渲染，不要求写进文案。
未经核实的性能、评价、折扣、销量或收益不得写成事实保证；不把旧素材自由文案、经验或描述自动当成已批准素材。
这是开放文案提交加事实约束，不是已验证的营销文案创作能力；效果须由下一轮实际新流量检验。
新proposal v2保存前复用同一函数，对原持久observation再次检查素材资格与主动选择的事实；不在旧计划恢复时重新渲染。
普通管理端继续由商家明确保存DRAFT文案或提交 `copy_text` 替换，沿原grant/CAS/幂等执行器处理，不套用模型的选项协议。
模型输入为活动/素材附带按当前状态、点击/曝光成熟度、证据和库存筛选的 `allowed_actions`，
并用 `blocked_actions` 指明不可规划的原因。`action_requirements` 标明启用/恢复前需要同计划补预算、
启用父活动或配套启用素材的条件；动作预算仍须满足计划总约束。这些是规划提示，执行器仍逐项复核，
没有 grant 时也可以提出合法的待批准计划，提示不授予执行权限。
`replace_creative` 只改文案并递增版本，保持原状态，ACTIVE 素材替换后无需 activate/resume。
DRAFT 素材只有所属活动满足同一素材试验条件时才允许先替换，再按需独立启用；初始无样本DRAFT使用商家已保存文案提议activate，
没有以草稿状态跳过素材门槛的replace特例。状态提示保留成熟度/授权门禁。
预算调整也不自动恢复投放；ACTIVE 活动调低后余额不足一次 CPC 时会标为 EXHAUSTED，
之后增加预算仍须显式恢复，不能把预算写成功当成重新启用。

单步动作可独立；同资源仅在需要合法状态转换时允许 `set_budget` 或 `replace_creative` 后接一次 activate/resume，最多两步。
控制器在审批前从同一规划快照固定动作顺序、依赖及第二步递增后的预期版本；
这是规划阶段绑定，不能在执行冲突后覆盖版本重试。
计划顺序为保护暂停、预算、素材替换、活动启用/恢复、素材启用/恢复、推荐策略。
所有预算动作合为一个事务批，其余动作按批顺序执行；不同批之间不承诺整体原子性。

## 稳定 grant、累计预算与推荐策略

首次批准继续 `POST /admin-api/assistant/ads/grants`：保存 immutable envelope、
initial plan ID/version、批准商家/时间、当前活动/素材 CAS 快照及 hash。
关联 Merchant 计划时额外提供 `merchant_plan_id`，必须与 initial plan ID/version 相等，
计划状态为 VALIDATED/WAIT_APPROVAL，目标及商品范围与 envelope 相容；批准快照包括完整计划 spec。
没有单独的“模型批准”接口，创建 run 或计划不等于批准。

执行时检查同一目标、商品子集、动作白名单、未过期/未撤销、商家归属及预算/策略范围。
后续新观测计划可复用仍有效的同一 grant；超范围落 `WAIT_APPROVAL`。
修改 envelope 需新 grant 明确 `replaces_grant_id`，旧 grant 撤销并暂停投放。
已开始执行的旧计划恢复时保持原 grant，不能静默改用新授权。

账户以稳定 scope 为键，period 固定 `scope_lifetime`，当前 reservations 恒 0。
新 plan/version、run、round、活动或替代 grant 都不清零已花费。
计划总预算不超过用户本轮约束及 grant cap；单次预算变化不超 envelope 上限，
活动预算不得低于已花费，跨活动同时调整检查整个 scope 的聚合预算。
预算计划不是已经花费，也没有必须把预算用尽的要求。

公共 Ads HTTP 的推荐动作请求为 `{action_type: "set_recommendation_policy", expected_version, policy}`，
policy 包含 `strategy_version/group/config`；不接受 campaign/creative/budget/copy 字段。
expected_version 对应调用者所见的实验 revision；Merchant 模型只提出 policy，控制器从规划输入绑定 revision。
授权范围的 `rankings` 只能含 rule/content，
`groups` 只能含 control/treatment，`max_weight/max_quota` 为 0–20。
config 使用原七项特征权重和五路召回配额，经营动作只接受整数权重，配额总量 1–50且权重非全零；
每个参数还须在具体 grant 上限内。

策略动作只对已注册资源 scope 开放，默认 `store` 返回 `policy_requires_registered_scope`。
模型输入对此提供 `recommendation.change_supported=false`；其他 scope 的 true 只表示支持该能力。
只有 revision 有效且本 scope 真实推荐点击达到门槛时，`recommendation.allowed_actions` 才列出策略动作；
否则 `blocked_actions` 提供具体原因。`policy_enums` 显式列出 group=control/treatment、ranking=rule/content。
曝光成熟不能替代策略的点击门槛；提示不代替 grant 或注册商品覆盖检查。
因为策略影响该 scope 全部推荐，grant 和 Merchant plan 的商品范围必须覆盖该 scope 注册的全部商品。
策略版本/配置 hash 不可变，修改配置须使用新的唯一 strategy_version；旧版本只能按原配置重用。
保存新版本并 CAS 更新所选实验分组引用；
原 salt、assignment ID 和分组保持，历史推荐 receipt 保留旧版本，新请求读取新策略。
这只改变推荐候选配额/排序参数，不改变 Java 价格/库存或归因规则，也不保证更高收益。

## 持久运行、回执与恢复

每个 Merchant run 沿用持久 AgentRun、会话租约与 fencing；租约 30 秒，运行任务每 10 秒续约。
同请求进程恢复沿用原 run/deadline、已接纳模型次数、修复次数和已保存计划。
若计划已经保存，恢复直接检查/执行该计划，不再让模型重造动作。

| 模型限制 | 实际执行 |
|---|---|
| 实际 HTTP attempts | 每个 run 最多 4 次，Provider 重试和计划修复均计入；调用前先持久化次数 |
| 单次调用 | 至多 2 attempts，各 25 秒；输出上限 3,000 tokens；与现有 Provider 共用模型并发限制 |
| 修复 | 至多一次格式/事实修复，仍占 4 次额度；失败转保守规则并明确标记 |
| 时间 | 原 run deadline 最多 90 秒，模型阶段预留最后 5 秒给保存/执行收尾；恢复不刷新 deadline |
| 图步数 | recursion limit 6，不是额外模型额度 |
| 上下文 | JSON UTF-8 最多 36,000 bytes，作为约 12k-token 目标的粗估；超过即停止模型路径，不声称精确 token 上限 |

默认模型保持 qwen3.7-plus。实际 trace 保存 provider/model/prompt/Skill/schema、usage、延迟、
失败/重试和可计算的费用估算；供应商缺失字段保留未知。无累计模型费用封顶不解除单 run 限制，
不会自动升级昂贵型号。最终 `live` 需要本轮真实 Provider 成功 trace；合同 fake 不能作为 live 证据。
模型失败后的计划标为 `rule-fallback`，真实调用产生的 usage 仍保留。
`plan_rejections` 保存拒绝原因和已脱敏的候选正文，分别限 1,200 和 12,000 字符，正文截断另有标记；
成功候选另存`accepted_candidate`：绑定事实/版本之前的已脱敏Provider正文、完整脱敏正文SHA、12,000字节上限和截断标记，不保存隐藏推理。原v16及以前成功运行没有该字段，不能事后用compiled plan冒充原始模型输出。共享模型观测明确`currency=CNY`、整数最小单位及100:1换算，避免无单位金额；这不验证正文因果或营销主张。
不保存隐藏思维链。素材诊断被拒时列出当前筛查支持的活动，要求移除已不成立的诊断，
仍只允许一次修复，不新增模型额度或绕过证据校验。

每个执行批使用由 plan ID/version/批次派生的稳定 action ID/幂等键，记录 grant/hash、原 run/round、
reason/evidence 和 before/after。人工操作、规则计划和 LLM 计划共用 AdsService/AdsStore 执行器。
计划执行有独立 30 秒 lease token；收尾只接受当前 token，旧执行者不能覆盖新执行者的状态。
执行接口先查原批回执，再检查新增写的当前授权；已完成事实即使后来授权过期也能恢复展示。
未知结果以原 action ID 查询/重试，不能换幂等键制造第二次效果。

| Plan / Run 状态 | 含义与后续动作 |
|---|---|
| `VALIDATED` | 有不可变计划，尚不代表授权或动作完成 |
| `WAIT_APPROVAL` / `WAIT_USER` | 当前 grant 不覆盖所需动作；商家明确批准后调用原计划 execute |
| `EXECUTING` / `WAIT_OUTCOME`，`execution_status=UNKNOWN` | 外部/数据库结果未知或执行等待超时，保留原计划并恢复回执 |
| `WAIT_OBSERVATION` / `WAIT_OUTCOME` | 已有确定结果，等待实际新观测；可为所有动作已完成，也可为合法的零动作计划 |
| `PARTIALLY_APPLIED` | 前批完成而后批拒绝/不能继续，保留所有已发生效果与费用 |
| `FAILED` | 没有已完成批而动作明确拒绝，或运行出现不能继续的失败；不能算动作完成 |

**零动作和 UNKNOWN 不同。** `actions=[]` 的计划以 `authorization.required=false`、
`reason=no_business_action` 保存 WAIT_OBSERVATION，不要求 grant，不生成动作。
样本不足时明确等待可算正确保留判断；UNKNOWN 表示已有执行结果尚不能确认，必须先恢复，不能算成功或支付失败。
暂停/耗尽/版本冲突等确定性拒绝与 HTTP/数据库结果未知分别记录 `rejected` 和 `unknown`。
通用状态机保留 REVIEWED/COMPLETED 分支，但当前 API 没有人工“评审计划完成”入口。

## 重新审批与保护暂停的版本衔接

已有有效 grant 的计划若整体越界，先停在 WAIT_APPROVAL，不执行合法子集。明确 replacement 审批保留原有保护暂停；只有绑定同一未执行 merchant_plan_id/version 的审批，才把该事务确定发生的 ACTIVE/EXHAUSTED→PAUSED、version+1 存入 grant.plan_snapshot.approval_resource_transitions，并纳入 snapshot hash。审批前先逐目标校验原 spec 版本及已知计划内依赖，已有独立变更、已 claim 或已有动作记录的计划不能据此重新绑定。

claim 将匹配原 plan/spec 的固定转换及 approval_snapshot_hash 保存到 authorization；plan_action_request 在执行和回执恢复时共用这个已批准的固定偏移。原 spec 和普通 Ads CAS 都不改，不使用执行时最新版本覆盖预期版本。新自动计划和未绑定 Merchant plan 的普通 grant 不使用该转换；审批后独立修改仍会冲突。只改预算或文案的计划不会额外得到恢复动作，保护暂停继续保留；管理端明确提示这一后果。

真实证据：原实现单项 MySQL 测试得到 FAILED而非WAIT_OBSERVATION；修复后 Merchant25项MySQL全过，包括审批前/后独立版本变更拒绝、无bound grant不转换、后续新plan不复用旧转换。scripts/check_f5_reapproval.py 经真实 API 运行规则规划/同一执行器，混合4动作整体越界零回执→明确cap400→500和delta100→200的replacement审批（有效期未扩大）→原spec不变且4动作APPLIED/重放→旧活动仍PAUSED、新活动产生新曝光/点击，稳定账户累计1→2分。详见 artifacts/f5-reapproval.json，不是模型收益或正式四分支对照。

## 经验与验证边界

模型 `experience_draft` 与计划同事务保存为一条 DRAFT 经验，关联 plan/evidence。
人工可删改待审核正文，编辑会取消勾选，需明确重新批准；按 expected_version 批准后才写 APPROVED、确认正文、批准人/时间及新版本。可选 reviewed_content 最长 2,000 字符，保存与比较前均脱敏；省略时始终指来源计划里的原始草稿。原 plan.spec.experience_draft 不变。重复审批须匹配旧版本和同一确认正文；改词或在已修正后省略正文均 409。
上下文只读取同 actor/scope 的最近 5 条 APPROVED 经验，模型输入最多取其中 3 条；run context 的 model_input_experiences 记录本次模型输入准备使用的 id/version，结合实际 attempt 判断是否确有调用。未经批准原稿不会通过 previous_plan 重新进入模型。
批准经验不批准业务动作、不改 grant，也不把经验正文变成程序性指令。

以下开发记录保留失败及已发生效果；版本修订、fake Provider 合同或局部成功都不代替完整 live 门禁。

| 开发记录 | 结果及当前合同处理 |
|---|---|
| v2–v5 | v2/v3 降级、v4 缺少可投素材、v5 后续保留观察；不能只凭计划保存或等待状态判定完整纵切通过 |
| v6–v8 协议整理 | 将版本绑定交给控制器，区分素材曝光与预算/推荐点击门槛，明确替换保持状态及动作依赖；补齐同活动证据/策略能力/不可变配置。低 CTR 统一已有广告基线 0.5%，取代 Merchant 原 10% 判断，非按 live 收益调参 |
| v9 → v10 | v9 将缺 grant 误解为不能规划而返回空计划；v10 明确首次无 grant 仍提出有据的待批准动作，只有执行被阻止，DRAFT 启动不需历史优化样本 |
| v10 → v11 | v10 第二轮误判 1/250 与 0.5% 的关系而返回空计划；失败及该 scope 累计 1 分模拟费用保留。v11 给模型提供与校验共用 helper 的当前 screening 及原始事实 |
| v11 → v12 | v11 前两轮 live 及 Java 拒付/取消/库存恢复完成，第三轮沿用已不成立的素材低 CTR 诊断，两次被拒后降级，未计完整 live 通过。v12 细化当前筛查拒绝反馈并保存有界脱敏候选；v12 的原脚本将合法 other 归类误判失败，校正为权威事实引用/指标/值后，原执行与当前账本复核通过（RECORDED_PATH_VALIDATED）；同版本 v12b 漏读拒付，仍判失败。不得称全部开发运行或质量已通过 |

历史 F5 记录包含 Merchant31项轻量、25项MySQL回归，分别为fake Provider合同与真实持久/授权检查；这些不是当前版本成绩，也不代表模型语义质量。F5功能证据包括v12已有模型路径的事实复核、真实浏览器审批/经验加载，以及重新审批后的原计划执行与新流量。v12b漏引和经验复用答复的语义错误仍单列为失败，进入F6质量分析。实际命令、失败和新证据以实施状态及对应产物为准。

F6 三场景、四独立分支/至少三种子、固定版本真实重复及 RAG/工具/可靠性评测的已完成证据与缺口，
以及 F7 干净构建和独立运行的进度，统一看实施状态；完整阶段门禁仍未完成。本次契约调整未读取 RAG 样例或留出内容。

## F6：行为作用域与推荐证据

schema1 的已验证非金融事件也冻结 `commerce_attribution_meta`：scope取可信注册用户映射，
没有映射则固定为store；payload中的scope不作为授权依据。0010仅为历史已APPLIED的已知非金融类型
补缺失meta，记录`projectionVersion=nonfinancial-scope-v1`与`projectionSource=migration_0010`。
已有meta不变，后注册和重投不能搬迁事件；reset保留旧映射。PAYMENT/REFUND的原始事实、金额及
LEGACY/UNKNOWN金融归因均不重新分类。实际数据保护及升级故障见实施状态。

观测分开记录广告`clicks`与`recommendation_impressions/recommendation_clicks`。
推荐两指标来自本scope可信、去重的REC_IMPRESSION/REC_CLICK触点，原touch IDs进入事实与watermark。
仅广告CPC点击成熟不能解锁推荐策略；策略候选需要真实推荐点击达到10，并在诊断中精确引用该事实。
广告预算/素材仍使用自己的既有点击/曝光门槛。触点去重不增加样本，纯参数变化仍不算新效果。
点击门槛不是财务样本成熟或因果证据，单笔退款也不能证明排序缺陷或总体退款趋势。

已确认的正值PAYMENT_ATTEMPT/DECLINED须在任一诊断主动选择其事实 ID；
同一诊断可以说明确认失败但原因或样本不足，动作可以为空，不要求拆成两条。
使用payment_failures肯定标签仍须正的权威拒付事实，取消和UNKNOWN不能替代；实际说明是否如实承认仍由语义审查验证。
这类检查只拒绝不完整计划，并沿原一次修复/4次实际attempt执行，不代模型制造事实或扩大授权。

新版 reference-only 输出不再把“广告不足必须在同诊断复制曝光/点击”和“正退款必须复制付款/退款/转化”
作为编译通过条件；模型只能提交所选 ID，编译器不补全遗漏。真实库存、样本、范围、累计预算、授权及版本动作门禁不变，
肯定的售罄/退款/拒付诊断仍须主动选择对应真实事实。低CTR由同一权威观察筛查，点击阈值仍不证明因果或财务成熟。
解释净成交仍须有足够付款、退款及样本证据；漏选、漏述和无依据解释保留在独立语义审查中。
本次删除重复填数职责、输出完整组硬门禁、诊断正文数字正则和确认事实/未知原因必须拆成不同标签的要求。
保留正值拒付事实必选及肯定诊断的真实证据检查。
v18自动广告文案以固定通用选项编译替代自由文本禁词过滤，不用新增badcase词表判断事实。交易、预算、授权及版本边界继续生效；
素材动作的门槛收敛为足量曝光且当前低CTR，并必须主动选择同活动曝光/点击，不对无动作诊断要求补齐事实组。

新版本评测区分“模型选择相关事实/资源”“解释是否有据”“编译绑定原值是否精确”和“实际动作前提/回执/新观测”。
不能把系统复制后的数值正确率或原指标齐全率称作模型理解率；不得通过编译补全来掩盖漏选。
旧冻结 manifest、原评分与失败产物均保留。新模型输出版本需要新的冻结绑定；单次修复、四次实际 attempt、deadline与真实用量规则不变。

本次素材筛查仍使用campaign累计流量，不能据此把某一文案版本的效果单独归因，也不保证避免后续小样本反复试换。
选择、动作回执与下一曝光/点击继续逐轮记录；是否需要按素材版本划定新样本窗口，须由真实多轮观察验证。
固定选项不会修正模型摘要中的因果或收益断言，这些原文仍须独立语义审查，不能据结构通过宣称经营语义门禁通过。
