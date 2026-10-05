# Smartlect 实施历史记录（2026-09，已归档）

**这份文件是历史过程记录，不是现状。** 判断现在做到哪里、跑过什么，看 [../../IMPLEMENTATION_STATUS.md](../../IMPLEMENTATION_STATUS.md)。

保留在这里的原因是：项目规则要求历史失败不得删除，其中的原始失败、命令、版本号和当时的结论对复盘有用。
但里面大量陈述在后续轮次已被取代——例如阶段划分、待办清单、"下一步"、以及各轮的测试数量与版本号。
**不要把本文任何一句当作当前代码或当前成绩。**

---

更新时间2026-09-10；目录/home/song/code/Smartlect；分支codex/smartlect-implementation。

> **2026-09-10 产品闭环补齐与全栈全量测试（已实施并实测）**：核对四步产品闭环计划后确认此前四步都只到 PARTIAL，本轮补齐浏览入口与广告排序，并真实浏览器跑通商家→用户反馈环。提交 `78ad34d`。
>
> 补齐内容：新增 `/browse` 读真实 Java 目录（`loadCategory` 分类 chip、关键词、价格区间、排序、分页），首页与侧栏接入；目录行不带推荐回执，所以逛货架不产生曝光、不算推荐触点。公开 `POST /product/loadProduct` 增加有界 `keyword`（`productNameFuzzy` 与 mapper 本就支持，只加一个参数），且带关键词时不再限制在 `commendType=0` 的落地位列表内，否则大部分匹配会消失。商品详情补封面图与描述，咨询入口改名"问问 AI"并携带 `product`/`sku`，草稿仍可编辑。广告不再只是"带标签的普通推荐"：`rank_ads` 按相关性、该访客对该素材的疲劳（看过未点则降权、点过不算疲劳）与预算配速打分，`ranking_mode` 为 `ad-fatigue-pacing-v1`；相关性只缩放分数、不会把合格广告排除。
>
> 测试期间发现并修掉的真实缺陷：价格与排序原先是本地状态，只要关键词/分类没变，改价格或排序点"查询"会静默无反应；现在全部筛选进 URL，既可分享也统一由一个 watcher 驱动加载，排序键与价格在发请求前校验（手改链接可能带任意值）。
>
> 全栈全量测试（本轮实跑）：Java `mvn clean test` **387项，0失败0错误，2项Rabbit条件跳过，BUILD SUCCESS**（含新增 `PublicProductSearchTest` 4项）；Python `SMARTLECT_RUN_MYSQL_TESTS=1` **266项全通过、0跳过、188.539秒**；用户端 Vitest **40项**（含新增 `browse.test.ts` 9项）、管理端 Vitest 24项、用户端 typecheck 与两端 build 通过；`dev.sh build` + `up` 后13应用/5中间件健康。
>
> 真实浏览器验收（买家侧7步全过）：首页 hero／分类 chip／为你推荐／推广+广告标签；点"数码"→`/browse?category=90` 显示5件并给出"共 5 件在售商品"；关键词精确匹配1件、无意义词提示"没有匹配…的在售商品"；价格升序实测 ¥10→¥23→¥36→¥49→¥62，最低价20正确过滤掉¥10；详情页显示图片占位、2个SKU含价格与库存；"问问 AI"跳 `/assistant?product=…&sku=…&draft=…` 且输入框预填"关于商品「Smartlect数码4」（商品编号 …，规格编号 …），我想了解"。无 JS 控制台报错。
>
> 反馈闭环实证（第4步）：默认 store scope 原有3个活动均 PAUSED、grant 已过期，所以推广位起初为空。经真实商家流程——Merchant Agent 规划（引用真实 paid/refunded 事实，明确写"仅1个样本无法确定退款原因"）→ 商家批准 grant → 执行——活动与素材转 ACTIVE，访客侧 `/api/assistant/ads/recommendations` 返回 `ad-fatigue-pacing-v1` 与 `ad_rank_score`；真实曝光+CPC点击扣费10分后，同一素材分数由 0.40 降到 0.38（配速项生效）。第二轮商家规划自主产出 `replace_creative` 与模型自写文案，执行后**浏览器实见**推广卡文案变为「Smartlect 智能助手：稳定可靠，高效处理您的日常任务。立即体验，让工作更简单。」并带"广告"标签，而"为你推荐"4件普通商品无广告标签。
>
> 闭环摩擦（如实记录，未改设计）：① 广告动作必须绑定已批准 plan，且 `claim_plan` 要求 `spec['objective']` 与 grant envelope 的 objective **完全一致**，换目标即 `plan_outside_grant`→WAIT_APPROVAL，需重新批准；② 替换 grant 会把原活动置为 `grant_replaced` PAUSED，买家侧随即无广告，须再授权恢复；③ 无新观测时 Merchant 返回 `WAIT_OUTCOME` 不规划，而全部暂停后又不会产生新广告观测，此时要靠普通推荐曝光/点击等非广告触点推进水位（本轮即用真实推荐曝光+点击解开）。这三条都是有意的安全边界，但让演示前置链偏长，若要更顺可考虑在控制台把"批准并恢复"做成一次引导，而不是放宽校验。
>
> 仍未完成：RAG 三项语义指标仍为 `None`、`FAILED_SAFETY` 未改判、12条 holdout 未读；正式四分支3种子对照、完整20×2工具任务、五经营病例复验、F6/F7 全门禁未执行。购物车与独立结算页仍无（原计划未要求，Java cart 模块前端零引用）。广告排序的疲劳/配速只有本轮单次纵切证据，未做多用户对照，不能宣称提升点击或转化。

> **2026-09-10 去过拟合落盘与四项能力补齐（已实施并实测）**：本轮把此前只在工作区的去过拟合清理提交，并修掉两处"评测在奖励错误行为"的问题，再补检索精排、上下文丢失上报和 MCP 只读面。提交：`4d937bb`（删除两个Agent的badcase关键词规则：问候语白名单`{你好,您好,hi,hello,谢谢}`、`policy_answer_requires_citations`、冲突/注入时强制改写为固定转人工话术、Merchant文案禁词正则与五条统一样本阈值；检索层不再替Agent决定是否转人工）、`ecb1494`（商城首页推荐与明确标注广告位）、`bc9cb05`（评测修复）、`42896ab`（精排／上下文／MCP）。
>
> 评测层两处必须记住的根因：一是 `eval_comparison.py` 的 `copy_quality` 按字面词 `规格`/`用途` 与 `推广` 前缀打分，而 Merchant 规则兜底的固定句子逐项命中，**打分器与被测对象共用一张词表**，分支差异测的是词面不是文案质量，还在奖励模型重复展示端已渲染的广告标识；现改为按被投SKU自身的 Java `productName`/`propertyValue` 打分，协议升 v3，v2 的 smoke 产物保留但标注不可比。二是 RAG 44 例里 20 例要求人工工单、19 例期望 `needs_human`，而三项语义指标恒为 `None`，一个"永远转人工"的退化Agent能白拿这些结构分；现 `summary()` 输出 escalation 判定，`passes_from_escalation` 与 `passes_from_answering` 分开计，`DEGENERATE_ESCALATION` 返回非零。`rag-d-026` 期望的 `conflicting` 在收窄 `answer_status` 后已无任何代码路径可产出，属构造性必红，改为 `needs_human`（其 `must_include_facts` 本来就这么写），修订与被取代的 SHA 记在 manifest `revisions`，holdout split SHA 未变、未读取。
>
> 新增能力：检索由单段变两段——BM25与稠密各Top20、RRF合并12、精排按查询词覆盖率与最小覆盖窗口紧密度取最终8条，两段排名都记进 `retrieval` 以便区分召回未进候选与进了候选排序输掉；长问题单一词命中改为降权而非丢弃。开发集24例 recall@4 0.917→0.958、recall@8 不变（`artifacts/retrieval-rerank-attribution-v1.json`，语料仅32片段，明确不能外推）。同义词表去掉意图映射（`转人工→人工客服`、`清空聊天→清理记忆`），只留词形归一并补 `清空→清理`；未见表述实测：`清空记忆`、`把聊天记录清理掉` 命中正确文档，`找个真人聊`、`叫客服` 检索不到——这是对的，要求人工属 `request_handoff` 动作而非文档查询，不为这两条加词。`working_context` 原先静默丢弃放不下的更早请求，现按条数与sequence区间上报（一条都放不下时同样上报），提示要求向用户确认；压缩有意保持抽取式，理由记在 `docs/agent-design.md`。新增 `POST /api/assistant/conversations/{id}/mcp`：JSON-RPC 2.0 的 initialize（版本协商）/tools\_list/tools\_call，复用同一 `REGISTRY`、Schema与权限，**零新依赖**，仅暴露只读工具；写工具、`load_skill` 及 `search_skus`/`recommend_skus`（后两者同一实现且写归因回执，外部客户端无曝光上报契约）全部 `tool_not_available`。降级轮次不再开工单后原本毫无痕迹，现发 `error` 事件标 `degraded`；文案替换按去空白标点归一化比较。
>
> 实际验证：全量 Python `SMARTLECT_RUN_MYSQL_TESTS=1` **264项全通过、0跳过、189.271秒**（含新增 test_mcp 7项、knowledge 13项）；scripts 自测26项、`eval_comparison.self_test` 通过；用户端 Vitest 31、管理端 Vitest 24、用户端 typecheck 与 build 通过。Maven `clean package -DskipTests` exit0（22.4秒）。13应用/5中间件健康。真实 live 探测：MCP `initialize` 协商 2025-03-26 与 2025-06-18 均正确回 `MCP-Protocol-Version` 头，`search_knowledge` 返回 `answered`＋4条引用、`rerank_version=zh-coverage-proximity-v1`，问"包装破损怎么处理"首条引用为 `19-damaged-package`；被排除工具逐个返回 `tool_not_available`。一次真实模型导购问答 `COMPLETED`/live/`answered`，引用 `19-damaged-package`，3次模型调用、1次工具、无 fallback，且**没有对可回答问题开工单**。
>
> 本轮踩到并修掉的两个真实缺陷（不是我的Python改动引起）：① venv 是**拷贝安装**而非 editable，先前若不 `pip install ./growth` 就跑测试，测的是旧安装包——新增的 Skill 漂移守卫测试正是这样暴露出 `creative_copy.json` 仍在承诺已删除的 `copy_options` 机制；后续每次改源码都已重装。② IDE 的 Java language server 在 12:27 把带 `Unresolved compilation problems` 的 class 写进 `target/classes`，`dev.sh up` 打包后 order 服务启动即崩；已用 Maven `clean package` 重建（0个受污染class）并全部恢复健康。
>
> 仍未完成、不能宣称的：RAG 三项语义指标仍是 `None`，`FAILED_SAFETY` 未改判，12条 holdout 未读；正式四分支3种子对照、完整20×2工具任务、五经营病例复验、F6/F7 全门禁均未执行。精排收益只是24例小语料的检索召回，不代表回答质量、引用支持率或转化改善。MCP 只实现三个方法，无 resources/prompts/sampling/SSE 恢复。

> **求职评估补充（2026-09-10，只读分析）**：已结合用户提供的18章面试知识图谱、当前源码/历史产物与百度/京东/运梦官方岗位页面，完成[知识图谱与岗位适配评估](docs/reviews/job-fit-knowledge-map-review-2026-09-10.md)。本次实际执行 `python3 handoff/verify_package.py`（5来源、14校验通过）及 `./scripts/dev.sh status`（13应用、5中间件健康），直接核对Shopping源码/安装均v16同SHA、Merchant源码v18/安装v17不同SHA。未重跑构建、DB、模型、交易、浏览器或完整评测，未读取holdout；所有质量/性能数值均引用历史产物。新增明确边界：SSE为持久进度/最终答案恢复，非逐token正文；推荐小样本语义P50约3.19秒、规则约0.18秒，相关性/转化收益仍未证；RAG development子套件FAILED_SAFETY、Merchant语义尚未完整支持。仅新增报告和本状态记录，原业务改动保留，未实施增删。后续建议冻结现有范围、完成正式F6/F7、补交付/体验证据及小清理；当前仍暂停新增实施，不因本次评估自动执行建议。工具限制：WSL无rg，改用git grep/grep；部分面经网页正文不可读，未宣称全量来源审核。

