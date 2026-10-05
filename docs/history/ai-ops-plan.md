# AI 资产运维化 + admin 全站统一 · 实施路线

> 本文档是跨会话执行用 to-do list（2026-09-16 制定）。
> **执行状态（2026-09-16）**：Phase 0-7 已完成并分批提交。两处偏离已记入
> docs/adr/0005-ai-asset-ops-surface.md「已知边界」：Phase 7 的 growth-console.scss 全量退役延后
> （四页仅统一页头）；Phase 5/6 的 diff 视图、EditorMarkdown、ECharts 图与 attribution UI 接入未做。
> 下方复选框保留为原始清单，未逐项勾销；完成度以 ADR 的「已知边界」为准。来源：Smartore 可借鉴点调研（知识运维/模型配置/Agent 留痕/工具调试/分析类功能）+ Smartlect 实现级体检。
> 完成一项勾一项；顺序原则上按阶段推进，阶段内条目可并行。每阶段结束：CI 三 job 全绿 + 本文档勾销 + IMPLEMENTATION_STATUS.md 追记。

## 已拍板的决策（不再讨论）

1. **Prompt/Skill：热生效 + 版本回滚**。入库、页面编辑、激活即生效、可回滚；结构（intents/tools 白名单）变更仍需发版。
2. **模型 Key：留 run/model.env**。DB 只存白名单内的激活选择/参数/备注，页面只显示"Key 已配置"状态 + 测试连接。零密钥落库。
3. **前端：admin 全站统一**（含老电商页翻新）；web/user 不动（其 token 体系已是三边最佳）。
4. **商品知识自动导入：生成 DRAFT + 人工发布**（复用 checksum/ACL 生命周期，重复导入按来源覆盖、不碰 MANUAL）。

## 架构师裁决（未问用户、按最小复杂度定的，理由记录在案）

- **异步索引用 app 进程内 asyncio 任务 + MySQL 任务表**，不引 MQ 新队列、不塞进 worker.py：单实例部署（node1），app 已有 tasks dict + lifespan cancel + admit_runs 并发门基建；crash-safe 靠任务表 + chunk 粒度游标（重启续跑）；规模化迁移路径（worker 线程/MQ）写进 ADR。避免过度设计。
- **新端点全部进新包 `smartlect/adminapi/`（FastAPI APIRouter）**，create_app 只做注册组装。app.py（现 898 行/58 端点）不再增长；顺手把它内嵌的业务编排（publish-embed 流水线、execute_proposal）外移。
- **安全边界一律不动**：模型/endpoint 白名单、快照锁、MCP 只读、写操作提案制、admin:legacy + CSRF、知识 ACL fail-closed。DB 化只发生在白名单"之内"。
- **git**：沿用 main 分支 + 每阶段语义化 commit 组（与仓库现状一致）。
- migration 编号从 **0012** 起按实施顺序递增。
- 索引任务的 embedding 并发用**独立 Semaphore**，不与对话 run 抢 Provider 成本闸的槽位（防批量向量把客服对话饿死）；chat 探测同理。

## 现有代码体检结论（Phase 0 的依据）

后端（growth）：
- app.py 898 行单文件承载 58 端点；publish 的 embedding 流水线（823-847）和 execute_proposal（135-183）是业务编排，不该在路由文件。
- `/internal/order/commerce/v2/actionStatus` 等内部 URL 字符串散落 6 处无常量。
- merchant/store.py 压缩风格与全库割裂；app.py 186-187 文件中部 import。
- 死文件：growth/build/lib/（构建残留）、.venv-f0 / .venv-f0-locked / .venv-p2（废弃 venv）、.pytest_cache（用的是 unittest）。
- Python 侧无 Redis（进度一律 MySQL + TtlCache，沿用）。
- 30 天 purge（maintenance.purge_expired）会清空 context_json/tool_call/event —— 运行浏览器必须兼容"已清理"态。

