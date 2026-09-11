# Vue 集成状态与冻结来源

更新：2026-09-10。`web/user/` 与 `web/admin/` 已从冻结 Vue 源码迁入并适配；用户端当前根路由是商城首页，管理端包含活动/授权、经营助手、知识库和人工客服。用户端推荐与管理端构建、类型检查和契约测试已实际执行；广告候选 API 与真实 campaign demo 已通过后端/Java/模拟账本纵切。完整阶段结论以根 `IMPLEMENTATION_STATUS.md` 为准，F6/F7仍未全部完成。

## 商城浏览入口（2026-09-10）

`/browse` 是逛货架的入口，读真实 Java 目录而不是推荐服务：分类 chip 来自 `GET /api/product/loadCategory`，
列表来自 `POST /api/product/loadProduct`，支持关键词（公开端点新增有界 `keyword`）、价格区间、排序与分页。
目录行不带 `recommendation_id`，因此 `AgentProductList` 对它们不上报任何触点——**逛货架不是推荐曝光**。
全部筛选状态放在 URL（`keyword/category/priceFrom/priceTo/sort/page`），既可分享也让单个 watcher 驱动加载；
排序键与价格在发请求前校验，手改链接带非法值会被拒绝而不是转给 Java。商城首页同时提供分类 chip 直达 `/browse`。
商品详情（`/catalog?product=&sku=`）显示封面图与描述，"问问 AI"携带 `product`/`sku` 与可编辑草稿进入导购会话，
让助手能查权威 offer 而不是从文字里猜是哪件商品。

## 当前商城首页与广告展示（2026-09-10）

`web/user/`根路由 `/` 是普通自然访问入口。`StorefrontView`并列请求 `GET /api/assistant/recommendations?limit=4` 和 `GET /api/assistant/ads/recommendations?limit=2`：上方“为你推荐”使用现有推荐服务及用户明确偏好，下方“推广/广告”只显示当前scope有效授权、活动和素材版本均为ACTIVE、Java复核有货且余额可扣CPC的候选。无有效广告时为空态，不用静态素材补位。

普通推荐继续由 `AgentProductList` 按IntersectionObserver登记真实 `REC_IMPRESSION/REC_CLICK`；广告由 `PromotionCard` 在文档可见且卡片至少50%可见时提交带campaign/creative版本的曝光，收到持久曝光回执后点击才提交CPC。广告与推荐触点分开，商品点击统一进入 `/catalog?product=&sku=`，详情页继续调用Java商品/库存与已有导购/提案确认链。候选读取本身不记曝光或扣费；素材/活动版本变化、暂停、售罄或预算不足会拒绝旧曝光并要求刷新。

广告候选接口只提供展示和排序，不授予模型、用户或前端执行权；管理端的首次授权、启停、素材替换、Merchant规划和动作回执仍是唯一经营写入口。真实前后端纵切见 `artifacts/final-b45dbe1e6bdf4f7dabf794448613b223.json`（历史demo证据，模拟支付/广告费用，无收益结论）。

## 当前商城首页与广告位接线

根路由 `/` 由 `StorefrontView` 提供自然访问入口；页面并列读取普通推荐和广告候选。普通推荐仍走 `GET /api/assistant/recommendations`、`AgentProductList` 及 `REC_IMPRESSION/REC_CLICK`，广告走 `GET /api/assistant/ads/recommendations`，仅展示当前scope有效grant、ACTIVE活动/素材、余额和Java逐SKU库存均满足条件的候选。候选读取没有曝光或扣费副作用。

`PromotionCard`在卡片至少50%可见且文档可见时提交带活动/素材版本的 `/api/assistant/ads/exposures`；服务端返回持久曝光回执后才提交 `/api/assistant/ads/clicks`，CPC与`AD_CLICK`在Growth事务内记账。版本变化、暂停、售罄或余额不足会清晰要求刷新，不把失败写成归因成功。广告卡点击沿已有商品详情、SKU核对、提案和用户确认流程。商家仍在独立管理端处理活动/授权、经营观察/规划与执行；下一轮流量由真实商城展示产生或由演示脚本驱动，尚无后台自动调度。

## F3 用户端推荐与触点接线

F2 检查点为 `1fb74da`。本节为后续 F3 前端接线，服务端归因/真实浏览器验收由根阶段单独记录，不把下面的模拟 HTTP 测试当作 F3 全链路通过。