> **当前任务转为求职架构审查（2026-09-09）**：已暂停新增实施并保留v18工作区；运行仍为Shopping v16/Merchant v17，v18仅报告50项Merchant+AdsService轻量通过，未做DB/live/安装。审查结论见[秋招AI应用架构审查](docs/reviews/job-fit-architecture-audit.md)：工程闭环有历史实证；每轮Merchant由按钮/driver触发，不是后台持续自治；主要超配在继承电商底座、重复评测/证据和技术化管理界面。建议收敛展示、统一入口、归档重复叙事，不能删正式门禁或失败，不推倒交易底座。审查未实施任何功能删改，F6/F7和原完整目标仍未完成。下面逐轮记录为历史过程，旧“下一步”不应覆盖本段当前恢复位置。

> **2026-09-10 页面入口核对与现场状态**：用户询问当前各环节如何展示，本轮仅只读核对源码和`dev.sh status`。现有用户端默认`/assistant`，直接访问记自然entry；推荐卡有真实曝光/点击上报，但尚无用户可点击的广告展示位或广告落地跳转。独立管理端已有活动与授权、经营助手、知识库、人工客服；经营目标/计划审批/执行与回执可操作，下一轮广告曝光/点击主要由demo/eval脚本调用真实本地API产生，暂无可视化流量启动按钮。已有闭环证据应描述为业务/API链路，不能冒充全浏览器可点击产品闭环。现场13应用均stopped，5中间件均Exited(255)，本轮未重启、未改业务源码、未跑模型/数据库实验；不推断停止原因。v18仍保留待验证，原F6/F7目标未完成。

> **2026-09-10 前后端展示闭环可行性评估（未实施）**：用户要求保留Java底座，评估把自然访问、个性化推荐和广告位接回商城前端。建议在现有Smartlect Vue内复用商品/详情/订单/助手组件，所需原首页组件仅从冻结ZIP择取；先接“为你推荐”和明确标识的广告区，补服务端可投广告候选筛选/轻量个性化排序，复用现有曝光/CPC/归因/授权/交易接口。商家沿原管理端观察、规划、批准和执行；返回同一商城页面产生下一次真实本地可见曝光/点击，验证新素材/策略及账本变化。优先打通真实浏览器操作，批量模拟按钮为后续演示便利项，不是第一步必需的新平台。本轮仅分析，未改业务代码或启动服务；不把现有推荐能力等同已经实现个性化广告选择。

> **2026-09-10 产品闭环实施推进**：恢复5中间件及13自有应用后，加入商城首页 `/`、普通“为你推荐”与明确“推广/广告”分区。新增Growth `GET /api/assistant/ads/recommendations`：服务端只返回当前稳定grant、ACTIVE活动/素材、余额与Java逐SKU库存复核均通过的候选；用户偏好影响排序，读取不记账。广告卡仅在页面可见≥50%且document visible时提交带campaign/creative版本的曝光，点击需先收到持久曝光回执，版本变化/暂停/库存/余额失败则刷新，不伪造归因；推荐触点仍走独立REC_IMPRESSION/REC_CLICK。商品点击进入已有Java商品详情/用户确认链，商家端继续在独立控制台观察、规划、批准和执行。

> 实际校验：广告服务9项轻量、广告/推荐22项MySQL、Agent/知识/Shopping/广告组合79项轻量、全量Python251项（含115条件跳过）均通过；用户Vitest31、admin Vitest24、用户typecheck、两端build通过；Java `mvn -B -f backend/pom.xml package`在SDK依赖下沉后BUILD SUCCESS（48.651s）。真实campaign纵切 `artifacts/final-b45dbe1e6bdf4f7dabf794448613b223.json` exit0/PASSED，88 checks/live qwen3.7-plus/模拟支付和广告CPC，新增验证商城广告候选读取不扣费；前一次配置范围不一致的失败`final-162...json`保留。一次广告全量命令初始偏好测试缺source字段失败，测试修正为显式偏好来源后通过；所有失败与中间日志保留。用户端31项与管理端24项构建日志仍是当前修改前后端契约，不代替真实浏览器广告点击验证。

> 泛化原则执行：Shopping预加载三类领域Skill但不强制模型先逐个load_skill；回答与检索/客服转交拆分，未知/冲突不再一律控制器开工单，工具权限/用户确认/Java权威保留；知识注入片段隔离为低可信数据并继续可完成部分。Merchant取消固定copy_variant模板和创意/预算/推荐的统一样本阈值硬拦，仅保留事实一致、授权、预算、库存、版本和动作合法性检查；prompt现v19，工作区当前与安装包需复验SHA，旧v16/v17运行结果不改判。对应源码变更尚未完成最终DB/live复验，不能用这些单测宣称模型泛化已改善。

> **2026-09-10 商城前端闭环当前检查点**：按最新原则先修系统职责，不为单条badcase加词表/固定答案。Shopping v17预载三领域Skill而不强迫模型逐个加载；知识注入片段作为低可信数据隔离，回答/检索/转交拆分，未知或工具失败不再一律开工单。Merchant v19取消固定`copy_variant`模板和创意/预算/推荐统一阈值硬拦，仅保留Java权威、身份、库存、累计授权、预算、版本、事实绑定与幂等。对应轻量 `test_knowledge_memory test_shopping test_merchant test_ads_service test_recommendation` 56/25及全量 Python 251（无DB条件115跳过）通过；当前工作区已安装包SHA一致。以上是契约/泛化方向验证，不等同真实模型泛化改善，原历史失败保留。

> 用户端根路由改为商城首页`/`：并列展示普通“为你推荐”和明确“推广/广告”区；推荐商品卡和推广卡进入同一Java商品详情/SKU核对/用户确认路径。新增`GET /api/assistant/ads/recommendations`，广告候选由稳定grant、ACTIVE状态、预算和Java库存实时筛选，普通偏好只影响排序；读取无曝光/扣费。PromotionCard仅在可见≥50%且document visible时带页面所见campaign/creative版本写曝光，持久回执成功后才写CPC点击；旧版本/暂停/售罄/余额变化拒绝并要求刷新，广告和REC触点分账。管理端首页重排为最新经营结果→计划/待办→高级证据，首次授权、执行与回执仍显式；下一轮实际流量可由商城展示产生，也可脚本驱动，尚无后台自动调度。

> 真实验证：5中间件由`infra-up`恢复，13应用`up/apps-check`健康；`mvn -B -f backend/pom.xml package` SDK下沉后BUILD SUCCESS 48.651s，依赖tree显示Alipay只在pay、Aliyun只在user；广告服务9轻量、广告MySQL22项、全量Python251项、前端user31/admin24/typecheck+两端build通过。`final-b45dbe1e6bdf4f7dabf794448613b223.json`为最新真实campaign纵切PASSED，live qwen3.7-plus、88 checks：首次grant/投放→250广告曝光/1 CPC→广告A导购B真实SKU交易/退款→Merchant新观测/授权内动作→下一轮新曝光并累计1→2分，同时验证商城广告候选读取不记账；模拟资金且无收益结论。首次权重授权不匹配失败`final-162...json`保留。当前中间件/应用仍运行，下一步按序执行真实商城浏览器广告卡、完整工具20×2、正式对照与RAG/F7；12条holdout尚未打开。

## F6 实施与开发评测中（2026-09-09；尚未通过）

最新已提交F5功能检查点：`cf97d58`、`ded81e1`。以下F6源码/证据仍为进行中检查点，不能把驱动器存在或自测通过当作完整验收。完整目标仍含F6全部门禁与F7独立交付。

本轮新增实际证据（Shopping v14 / shopping_advice 1.4.0；Merchant v13；仍非完整F6通过）：

- 三个实际live演示均exit0：`artifacts/f6-natural-v6.json`（实付/退款1000分、净0、库存5→5）、`artifacts/f6-campaign-v3.json`（广告A买B、实付/退款1325分、净0、独立归因；同grant替换素材后真实下一次曝光/点击，累计1→2分）、`artifacts/f6-support-v3.json`（1000分全退、原操作丢响应恢复、人工接管/回复/关闭）。没有将退款归零写成优化收益。
- 真实开发失败保留：natural-v1上下文字节超限；v2输出正文/误引用工具ID，campaign/support-v2同类推荐失败；v3虽原生终答协议通过但冗余商品观测超限；v4把商品ID放入required_terms导致空推荐。压缩重复系统说明/schema标题、商品级观测移除聚合/未知SKU库存，保留12,000字节/6模型/10工具/2检索限制；Provider提供受限`tool_choice=required`并实测两调用协议通过。新增`product_id`筛选只与服务端授权scope取交集，未知类目不得猜，SKU仍由Java逐项复核；没有放宽金额/权限校验。
- natural-v5已完成live导购/确认/支付/本人查询，但driver误读Java嵌套item.orderId=null而失败；模型查询实际正确。ScenarioClient.pay现验证单明细并取Java父orderId，未改交易实现。`artifacts/f6-natural-v5-recovery.json`沿原scope/会话/付款继续原明细退款并对账，为RECORDED_PATH_RECOVERED，原失败文件保留；随后natural-v6从头完整exit0。ScenarioClient另保存真实工具参数/回执，便于离线核查失败。
- 当前轻量Python总219项中122通过、97项数据库条件跳过（`f6-v14-python-light.log`）；新增商品ID范围测试在11项推荐检查通过，5项Shopping边界通过，Provider10项通过；v11/v12各12项真实Shopping MySQL通过，未把轻量跳过计为数据库成绩。所有构建/数据库/live/浏览器仍串行；现有13应用健康，64GiB swap保留约61GiB可用。
- 总入口`./scripts/dev.sh eval`已接`evaluate.py`：串行case、版本/SHA绑定与原失败保留、显式语义/holdout/fault检查点；9项本地自测通过。五Merchant病例及reset旧消息隔离驱动已实现、自测，推荐评测驱动在实施；正式四分支、完整工具/RAG双重复与holdout、UI首字及F7仍待执行。当前正在跑`eval --suite comparison --smoke --repeat 1`，小规模不能算正式对照通过。

- 真实浏览器`artifacts/f6-browser-ui.json`为UI_CONTRACT_PASSED：当前Java商品/SKU卡→新的具体报价确认→独立模拟支付→原退款确认/恢复→人工转交→商家接管/读取原会话引用和提案/回复/关闭；所记录AI接口写请求22个，最终reload保持22→22，页面JS异常0，用户/管理端1365与390均无横向溢出。首个非进度正文的可见rAF延迟一次干净样本6223.3ms，不是供应商首token或SLA；其他中断测量未补零。截图`artifacts/f6-browser-*.png`。
- 浏览器发现新Java seed未加入Bloom缓存导致公共getProduct返回code600，UI名称/规格未核对而安全禁用确认，原提案过期且未提交。Java Bloom negative现回查权威mapper，存在才回填，不将缓存当库存/存在权威；新JUnit1项、定向package及启动后新seed两商品详情真实200通过：`artifacts/f6-product-bloom-fresh-seed.json`。未知ID现在会多一次DB查询，缓存防穿透收益的边界已明确；未改交易/库存写逻辑。
- UI harness的URL全局缺失、原退款恢复控制消失时超时、管理会话失效和scope切换读竞态均保留失败文件；原退款实际上按同ID恢复完成，没有换ID重做。`artifacts/f6-browser-financial-audit-v2.json`核对唯一Java订单明细1000分付/退、净0、2条APPLIED事件、自然/同SKU推荐独立归因、全部4SKU库存5。首次audit错误比较Decimal与格式字符串失败，改用既有cents换算；一次误用Growth最小权限连接读取Java表被1142拒绝，后续仍只走受控Java HTTP，没有扩权限或写交易表。
- 成功广告run `final-a9d0367cdf5847d18ddc7a0b4a72cfe9`实际reset为replacement `reset-bc68eb1d040306248c8720fa03e023ad`：`artifacts/f6-reset-campaign-v3.json`。`f6-reset-campaign-isolation.json`真实原金融event IDs提交未ACK→broker redelivered→自有worker重启ACK，旧Java/原始事实/归因和累计2分保持，新scope空且资源独立；重复reset不补库存/新增资源。另保存真实重置前Growth基线，与重投后除新增RETIRED guard外逐项一致：`f6-reset-pre-to-post-preservation.json`。
- 四分支1轮小规模`artifacts/eval-comparison-smoke-v14/acceptance.json`仅SMOKE_COMPLETED，不算正式对照；随后源码复核去掉与本支付无关的全局异常零断言、收紧仅推荐grant无投放暂停权限、原未决plan按原ID/版本有界恢复否则PENDING_RECOVERY阻止新轮及配对、按索引持久延期订单变化，并检查每branch前后runtime冻结一致。正式2重复/3种子仍待跑；后续smoke改2轮以实际进入Merchant阶段。

