# Smartlect 管理端 / 商家后台真实使用测试

- 时间：2026-09-17
- 入口：`http://127.0.0.1:18181/`（302 到 `/admin/`，哈希路由）
- 账号：`admin`（密码来自 `run/runtime.env`，未写入仓库、未打印全文）
- 方式：真实 Chromium 按运营日常顺序打开各页；点刷新/搜索/详情/预览；写操作仅取消或只读
- 约束：未 git commit、未重启整栈、未改功能
- 接口：抽查 `/admin-api` 与 `/api/assistant`。本轮助手流量全部走 `/admin-api/assistant`，未观察到 `/api/assistant`
- 截图：`/tmp/smartlect-qa-admin-run/shots/`
- 原始观察：`/tmp/smartlect-qa-admin-run/raw.json`

通过项（不单独开单）：登录 toast「登录成功」可读；刷新 `#/home` / `#/ai/tools` 不掉登录；退出回到 `#/login` 后再登入成功；分类/属性/订单/用户/优惠券/签到/会员礼券/经营助手/活动/知识库读取/模型/提示词/运行浏览器/工具调试台主列表均可打开；敏感词「刷新缓存」toast「缓存已刷新」。

---

## A-01

- 严重度: high
- 页面 hash URL: `#/setting/logistics`，连带 `#/order/orderList`
- 复现步骤:
  1. 登录后打开 `#/setting/logistics`
  2. 打开 `#/order/orderList`，点今日待发货订单「确认发货」（例：`20260917173547675LUZDbhsTQCGsVSL`）
- 期望 vs 实际:
  - 期望：发货地址已配置，发货弹窗自动带出发件人/电话/地址
  - 实际：`POST /admin-api/setting/getLogistics` 200，`data: null`，表单三个字段都是空占位；发货弹窗收件人有值，发件人/电话/发货地址为空（必填）
- 证据:
  - 截图 `logistics.png`、`order-ship-dialog.png`
  - `POST /admin-api/order/getLogistics` 200，`senderName/senderPhone/senderAddress` 均为 null
  - 侧栏无「发货地址」入口（见 A-09）
- 是否挡住商家日常: 是。今日已有待发货单，不先手输 hash 填发件信息就无法完成发货。

## A-02

- 严重度: high
- 页面 hash URL: `#/product/updateProduct/917186661226040`
- 复现步骤:
  1. 打开该商品编辑页，等待基础信息与「导购可见性」
  2. 查看品牌、卖点/用法/成分/包装/禁忌/售后备注
- 期望 vs 实际:
  - 期望：已有商品带品牌与 `content_json` 内容轴；导购可见性为已投影或至少有索引任务
  - 实际：品牌空；六个内容轴全空（0/4000）；状态栏「导购可见性 尚未投影」
- 证据:
  - 截图 `product-edit.png`
  - `GET /admin-api/assistant/productProjection/917186661226040` 200  
    摘要：`{"product_id":"917186661226040","ai_status":"idle","job":null,"index_job":null,"published":null,"draft":null}`
  - `POST /admin-api/productInfo/getProductInfo` 200，商品名正常，描述为 `/api/file/getResource?...` markdown 图
- 是否挡住商家日常: 挡住导购/知识投影，不挡传统下单列表。这件笔已出现在今日订单里，但 AI 侧仍不可见。

## A-03

- 严重度: high
- 页面 hash URL: `#/product/updateProduct/917186661226040`
- 复现步骤:
  1. 打开商品编辑，看商品描述编辑器里的图片
  2. 观察错误 toast
- 期望 vs 实际:
  - 期望：管理端能加载商品图；失败 toast 应说明资源 404 / 路径不对
  - 实际：描述里写的是用户端路径 `/api/file/getResource?sourceName=202601/...png`；控制台 5 次 404；页面 toast「网络异常」。同一文件走 `/admin-api/file/getResource` 为 200