前端（web/admin）：
- 两套 UI 语言并存：老电商页（Element Plus + 全局 Table/Dialog + .search-panel 全局类）vs 4 个 AI 页（自绘原生表单 + growth-console.scss 382 行）。
- 三套弹窗（全局 Dialog.vue / 页面 el-dialog / AI 页内联 panel）；消息提示两套（Message vs 内联 error/notice）；loading 两套（全局 ElLoading vs busy ref）。
- token 分散在 base.scss(:root) / desktop-admin.scss / smartlect-admin.scss / growth-console.scss(--gc-* 桥接) 四处。
- 死代码：src/GrowthShell.vue（生产零引用，但**含全工程唯一 selectScope UI**，删除前必须迁移）、src/views/Account.vue（28 行，仅 GrowthShell 与 admin.test.js 引用）、src/stores/counter.js。
- 测试工具函数（response/field/button/render）在各测试文件重复定义，应抽 tests/helpers.js。
- user/admin 两端手工拷贝且已分叉的组件（LiquidGlassSurface 等）本次不动（范围限定 admin）。

---

## Phase 0 · 清理与前端基建（无行为变更）

后端卫生：
- [ ] 删 growth/build/lib、.venv-f0、.venv-f0-locked、.venv-p2、.pytest_cache；.gitignore 核对补齐
- [ ] 内部 URL 收拢为 commerce.py 常量（actionStatus 等 6 处改引用）
- [ ] merchant/store.py 纯格式化（零逻辑变更，单独 commit 便于 review）
- [ ] app.py 文件中部 import 移顶部

前端基建（一次建好，后续所有阶段复用）：
- [ ] `src/assets/tokens.scss` 单一 token 源：收敛 base/desktop-admin/smartlect-admin 的 CSS 变量，growth-console.scss 的 --gc-* 改为从 tokens 取值（老值原样平移，不做视觉变更）
- [ ] 共享骨架组件：`PageHeader.vue`（标题+职责一句话+右侧主操作，借鉴 Smartore page-heading 模式）、`DetailText.vue`（descriptions 结构化 + pre 原文双层）、`JsonCollapse.vue`（GrowthTechDetails 的 EP 化升级：折叠+等宽+复制）、`StatusTag.vue`（状态色 map 单点维护）
- [ ] `composables/useTaskProgress.js`：容错轮询（interval/deadline/单次网络失败不中止/onUnmount 清理），语义取 MerchantView 轮询 + Smartore 进度页之并集
- [ ] `tests/helpers.js`：统一 fetch stub / response / field / button / render 工具，既有 5 个测试文件改用（不改断言语义）
- [ ] 死代码：删 stores/counter.js；selectScope 切换 UI 迁入 Layout.vue 顶栏（商家身份可见），随后删 GrowthShell.vue 与根目录 views/Account.vue，改写 tests/merchant.test.js、tests/admin.test.js 对应用例
- [ ] 菜单重组：「AI 资产」新组（模型配置/提示词与技能/知识索引/运行浏览器/工具调试）+「经营」组归位（Merchant/Ads/Knowledge/Support/评价分析/增长报告）；router.js 桌面 children + /m/more 移动端 + DESKTOP_TO_MOBILE 映射 + Layout menuList + MobileMore 入口一次改齐（页面组件先占位）

验收：diff 无行为变化；unittest + vitest 全绿；视觉零变化（token 平移）。

## Phase 1 · Agent 运行浏览器 + 工具调试台（纯读面，数据已在库）

后端：
- [ ] 新包 `smartlect/adminapi/`（`__init__.py` 组装 APIRouter；本阶段 runs.py、tools.py；create_app 注册，权限统一 `ads_merchant()` 同款 realm='merchant' + admin:legacy + 写操作 CSRF）
- [ ] migration 0012：agent_run 加索引 (state, agent_run_id desc)、(conversation_id)（列表/筛选路径）
- [ ] `GET /admin-api/assistant/runs`：分页列表，字段白名单学 memory.get_ticket(497-499) 的脱敏选择——run_id/conversation_id/agent 类型(shopping|merchant)/state/model_mode/prompt_version/skill_versions/token 汇总与费用（从 context_json.model_attempts 聚合）/耗时/错误摘要/created_at；purge 后的 run 显示"已过期清理"态（context_json=='{}' 判定）
- [ ] `GET .../runs/{id}`：详情 = run 白名单字段 + model_attempts 逐次（模型/状态/token/耗时/费用）+ tool_call 全量（tool_name/arguments_json/receipt_json/outcome）+ event 时间线（复用 SessionStore.events）+ 决策记录（decision/checks，沿用 get_ticket 字位）
- [ ] `GET .../tools`：tools.py REGISTRY 只读目录（名称/描述/JSON Schema/读写性）
- [ ] `POST .../tools/invoke`：仅只读工具白名单（复用 mcp.py 的权限过滤口径），参数按 schema 校验，走 invoke() 原 receipt 契约；独立小并发闸 + Prometheus 计数
前端：
- [ ] `views/ai/AgentRunBrowserView.vue`：筛选（agent/状态/会话）+ 列表（StatusTag/耗时/token/费用列）+ 详情弹窗（DetailText 双层：model_attempts 表格 + 工具轨迹 + 事件时间线，原始 JSON 用 JsonCollapse）
- [ ] `views/ai/ToolDebugView.vue`：工具下拉 → 参数表单按 schema 动态生成（商品/用户/订单入参下拉化，选项走既有 admin API）→ 结果区"结构化 + 原始 JSON"双展示（借鉴 Smartore ProductToolDebug）
测试：adminapi 端点 unittest（mock store/FakeProvider）；两页 vitest。