- v14当前完整Python/MySQL重新执行219项全部通过，0跳过（188.629秒，`artifacts/local/f6-v14-python-mysql.log`）。此后仅Shopping Skill补充“没有功能资料不能声称符合用途”的已知语义约束，压缩重复文案，版本v15/Skill1.5.0；5项边界检查通过、已安装并逐服务健康。旧v14的用途适配表述保留为语义缺口，不把提示词修改当作已验证质量改善。
- eval总入口现遇到首个外部检查点即暂停（含后续comparison），避免#8待确认卡在后续采集中超时；原#8/#13 resume后仅续未开始项，固定20×repeat分母不变。10项pure检查通过；comparison smoke已改为2轮且维度纳入冻结绑定。原1轮smoke不复用为2轮证据。

当前凭证精确值扫描：1294个仓库/前端文件、1919个非目录ZIP成员，0泄漏，原RAG题答及明确holdout路径不读；报告`artifacts/f6-current-secret-scan.json`。独立源码扫描1028文件0问题，14项冻结包校验通过。该扫描不冒充完整安全审计。

最新本地F6检查点为`53771e0`（仍未完成F6/F7）。其后实际评测：两轮smoke `artifacts/eval-comparison-smoke-v15`仅SMOKE_COMPLETED，已实际进入3个Merchant运行；五经营病例`merchant-v15-s1-r1/r2`各3待语义审查/2自动失败，独立`merchant-v15-semantic-review.json`合计6SUPPORTED/4PARTIAL，实际Merchant prompt仍v13。失败拆分：支付案已确切引用失败但分类过滤误拒部分语义，已APPLIED的schema1 CANCEL因缺scope meta被漏计；退款案在grant内执行了缺乏推荐表现依据的策略调整，不是越权，也不能算正确优化。当前修复v1非金融事件的持久scope与历史meta补投影（不改raw/金额/金融归因），并分开广告CPC点击与真实REC_CLICK成熟条件；源码/测试在补，尚未安装/实测。

推荐评测`artifacts/f6-recommendation-v15-s42.json`固定2重复都在模型调用前失败：HTTP ActorContext.permissions数组被当Python严格tuple验证；driver已改按JSON边界解析并保留同一身份权限，自测通过，实际重跑待上述源码稳定后进行。永久`scripts/check_secrets.py`真实扫描1323文件/1919ZIP成员0泄漏/0错误，`f6-secret-scan-permanent-v1.json`；docs/architecture-interview.md及新评测失败/独立审查待下次本地提交。12条holdout仍未执行或用于调试。

本次修复已实测：229项完整Python/MySQL全部通过（199.802秒，`artifacts/local/f6-nonfinancial-rec-evidence-mysql.log`），含从≤0009真实升级的新容器、v1行为scope持久冻结/重投不漂移、原金融归因保持、广告10点击不能解锁推荐/真实REC_CLICK 9→10解锁、同触点去重/跨scope隔离。当前已安装Shopping v15、Merchant v14、campaign_plan1.6.0/performance_review1.5.0及0010。

真实0010升级新增26条历史非金融meta，原100条事实/raw/fingerprint、50条归因、52条已有meta和30账户逐项保持，所有已APPLIED非金融事件均有scope：`artifacts/f6-nonfinancial-scope-upgrade.json`。部署中首次停worker辅助命令误用不含pidfd_open的python3，迁移仍在ledger锁下完成；项目指定/usr/bin/python3的up随后正确重启两个变更Python进程，包fingerprint复核一致、13应用健康，间隔未跑流量实验，原数据/完整性检查证明无漏投影。首次只读升级核对器误期望所有缺meta事件都回填，现按schema1/APPLIED/非金融明确谓词核对，金融旧事件保持未知，未放宽数据门禁。

比较协议在正式规模前修订为v2：规则推荐策略同样只以实际recommendation_clicks≥10及原事实引用触发；模型也需精确引用该事实，广告预算/素材旧门槛不变。正值真实payment_attempt另须明确payment_failures或other诊断，未知原因/样本不足可并列，不强制动作；原两次v13输出/评分不改。下一步重新执行五病例与推荐双重复、正式四分支/完整工具与RAG开发-冻结-留出，再F7。

后续当前版本实测：`merchant-f6-v2-s1-r1/r2`中取消scope及推荐成熟条件已通过，两次仍各有1/2个诊断引用不完整（不足样本漏impressions；退款一轮漏paid_cents），原失败保留；没有通过放宽判据取绿。现Merchant v15、campaign_plan1.7.0/performance_review1.6.0要求同诊断完整广告/退款证据组，模型缺项只走原一次repair，不代填；39项轻量与27项真实Merchant MySQL全部通过，待新实际五例复验。

`artifacts/f6-recommendation-v2-s42.json`固定42、两重复全部PASS：4个真实content_llm调用、约束违规0、全4SKU实际售罄空结果后用户确认取消恢复，未付款/取消仍失败计数0。前2项覆盖率：HTTP规则3/4=75%，语义2/4=50%；一profile两次语义顺序不同，不声称语义更优或测得收入提升。此小样本不是正式四分支/三种子。

最新固定代码（Shopping v15 / Merchant v15）结果：`merchant-f6-v3-s1-r1`五例均待语义，r2四例live/信息不足一例因evidence_ids重复列表与observed_facts不一致，在唯一repair后规则回退空动作；原FAILED保留，不计live成功。独立`merchant-f6-v3-semantic-review.json`支持五类核心事实/安全行为，9/10最终live、6SUPPORTED/4PARTIAL，三处措辞缺口和格式失败变异保留；不代表100%语义正确或完整F6/F7。`f6-recommendation-v3-full.json`默认42/73/101×2共6次、12真实重排调用，全部约束/库存恢复检查通过，不保证语义排序优于规则。

完整RAG development v2已采集64/64：`artifacts/eval-rag-development-v2`。自动门禁有3次所需人工工单未创建（025-r1、019-r2、025-r2），普通状态/引用问题另列；不能计为RAG通过。实际Provider/embedding共2343attempt，1失败；已知费用估算0.837348CNY，2137个attempt未定价（主要embedding），不是总账单。64项独立审查已合并并绑定原case SHA：正文事实97/124、引用103/104、Recall@4及@8均1（56个可评重复）；所需拒答/转人工正确率0.75（28项）。原自动报告另存acceptance-before-review.json，同一64条用人工审查重算后的acceptance.json为FAILED_SAFETY，原输出和失败均保留。

用户最新要求优先系统设计与泛化，避免针对badcase拼接规则。已撤回未提交的转人工短语/正文regex guard，隔离草稿与SOURCE_ONLY回放保留，不曾安装或创建新工单，不计新成绩。Shopping源码及其测试已恢复至2450d7e；基线5项轻量检查通过。接下来以显式转人工动作/真实回执及Merchant单一证据引用契约修复职责问题；合成验证按通用能力、否定/复合意图、重复/恢复与接管边界设计，不用固定case措辞。

当前源码已加入Shopping v16 / answer-v2的`request_handoff`终止工具（support_policy1.3.0、shopping_advice1.6.0）：纯转交无需加载Skill/检索，复合咨询可附本轮有据说明/引用；原租约下建本人工单、真实ToolReceipt后终止；普通finish_answer不暗中建工单。controller_safety/controller_fallback/model_tool/recovered_existing_ticket分开记录。建单→回执→终答仍非单事务，崩溃后只读原工单并取消续跑，不虚称丢失回执已完成；接管fencing及混合批次执行前拒绝保持。撤掉重复政策例句，以通用事实/未知/动作契约说明。

实际新增验证：11项Shopping/身份工具轻量通过；首轮16项真实Shopping MySQL通过后补了建单后回执写入中断的测试，最终Shopping+知识/记忆26项MySQL全部通过（38.789秒，`artifacts/local/f6-handoff-memory-mysql.log`），包含两个崩溃窗口、原工单恢复、重复call_id、访客、引用、混合批次与人工接管。模型均为显式FakeProvider，只证明契约不证明真实模型语义。一次全量轻测在Merchant源码/旧fixture并发中间态出现14错误及新增工具名单1失败，原log保留；名单已适配，Merchant完成后重新串行执行最终全量，不能把该中间态当最终成绩。当前runtime仍为已安装v15，v16尚未安装/live；12条holdout未读。

Merchant v16 / merchant-proposal-v1已完成reference-only契约：模型只选evidence_ids，编译器按原观测绑定恰好这些事实（不代选/补组），compiled仍merchant-plan-v2并另记evidence_binding_version。删除解释数值的regex、逐诊断完整指标组和强制拆标签规则；真实DECLINED仍须主动选择，肯定诊断核对权威事实，动作独立按授权/成熟度/预算/CAS检查。首次推荐revision固定到既有run context，保存时核对原事实与revision，旧已保存spec不重编译。campaign_plan1.8.0/performance_review1.7.0按最终职责重写，未新增模块/表/Agent。45项Merchant/Service轻量通过，含新真实DB测试的完整Python/MySQL240项全部通过（236.610秒，`artifacts/local/f6-general-contract-python-mysql.log`）。

随后交叉审查发现HTTP在工单存在时先409，原message重试到不了Agent恢复分支。已修为会话锁内先核对原ID/指纹再拒绝新消息；精确原请求恢复原run+工单并fence旧租约，保留原上下文和调用预算，任何新模型/交易都不启动。新增新app生命周期的HTTP恢复测试覆盖有/无回执、异参、新消息、跨用户及迟到写。首条定向命令误写test_ai_state_mysql模块名，27个真实测试通过但模块导入错误使整体失败；原log保留，现用正确test_state_mysql串行重跑。最终轻量241项中131通过/110按DB条件跳过，不将跳过算MySQL证据。

HTTP修复最终33项Shopping/State/Knowledge MySQL全过（52.563秒，`f6-handoff-http-recovery-mysql-v2.log`）；只读交叉复查确认实际HTTP门槛已解决。安装前Growth检查CREATED/RUNNING为0，不重解释在途旧合同。首次沿dev.sh写法pip install裸`growth`被当成外部distribution并报无可用版本，未安装；已将入口改为`--no-index --no-deps --no-build-isolation ./growth`，显式本地包实际安装与pip check通过。原失败与v2成功日志均保留。当前正在逐服务安装后up/健康，随后固定handoff辅助8×2与Merchant五例双重复；不以辅助样例替代RAG开发/留出。

v16现已安装并核对源码/安装包SHA一致，13自有应用健康、9注册/8undo；全量凭证扫描1440文件/1919ZIP成员0泄漏/0错误，独立扫描1032运行文件0问题。当前契约检查点见`artifacts/f6-general-contract-validation.json`；真实模型跨表达与经营复验尚待采集，F6/F7保持未完成。