- 证据:
  - 控制台：`Failed to load resource: 404 (Not Found)` ×5，发生在商品编辑页
  - `GET /api/file/getResource?sourceName=202601/IIcM83JFgrYvMNbG4SDsyDjylH3xFs.png` → **404**
  - `GET /admin-api/file/getResource?sourceName=202601/IIcM83JFgrYvMNbG4SDsyDjylH3xFs.png` → **200**
  - 截图 `product-edit-save-dialog.png` 同时出现「网络异常」与保存确认框
- 是否挡住商家日常: 是。编辑真实商品时会误报网络故障，描述图在管理端裂开；主图走 admin-api 仍正常。

## A-04

- 严重度: medium
- 页面 hash URL: `#/product/updateProduct/917186661226040`
- 复现步骤:
  1. 不改字段，点「发布商品」
  2. 阅读确认框后点「取消」（未输入管理员密码、未落库）
- 期望 vs 实际:
  - 期望：保存路径应提示将投影/重建导购索引
  - 实际：确认文案只有「保存将更新商品价格与库存等信息，是否继续？」；无投影/索引字样。成功 toast 在代码里是「保存成功，正在投影给导购」，本次取消所以没出现
- 证据:
  - 截图 `product-edit-save-dialog.png`
  - 当前状态栏已是「尚未投影」，与 A-02 叠加
- 是否挡住商家日常: 否。但商家不知道保存会触发投影，也不知道这件商品现在没有索引。

## A-05

- 严重度: medium
- 页面 hash URL: `#/product`
- 复现步骤:
  1. 打开商品列表，点「搜索」
  2. 点首行「预览」（Smartlect运动14）
- 期望 vs 实际:
  - 期望：列表以在售真实商品为主，预览有封面
  - 实际：`POST /admin-api/productInfo/loadProduct` 200，`totalCount: 58529`，首页全是 `Smartlect运动/数码/阅读/家居*` 种子货；指定商品 917186661226040 不在第一页。预览弹窗标题「商品预览」，主图裂图，规格「标准/加大」，库存 5 标「库存紧张」
- 证据:
  - 截图 `product-list.png`、`product-preview.png`
  - 列表 API 摘要：`pageTotal: 3902`
- 是否挡住商家日常: 部分挡住。不搜全名很难找到真实商品；预览种子货无图。

## A-06

- 严重度: medium
- 页面 hash URL: `#/home`
- 复现步骤:
  1. 打开仪表盘，等今日概览与经营趋势
- 期望 vs 实际:
  - 期望：今日销售额 ¥25.90、订单 1，昨日为 0 时应显示上升，而不是「持平」；趋势应能看见当天
  - 实际：四张卡都显示「持平」。`POST /admin-api/home/getTodayData` 200：`orderAmount today 25.90 / yesterday 0 / increase 0`，订单 `1 / 0 / increase 0`。经营趋势横轴 2026-09-10～09-16，不含当天 09-17
- 证据:
  - 截图 `home.png`
  - 同上 getTodayData、`POST /admin-api/home/loadWeeklyStatisticsData` 200
- 是否挡住商家日常: 否。数字本身在，环比与趋势会误导。

## A-07

- 严重度: medium
- 页面 hash URL: `#/ai/knowledge-index`（对照 `#/knowledge`）
- 复现步骤:
  1. 打开知识索引，点「刷新」
  2. 检索试验台输入「支持几天退款」，点「检索」
- 期望 vs 实际:
  - 期望：已发布文档应有索引任务/历史；空态不应说「发布后才会出现任务」
  - 实际：任务表空态「还没有索引任务；在知识库页发布文档后这里会出现任务」。同库 `#/knowledge` 有多篇「已发布」。检索结果 `answer_status: answered`，候选 8 条（如何申请退款、模拟支付方式等）