| 入口 | 实际浏览器行为 |
|---|---|
| `POST /api/assistant/traffic/landing` | App 完成可信 session 后调用，每个浏览器文档仅生成一个 UUID，body 只有 `entry_id`；组件重挂、focus 和账号切换不重复创建页面访问。URI 中的 source/campaign 等不参与请求，不由前端把访问改成广告。 |
| `GET /api/assistant/recommendations` | Catalog 传用户明确填写的 query/可选最高单价整数分，limit=8；只显示此接口返回的真实 SKU 列表和服务端推荐/分桶/策略/排序凭据。失败清空推荐并说明，没有旧静态 commend 列表兜底。 |
| `POST /api/assistant/recommendations/{id}/exposures` | 聊天和 Catalog 共用 `AgentProductList`；原生 IntersectionObserver 确认可见比例至少 50%，且 document 处于 visible 后，提交该服务端推荐下的 `positions`。没有 observer 或推荐凭据时不捏造曝光。相同卡片的重复/并发回调抑制，服务端继续负责持久幂等。 |
| `POST /api/assistant/recommendations/{id}/clicks` | 仅用户点击卡片后提交服务端 `position`，先短超时登记再导航；重复进行中的点击只提交一次。失败仍允许查看商品，前端不声明已归因，也不补造自然来源。 |
| `POST /api/assistant/traffic/bind` | Java 登录后携当前 cookie 和新 CSRF，body 严格为 `{}`；只在服务端证明已绑定且 conversation_ids 含登录前当前会话时恢复原 ID。不会提交 visitor/user ID 或重分实验组，也不会恢复列表中无关会话。 |

触点写请求仅带服务器 recommendation_id/position 或页面 entry_id，不传用户、发生时间、价格、广告标识或报价 context token。自然访问/曝光/点击/绑定请求使用 2 秒总上限，包含 CSRF 会话核对；不可用不阻断交易。推荐 GET 使用独立 30 秒上限。用户数量、预算和交易绑定参数仍经原确认链，前端不把归因凭据发送给模型。

当前 `tests/recommendation.test.ts` 验证可见/隐藏状态、50% 门槛、服务端位置、回调/双击去重、触点失败仍浏览、无凭据不伪造、当前 cookie 绑定与会话授权、推荐失败不回退及整数分输入；完整用户单测最终为 23 项（含后续会话并发/身份恢复回归，F2 的 14 项保留）。其中测试实际发现 Vue 原生 number 输入会返回数字，使 `.trim()` 失效；已在推荐最高单价和同类购物偏好输入处先规范化文本，再按整数字段解析，保留精确金额和输入校验。没有引入依赖、用户画像本地持久化或广告 UI。当前构建/测试结果记录为 `artifacts/f3-ui-contracts.json`，真实可见性和归因已经分别通过 `artifacts/f3-browser-recommendations.json` 与 `artifacts/f3-live-attribution.json` 核对。

## F2 用户端实际交付

| 范围 | 当前实现与验证边界 |
|---|---|
| 源码和依赖 | 从已核验前端 ZIP 选取 20 份源文件适配聊天、卡片、金额、布局和样式；来源 MIT 许可保留。旧锁离线裁剪为 253 个节点，当前平台实际安装 216 个依赖包；保留节点版本变化和新增发行包均为 0。没有旧实例、旧 WS/Java AI、PWA 或真实支付路径。具体复用及未迁入功能见 [`web/user/SOURCES.md`](../web/user/SOURCES.md)。 |
| 用户入口 | `/assistant`、`/catalog`、`/orders`、`/preferences`、`/login`。PC/移动端共用响应式 Vue 页面；普通登录继续 Java 邮箱/密码/图片验证码和 HttpOnly cookie。演示身份由受保护的 Java 合成数据入口准备，没有公开无密码登录后门。 |
| 会话与 SSE | 消息先返回 RUNNING，再消费持久化工具进度及经过验证的正文。按会话/运行/序号去重；断流最多 3 次只读恢复，单连接最多 100 秒。刷新读取会话、运行、当前提案；已保存 proposal 即使其 run.result 未提交或 run 已 FAILED，也按原运行恢复显示。浏览器只保存按主体隔离的 conversation ID，不缓存聊天或批准结果。 |
| 知识与人工客服 | 引用显示文档、版本、切片和原片段；点击来源重新 GET 当前 published/ACL 过滤的文档。撤回后的片段标为历史引用，不能冒充当前知识。Markdown 禁止 HTML、模型链接及远程图片。人工接管时禁用 AI 输入和交易确认，刷新显示人工消息；接管状态以当前服务器记录为准。 |
| 商品与交易确认 | 商品、SKU、数量、库存和报价均沿 Java 事实链。Catalog 规格名从 Java 属性 ID 映射；下单确认卡只读补商品名、规格和本人收件信息，金额仍用原绑定提案。退款/取消按原提案查询 `/proposals/{id}/display`，仅显示 Java 固化的已购商品和规格，不使用模型文本，也不重新估算退款。编号、原始时间、报价和版本保留在展开凭据区。 |
| 过期及恢复 | 截止时间显示浏览器本地日期和时区。PROPOSED 到期后禁用确认并引导用户重新咨询生成提案；点击仍检查当前时间，后端继续做权威有效期校验。已批准动作不因原 TTL 到期而失去原决定/幂等键的恢复能力。受理、待定、订单创建、付款和退款终态分别展示。 |
| 本人订单与付款 | 订单读取 Java 公开本人接口；模拟付款在独立金额对话框中由用户点击，发送所见整数分，由服务端复核归属/金额。只有 `commandStatus=business_completed` 才显示付款完成；订单创建不表示付款成功。 |
| 偏好和账户隔离 | 本人偏好 GET/PUT/DELETE 已接；访客不写长期偏好。AI 写操作先刷新主体和 CSRF，账号变化拒绝旧页面写入。交易对象/地址补充查询只用于 UI，异步结果需主体和当前提案一致，失败显示待核对；不向模型发送详细收件信息。 |