固定handoff辅助8×2已在v16真实跑完：`artifacts/f6-handoff-contract-v1`，14待独立语义/2失败，原失败仍在。两次未知规则都由有界检索耗尽后controller_fallback建真实工单，不算模型request_handoff成功；其余直接/中英/复合以及否定/假设/引用的自动合同检查通过。此辅助分母不替代RAG，holdout未读；不再针对这两条输入加规则。当前串行五Merchant病例双重复v4，完整F6/F7仍待后续。

v16最新live完整复核：handoff独立审查16/16，14pass/2fail（同一未知规则两次都controller_fallback），8次model_tool、6次纯政策未误转、引用10/10支持、强违规未观察到；报告`f6-handoff-contract-v1-semantic-review.json`。含索引共62实际attempt、已知64642tokens、估算0.14073CNY/24attempt未定价，非总账单/前端首字。

Merchant五例双重复v4全部采集：10次live、0repair/fallback，原9待语义/1FAILED；独立`merchant-f6-v4-semantic-review.json`判2SUPPORTED/7PARTIAL/1UNSUPPORTED。真实失败包括已曝光的无据价值/评价文案、正文把CNY分称美分、把退款/低CTR当原因、漏选取消或付款转化、跨SKU推广库存判断。r2退款replace_creative确实在runtime允许范围内（10广告点击OR100曝光），但不符合冻结病例动作范围且理由无据；没有将它误报越权，也不把原FAILED改绿。稳定grant/预算保持、5个真实变更/6个新曝光/4次拒绝可追溯；经营语义门禁仍不能宣布通过。原成功provider正文未保存，compiled模型字段不冒充原始报文。

已另补共享观测CNY最小单位元数据与有界accepted_candidate正文/SHA/截断标记，v17的46项Merchant/Service轻量通过、实际本地安装/13应用健康；没有事后补造v16原文。正在收敛v18通用动作证据契约：自动素材试验与预算样本拆开、通用已审CTA变体由模型选择后编译回原copy_text，保留原手工DRAFT→启用及手工文案路径；不以旧无据文案当批准材料，不加坏例词黑名单。此为代码实施中，尚未安装/实测，全部20×2工具、最终RAG/holdout和正式对照仍待最终源码冻结。已准备run/f6-tool-checkpoint-commands.md及run/f7-clean-checks.md；当前没有重型实验在跑。

下一步：最小契约修复/通用边界验证→完整工具20×2（008/013停外部checkpoint即时处理）、最终RAG开发复验/冻结后12holdout×2、正式四分支3种子×2、成本/可靠性汇总与最终全门禁；随后F7干净Maven/venv/前端及README命令。当前无重型实验在跑，browser已关闭，13应用/5中间件保持，所有服务进程管理用/usr/bin/python3以支持pidfd。

当前实现：

- `scripts/final_demo.py`与`scenario_client.py`提供3个新演示，`scripts/demo.py`/dev.sh已接新名称并保留purchase_stockout。三个实际live纵切已通过，见上方本轮证据；live合法等待而未产生场景所需调整会明确SAFE_WAIT/exit3，不能算完成；mock仅合同回归，不冒充AI能力。
- `MemoryStore.get_ticket`及support GET/分页、Vue工单详情展示真实历史/引用/当前提案，不提供客服代确认交易。24项管理端测试、8项轻量通过；与匿名范围/接管合并3项真实MySQL通过，日志 `artifacts/local/f6-visitor-support-mysql.log`。
- Java scenario V2 run级registry、inspect/reset/reset-result与Growth0009持久QUIESCING/RETIRED guard、`scripts/reset_demo.py`已实现；`dev.sh reset-demo`已接。Java当前定向8项与package通过（`f6-admin-package.log`），Growth reset3项真实MySQL通过（与all policy合计4项，`f6-policy-reset-mysql.log`），20项轻量通过。真实reset已在旧F5-v10注册run成功：`artifacts/f6-reset-owned-v10.json`，退役旧run并新建独立replacement run `reset-d1f19b0ad3a0f041ade1af43d642d7fa`。首次被归属检查拒绝，真实JDBC探针发现TINYINT(1)映射Boolean；检查SQL改显式CAST数值状态后，8项Java/package和实际reset通过，未放宽归属检查。重复恢复、旧消息重投/新scope不污染以及真实用户/商品停用仍待补验。旧数据不删，新Java资源独立；原请求/hash和未知结果guard持久，旧scope不可复用；并发旧Java请求边界见docs/reset-contract.md，不声称水位hash可证明全链静默。
- all推荐动作一次CAS同时切两组同版，不改变分桶；必须显式all授权。新版管理端有all选项。真实MySQL原子/回滚/旧授权拒绝/assignment稳定通过。首次新测试误传StrategyStore(clock=...)，已修fixture并保留失败日志，未放松门禁。
- `scripts/eval_comparison.py`及冻结`evals/comparison-protocol.json`已实现/自测，尚未真实运行。默认4分支×17/42/73×4轮×300机会，20商品/40SKU/100用户/6活动/12素材，按逻辑机会哈希取随机数，实际API状态决定行为，隐藏概率不交给Agent，无优化分支硬奖励；小规模只能smoke。live无动作/降级照实，rule推荐干预是预声明的一次成熟样本策略规则，均沿稳定grant和执行器。
- 20工具任务已先冻结，`evals/tool_tasks.jsonl` SHA256 `400e3d2085574389edb59d768e5bbf53804169f1c0cbf973cdc2a9e921a7c98c`；8个实际Agent多步、11服务恢复、1显式transport故障分开。`eval_tools.py`/`tool_fault_fixture.py`/9项本地自测已完成；实际20例/双重复未运行。#8需root按原proposal checkpoint重启自有API再resume；#13需root串行启动仅该scope的loopback MockTransport fixture，明确非真实模型调用；#15/16错过在途窗口不能算通过。

RAG开发集与真实失败：

- 已按预声明split仅向实施上下文输出32个development案例，写入忽略的 `run/rag-development.jsonl`；整份/开发split SHA一致，源文件为选取split而机械流式读取，holdout题答没有输出、没有执行或用于调参。12个holdout仍须在最终模型/提示词/Skill/索引/源码freeze后才评测。[选择记录](artifacts/f6-development-selection.json)。
- `eval_rag.py`以真实Java身份、每case/repeat新scope、全部32基础文档protected API发布及声明lifecycle执行；guest使用真实签名访客ID的服务端注册，仍是visitor且无订单权限，跨scope bind拒绝；同scope登陆迁移已测。runner只把用户turn和真实检索交给模型，不传expected；语义评分保持待审，不用substring/模型自评替代。
- 首个guest smoke完成，实际hybrid embedding与引用位置/权限等结构检查通过，未当正式评分。随后 `artifacts/rag-development-v1` 在shopping-react-v7固定版本跑完32条/repeat1，exit1：18待语义审查、14结构/状态失败。独立只读[语义审查](artifacts/rag-development-v1/semantic-review.json)为9PASS/10PARTIAL/13FAIL；62必需事实中33完整/24部分/5缺失，47引用中39完整支持/4部分/4无关；严格支持率82.98%，7个零引用案例为null。11个人工必需案例中5缺工单，5案例含rule-fallback。未发现交易越权/ACL泄漏，注入marker在原文引用中不等于执行。所有原case/summary保留，不代表正式双重复/留出或完整RAG通过。
- v8修了检索候选状态与最终答案状态混淆、修复提示禁止补证、政策意图/未知不等于否定事实、明确人工应needs_human。知识可疑指令直接终止且不附无关/危险引用。9项Shopping MySQL通过。定向005/006仍FAILED，025/029结构通过待语义审查，证据 `artifacts/f6-v8-smoke-summary.json`；005原始拒绝输出显示模型直接沿用历史自然语言且未本轮检索，随后仅改JSON仍无证据。006文本保留未知但仍answered且无工单。
- 真实协议探测显示工具+json_schema组合仍可返回Markdown/错误字段，两次失败保留在 `f6-structured-tools-protocol*.json`；而先工具查询再finish_answer函数提交结构化结果的2调用探测通过。v9输出协议实现：finish_answer只是同一控制者输出通道，不是业务服务/新Agent；普通JSON仍须同一验证，状态不再默认answered，混合final与业务批次先整体拒绝，错误补齐tool回复再有限修复。修复额度持久，重启不重置。12项Shopping MySQL通过，`f6-shopping-v9-mysql.log`。精确v9协议已PASS；005两轮均为live/finish_answer且本轮有新检索，结构检查通过待语义审查；006仍answered且没有必需工单，FAILED保留。见 `f6-final-tool-protocol-v9.json`、`f6-v9-smoke-summary.json`。最新源码v10进一步定义“明确不支持”与“未发布承诺”的状态区别，support_policy 1.2.0；轻量4项通过，尚未安装/真实验证，当前服务仍为v9。
- Merchant源码v13提供Java已确认DECLINED/原因码小摘要，禁止把取消/超时重新猜成确认拒付的原因，并支持显式all策略组；32项轻量通过。一个新增测试首次插入位置错误造成NameError，修正测试位置后通过，原失败日志保留。Merchant v13实际5类语义场景尚待F6运行。

恢复任务：当前没有需要等待的重型测试/模型进程；从安装最新Shopping v10并真实验证006政策缺口开始，修复已观察问题，保持全部开发失败。正式RAG development双重复、freeze及holdout仍未执行。再运行三demo、真实reset与重投、四分支3种子与两次固定版本模型重复、20工具任务/重启/fault fixture、五经营病例/推荐差异与全无货、可靠性/成本/首字时延。实现最终 `dev.sh eval --mode live --suite acceptance` 汇总与严格语义审查绑定入口（当前尚未接），完成开发后才freeze/读取holdout。F7干净Maven仓、新venv/两前端安装与完整最终文档/命令仍全部未完成。重型工作串行；当前仅Smartlect资源，没有外部发布/push或真实广告/支付。

## F5 功能门禁已核验；下一阶段 F6（2026-09-09）

F4检查点 `ba6bfb0`；F5主体检查点 `cf97d58`，其后重新审批修复及证据见包含本状态的本地提交。F5功能门禁已核验；模型语义质量仍有明确失败，F6/F7和完整目标未完成。汇总：[f5-validation.json](artifacts/f5-validation.json)。

已实现：Java mock渠道权威DECLINED尝试及同事务Outbox/v2非金融事实；Java独立scenario资源；Merchant持久观测/计划/有界规划、规则基线/共享执行器、稳定scope/grant、推荐策略动作、恢复和经验审批；Vue范围选择/计划/证据/版本/用量/明确grant审批。旧价格库存订单付款退款权威不改，取消、未付、超时、UNKNOWN不能计作支付失败。

真实检查（不同轮次不相加冒充一次全量）：