## Phase 2 · 知识索引异步流水线 + 进度 + 检索试验台

后端：
- [ ] 新模块 `smartlect/indexing.py`：app.py 823-847 发布-嵌入流水线整体迁入；发布端点瘦身为"切片校验 → 建 job → 返回 job_id"
- [ ] migration 0013：`knowledge_index_job` 表（job_id/draft 标识(scope,doc_id,version)/total/processed/success/fail/state PENDING→RUNNING→DONE|FAILED|CANCELLED/游标 batch_index+chunk 水位/message/created/updated），crash-safe 状态机学 knowledge_index_attempt；IndexModelAudit 逐批照写
- [ ] 执行器：app 进程 asyncio.create_task 进 tasks dict，独立 Semaphore（与对话 run 的 admit 门分离）；lifespan 启动扫描 PENDING/RUNNING 遗留 job 续跑；chunk 粒度幂等（已写向量跳过；注意 set_embeddings 的"chunk 集合完全匹配"约束，改为按批事务落向量）
- [ ] 取消 `document_exceeds_synchronous_index_limit`（40 上限），文档上限沿用 5000 chunk/发布容量检查
- [ ] 致命错误熔断：欠费/Key 无效/模型名错 → 中断 job，message 写"已成功 N/共 M"；普通失败计数继续
- [ ] `GET .../knowledge/indexJobs` 与 `/indexJobs/{id}` 进度端点（processed/total/fail/message）
- [ ] `POST .../knowledge/searchProbe` 检索试验台：默认按请求者 merchant scope 走正式 search()（ACL 不旁路），返回每条结果的稠密分/BM25 命中/RRF 名次/最终名次 + chunk 元数据；admin:legacy 可选 scope 参数扩大到其合法范围
前端：
- [ ] `views/ai/KnowledgeIndexOpsView.vue`：job 列表 + 进行中进度卡（useTaskProgress 1s 轮询 + 条纹进度条 + "关页不影响后台"提示 + 失败计数）+ 检索试验台（query/topK/范围 → 结果带分数标签）
- [ ] KnowledgeView 发布按钮接异步流程：提交后提示并引导至索引运维页（或页内嵌进度卡）
测试与评测：indexing 单测（FakeProvider 注入、致命熔断、断点续跑）；quality-v2 dev 集回归——检索行为未变，指标应持平。

## Phase 3 · 商品知识自动导入（DRAFT + 人工发布）

Java（backend/smartlect-product）：
- [ ] ProductCommerceInternalController 加 `POST /internal/product/commerce/batchDetail`：复用 getDetail 逻辑 + ProductIndexTextSanitizer 清洗，ids ≤ 50/批；Maven 单测
Python：
- [ ] 新模块 `smartlect/knowledge_import.py`：按商品详情生成知识草稿——`source_uri='product:{productId}'` 标记来源（migration 0014 给 document 加 source_type 列：MANUAL|PRODUCT_AUTO，便于筛选与覆盖判定）；内容分组：商品描述/参数（按 propertyValues 分组归并，避免碎片）/价格与库存快照；售后政策留人工（product 服务无此数据）
- [ ] 覆盖语义：重导入按 (source_type=PRODUCT_AUTO, source_uri) 删旧草稿重建；PUBLISHED 的自动文档**不自动撤回**（提示人工处理），MANUAL 永不触碰
- [ ] 导入产物接 Phase 2：草稿(含 chunks) → 自动入索引 job → 向量就绪 → 状态"待人工发布"；发布仍走既有 publish（checksum/ACL 人工核对）
- [ ] `POST .../knowledge/importProducts`（body: productIds[] 或 all=true 走 listOnSaleProductIds 分页；返回导入摘要：成功/跳过/失败计数）
前端：KnowledgeView 加"从商品导入"弹窗（指定商品下拉/全部在售 + 覆盖语义文案）+ 列表 source_type 筛选 + "待发布"队列视图
测试与评测：导入幂等/覆盖语义单测；**新增商品知识后跑 support/shopping dev 评测**——重点确认规则类回答不被商品知识污染（ACL 与 ranking 回归）。