统一适配层为 `web/user/src/api/client.ts`：Java 使用 `/api` 与 ResponseVO，AI 使用 `/api/assistant` 原始 JSON；没有内部 token、业务认证密钥或模型 key。F2 实际合同在 `growth/src/smartlect/app.py` 和 [`contracts.md`](contracts.md)，不再沿用旧 Java `/agent/*`。

运行由根 `scripts/dev.sh` / `runtime.py` 管理 `web-user`，Vite preview 只监听 `127.0.0.1`，采用 `SMARTLECT_WEB_USER_PORT` 和 `SMARTLECT_GATEWAY_URL`，端口冲突退出。构建命令为 `npm ci --ignore-scripts`、`npm run test`、`npm run build`（含 `vue-tsc`）；入口及单独构建说明见 [`web/user/README.md`](../web/user/README.md)。不复用其他项目或任意已有浏览器服务。

本地 UI 契约测试覆盖：确认版本/双击/CSRF、变价重确认、过期禁确认与已批准恢复、原始提案和空 run.result 恢复、SSE 重放、人工接管、引用撤回、安全 Markdown、Java ID 展示映射及失败不伪造、跨账户异步隔离。最新可运行结果为 [`f2-ui-contracts.json`](../artifacts/f2-ui-contracts.json)，详细构建日志在 Git 忽略的 `artifacts/local/f2-user-build.log`。这些是 mock HTTP 的前端契约检查；真实模型能力不由它们证明。根浏览器验收已记录合成用户的真实模型下单、单独模拟付款、过期退款拒绝、新退款确认和终态恢复；本次最后的展示/到期修正仍须由根任务重新加载新构建复核。

## F4 管理端已迁入，联验状态另记

`web/admin` 使用冻结管理端 Vue/表单/布局/价格与权限结构，原锁离线裁剪，保留节点无版本漂移、无新增发行包；实际取材与许可证见 `web/admin/SOURCES.md`。管理端通过Java验证码登录、cookie身份与Growth CSRF接活动/素材草稿、审批资源版本/envelope/plan快照、两级启停恢复、整分预算、素材替换及动作前后值/拒绝原因/库存观测；刷新只读取服务端。知识版本读取/草稿/发布/撤回与人工工单接管/回复/结束也已接现有API；完整人工会话详情待F6。

管理端端口默认18181，入口 `/admin/`，与用户端一样由本项目 runtime 监管。F4 npm构建和UI契约已实际执行，浏览器与全链路门禁尚在联验，最终成绩以实施状态及f4 artifacts为准。

## F0 冻结输入与原接入计划（历史记录）

以下记录保留 F0 的原始输入、锁哈希和当时的接入计划；其中“尚未迁入/待 F2/本次未构建”均指 F0 当时，当前进展以上述 F2/F4 状态为准。