- Java支付10项unit与3项真实MySQL IT、场景6项unit通过；全Maven25reactor/379项，0失败错误、2项Broker条件skip，exit0，日志 `artifacts/local/f5-java-reactor-fixed.log`。首次全量失败因为SchedulingFlagConsistencyTest只扫描R__current_schema而遗漏V1 Outbox；改为扫描真实迁移并保留原Outbox约束后通过。
- Python177项全量含MySQL通过，`artifacts/local/f5-python-mysql-final.log`；此前176项失败为fixture构造过长pay ID，修fixture并保留边界拒绝，不放松运行校验。后续当前Merchant31项轻量、未知恢复2项MySQL、经验审核3项MySQL分别通过；日志 `f5-merchant-experience-trace.log`、`f5-unknown-recovery-mysql.log`、`f5-reviewed-experience-mysql.log`。预算降至已花费即EXHAUSTED、提高后仍需明确恢复的单项DB也通过。已提交原动作回执优先于新写授权判断；unknown/REJECTED不算部分成功。
- 用户端23项通过；最终管理端21项及构建通过，`artifacts/local/f5-admin-final.log`。包括真实SKU选择、scope-CSRF切换、计划固定版本审批、未知请求恢复、经验编辑撤销勾选、EXHAUSTED显式恢复入口。预算显示挤压已在真实截图中发现并修正。
- [v12原纵切](artifacts/f5-live-merchant-v12.json)三轮live均各一次qwen3.7-plus：首次待批计划→明确稳定grant→启用；250曝光/1点击的新观测→同grant自动换素材→新曝光/点击使用新版本，累计1→2分；无新观测不调用模型；用户确认Java订单→持久DECLINED/重放/消费→live引用该事实→确认取消/库存恢复/原拒付事实不变。账本付款/退款/净額均0。原脚本最后把合法`other`分类误判失败；校正判据为真实event引用、payment_failures指标及精确值后，`--audit-recorded`没有新增业务写，复核原路径与当前账户/账本/库存为 `RECORDED_PATH_VALIDATED`：[复核](artifacts/f5-v12-recorded-audit.json)。原失败文件和首次审计脚本调用签名错误日志保留，不能声称原脚本exit0。
- 同prompt/Skills的[v12b](artifacts/f5-live-merchant-v12b.json)漏引拒付，按同一判据仍[FAILED](artifacts/f5-v12b-recorded-audit.json)。早期v2/v3格式/数值/样本降级、v4缺素材、v5保留观察、trial-v2/v6版本/状态问题、v8推荐枚举/成熟度降级、v9无grant误解、v10比例误判、v11第三轮沿用旧筛查判断均保留。不删除原费用，不把开发重跑当正式效果评测。当前prompt `merchant-plan-v12`；确定性代码提供当前筛查与动作边界，模型最多4实际attempt/一次修复/90秒，原预算不重置。F5保留的API和浏览器记录按run去重共31实际attempt，费用估算0.391298元，非实际账单/收益。
- [真实浏览器](artifacts/f5-browser-admin.json)：同一规则降级计划未批执行→WAIT_APPROVAL且0回执→明确勾选grant→原计划2项APPLIED；live模式与实际用量分标记。真实模型生成含无据原因猜测的DRAFT，没有批准且未进planner；商家修正正文后明确批准v2，原spec草稿保留，改正文旧勾选失效。新增免费曝光后实际live一次，trace明确载入该v2、动作空、花费仍2分。**经验装载正确不代表语义应用正确：这次输出仍把已确认拒付与取消/超时可能原因混淆，已标语义FAILED，须进入F6失败分析。** 1365/390无横向溢出，JS页面错误0；最终reload写请求6→6。截图在 `artifacts/f5-browser/`；只关闭了自有Smartlect浏览器。
- 46条F4基线的原始raw/fingerprint完整，当前63条，包/源码hash一致：[保护检查](artifacts/f5-ledger-preservation.json)。冻结14校验通过；独立扫描、runtime自测、pip check和diff检查通过。实际配置密钥扫描1144文件/1921冻结ZIP成员0泄露，排除RAG题答：[扫描](artifacts/f5-secret-scan.json)。合同见 `docs/merchant-contract.md`、实际服务导出的 `docs/openapi-f5.json`。

**F5重新审批缺口已修复并实测**：原单项真实MySQL已复现FAILED≠WAIT_OBSERVATION（`f5-reapproval-red.log`）。现保留replacement保护暂停和spec不变，将审批同事务精确version+1转换纳入grant snapshot/hash；审批前验证原版本，执行/恢复使用固定偏移，禁止fresh CAS覆盖、禁止已执行计划换grant、普通grant和后续新plan不套旧转换。Merchant25项MySQL全过，`artifacts/local/f5-reapproval-green.log`；含审批前后独立编辑仍拒绝、普通grant不转换、下轮新plan不复用偏移。

`growth/.venv/bin/python scripts/check_f5_reapproval.py --output artifacts/f5-reapproval.json` exit0：[真实API证据](artifacts/f5-reapproval.json)。沿原v10保留scope/250曝光/1点击/1分费用，以规则基线（模型0调用）生成混合合法/越界4动作；有效grant下整体WAIT_APPROVAL且无子动作；明确批准cap400→500、delta100→200的replacement（有效期原样保留）；原不可变plan的4动作APPLIED并精确重放；旧活动继续保护暂停，新活动实际曝光/点击，原账户累计1→2分。新Vue提示替代授权先暂停、扩大预算本身不恢复。构建并逐服务更新后13应用健康。没有把规则验收冒充live，原v10失败记录未改。

WSL由用户扩容：swap64GiB，现场恢复时空闲64GiB/可用内存约16GiB；Docker CLI/socket恢复，5中间件健康而13应用均已停止。已仅通过本项目入口逐个恢复，最近13应用/9注册/8undo表健康。运行期间可用内存约10GiB、swap基本空闲；重型Maven/MySQL/live/浏览器仍串行，没有重启共享WSL/Docker或停止其他项目。扩容期间CLI/socket缺失、首次浏览器登录失败等现场记录保留；没有清库或修改旧.env。

**恢复位置：从F6开始**，继续[F6/F7完整门禁矩阵](docs/f6-f7-gate-map.md)：三场景、四分支×三种子、固定版本真实重复、冻结RAG开发/留出与工具质量、五经营病例/失败分析、可靠性成本时延、人工详情与安全reset；最后干净Maven/新venv/前端安装及完整独立交付。F4/F5未打开RAG题答用于调试。没有push、发布、真实广告或真实资金；总目标保持有效。

## F4 已通过；下一阶段 F5（2026-09-09）

本轮从干净 `03b5497` 接手，保留业务检查点 `0a22155`，未重做冻结或读取旧.env。F4完成不代表完整目标完成；F5→F6→F7继续按HANDOFF门禁推进。

- SQL0007及AdsStore/AdsService实现草稿、不可变grant/计划资源快照与审批CAS、两级启停/恢复、整分预算和原子CPC。账户固定scope_lifetime，reservations恒0；新plan/run/round/grant不清零，替代授权明确重新批准。所有广告写共享scope行锁，跨scope全局ID碰撞安全409。
- Java库存查询前持久开始时间/generation，1秒保守年龄；unknown不投、零库存独立提交两级保护暂停，晚正响应不能越过栅栏。显式resume重验库存/预算/授权。Java查询和Growth扣费不是跨服务原子事务，Java交易仍防超卖。
- 新曝光免费；唯一click/exposure、费用、账户累计和F3 AD_CLICK同事务。先恢复原点击，再查当前资格；暂停/耗尽/换素材/撤销后原成功点击仍原样恢复。MySQL JSON浮点规范化导致的首次/重放差异已经真实复现并修复，首次响应也读取持久回执。
- 冻结Vue管理端已迁入，保留原锁版本、无新增发行包；真实验证码登录/Java商家session/CSRF、草稿、明确审批、预算/素材与启停恢复、动作/观测、知识版本与人工工单操作已接。管理员浏览器跨页CAS冲突可见、刷新不重放。运行器现在监管13应用：9 Java、API、worker及两个前端（用户18180；管理18181/admin/），Node不接收模型/业务密钥。

实际命令和证据（独立运行不相加冒充一次全量）：

- 开始和最终 `python3 handoff/verify_package.py`：14项；`./scripts/dev.sh status/apps-check`由开始12应用到最终13应用，均exit0，5中间件/9注册。运行器self-test、独立扫描最终975文件0问题、pip check、包/源码hash一致。
- `PYTHONPATH=growth/src SMARTLECT_RUN_MYSQL_TESTS=1 growth/.venv/bin/python -m unittest discover -s growth/tests -v`：129项全部通过，含57项真实MySQL，exit0，日志 `artifacts/local/f4-python-mysql.log`。随后21项ads增量、跨scopeID/耗尽版本2项、浮点回执/动作2项定向均exit0；最后变化只在对应广告路径，没有删旧测试。轻量先前128项中56跳过不计数据库成绩。
- `mvn -B -f backend/pom.xml verify`：25 reactor，370项、0失败/错误、2项Broker条件显式跳过，exit0；日志 `f4-java-reactor.log`。用户端23项、管理端11项，以及两端构建均成功。
- `growth/.venv/bin/python scripts/check_f4.py`：[真实投放纵切](artifacts/f4-live-execution.json)，4个新收费click共40分；广告A→推荐B→自然回访→用户确认Java实付1000分/确认退款1000分/净0，B库存5→5。付款后第三/第四点击不得劫持冻结来源；买尽A→Java库存0→两级保护暂停→未点击曝光的新click拒绝→确认取消恢复库存→两级显式resume→第四新click。临时未付款取消明确不是payment_failure。
- 首次live在第二click的精确回执比较失败，两笔各10分费用和触点实际上正确提交。失败日志/进度及专用MySQL先失败/后通过保留；新运行明确批准replacement但累计不清零，最终账户60分（失败20+成功40），UI操作仍60。详见[f4-validation.json](artifacts/f4-validation.json)。
- [浏览器](artifacts/f4-browser-admin.json)：13检查、15真实写步骤/9截图；新草稿→审批maps/hash→预算/两级启停恢复、两页v5→v6冲突409、reload写请求15→15/动作26→26；1365/390无横向溢出、0JS异常。favicon初始404修为200，预期401/409单列。全部活动最终PAUSED。
- `./scripts/dev.sh demo --scenario purchase_stockout --seed 42`：原交易11项通过，证据 [smartlect-5b71f7497fde416ca7a4d07e.json](artifacts/smartlect-5b71f7497fde416ca7a4d07e.json)，没有改名冒充新全闭环。
- `scripts/check_event_replay.py --schema-version 2 --output artifacts/f4-amqp-replay.json`：18个已有v2事实提交后未ACK→redelivered→worker重启ACK，57条当时账本及归因不变。[API真实重启](artifacts/f4-api-restart.json)后旧点击仍逐字段相同、账户60分且无新费用/触点；`check_f4.check_restart`提供可调用检查。
- [账本保护](artifacts/f4-ledger-preservation.json)：原46条raw_json/fingerprint全部保持，最终57条；[实际密钥扫描](artifacts/f4-secret-scan.json)1083文件及冻结ZIP成员/前端产物0泄露。通用扫描曾机械读取RAG文件字节，但题目/答案未进入任何模型上下文或调试，最终扫描已排除此文件；不宣称文件从未被程序读取。holdout仍未用于模型/提示词调整。

合同见 [ads-contract.md](docs/ads-contract.md)、[OpenAPI F4](docs/openapi-f4.json)、运行/前端说明；取材见web/admin/SOURCES.md。配置仍live qwen3.7-plus，F4调用确定性路径没有调用经营模型；支付/投放均模拟，无push、发布或真实资金。

**下一步F5**：先补Java支付尝试DECLINED的持久事实和事务Outbox（取消、未付、超时、UNKNOWN绝不能当失败），再Merchant Observe→Diagnose→Plan→Grant→Execute→Await→Replan、3项商家Skills/经验审批/实际新观测和live计划；共享当前执行器，稳定授权不扩权。F6完整三场景/四分支三种子/留出与工具评测/人工会话详情/reset-demo，F7干净构建/独立交付全部尚未完成。

## 新会话交接入口（2026-09-09）

用户要求把后续工程交给新的Codex会话，本次仅整理文档，旧会话不继续F4业务实现。新会话读取 [HANDOFF_F4.md](HANDOFF_F4.md)、[F4指南](docs/F4_IMPLEMENTATION_GUIDE.md) 和 [启动提示词](docs/NEXT_CODEX_PROMPT.md)，从F4→F7按序接手；完整项目目标未完成，不能把文档交付标成全部实现。

最新业务检查点 `0a22155`，本次文档提交在其后；新会话保留当前HEAD及工作树，不硬重置丢交接文件。本次只读核对：12应用健康/9注册、14冻结校验、增长账本46条且此前34条raw_json/fingerprint一致、Python安装包与源码hash一致、两份run凭证文件600且Git忽略。时刻与端口见 [handoff/f4-state.json](handoff/f4-state.json)；新会话再次核验现场。未重跑Maven、DB集成、模型、交易或广告，没有启动/停止服务。