## Phase 4 · 模型配置动态化（Key 留 env）

后端：
- [ ] migration 0015：`model_runtime_config`（id/role chat|embedding|rerank/model_id/params JSON（字段白名单：temperature、max_output_tokens 等）/enabled（每 role 至多一个 enabled，服务端原子保证）/note/updated_by/updated_at）
- [ ] Provider 加"配置解析层"：`_endpoint`/`embed`/`chat` 取值处改为读可刷新快照（TtlCache 短 TTL 读 DB）；**校验链原样保留**：model_id 必须 ∈ 代码白名单、endpoint 域名/路径校验、快照锁、returned_model 回显校验；DB 空或不可用时回落 env 快照（冷启动零配置兼容）；`_breakers`/`_slots` 按 endpoint 前缀的组织语义不变
- [ ] 三处 env 旁路统一走解析层：app.py 831（embedding key 判定）、shopping.py 501-503（embed_query）；settings.model_mode 不动（部署态语义保留）
- [ ] 端点：CRUD `.../models` + `POST .../models/testConnection`（chat 1-token 探测 + embed 1 条探测；独立信号量；返回延迟/模型回显/错误人话翻译——借鉴 Smartore describeModelError）
- [ ] Key 状态只读端点：从 env presence 报"已配置/未配置"，永不回显值
前端：`views/ai/ModelConfigView.vue`：role 单选 + 白名单内模型下拉 + 参数 el-input-number + "Key 已配置"徽章（只读）+ 测试连接按钮（结果内联展示延迟/错误）+ 每 role 单激活约束提示
测试：解析层单测（mock DB：白名单拒绝/回落 env/TTL 刷新）；testConnection 端点测试。

## Phase 5 · Prompt/Skill 热生效 + 版本回滚

后端：
- [ ] migration 0016：`prompt_template`（id/domain shopping|merchant/kind system_prompt|skill/key（skill_id 或 'system'）/version 自增/body longtext/meta JSON（variables 说明、skill 结构摘要）/status draft|active|retired/updated_by/updated_at；唯一 active：(domain,kind,key)）+ 种子迁移：当前 shopping-react-v24 / merchant-plan-v19 全文与 6 个 Skill JSON 按原版本号入库为 active（保证零行为变化启动）
- [ ] 新模块 `smartlect/prompts.py`：`load_active(domain,kind,key)`（TtlCache 短 TTL，缓存键含 version）；接线点：shopping.py 466-467（skills 预载）、767-812（system 拼装）、31-32 常量；merchant.py 334-340、579-598、25-27 常量。PROMPT_VERSION 变运行时数据；`context.update(prompt_version=...)`、decision_record、trace 留痕链路原样（自动记录每次运行用的版本）
- [ ] 保存校验：system_prompt 仅长度/占位符校验；skill JSON 入库时按打包版同 schema 结构校验；**结构面（intents/tools 白名单、新增 skill）不可通过页面变更**——只允许改指令文本/流程说明/输出契约文本，保留"文档不能装代码"语义
- [ ] 激活/回滚 = 切换 active 版本（乐观并发 + updated_by 审计）；draft 可编辑、active 只读、retired 只读可回滚
- [ ] tools.py 的 load_skill 工具（270-271）同步读 DB active
- [ ] 测试更新：test_shopping.py 15-16 的硬编码版本断言改为"与 DB active 版本一致"断言；新增解析/校验/回滚单测
前端：`views/ai/PromptSkillView.vue`：域+类型筛选 + 版本列表（active 徽章/更新人/时间）+ 编辑（system 用 EditorMarkdown，skill 用 JSON 编辑器+结构校验）+ 版本 diff 视图（文本对比组件）+ 激活/回滚二次确认（显示 diff 摘要）
测试与评测：换版本后 dev 评测抽样；holdout 不动（版本纪律：holdout 绑定版本号，换版本需重跑 dev 集再决定）。

## Phase 6 · 评价分析 + 增长报告 + attribution UI

