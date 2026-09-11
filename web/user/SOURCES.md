# Smartlect 用户端取材与适配

来源仅为本仓库 `handoff/sources/shop-frontends.zip`，校验通过后按白名单读取；未读取原工作区或 `handoff/extracted`。固定提交 `94d36aee925c75d286f48d2aee2eeea059a74dd9`，包 SHA-256 `7be44cae181067e4e4d993b25e56bbb9813656da8eb22619895d334561933da2`。原前端路径 `AI_Shop-front/AI_Shop-web/`。应用构建与运行仅使用 `web/user` 中的源码与 npm 锁。

保留来源根 MIT 许可及 `Copyright (c) 2026 Audreator`，见 [LICENSE.md](LICENSE.md)。此声明不替代各依赖包自身许可证；安装后的依赖声明随各包保留。源包中来源未明的二进制图片、旧 `public` 媒体均未迁入；当前标志为本项目简单 SVG 源码，商品图缺失显示原 Element 图标占位，不伪造商品媒体。

## 实际复用

下表是运行源码的真实来源，非只冻结即算完成。相同相对路径即原前端文件名。

| 来源 | 适配后保留的实际部分 |
|---|---|
| `src/components/agent/AgentChatItem.vue` | 回复气泡、头像、商品/订单/确认卡组合、来源折叠面板及对应样式；替换旧消息解析器，读取结构化 `Run.result`。 |
| `src/components/agent/AgentConfirmCard.vue` | 确认卡的标题/明细/金额/状态/操作布局及样式；完整替换 actionToken/数值状态协议，改 proposal version、CSRF、原决定恢复及 Java 业务终态。 |
| `src/components/agent/AgentProductList.vue` | 网格商品卡及价格/库存/点击布局；删除旧客户端归因与图片识别/比较逻辑，读取真实商品与 SKU 字段，跳转本项目商品页。 |
| `src/components/agent/AgentOrderList.vue` | 原订单和订单明细结构及样式，读取已有 Java 本人订单响应；订单状态映射保留。 |
| `src/components/agent/AgentUserBubble.vue` | 用户气泡和文本样式；不迁入图片上传/商品咨询隐式解析。 |
| `src/components/common/MarkdownContent.vue` | `markdown-it` 与正文排版样式，继续 `html:false`；另外禁用模型文本中的链接和远程图片，知识引用单独结构化显示，并从受 ACL/发布状态控制的文档接口重新核对来源。 |
| `src/components/common/ProductImage.vue` | 原 Element 图片/占位图标及尺寸布局，限定本项目媒体路由。 |
| `src/components/business/OrderAmountSummary.vue`, `src/utils/orderAmount.ts`, `src/constants/backendEnums.ts` | 已有订单金额/优惠展示及 Java 数值状态映射；优惠标签导入改为已有枚举。 |
| `src/views/pc/PcAIAssistantView.vue`, `src/views/agent/AgentChatList.vue`, `src/views/agent/AgentSendPanel.vue` | 继续页面→聊天列表→输入面板的组件结构，保留快捷问题、原生输入框和气泡组合；传输改 SSE/持久化查询，保留输入法组合键保护。PC 与移动端共用一份响应式页面。 |
| `src/styles/variables.scss` | 原配色/间距/字体/圆角 tokens；新增应用 shell 适配本项目路由和较窄屏幕。 |
| `package.json`, `package-lock.json`, `tsconfig*.json`, `src/vite-env.d.ts` | 保留 Vue 3 / Vite 8 / Element / TypeScript 构建方式及锁定版本，名称改为 Smartlect。 |

共选入 20 份源文件及 MIT 许可后适配。新增统一 `api/client.ts`、会话恢复 composable、应用 shell、商品/订单/登录/偏好页面与回归测试。没有另一套 UI 框架、全局通用状态平台或自制 Agent 编排。

## 有意不迁入

- 旧 Java AI `/agent/*`、WebSocket、旧用户/设备/消息全局 stores、在线 prompt、旧实例/端口、原外部部署和 PWA 路径。
- 真实支付渠道、二维码支付、支付宝跳转、客户端推荐归因时间/用户标识与原有业务 token。
- 会员/签到/图片编辑/地理天气/复杂全站导航等当前阶段无关界面；它们仍在冻结包中供后续有必要时取材，未建立空可点击菜单。
- 旧测试留在冻结包，不把未迁入旧测试计为当前测试。与已采用组件相关的确认终态、消息重放、结构化卡片安全呈现用本目录当前 `tests/assistant.test.ts` 适配验证；没有删除原项目或本仓库已有业务测试。