本次文档变更：新增F4恢复文件、实施指南、提示词和安全现场快照；更新AGENTS/总HANDOFF/README的恢复入口，清除“新会话从F0再来”的失效指引。下方F0–F3是已有执行证据，不是这次文档任务的新增测试成绩。

## F0–F3 主要门禁已通过；下一阶段 F4（2026-09-09）

已按新版 Final Integration v1 接手，开始时分支 `codex/smartlect-implementation` 干净、HEAD `f93b73f`。
保留 `a7b5d1b` 的 Java 交易修复与增长账本。目标持续覆盖 F0–F7，F0 通过不代表 AI 闭环已完成。

| 新阶段 | 状态 | 当前证据 / 下一门禁 |
|---|---|---|
| F0 | 已通过 | 14 个冻结校验、968 个新增取材文件；47 项 Python 全锁安装及框架 smoke；模型白名单安全迁移；ADR/复用表；现有资源健康 |
| F1 | 已通过 | 25 reactor / 349单元、4 Java MySQL、27 Python轻量及12 Python MySQL通过；真实确认/重启/退款、原交易与AMQP重投通过；旧16条账本事实不变 |
| F2 | 已通过最小纵切 | qwen3.7-plus真实引用/记忆/拒答；用户确认Java下单付款退款；Vue用户端、持久知识/人工状态；详见下节 |
| F3 | 归因门禁通过 | 真实多路推荐/最终SKU、持久分桶/访客绑定、VIEW/v2事件/冻结归因、真实模型重排与实际点击；详见下节 |
| F4–F7 | 未完成 | 有状态投放、Merchant、完整评测与干净交付继续按序；专用支付失败诊断事实仍待后续观测补齐 |

F0 交付：
- 原仓只读固定完整 SHA `94d36aee925c75d286f48d2aee2eeea059a74dd9`；未提交 `docs/resume/` 未纳入。Git对象导出 Python 542 文件、Vue 426 文件，精确成员/blob/SHA-256/许可证/排除项见 `handoff/integration-manifest.json`。旧 `handoff/manifest.json` 及原哈希未改。
- `handoff/freeze_integration.py` 一次性导出；`verify_package.py` 可脱离原仓校验新旧5包与每个新增成员。冻结只是取材，尚未迁入web/或恢复旧AI启动链；6份来源未明前端二进制媒体被审查后排除。
- `run/model.env` 已经非执行dotenv解析、关闭插值、按确用模型字段迁移；权限600、Git忽略且未跟踪。默认 `qwen3.7-plus`，保留已配置embedding/rerank模型字段，未复制旧旗舰/回退/业务凭证。提供者域名对照阿里云官方地域域名文档核验。未调用真实模型，运行模式仍mock。
- 启动器只向Python应用合并模型字段，拒绝业务字段覆盖/非600文件；Java继续独立业务配置。`scripts/check_independence.py` 增加web/及模型文件忽略/权限检查，保留旧品牌/原目录/旧Java search/schema约束。
- `docs/adr/0001-final-integration.md` 明确双领域/两模式、4层记忆、6个业务Skills、共享工具及无MCP必经层、MySQL业务阶段恢复。`docs/integration-reuse.md`、`docs/frontend-integration.md` 区分旧能力取舍与实际冻结范围。
- `growth/requirements.lock` 唯一全传递锁47发行包；`pyproject.toml` 保留直接依赖，安装入口先装锁再装包，不带入旧AI全部依赖。

本轮实际命令/结果：
- `python3 handoff/verify_package.py`：开始原12项通过，扩展后14项通过，旧包不变。
- `python3 handoff/freeze_integration.py --source <只读旧仓> --commit 94d36aee925c75d286f48d2aee2eeea059a74dd9`：两个新ZIP；不执行其中源码。
- `growth/.venv-f0/bin/python handoff/migrate_model_env.py --source <旧模型.env>`：11个模型字段，只有字段名写入报告；对所有非忽略文件/ZIP解压内容查实际key，0处泄露。
- 两个新venv安装，最终 `growth/.venv-f0-locked/bin/python -m pip install -r growth/requirements.lock`、`pip install --no-deps --no-build-isolation ./growth`、`pip check`、`-I`隔离导入和安装集合对照均通过。
- 新锁环境 `python -m unittest discover -s growth/tests -v`：22项，17通过、5个MySQL集成明确跳过；不计作本轮数据库测试成绩。`python handoff/test_integration_inputs.py`：3项通过。
- `python3 scripts/check_independence.py --self-test`、普通扫描785运行文件0问题；`/usr/bin/python3 scripts/runtime.py self-test`、`git diff --check`通过。
- `./scripts/dev.sh apps-check`、`status`：5中间件/10自有应用健康、9服务注册；保留运行实例，未重启共享WSL/Docker或原项目。

已修正失败：新校验最初误拒旧包`.env.example`（新排除规则限定新增包）；首次未提交前端包含6媒体（固定同SHA重导为纯源码，初稿留忽略目录）；框架SSE检查曾假定JSON无空格（改解析JSON验证）。没有删业务测试、没有把旧成绩计入当前。
详细证据：`artifacts/f0-integration.json`、`artifacts/f0-python-stack.json`。F0未重跑Maven/Java交易或MySQL集成，也未运行真实模型/前端构建。下一步F1认证与数据合同，重型Maven/数据库/全链路测试串行。

## F1 已实施与验收（本次本地检查点见包含本状态的提交）

F0检查点 `d02d171`。本阶段在此基础上保留原交易/库存/金额/事件账本，新增如下合同：
- 四个委托缺口统一fail-closed；Gateway公共内部头清洗、AI路径交给Python逐请求Java cookie bridge认证；Java用户启用状态、管理员当前会话版本/权限复核，重复cookie拒绝；移除共享token签管理断言回退。
- Java `commerce/v2` 签发单次报价，绑定用户、规范化SKU/数量/地址/优惠、最终价格和TTL。最终锁券/核验库存之后、持久订单/支付意图之前验证报价；不匹配回滚且要求重确认。重复创建先查原幂等结果；保留普通postOrder回归兼容。
- 下单/付款/退款/取消回执区分受理、待定与完成；支付需核对意图及订单同步，退款只在Java COMPLETED宣告完成，取消核对实际库存恢复幂等记录。REFUND当前只支持确认明细剩余可退全额，不新增任意部分退款。
- FastAPI替换临时HTTP server；共享Pydantic工具registry不暴露主体替换或批准执行。cookie写请求绑定同源Origin和会话CSRF；公开会话/run/proposal均按actor+scope验归属。
- 版本SQL迁移包含旧账本原SQL和6张任务/会话/提案/trace表；有checksum、前向顺序和迁移锁。MySQL DDL不是事务原子，当前CREATE/seed可重放，后续ALTER必须另给恢复方案。
- 确认决策/参数hash/Java quote/动作幂等键持久化；每次非终态确认或恢复HTTP调用有新的有界run，原proposal/action/key不变。会话租约带epoch/token fencing，未知先查原回执，查询被拒绝不能把原业务写成失败。终态复用已存回执。
- API与财务worker物理分离，worker不等待模型；11个自有应用受监管。源码指纹覆盖已安装包的Python/SQL等资源，排除pycache；模型配置仅合并Python进程。SSE在开始流式响应前认证，重连仅回放持久事件。

实际验收：
- `SMARTLECT_RUN_RABBIT_INTEGRATION=1 mvn -B -f backend/pom.xml verify`：25项目、86套/349单元全部通过，0失败/错误/跳过。首次clean verify因两个JsonPath断言转换错误失败，精确数组断言修复后全reactor重跑通过。
- `mvn -B -f backend/pom.xml -pl smartlect-order/app -am -Dtest=OrderMoneyPersistenceIT -Dsurefire.failIfNoSpecifiedTests=false test`：4项真实MySQL通过，含报价持久化、消费回滚/重建及原实付分摊/退款合约。
- Python全量含DB运行39项中12个真实MySQL全部通过（原ledger5、状态6、HTTP+mock Java1）；其余一次独立进程health首次读取超时，探测补捕获TimeoutError、仍保持总5秒上限后定向7项通过。最终实际运行venv `python -m unittest discover -s growth/tests -v`：27轻量通过、12 MySQL明确跳过，未把跳过冒充本轮DB执行。
- `growth/.venv/bin/python scripts/check_f1.py`：8项真实Java/Gateway/AI API检查通过。实付1000/退款1000/净0分、库存5→5；实际重启自有API后提案/报价/hash保留，拒绝越权与CSRF缺失，重放确认与SSE不重复写，模拟付款需独立显式步骤。证据 `artifacts/f1-live-confirmation.json`。
- `./scripts/dev.sh demo --scenario purchase_stockout --seed 42` 原交易回归11项通过，实付3475/退款1000/净2475分，库存[5,3,4]→[5,2,3]；`artifacts/smartlect-d802346630f7481d81e5f20d.json`。
- `growth/.venv/bin/python scripts/check_event_replay.py`：真实提交后未ACK、Broker重投、新worker重启和ACK通过，26事件/11425实付/4000退款/4支付转化均不变。新结果 `artifacts/f1-amqp-replay.json`；原P2归档已保留，脚本新增--output避免再覆盖历史P2文件。
- 升级前16条原始账本raw_json/fingerprint逐条与升级后完全一致；新依赖pip check、已安装包与源码内容指纹一致、11应用/5中间件健康、9服务注册、14项冻结校验、独立扫描815文件0问题、runtime自测、密钥不在非忽略文件/ZIP内容中检查均通过。

修复过的真实失败/审查问题：首次退款零值误转int；httpx超时误记rejected；重复cookie折叠；退款查询成功混作业务完成；过期RUNNING无法恢复；恢复查询丢金额/理由；查询拒绝错误终结原动作；终态竞态重复查Java遗留租约；SSE coroutine和直接Response未编码；JsonPath对List.of私有类型转换假失败；启动探测单次TimeoutError未捕获。没有删除原业务测试。源码再定向增加了实际quote validator与SKU1000→1100分变价的联合单测；外部商品端口mock，不能称HTTP实际改价，HTTP验收测的是篡改确认金额。

总证据 `artifacts/f1-validation.json`、`f1-java-unit.json`；详细日志均在Git忽略的 `artifacts/local/f1-*.log`。HTTP合同和前端接线见 `docs/contracts.md`、`docs/openapi-f1.json`、`docs/frontend-integration.md`。

**F1结束时的下一阶段（由下方F2现状更新）**：使用已冻结AI/Vue取材接qwen3.7-plus真实Provider能力smoke、Shopping有界ReAct、3个用户业务Skills、记忆隔离、知识生命周期/词法RAG/引用/拒答和用户UI；最小真实模型下单/退款沿已验证提案与Java接口。当前 `/messages` 明确保存FAILED/agent_runtime_unavailable，尚无模型图、RAG或Vue运行；不能把F1确定性提案与模拟Java的测试计作真实模型能力。F3–F7仍未完成。当前11应用+5中间件保持健康运行，无push/发布、真实广告花费或真实支付。

## F2 已实施与验收（本次本地检查点见包含本状态的提交）

F1检查点 `a5f442d`。本阶段保留原Java交易/账本，完成用户AI与RAG最小纵切，当前模型live、支付mock，12个独立应用含Vue用户端 http://127.0.0.1:18180 。