核对时间：2026-09-09。来源固定提交：`94d36aee925c75d286f48d2aee2eeea059a74dd9`。本次只通过 `git ls-tree` / `git show <sha>:<path>` 读取已提交对象；未读取旧 `.env`、未使用旧工作树源码或运行旧程序。正式导出范围、文件数与 ZIP 哈希以 `handoff/integration-manifest.json` 为准。本文是 F0 输入核对和 F1–F6 适配计划，不代表前端已经迁入或通过运行验收。

## 已确认目录与冻结范围

| 用途 | 所选提交的实际目录 | 后续迁入位置 | 原目录文件数 | 实际冻结文件数 |
|---|---|---|---:|---:|
| 用户端 | `AI_Shop-front/AI_Shop-web/` | `web/user/` | 341 | 277 |
| 管理端 | `AI_Shop-front/AI_Shop-admin/` | `web/admin/` | 156 | 148 |
| 项目许可证 | 根 `LICENSE.md` | 随冻结包保留；应用分发时保留声明 | 1 | 1 |

已导出的 `handoff/sources/shop-frontends.zip` 共 426 个文件，SHA-256 为 `7be44cae181067e4e4d993b25e56bbb9813656da8eb22619895d334561933da2`。实际白名单由 `handoff/freeze_integration.py:group_for` 决定，包含以下输入，保留旧名称用于来源核验；F2 在应用副本里改为 Smartlect：

- 两端 `src/**`、`tests/**` 的文本源码，允许扩展名 `.vue/.ts/.js/.mjs/.json/.css/.scss/.svg`；两端 `package.json`、`package-lock.json`、`index.html`、`eslint.config.mjs`、`vite.config.*`、`vitest.config.*`。
- 用户端 `tsconfig.json`、`tsconfig.app.json`、`tsconfig.node.json`、`postcss.config.cjs`、`playwright.config.ts`；管理端 `jsconfig.json`。
- 两端仅 `scripts/check-bundle-budget.mjs`；F0 不执行。未复制用户端 `scripts/generate-pwa-assets.mjs` 和 `scripts/deploy-web.sh`。
- 两端 `README.md` 作为来源说明保留，其启动/部署命令不成为 Smartlect 命令；两端整个 `public/` 均未复制，包括 `public/*.svg`。

排除 `.git`、`.env*`、`node_modules`、`dist`、覆盖率/测试报告、运行数据、日志、证书、用户上传、缓存和外部软链接；排除用户端 `scripts/deploy-web.sh`。排除整个 `public/simlect-origin/`：其 README 指向第三方 `id88/taobao` 静态页面，含旧品牌、二维码、商城参考图片，业务主线不需要它。

最初未提交的导出候选选入了 6 份二进制素材，经 F0 审查后收紧为纯文本白名单并重导出。最终包排除用户端 `src/assets/hero.png` 和管理端 `src/assets/avatar.png`、`src/assets/left-side-bg.png`、`src/assets/loading.gif`、`src/assets/login-bg.jpg`、`src/assets/icon/iconfont.ttf`。`public/favicon.ico`、生成的 PWA 图片和 `startup-links.html` 也未冻结。F2 清理这些 import/CSS 引用，使用现有 Element 图标、CSS 或 Smartlect 自有素材。

F2 必须删除或替换 `package.json` 中指向未冻结 PWA 生成器/部署脚本的命令，并调整 `index.html`/Vite 的旧 `public/` 引用；默认以 Smartlect SVG 图标即可满足界面入口。只有实际需要 PWA 安装能力时再在本项目内生成素材。上述是后续适配建议，当前冻结包不是可直接启动的应用。

## 依赖锁定

两端均为 npm `lockfileVersion=3`，保留各自完整锁文件；不合并锁、不顺手统一 Vite 主版本。精确版本来自锁文件，而非 `package.json` 的范围。

| 依赖 | 用户端锁定 | 管理端锁定 |
|---|---|---|
| Vue | 3.5.35 | 3.5.30 |
| Vite | 8.2.0 | 7.3.6 |
| `@vitejs/plugin-vue` | 6.0.7 | 6.0.5 |
| Pinia | 3.0.4 | 3.0.4 |
| Vue Router | 4.6.4 | 4.6.4 |
| Element Plus | 2.14.0 | 2.12.0 |
| Axios | 1.19.0 | 1.19.0 |
| TypeScript | 6.0.3 | JavaScript 应用，无直接 TS 依赖 |
| Vitest | 4.1.10 | 4.1.10 |
| `@vue/test-utils` | 2.4.11 | 2.4.11 |
| Playwright | 1.61.1 | 无直接依赖 |