Java：
- [ ] 查证评价域内部接口（order/comment）；若无"按 productId 拉已审核评价"的 internal 端点则补齐（模式同 Phase 3，含单测）
Python：
- [ ] 新模块 `smartlect/review_analysis.py`：确定性统计代码算（评分分布/均分/好评率/情绪阈值），LLM 只产四项洞察（优点/问题/关键词/改进建议，provider.chat + 结构化输出）；migration 0017 `review_analysis_snapshot`（product_id/统计 JSON/洞察 markdown/模型版本/created，覆盖式重算）
- [ ] 新模块 `smartlect/growth_report.py`：dataSnapshot 代码拼（Ledger.summary + AttributionStore.summary + merchant_observation 摘要 + AI 域指标：会话数/handoff 率/工具调用 top/知识引用 top），LLM 只写 3-5 条建议（system 明示"不要编造数据中没有的信息"，风格对齐既有 performance_review skill）；migration 0017 同批 `growth_report_snapshot`
- [ ] 端点：POST `.../reviewAnalysis/{productId}`（生成）+ GET 列表/详情；POST `.../growthReport/generate` + GET 最新/历史
前端：
- [ ] `views/biz/ReviewAnalysisView.vue`：生成入口（仅有已审核评价的商品下拉+条数标注，借鉴 Smartore）+ 统计卡 + markdown 洞察（MarkdownView）
- [ ] `views/biz/GrowthReportView.vue`：数据快照卡 + ECharts 图（订单/归因趋势，复用 admin 已有 echarts 6）+ markdown 建议 + **attribution API 首次接入 UI**（/admin-api/assistant/attribution 零引用现状终结）
测试：统计确定性单测；mock provider 洞察/建议测试；快照覆盖语义测试。

## Phase 7 · admin 全站风格统一（老电商页迁移）

- [ ] 外壳翻新：Layout 侧边栏/顶栏/面包屑统一走 tokens.scss（保留深色侧边栏基因与既有品牌色相）；MobileShell 同步；单一弹窗体系（全局 Dialog 组件收编页面级 el-dialog）
- [ ] 分批迁移老页到统一骨架（PageHeader + 全局 Table/Dialog + SearchPanel 规范 + StatusTag + 统一 Message/loading 走 Request.js 全局），每菜单组一个 commit：商品 → 订单/售后 → 营销/优惠券 → 用户/权限 → 内容/其他；每批跑既有 vitest 回归
- [ ] growth-console.scss 退役：4 个 AI 页全部迁 EP 骨架（保留 work()/busy 三态、幂等重试、显式确认 checkbox 等行为语义，凭据审计语义保留为 JsonCollapse）后删除该文件
- [ ] 视觉验收清单：全站同 token 源 / 每页有 PageHeader / 状态列统一 StatusTag / 弹窗一套 / 密度与圆角一致 / 无平行 UI 语言残留
注意：本阶段纯 UI 层迁移，禁止顺手改业务逻辑；行为变更零容忍。

## Phase 8 · 收尾

- [ ] ADR（growth 侧 1 篇即可）：AI 资产运维面架构——为什么索引用进程内任务不上 MQ（单实例+表持久化+迁移路径）、为什么 Key 不入库、prompt 热生效的安全边界（结构不可变、版本留痕、评测纪律）
- [ ] docs/model-provider.md / agent-design.md 补动态配置与 prompt 管理章节；IMPLEMENTATION_STATUS.md 战役追记；README 截图/描述更新
- [ ] 全量回归：CI 三 job（backend mvn / growth unittest / web vitest×2）+ `dev.sh check` + 手动 demo 走查（导购/客服/知识发布/索引进度/运行浏览器/工具调试/模型切换/prompt 回滚）

## 风险清单（实施时对照）

1. 索引 job 与对话 run 的资源隔离（独立信号量，验证批量向量时对话 P95 不劣化）
2. 30 天 purge 对运行浏览器/成本页的空态兼容
3. prompt 热生效后版本纪律：每次激活必须在 dev 评测集跑过；holdout 与版本号绑定不混淆
4. 商品知识入 RAG 后对规则类问答的污染（Phase 3 评测门禁）
5. admin 老页迁移的回归面大 → 分批 + 纯 UI 约束 + 每批测试
6. Provider 解析层改动触碰成本闸/熔断语义 → 单测覆盖白名单拒绝、回落 env、TTL 刷新三条路径后再动旁路接线