- 证据:
  - 截图 `ai-index.png`、`ai-index-probe.png`、`knowledge.png`
  - `GET /admin-api/assistant/knowledgeIndex/jobs` 200（空列表）
  - `POST /admin-api/assistant/knowledgeIndex/searchProbe` 200，摘要含 `answered` / citations
- 是否挡住商家日常: 否。召回可用，但无法在本页核对投影/失败任务。

## A-08

- 严重度: medium
- 页面 hash URL: `#/support`
- 复现步骤:
  1. 打开人工客服，点「刷新工单」
  2. 点首张工单「查看会话」
- 期望 vs 实际:
  - 期望：会话详情进入视口
  - 实际：大量「知识或模型未能解答 / 待接管」工单。`GET /admin-api/assistant/support/{id}` 200，但详情渲染在长列表下方，首屏截图仍是列表，看起来像没点进去
- 证据:
  - 截图 `support.png`、`support-detail.png`
  - 例：`GET /admin-api/assistant/support/e7088fa577774ee6b316ff0ee05fd1eb` 200
- 是否挡住商家日常: 部分挡住。工单能列出来，处理时要自己往下翻；堆积的待接管会拖慢客服。

## A-09

- 严重度: ux
- 页面 hash URL: 全局侧栏（对照 `#/product/category`、`#/product/ProductProperty`、`#/user/address`、`#/setting/*`、`#/marketing/*`、`#/data/*`）
- 复现步骤:
  1. 登录后看左侧菜单
  2. 用手输 hash 打开分类、属性、地址、发货、敏感词、图片审核、签到、会员礼券、运营工具、统计、MQ
- 期望 vs 实际:
  - 期望：一天会用的发货/分类/营销配置在菜单里
  - 实际：菜单只有首页、商品管理、订单四页、用户列表、优惠券、经营六页、AI 五页。上述页面路由可用，但侧栏没有
- 证据:
  - 菜单快照：首页 / 商品管理 / 订单管理·评论·举报·退款 / 用户列表 / 优惠券 / 经营六页 / AI 五页
  - 这些隐藏页均可打开且接口 200
- 是否挡住商家日常: 间接。和 A-01 叠加后，运营不容易找到发货地址。

## A-10

- 严重度: ux
- 页面 hash URL: `#/ads`
- 复现步骤:
  1. 打开活动与授权，点「刷新事实」
  2. 看已暂停活动的原因
- 期望 vs 实际:
  - 期望：暂停原因是中文
  - 实际：展示「暂停原因：grant_replaced」
- 证据:
  - 截图 `ads.png`
  - `GET /admin-api/assistant/ads` 200
- 是否挡住商家日常: 否。数字与恢复/调预算按钮在，原因码不好读。

## A-11

- 严重度: low
- 页面 hash URL: `#/order/comment`、`#/order/report`、`#/order/refundReview`、`#/setting/sensitiveWord`、`#/setting/imageModeration`、`#/data/mqCompensationLog`、`#/reviewAnalysis`、`#/growthReport`
- 复现步骤:
  1. 逐页打开并点搜索/刷新
- 期望 vs 实际:
  - 期望：有数据则列表，无数据则中文空态
  - 实际：均为空态，文案可读（「暂无数据」「还没有生成过评价分析」「还没有生成过增长报告」）。与订单评论接口空列表一致，评价分析空并不意外
- 证据:
  - 对应 `loadComment` / `loadDataList` / `reviewAnalysis` / `growthReport` 均为 HTTP 200
  - 截图 `order-comment.png`、`review-analysis.png`、`growth-report.png` 等
- 是否挡住商家日常: 否。

## A-12

- 严重度: low
- 页面 hash URL: `#/ai/runs`
- 复现步骤:
  1. 点「查询」，打开首行「详情」（`564a2ce0cb`，规则降级）