去除无调用的图片编辑、支付、PWA、部署、eslint 等直接依赖并离线修剪原锁，803 个包节点缩至 253（当前平台实际安装 216 个依赖包）；保留节点版本变化为 0，新引入发行包为 0。未升级 Vue/Vite，不保留指向缺失脚本的命令。

## 接线及边界

- Java 公开 API 使用 cookie + `ResponseVO` 解包；AI API 使用原始 JSON、cookie、当前会话 CSRF，前端没有内部 token 或模型 key。每次 AI 写请求重新核对主体，账户切换拒绝旧页面写入。
- 商品和订单来自 Java；普通商品页亦生成 F1 报价确认卡。商品/规格展示从当前 Java productInfo 与 propertyValues 按原 ID 映射，确认卡收件人与地址仅从本人地址列表匹配后展示，不发给模型、不改原报价或参数；读取失败显示待核对且不能批准新下单，身份变化丢弃旧异步结果。退款/取消另按原提案的受保护 display 接口读取 Java 已购明细，展示固化商品名与规格，不分页查找、不用当前价格改退款金额。编号/版本保留在可展开凭据区；有效期显示本地日期和时区，PROPOSED 到期禁确认并引导重新提案，已确认动作保留原决定恢复。卡片不接受浏览器修改报价/SKU/金额。确认接口只发送所见 `proposal_version` 与明确决定；受理和业务完成分别展示，订单创建不代表付款成功。
- 模拟付款只有在本人订单的金额确认对话框中点击后，发送 `expected_amount_cents`；服务端复核金额和归属，UI 只以业务回执判终态，不由模型回复推断。
- 消息先返回 RUNNING，UI 消费持久化工具进度和经验证的正文；断流最多 3 次只读恢复，单连接最多 100 秒。刷新使用 GET 会话/运行/当前提案和 SSE 回放；事件按 conversation/run/sequence 去重；不会自动重新下单或批准。网络失败后的消息重试需用户点击且保留同一个 message ID，未知交易保留原提案和决定版本。
- 恢复同时读取会话的当前 proposals，按原 agent_run_id 挂回卡片并按版本拒绝旧快照覆盖；进程在提案已保存、运行 result 尚未保存时中断，也不会丢失已保存提案。人工接管期间交易确认按钮不可用。
- 浏览器仅持久化主体隔离的最近 conversation ID，不保存聊天、偏好正文、金额或批准结果。会话和确认事实重新向服务端读取。
- 偏好页面接当前本人 `GET /preferences`、`PUT /preferences/{key}`、`DELETE /preferences/{key}`。访客不写长期偏好。RAG 引用显示文档/版本/切片和片段，不将任意模型 URL 当来源；查看来源时重新校验 published/ACL，已撤回文档的片段明确标为历史引用。
- 已接本人/访客明确转人工按钮与当前 handoff 状态；人工接管时禁止继续 AI 输入，刷新能显示无 agent_run_id 的人工回复。已关闭状态由服务器返回，不能根据历史工单快照自动恢复。

当前独立验证：`npm ci --ignore-scripts`、`npm run build`、`npm run test`（14 项）通过；浏览器真实服务检查由根任务统一执行，不能把这些 mock HTTP 的 UI 契约测试称为模型或交易 live 验收。构建首次 TypeScript 参数属性不符合冻结 `erasableSyntaxOnly` 已改普通字段；Node 25 ambient Web Storage 与 jsdom 冲突导致首轮 7 项启动失败，测试明确使用 jsdom 的 Storage 后全通过，没有跳过测试。

F3 在 F2 检查点 `1fb74da` 上继续：复用同一商品卡加入原生 IntersectionObserver 可见曝光和显式点击；Catalog 改用真实推荐 API，携服务器 recommendation_id/position，所有归因来源/时间/身份/分桶由服务端决定。新增 `src/api/traffic.ts` 处理每文档一次自然入口、当前 cookie 登录绑定及 2 秒有界触点请求，未增加依赖或广告界面。`tests/recommendation.test.ts` 另加 8 项，当前用户测试合计 22 项；原 F2 测试和归档 `f2-ui-contracts.json` 保留，F3 新证据写 `f3-ui-contracts.json`。当前测试模拟 HTTP 与可见性，不能替代浏览器和账本真实联验。详细接线见根 `docs/frontend-integration.md` 的 F3 小节。