- 真实Provider仅qwen3.7-plus及其已核验快照，HTTP每attempt25秒/最多2次、共享并发2；函数调用、严格JSON、流式、usage/地区/版本/错误审计已实测。生产模型调用保存在run context；知识发布embedding另有独立持久attempt表，不伪装成Agent。API/worker不继承旧业务凭证，Node不持有模型key。
- LangGraph Shopping有界ReAct，渐进加载3项用户Skills，共享严格工具/ToolReceipt；6实际模型尝试（含embedding、重试、一次格式修复）/10工具/2检索/原90秒deadline、12k保守上下文预算。当前prompt `shopping-react-v6`，仅给模型精简知识观测，完整原文版本和定位仍持久化；不保存隐藏推理，不允许模型确认交易。Merchant及其3项Skills待F5。
- 32份新合成政策，中文BM25＋真实text-embedding-v4 1024维/RRF；先ACL/发布/时效过滤，再检索。草稿、发布、撤回、历史引用、文本PDF解析（pypdf固定版本/体积页数解压限制）已接。引用有效性、最终消息/事件、租约在同一事务校验；可疑知识立即停止后续工具/提案并转人工。
- 本人最近8轮、可追溯用户原话摘要、结构化偏好；用户更正/删除优先、当前原话证据、30天推断有效期、删除墓碑和租约fencing。人工接管持久化，HTTP拒绝后续自动消息、模型/工具在途返回不能越过接管。管理员本地工单API可接管/回复/结束，管理页面待F4/F6。worker独立线程清理30天聊天/trace，保留所有交易提案与账本事实。
- 从冻结Vue选取20个组件/样式再适配，保留裁剪锁、SSE重连/会话恢复/引用源/真实SKU/交易确认/独立模拟付款/偏好页面；退款卡显示Java已购商品和规格，确认额不被展示查询改变。人工或过期禁止新确认，UNKNOWN恢复沿原批准版本；原Java登录、HttpOnly cookie与CSRF不变。
- 新增操作 `./scripts/dev.sh model-mode live`，随后`up`应用；`scripts/seed_knowledge.py --live-embeddings`、`scripts/check_model.py`、`scripts/check_f2.py`可复核。新增SQL0003/0004只在独立Growth库，已应用0001/0002哈希不变。OpenAPI快照 `docs/openapi-f2.json`。

本阶段实际检查（不跨版本相加成一次成绩）：
- 最终安装后 `SMARTLECT_RUN_MYSQL_TESTS=1 growth/.venv/bin/python -m unittest discover -s growth/tests -v`：80项全部成功，51轻量+29真实MySQL。收尾新增接管/精简观测/降级工单后，`-p 'test_shopping*.py'` 12项（4轻量+8真实MySQL）通过；最终全量默认81项，52轻量通过、29数据库明确跳过，DB已由上面本轮实跑覆盖。日志 `artifacts/local/f2-final-python-mysql.log`、`f2-v6-shopping-tests.log`、`f2-final-unit.log`。
- Maven `-pl smartlect-user/app -am -Dtest=UserCommerceInternalControllerTest,IdentityInternalControllerTest -Dsurefire.failIfNoSpecifiedTests=false package`：8项通过；本阶段不把F1的349项全reactor成绩重复算作本次重跑。npm锁安装、最终14项contract测试、vue-tsc/Vite build通过。
- `scripts/check_model.py --output artifacts/f2-provider-final.json`：7类协议/8实际HTTP请求全部通过，包括可省略整数参数严格校验；初次7请求报告保留。真实embedding索引32文档/32请求见 `f2-knowledge-index.json`，索引完成不代表答案质量评分。
- 最终 `scripts/check_f2.py --output artifacts/f2-live-vertical-v6.json`：6条live模型运行（政策引用、记忆、SKU、下单提案、退款提案、无依据拒答）全到合法终态/等待；记忆和拒答各用一次格式修复，均计入上限。实际Java付款1000、退款1000、净0分、1转化，SKU库存5→5，人工后新消息HTTP409。原v5成功纵切保留 `f2-live-vertical.json`。
- Playwright真实用户界面：游客问答查原文、合成用户70下单、独立按钮模拟付款、退款受理后核对原动作至Java COMPLETED；过期提案410拒绝后新提案正常确认。`f2-browser-vertical.json`及5张截图，1280px/390px布局，移动document宽度390无横向溢出。仅预期过期410，无JS异常。
- `scripts/check_f1.py --output artifacts/f2-f1-regression.json`：8条报价/重复请求/越权/实际API重启/确认/退款及账本回归通过，库存5→5；没覆盖旧F1证据。原16条raw_json与fingerprint仍完全一致，见 `f2-ledger-preservation.json`。
- 新锁48发行包pip check、运行安装包与源码hash一致、12应用/5中间件/9服务注册、14项冻结校验、独立扫描922运行文件0问题、runtime自测、实际密钥在非忽略文件及ZIP内容0泄露、diff检查通过。汇总 `artifacts/f2-validation.json`。

真实失败与修复保留：首次输出合同不符转规则；v3/v4供应商把可空整数转字符串（改可省略具体整数schema，仍严格类型校验）；PDF依赖未安装导致模块导入失败（安装新锁后重验）；一轮UI退款提案过期正常410；初期HTTP接管后先RUNNING再取消（改入口409）；两轮检索元数据占满上下文导致rule-fallback（精简观测，不扩大预算，并确保fallback仅给参考+工单）。相关失败存 `artifacts/local/f2-*` 和两份 `f2-live-refusal-*.json`，没有删失败样例、没有把回退算live。旧安装包导致新ToolReceipt导入失败也已在重装后全量验证。模型语义并非保证每次无修复通过。

**下一阶段F3**：真实候选/最终SKU过滤、持久策略分桶、VIEW/曝光/点击、可信匿名登录绑定、广告7天与推荐24小时独立归因、v2业务事件/投影及延迟/乱序退款对账。当前search_skus只是Java事实列表，不冒充F3推荐或归因完成；旧v1账本仍无这些新维度。44例RAG集已冻结（32开发/12留出），尚未执行正式评测；留出题未用于调参。F4投放、F5 Merchant、F6完整评测/人工工作台/reset-demo、F7干净交付仍待实现。无push/外部发布、真实支付或广告花费；真实供应商模型调用已发生且有授权。

## F3 归因门禁已通过（本次本地检查点见包含本状态的提交）

F2检查点 `1fb74da`。已接真实推荐、触点和冻结归因；F4–F7仍未完成，尚无真实投放、经营Agent或完整效果评测。

- `RecommendationService` 从Java内容/类目/共购/历史付款热门/上架顺序召回，商品范围和用户排除名单在SQL LIMIT前过滤，最终同批SKU再次验库存/价格/状态/硬约束。算法 `sku-rank-paid-units-v1`，热度是Java `confirmed_payment_units_v1` 历史确认付款件数（含0元和后续退款），不当作净销量；未知证据为null。原 `total_sale` 只在确认收货后尽力更新，已从推荐信号中替换。
- SQL0006保存固定分桶salt/assignment和不可变策略配置，rule/content配置确实进入不同排序；可选Plus语义回调只排列同批候选，失败回同批规则，最终复验不重新召回。Shopping prompt v7、shopping_advice 1.2；回调共享原6模型/10工具/90秒预算，不新增Agent。
- SQL0005保存可信自然entry、推荐真实曝光/点击、访客绑定、不可变context快照、事件meta和归因投影。浏览器不能提供actor/时间/价格。登录须同一有效Java用户cookie+当前签名visitor cookie，迁移原conversation ID并撤销旧租约；只认领绑定水位之前的匿名事实，再次明确bind才能扩水位，不永久认领未来匿名点击。冲突账户拒绝并清旧cookie，分桶历史不改写。
- Java本地验证独立 `SMARTLECT_ATTRIBUTION_SECRET` 签名（无共享token回退），确认外层可选context token不进入报价/购买幂等指纹。建单原事务冻结actor/context ID/hash/version/scope和真实订单时间；过期/缺失/无效为UNKNOWN，正常Java交易继续。新增order V2侧表，旧迁移及价格/库存/付款/退款写规则不覆盖。
- PAYMENT/REFUND发送v2；原v1消息及原文保留。广告按订单创建时冻结引用中的7天最后合法点击，可广告A买B；推荐按24小时内同SKU点击，曝光单列assist；实际自然回访和广告归因分别保存。退款继承付款明细，冻结外的新点击不得补归因；迟到的冻结内事实才可将PENDING转FINAL。触点参数冲突/串用户/改事实保留旧hash均拒绝或UNKNOWN，不修改金额。
- VIEW由Java真实浏览时间和稳定Outbox产生，消费时间不冒充发生时间；v2非金融scope按注册user映射保存meta，原文及producer声明保留。legacy validateBatch增同SKU四元键，缺SKU保守丢可选归因，多carrier不再被Map覆盖。取消原因沿原Java事件；专用支付失败尝试事实尚未新增，必须在F5经营观测前补齐，不能把未付款/超时/取消直接当支付失败。
- Vue目录页使用真实推荐；IntersectionObserver仅对50%以上可见且页面前台的卡发曝光，真实点击另记且幂等；原生会话请求合并在途、隔离取消并阻止迟到身份覆盖。商品详情显示在当前可见区域，原确认/独立付款流程保留。没有新依赖/框架。

实际命令与证据（不同运行不简单相加）：
- `mvn -B -f backend/pom.xml verify`：25 reactor通过，363项0失败/错误，2项Broker条件测试明确跳过。后续付款热门/范围增量 `-pl smartlect-order/app,smartlect-product/app -am -Dtest=OrderCommerceInternalControllerTest,ProductCommerceSearchScopeTest,ProductCommerceOfferConstraintTest ... test` 26项通过；`OrderMoneyPersistenceIT` 5项、`CoPurchasePersistenceIT` 10项真实MySQL通过；最终 `package -DskipTests` 构建25项目。日志 `artifacts/local/f3-java-reactor.log`、`f3-paid-popular-unit.log`、`f3-java-money-mysql-final.log`、`f3-paid-popular-mysql.log`、`f3-final-java-package.log`。
- 最终 `LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false SMARTLECT_RUN_MYSQL_TESTS=1 growth/.venv/bin/python -m unittest discover -s growth/tests -v`：109项全部通过（65轻量+44真实MySQL），退出码0，`f3-final-python-verified-exit.log`。随后密钥前缀/运行凭证脱敏补充在4项轻量回归中通过（`f3-privacy-final-unit.log`），已重装并重启。先前98项及多次增量也通过；一次全量日志虽109项OK但工具回报143，未据此认定干净完成，以本次明确exit0为准。没有删测试。
- npm最终23项全通过，vue-tsc/Vite构建成功，`f3-ui-contracts.json`。实际浏览器8条列表只对可见1、2位置记曝光，点击位置1只生成一条点击；详情可见、390px宽无横向溢出、控制台0错误。`f3-browser-recommendations.json`及3张截图。
- `growth/.venv/bin/python scripts/check_f3.py` 最终两个真实Gateway/Java场景通过：广告A买推荐B+自然回访、独立自然成交；各实付1000/退款1000/净0分，库存5→5。原visitor读迁移会话404、其他用户/错SKU拒绝、分桶不跳、真实新VIEW、付款后新广告不得劫持、重复确认/回执不重复记账。`f3-live-attribution.json`；广告为明确受控合成触点、0投放花费，不宣称F4已投放。
- `scripts/check_f3_model.py`：实际选中默认treatment分组进行能力覆盖（不是按结果挑样本），真实Shopping+语义重排共5模型调用，4个可售SKU，记录同批候选/策略/算法/usage；`f3-live-recommendation.json`。初始4调用版本和初始HTTP链保留 `*-initial.json`，不当效果对照。
- `scripts/check_event_replay.py --schema-version 2 --output artifacts/f3-amqp-replay.json`：6个已有v2事件实际提交后未ACK、Broker redelivered、worker重启与ACK通过，40条当时总账及归因不变；最终新增两场景后总事件46。升级前34条原始raw_json/fingerprint全保持，`f3-ledger-preservation.json`。
- 启动器已分为worker健康→其他应用，迁移/兼容消费就绪后才启Java。运行12应用/5中间件/9注册；安装包/源码hash一致、pip check、14冻结校验、独立扫描948文件0问题、实际密钥不在非忽略源码/产物/ZIP和前端构建中，汇总 `f3-validation.json`。OpenAPI快照 `docs/openapi-f3.json`。