- 期望 vs 实际:
  - 期望：有模型调用的运行能看到轨迹；降级运行应说明为何无上下文
  - 实际：弹窗中文可读：「该运行没有可展示的上下文（尚未产生模型调用，或已超过 30 天保留期被清理）」。列表里同时有 live 运行（有 token/费用），本次点到的是 rule-fallback
- 证据:
  - 截图 `ai-runs-detail.png`
  - `GET /admin-api/assistant/runs/564a2ce0cbf64c5498150af59b5d43a4` 200
- 是否挡住商家日常: 否。

## A-13

- 严重度: ux
- 页面 hash URL: `#/ai/tools`
- 复现步骤:
  1. 选 `catalog_search`，关键字「保温杯」，点「调用」
- 期望 vs 实际:
  - 期望：只读调试返回与关键字相关的候选
  - 实际：调用成功，候选 4，`ranking_mode: content_rule`。结果是种子「Smartlect数码0」等，不是保温杯。接口未失败
- 证据:
  - 截图 `ai-tools-run.png`
  - `POST /admin-api/assistant/tools/invoke` 200，`run_id=9f9996e1bc404482b52694e27ee89f2f`
- 是否挡住商家日常: 否。调试台可用；检索质量被种子目录带偏。

## A-14

- 严重度: ux
- 页面 hash URL: `#/login` → `#/home` → 刷新 → 退出 → 再登入
- 复现步骤:
  1. 验证码走 `POST /admin-api/account/checkCode` + Redis `smartlect:checkcode:{key}`
  2. 登录后刷新
  3. 点退出并确定
  4. 再登录
- 期望 vs 实际:
  - 期望：会话保持；退出回登录；再登入成功；错误 toast 可读
  - 实际：均符合。刷新后仍在已登录页且「退出」可见。再登入 toast「登录成功」。本轮 `/admin-api` 业务接口无 HTTP/业务码失败；唯一误导 toast 见 A-03「网络异常」
- 证据:
  - `relogin.json`：`login1 #/home`、`reload #/home hasLogout=true`、`loggedOut #/login`、`login2 #/home`
  - 截图 `after-logout.png`、`relogin-home.png`
- 是否挡住商家日常: 否。

---

## 失败接口摘要

| method | URL | status | body 摘要 |
| --- | --- | --- | --- |
| GET | `/api/file/getResource?sourceName=202601/IIcM83JFgrYvMNbG4SDsyDjylH3xFs.png`（及同商品另外 4 张） | 404 | 管理端未代理 `/api`；用户端资源路径在后台裂图 |
| GET | `/admin-api/file/getResource?sourceName=202601/IIcM83JFgrYvMNbG4SDsyDjylH3xFs.png` | 200 | 对照：同一文件走 admin-api 正常 |

其余抽查的 `/admin-api/**` 与 `/admin-api/assistant/**` 均为 200，业务 `code=200` 或助手 JSON 成功。未出现 `/api/assistant`。

未执行的破坏性操作：未删除知识库已发布文档、未真正保存商品、未确认运营工具/秒杀预热、未接管工单。

---

## 按严重度摘要

- **blocker**：无。能登录，主链路页面能开。
- **high（3）**
  - A-01 发货地址空，挡住今日待发货
  - A-02 指定商品未投影，品牌/`content_json` 空
  - A-03 商品描述图走 `/api/file` 404，并弹出误导「网络异常」
- **medium（5）**
  - A-04 保存确认不提投影索引
  - A-05 5.8 万种子商品淹没真实货，预览无图
  - A-06 仪表盘环比「持平」、趋势不含当天
  - A-07 知识索引任务空态与已发布/可检索矛盾
  - A-08 客服「查看会话」不进首屏，待接管堆积
- **low（2）**：A-11 多页合法空态；A-12 规则降级运行无模型上下文（说明可读）
- **ux（3）**：A-09 侧栏缺发货/设置/数据中心；A-10 `grant_replaced` 未翻译；A-13 调试检索被种子目录带偏；A-14 登录/刷新/再登入正常
