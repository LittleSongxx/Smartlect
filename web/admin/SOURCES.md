# Smartlect 管理端取材与适配

唯一取材输入为本仓库 `handoff/sources/shop-frontends.zip`，读取前执行 `python3 handoff/verify_package.py`，14 项校验通过。固定提交 `94d36aee925c75d286f48d2aee2eeea059a74dd9`，冻结 ZIP SHA-256 `7be44cae181067e4e4d993b25e56bbb9813656da8eb22619895d334561933da2`，来源目录 `AI_Shop-front/AI_Shop-admin/`。没有读取原项目源码目录、旧配置或 `handoff/extracted/`；未打开 RAG 留出数据。

来源根 MIT 许可证及 `Copyright (c) 2026 Audreator` 完整保存在 [LICENSE.md](LICENSE.md)。各 npm 包自己的许可证随安装包保留，此根许可不替代第三方依赖许可。

| 冻结来源 | 本项目实际使用 |
|---|---|
| `src/views/account/Account.vue` | 管理登录的双栏品牌/表单结构、账号/密码/图片验证码字段、验证码刷新、移动端单栏布局；替换为原生表单和本项目 Java POST 请求，加入单次提交保护，移除旧备案/品牌及全局 proxy。 |
| `src/views/Layout.vue` | 侧栏导航、顶栏账号操作、主内容区域及响应式布局；菜单只注册已接通的活动/授权、知识、人工客服。 |
| `src/components/Price.vue` | 货币符号/整数分金额布局；移除全局 Utils、路由和未用状态，复用本地精确分格式化。 |
| `src/utils/adminAccess.js` | 保留标准化权限数组和权限包含判断；仅控制展示，服务器仍逐请求认证验权。 |
| `package.json`、`package-lock.json` | 使用管理端自身锁定的 Vue 3.5.30、Vite 7.3.6、plugin-vue 6.0.5、Vitest 4.1.10、vue-test-utils 2.4.11；名称与 scripts 改为 Smartlect。 |

API 适配参考本项目已有 `web/user/src/api/client.ts` 的 Java/原始 JSON 分离、cookie、CSRF、身份隔离模式，管理端无用户端的访客身份或交易确认入口。新增活动、授权与动作页面采用当前 F4 合同；知识与人工页面直接使用已存在服务端合同。所有源码现在位于本目录，构建不引用另一前端或冻结 ZIP。

移除未调用的 Element、图表、图片编辑、Markdown 编辑器、全局 stores、旧 WebSocket、旧 AI/Prompt/自由 SQL/清库/部署/真实支付入口；不迁入未冻结媒体。样式沿冻结管理端表单/工作台布局适配，本项目界面未新增依赖。favicon 复用当前 Smartlect 用户端自有的简单 SVG，独立复制到本目录；真实浏览器最初发现默认 `/favicon.ico` 404 后补齐，不引用用户端运行资源。

依赖锁用现存冻结条目离线裁剪：558 个节点（含根）缩到 204 个节点（含根），保留条目版本变化 0、新增发行包 0；当前平台 `npm ci --ignore-scripts --no-audit --no-fund` 实际安装 154 个包。没有合并用户端锁或升级管理端 Vite。旧测试仍在冻结包中，当前业务交互由本目录 `tests/admin.test.js` 实际验证，旧成绩不计入本次结果。

本次实际检查：独立 npm ci 成功；当前 11 项模拟 HTTP 契约测试通过；Vite production build 成功。测试涵盖验证码登录字段/POST/双击、merchant CSRF/账号切换/失效、整数分、明确审批及版本绑定、DRAFT 不隐式启用、动作的原版本与幂等重试、拒绝后保护暂停刷新、安全文本显示、人工回复版本冲突与独立知识发布确认。真实浏览器/Java/MySQL/经营闭环验证由根任务另记，不能将本目录单测写为 live 能力验收。

授权审批携 `expected_campaign_versions` 和 `expected_creative_versions`，精确绑定本次产品范围下当前商家拥有的资源；完整范围与活动/素材内容可以在审批前展开核对。服务器回执中的 `envelope_hash`、`plan_snapshot_hash`、前后值均原样展示。累计账户跨计划、轮次和新授权保留，界面不生成可清零累计预算的配置。知识原文通过 merchant 权限的管理 GET 重新读取，发布选择绑定具体版本；人工完整上下文详情将在 F6 接入。

F5 在同一冻结 Vue/锁基础上新增 `MerchantView.vue`，沿用本项目表单、状态和安全文本呈现：观察/诊断/计划、实际模式与模型尝试、有限只读查询、授权执行/恢复和人工经验审批。App 增加服务端成员资格内的经营范围选择，切换重建各页面；共同 client 用含 scope 的主体键和 epoch 隔离在途响应。AdsView 增加真实目录选择、绑定 Merchant 计划的明确审批，以及可见的推荐策略范围。没有新增 npm 依赖、Agent 框架或浏览器长期状态库。

本次 F5 实际运行 `npm run test` 共 19 项通过（原 F4 11 项保留，新增 8 项经营/范围契约）；`npm run build` 成功。新增检查覆盖实际降级模式与未知 usage、不确定运行的原键重试/无新观测等待、仅 GET 的运行轮询、计划执行版本及不自动批准、Merchant 计划绑定审批、经验显式认可、真实 catalog SKU 填充、切换 scope 时旧请求失效与清空旧表单。F5 当前为 mock HTTP 契约证据，没有重用 F4 的真实浏览器成绩作为 F5 live 成绩。