用户端锁记录 803 个包节点，SHA-256：`2f86e74fb61cb39f8215d87e591cce53b824a9aa80f39f7ceb3cea79747e7cc6`。
管理端锁记录 557 个包节点，SHA-256：`c0c2333b3e8a1fe182eaf6dd7014ed8671f96043ba5ffaba28c26e82a1067aae`。

两端 Vite/plugin-vue 锁定条目的 Node engine 均为 `^20.19.0 || >=22.12.0`；官方 Vite 文档也列出 20.19+/22.12+ 要求。当前 Smartlect 环境实查 Node `v25.9.0`、npm `11.12.1`，满足这些最低约束；这只是环境核对，不是安装或构建验证。[Vite 官方要求](https://vite.dev/guide/)

F2 从已迁入的 `web/user`、`web/admin` 分别执行 `npm ci`，使用锁定树。锁与清单不一致时 `npm ci` 会失败，不会替用户重写锁。改应用名称时同步锁根项目名称；只在确有依赖改动时更新锁并重跑本端检查。[npm ci 官方合同](https://docs.npmjs.com/cli/v11/commands/npm-ci/)

来源根许可证是 MIT，版权声明 `Copyright (c) 2026 Audreator`，冻结包保留原文。依赖许可证另按包处理：两锁包含 MIT、ISC、Apache-2.0、BSD 等；用户端还记录 LGPL-3.0-or-later、MPL-2.0、CC-BY-4.0 等许可证，包括图像生成依赖链。不能将根 MIT 声明写成所有第三方素材/依赖都是 MIT。F2/F7 安装后保留实际使用依赖的许可证，排除未使用的旧参考页面和媒体素材。

## 复用判断与前端 API 适配表

| 旧入口 / 组件 | 判断 | Smartlect 接入合同 / 阶段 |
|---|---|---|
| 用户端商品、SKU、购物车、订单页面；`src/api/modules.ts` 的 `orderApi` | 适配复用 | 继续现有 Java `/api/product/**`、`/api/order/**` 等公开路由，保留已修金额、库存、幂等语义；F2 回归普通购买路径。AI 下单必须走 F1 报价绑定入口，不调用旧 `postOrder` 绕过确认。 |
| `AIAssistantView.vue`、`PcAIAssistantView.vue`、`PcAgentFloatingPanel.vue`、`AgentChatItem.vue`、商品/订单/确认卡 | 适配复用 | 保留双端布局与结构化卡片，F2 接 Shopping 会话；新增可定位文档版本/切片的引用展示及无答案/转人工状态。模型文字不能成为库存或交易成功判定。 |
| `src/api/http.ts`、`src/api/modules.ts` | 适配复用 | 用户 Java 请求继续 `/api`、cookie 凭证及 `ResponseVO` 解包；新增一个 AI API 适配区，匹配 F1 最终 OpenAPI。FastAPI 错误不得被误当作 Java `code=200` 响应。限制会话恢复重试，不能自动重放非幂等写入。 |
| `useAgentSession.ts`、`utils/websocket/*`、聊天发送/状态逻辑 | 替换 AI 传输 | 旧流程为 `/agent/sendMessage` + WebSocket；改为创建会话、幂等消息提交、`runs/{id}` 查询与 SSE。普通站内通知若仍使用 Java WebSocket，可单独保留，不恢复旧 Java AI 服务。 |
| `agentApi.confirmAction(actionToken)`、`AgentConfirmCard.vue` | 适配，必须修状态语义 | 接 `POST /api/assistant/proposals/{id}/confirm`，发送 `proposal_version`、确认/拒绝与 CSRF；SKU/金额取服务端原提案。旧组件会将任意 `success=true` 覆盖为 CONFIRMED 并提示“操作成功”，F2 必须按 proposal/operation/business 状态展示受理、执行中、核对中、业务终态。 |
| `agentV1Api.recommend`、`recordEvent`、`reportAgentProductClick`、`recommendationAttribution.ts` | 替换旧归因合同 | F3 接已签发 receipt 与服务端时间；旧 sessionStorage 的 7 天推荐缓存、浏览器 `Date.now()` 时间戳和 `userId` 字段不是可信归因。新推荐 24 小时、广告 7 天，各自独立展示和传递。 |
| `MarkdownContent.vue` | 适配复用 | 保留 `markdown-it` 的 `html:false`；引用及商品跳转来自受校验的结构化数据；检索文本/模型输出不执行脚本或动态组件。 |
| 用户 `ShoppingProfileView.vue`、`SupportCasesView.vue` | 适配复用 | 偏好按本人读写/删除，服务端 revision 与作用域；工单与人工接管在 F6 接完整流程。旧浏览器缓存键改 Smartlect，并隔离用户/访客切换。 |
| 管理 `src/utils/Request.js`、`Api.js`、`adminAccess.js` | 适配复用 | 统一 `/admin-api`；原 Java 管理接口继续使用；新增经营与知识入口映射 F1 合同。浏览器权限只决定展示，Java/Growth 服务端验权。不能由前端生成内部管理员断言或携带模型 key。 |
| 管理 `views/setting/Rag.vue`、`RagEdit.vue`、`utils/knowledgeUpload.js` | 适配复用 | F2 接文档草稿/版本/发布/撤回/ACL；旧 `/rag/*`、`/knowledge/*` 服务尚未存在，不能原样启用路由就声称知识库接通。 |
| 管理 `views/data/DataAnalyst.vue`、`components/AgentEvidenceReview.vue` | 页面适配，查询合同替换 | F5 显示 evidence_id、观测时间、计划版本和经营诊断；旧 dataAnalyst 接口不直连任意 SQL。新增目标/计划/授权 envelope/动作回执页，复用既有表格/表单组件。 |
| 管理 `AgentQualityCenter.vue`、`AIEvidenceCenter.vue`、人工客服页面 | 适配复用 | F6 读取本项目 trace、案例、成本和评测；live/mock/rule-fallback 分开，不能展示旧项目试用/收益数据作为 Smartlect 成绩。 |
| 管理在线 Prompt 修改、旧同步失败补偿页、`OperateTools.vue` 的导入/重建操作 | 不迁入运行功能 | 本版 Prompt/Skills 由 Git 版本化；不恢复旧 Java search/AI/RAG 启动链、清库/索引工具或旧试点管理流程。可冻结来源源码，但不注册可操作菜单。 |
| 真实支付宝跳转及旧部署脚本 | 不迁入运行路径 | 本版 UI 仅允许 Smartlect 模拟支付；不提供真实支付入口，不触发外部部署。 |

F1 应把上表新 API 的最终路径和响应 schema 写入统一合同；上表沿用 HANDOFF 拟定路径，当前不是已上线 API 列表。

## 运行配置与验收约束

旧用户端 Vite 默认端口 6001，普通 API 指向 6050，Agent/WS 指向 7050，`host:true` 并允许 trycloudflare 域名；旧管理端默认 6002、API 指向 8080、监听 `0.0.0.0`。F2 全部改为 Smartlect 启动器分配的 loopback 端口，普通及 AI 请求经本项目 Gateway/可信会话桥；不复用原实例。管理端 `base:'/admin/'` 可保留，但开发和构建必须统一 API 前缀。

SSE 消费 `message_delta/tool_started/tool_result/proposal_required/operation_pending/completed/error`，按 `agent_run_id`、`conversation_id`、序号去重；重连只恢复展示与查询，不重新提交已确认动作。刷新后从服务端恢复会话/提案，sessionStorage 不是确认、金额或身份的事实来源。

原 Playwright 配置会在非 CI 模式 `reuseExistingServer:true`，且可接外部 `PLAYWRIGHT_BASE_URL`。F2 改为验证 Smartlect 进程归属，不能碰巧复用旧端口上的应用；UI 检查使用自有合成用户/商品/订单。

保留原测试文件作为待适配输入，不把旧测试记录作为当前成绩。F2 至少实际验证：两端独立 `npm ci`、构建/类型检查、保留测试适配后的运行结果；用户会话隔离、引用跳转、确认后变价、提交/刷新/重连不重复写入、退款受理与确认退款分离。F4/F5 再验证预算/授权/计划页面；F6 补桌面和移动端完整三场景。当前 F0 未执行这些检查。

本次实际检查：最初旧三份冻结包校验 12 项通过；最终 `python3 handoff/verify_package.py` 五份包共 14 项通过，前端 ZIP/manifest 426 文件与两份锁哈希一致，且无 `public/`、PWA 生成器或二进制媒体；固定 Git 对象目录/锁文件/主要 API/卡片/路由只读核对；Node/npm 版本查询；Vite/npm 官方文档核对。没有执行前端安装、旧脚本、业务测试或真实模型调用。