失败/修复保留：新旧订单表collation不同导致首次MySQL JOIN失败（统一共享读取比较后实测通过）；root自动续行发现5容器Exit255/全部应用停止（仅恢复Smartlect，未触碰其他项目）；默认excluded_terms转储覆盖明确avoid、20项截成16项、中文categories误作ID均有先失败后通过回归；初期热门使用收货计数替换为真实付款事实；范围过滤过晚修为查询前；首次浏览器截图仍是旧dist，重新构建/重载后核对；新增工具精确列表断言随合同补齐。旧34条金额事实未修改，所有新钱为模拟支付，真实模型调用有授权。

**下一阶段F4**：实现DRAFT活动/素材、稳定授权grant、受控启用/暂停/恢复、CPC事务扣费和跨活动预算、1秒库存观测与已观察售罄fencing、新轮真实流量及管理Vue。首次授权由商家确认，模拟验收驱动器可明确扮演该动作；新run/plan/round不能重置花费或扩大范围。F5前补支付失败等经营诊断事实；F6三场景/4分支/3种子/留出质量评测和reset-demo、F7干净构建/完整交付仍未完成。44例RAG冻结集未用于F3调参，留出未打开。无push/外部发布、真实广告或真实资金。

## 历史交接范围（2026-09-09，F0前文档状态）

用户已要求最终融合“广告/自然流量→AI导购与RAG客服→可售推荐→Java成交→支付退款归因→经营助手→下一轮调整”。根HANDOFF.md已重写为Final Integration v1；旧稿和旧AGENTS保存在handoff/history/。

已确认：秋招作品集、真实模型/模拟广告与支付；优先复用原已提交版本的AI及Vue双端；用户确认交易、商家授权范围内自动调整；允许仅旧.env模型key安全迁入新配置；默认qwen3.7-plus，无总模型金额封顶、不得自动换昂贵旗舰。两个领域Agent，单任务单Agent，Shopping有界ReAct、Merchant Plan-and-Execute/Replan；记忆/Skills/MCP取舍及状态合同见新HANDOFF。

本轮仅调研、文档与图示校验，业务源码仍以a7b5d1b为基线，未读取/复制旧key、未调用真实模型、未改动运行资源或重新执行业务测试。原12项交接校验在本轮再次通过；两张Mermaid图已实际渲染并视觉检查。

文档交付检查已通过：6份Markdown的本地链接/围栏、根HANDOFF与两份.mmd/.md源代码一致、PNG渲染（Mermaid CLI 11.17.0退出码均0）、历史HANDOFF/AGENTS归档与原Git版本一致；8项架构审查意见已处理。可核对记录：artifacts/handoff-design-validation.json。本次只修改文档、图示和文档验证摘要，不沿用旧业务测试为本轮成绩。

下一次实施从新版F0继续：解析旧AI_Shop当时已提交HEAD并冻结AI/Vue源码；随后F1补可信身份、确认报价、动作终态等边界。下表P0–P6是历史实现进度，不能当作新版F0–F7已完成。本文后半段旧“下一步”由新HANDOFF实施顺序取代。

| 阶段 | 状态 | 实际证据 |
|---|---|---|
| P0迁移、更名、去旧AI | 已通过 | 25 reactor项目；Java 78套/303项，0失败/错误/跳过；Python12项；扫描764文件0残留 |
| P1独立运行与可信交易 | 已通过 | 9 Java+Growth健康；实际HTTP交易/库存对账通过，B9/B10和mock退款MySQL检查通过 |
| P2事件归因 | 部分完成 | 共购、事件标识、独立账本、真实AMQP重投及消费后对账通过；广告/推荐来源、实际浏览事件待实现 |
| P3推荐 | 未完成 | 仅迁移A/B基础 |
| P4投放反馈 | 未完成 | 仅整分指标与预算边界 |
| P5模型和对照 | 未完成 | mock，真实模型未调用/评价 |
| P6完整验收 | 未完成 | 端到端场景和干净Maven仓未执行 |

## 完成内容
12项SHA-256校验、953个冻结源码文件解包；不访问、修改、运行原三个项目，不复用原凭证/数据库/业务JAR。Java全面迁到com.smartlect、smartlect-*、0.1.0-SNAPSHOT，JDK21编译Java17目标。按调用关系移除旧AI/search、prompt/RAG/会话/路由/权限，保留真实交易和测试。旧镜像清库及预置交易/看板种子不迁入，仅保留静态类目。来源许可证保留。

Python3.13.11新venv本地安装、隔离导入和HTTP通过。Compose project smartlect新网络/卷/数据库/凭证；run/runtime.env权限600且Git忽略。详见docs/migration-notes.md、docs/java-pruning.md、docs/growth-migration.md、docs/runtime.md。

## 实际命令与结果
在WSL项目根执行：
- python3 handoff/verify_package.py --extract：12项通过，953个文件。
- python3 scripts/check_independence.py：764文件0问题；--self-test通过。
- ./scripts/dev.sh bootstrap/config/infra-up/infra-check：通过；down再infra-up检查身份/卷持久化通过。
- set -a; source run/runtime.env; set +a
- SMARTLECT_RUN_RABBIT_INTEGRATION=1 mvn -B -f backend/pom.xml clean verify：25项目全部成功，78套303测试0失败0错误0跳过。含2个专属broker/vhost的Rabbit实测，不含Testcontainers MiddlewareIT。日志artifacts/local/p0-java-verify.log。
- growth/.venv/bin/python -m unittest discover -s growth/tests：12/12通过。
- growth/.venv/bin/python -m pip check：通过。

实际修复过的失败：Redis私有常量误用、prompt删除后的引用、头像测试mock签名、MySQL嵌套只读挂载、增长URL重复前缀、预算Decimal舍入及顶层链接扫描漏检。未通过删除普通测试隐藏失败。未使用历史72项作为本次成绩。

## 运行资源
P0检查时smartlect-mysql-1、redis-1、rabbitmq-1、nacos-1、seata-1均healthy，无本项目Java/growth常驻进程。
端口MySQL13306、Redis16379、Rabbit15672/管理15675、Nacos18848/gRPC19848、Seata18092、gateway18082、growth18001、Java业务18101–18108。实时状态以dev.sh status/run/runtime.env为准。

## P1 当前验证（同日追加）

- `mvn -B -f backend/pom.xml verify`（启用本项目Rabbit测试）318项全通过；新增演示会话1项定向测试通过。后续Seata幂等修复的OrderRequestIdempotencyServiceTest/CommerceOutcomeClientTest定向package通过。完整当前源码单元报告合计319项，其中后续定向运行使common的Rabbit检查显示1项未启用；并非该项失败，早前全reactor启用实测已通过。
- OrderMoneyPersistenceIT 3项、PayChannel4MockIT 3项真实MySQL通过；原两个金额探针先实际失败再修复。CoPurchasePersistenceIT旧实现先失败，修复后7项真实MySQL通过，属于已完成的P2局部事实能力。
- `growth/.venv/bin/python scripts/demo.py --scenario purchase_stockout --seed 42` 实际成功，10条业务检查。实付3475分、确认退款1000分；库存[5,5,6]→[5,4,5]，下单扣减、支付/重复付款不再扣、退款/取消只回补一次，无货拒单、重复初始化不补库存。
- 完整JSON：`artifacts/smartlect-57ed770f4c2643a0863c6505.json`。支付单891160134984362783114586068329可供P2消费后逐明细对账。
- HTTP实际发现并修复：demo登录把MySQL tinyint(1)当Number（改由SQL筛选有效用户）；Seata对INSERT IGNORE零影响行构造空SQL（共享幂等入口改普通INSERT+唯一键冲突处理）。失败尝试留下的两个合成未付款子订单已通过Java取消接口恢复库存，没有直接修改交易表。
- 网关有效会话401污染已修复。应用用run/apps/{service}/{sha256}.jar不可变副本，避免重建target影响活跃JVM；Nacos/Sentinel日志和缓存移入run/。启动瞬间/proc空cmdline竞态已补稳定快照及完整命令核验，不降低停机身份检查。
- WSL曾短暂返回0x8007274c，已恢复；没有重启共享WSL/Docker，也未动其他项目。后续重型测试串行执行。
- 当前5个中间件与10个应用均保持运行。真实状态以`./scripts/dev.sh apps-check`、`status`为准。

## P2 当前验证（同日追加）

- 新增长包使用固定版本Pika/PyMySQL及MySQL8认证依赖，只连接smartlect_growth数据库/身份，数据库权限实查禁止读写Java交易表。事件保留业务/接收时间与原始记录、异常；先事务提交，再手动ACK。支付按明细实付入账、支付单去重；退款乱序保持待定并重放，复购仅标签。
- 新隔离环境growth/.venv-p2安装成功；20项检查全过（含5项512MB独立MySQL实测，临时容器已回收）。零元退款协议修正后新增轻量回归通过；最终runtime环境16项轻量通过，5项DB测试本轮明确跳过（此前已实际通过）。详见artifacts/local/p2-growth-mysql-tests.log、p2-final-unit.log。
- 真实队列消费：PAYMENT3+REFUND1→3475/1000/2475分、conversion1、异常0，证据artifacts/p2-live-ledger.json。
- 实际提交后断开未ACK投递、观察Rabbit redelivered标志、重启消费者、确认Broker新ACK且无未ACK消息，账本不变：artifacts/p2-amqp-replay.json。进程控制使用支持pidfd的系统Python，避免Miniconda缺少该接口；没有放宽进程身份核验。
- `./scripts/dev.sh demo --scenario purchase_stockout --seed 42` 第二次全过（11条检查），包含3个实际REPEAT_PURCHASE标签，仍只计3475分收入和1次转化；库存[5,4,5]→[5,3,4]。记录artifacts/smartlect-d9db410a2b044f358e8c39b5.json。
- 真实Java共购接口返回同支付单另一商品，证据artifacts/p2-live-copurchase.json；7项MySQL契约另验证未付款/退款/多SKU去重及稳定排序。
- 最终独立扫描783个运行文件0残留，runtime自测、pip check、十应用健康与九服务Nacos注册均通过。当前5中间件+10应用保持运行；没有push、对外发布、真实支付/广告花费或真实模型调用。
- Nacos多客户端关机时曾记录NotifyCenter关闭顺序异常；进程已退出并能正常重启，完整故障容错/生产认证仍属于未执行的P6范围。

## 下一步（从P2继续，不跳门禁）

1. growth/src/smartlect/app.py、events.py：实现有效推荐触点/广告点击持久化及/internal/attribution/validateBatch；广告和推荐来源分开，落实7天最后有效点击窗口，覆盖直购/购买其他商品/自然/延迟支付/退款。
2. backend/smartlect-user/app/src/main/java/com/smartlect/biz/impl/UserBrowseHistoryServiceImpl.java及RabbitMQBrowseListenerComponent：将已落库浏览事实接入增长VIEW事件，不能把协议支持VIEW当成已接通。
3. P3用Java真实目录、SKU库存、共购和增长行为实现候选/排序/固定分桶；P4再实现持久化活动/素材/预算及新观测驱动执行。现有Python预算/A-B函数只是基础，不代表闭环已完成。
4. P5缺真实模型端点只保留未评价标记；P6还需完整场景、干净Maven仓、新Python环境和不含交接解包目录的构建/演示验证。reset-demo、工作台和效果对照均未实现。

本轮本地检查点：f2d15cd（P0及初始P1工作）、b1ce241（可信交易与独立运行）；最新事件账本检查点见本文件所在提交。恢复时先读本状态，再运行apps-check确认实际资源。

本次仅更新最终改造规格；P0/P1/P2历史代码检查点如上。未push/发布，无真实支付或广告花费。
