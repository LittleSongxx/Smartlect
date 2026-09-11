# 已注册演示运行的退役与替换

状态：F6 源码实现；真实 Java/MySQL/Growth 联调证据待验收。入口属于现有
`DemoScenarioController`，只在 `smartlect.demo.enabled=true`、生成的 demo password
长度至少 24 且支付模式为 `mock` 时加载。所有请求还受内部 token 过滤器保护。
reset 不提供支付、取消、退款或补库存能力。

`scenarioRunId` 是 Java registry 中完整运行的 ID；一个运行下所有 branch 一起退役。
不能提交 `store`、任意用户/SKU 列表或未注册运行。V2 的 `demo_scenario_run`
为已有 registry 回填运行行，给 seed、session、inspect 和 reset 提供相同的运行行锁。
一次 reset 只改变注册运行的生命周期，并返回一组全新真实用户/SKU。

## 接口

`POST /internal/demo/scenario/inspect-run`，JSON 精确字段：

```json
{"scenarioRunId":"owned-run","password":"<ignored run configuration>"}
```

Java `ResponseVO.data`：

```json
{
  "scenarioRunId":"owned-run",
  "state":"ACTIVE",
  "branches":["完整原 Manifest 对象"],
  "scopeIds":["demo-..."],
  "watermark":{
    "manifestHashes":[],"users":[],"products":[],"skus":[],
    "orders":[],"items":[],"payments":[],"refunds":[],"commands":[],"outbox":[]
  },
  "watermarkHash":"Java 生成的 SHA-256",
  "ready":true,
  "blockers":[]
}
```

每个 Outbox 水位包含 `service/id/status/idempotencyKey/payloadHash/eventIds`。
仅选择消息 JSON 中精确引用该运行用户、产品、订单、支付或退款 ID 的行；覆盖已有
admin/user/product/cart/order/pay 六个 Outbox。原 payload 不返回也不修改。
Java 水位的 hash 由服务端生成，客户端原样带回；不把响应中的数字重排后自行替代它。

`ready` 要求没有待支付或未知状态订单、待支付或未知状态支付意图、非 mock 支付、
付款同步缺口、未完成退款 Saga、未决订单命令，以及尚非 SENT 的相关 Outbox。
已付款等稳定业务状态可以保留；reset 不替用户退款。已取消、超时、UNKNOWN 不计支付失败。
返回 `ready=false` 时，协调器先按原授权/确认规则处理未决事实，然后重新检查。

`POST /internal/demo/scenario/reset`，JSON 精确字段：

```json
{
  "scenarioRunId":"owned-run",
  "resetRequestId":"stable-local-reset-id",
  "password":"<ignored run configuration>",
  "expectedWatermarkHash":"inspect-run 返回的 64 位十六进制值"
}
```

成功的 `ResponseVO.data` 为持久回执：

```json
{
  "resetRequestId":"stable-local-reset-id",
  "retiredRunId":"owned-run",
  "retiredScopeIds":["demo-old"],
  "replacementRunId":"reset-...",
  "replacementManifests":["完整新 Manifest 对象"],
  "watermark":{},
  "watermarkHash":"原审批水位",
  "mode":"retire_and_replace"
}
```

服务端从原 registry seed 参数重建相同 branch、用户/商品数量、SKU 规格、初始价格和
初始库存模板。新 run ID 由原 run 和 reset request 确定，新用户/SKU 使用 registry 新序号，
不复用旧资源。若该目标 run 已存在则拒绝，不能把已有消耗的资源当作重置后的初态。

同一原 run、reset request 和原水位的精确重试返回原回执；不会再创建或补货。
同一原 run 改 request/hash、跨 run 复用 reset request 均为 409。
密码只用于验证，不进入请求指纹或持久回执。reset 后 seed/session 对旧 run 返回 410；
历史 manifest 仍能通过 read/inspect 读取。需要再次 reset 时必须显式使用 replacement run。

`POST /internal/demo/scenario/reset-result` 接受与 inspect-run 相同的
`{scenarioRunId,password}`，只读返回原持久 `ResetResult`；已注册但尚未 reset 时为 `null`，
未知运行仍拒绝。忽略的本地状态文件丢失后，用它恢复已发生的事实，不能另造 reset request。

## Growth 协调器

脚本入口为 `growth/.venv/bin/python scripts/reset_demo.py --run-id <owned-run>`，
支持可选 `--request-id` 和 `--output`。由 runtime 接入 `dev.sh reset-demo` 后仍须实际验收。
它只读取本项目忽略的 `run/runtime.env`，要求普通文件且权限 600、mock payment；
不读取模型配置，不调用模型。运行锁和恢复副本位于权限 600 的 `run/reset-demo/` 文件中。

Growth 0009 `execution_scope_reset` 以原 run 为键，持久保存固定 request、完整原 manifest、
事件水位、Java 调用前标记及结果。CLI 先核对所有 Java branch 与 Growth 注册的用户/产品
完全一致；保留已注册 visitor。事件必须已 APPLIED，付款/退款投影必须 FINAL。
存在 CREATED/RUNNING AgentRun、CONFIRMED/EXECUTING/UNKNOWN proposal 或 EXECUTING
Merchant plan 时拒绝，不创建 guard。

进入 QUIESCING 后再次检查 Java 和 Growth 状态。准备实际调用 Java 前先将固定 request/hash
写入 Growth，再保存本地恢复副本；网络结果未知时保留 guard，仅做有界原回执查询及精确重试。
本地文件丢失可由 Growth guard 和 Java reset-result 恢复。尚未调用 Java 的前置冲突只允许
撤销该 request 自己的 QUIESCING guard；一旦标记可能调用过 Java，就不能自动解禁。

Java 成功后，Growth 在一个事务中注册全新 manifests、复制原分支的商家访问成员资格并将
旧 guard 标为 RETIRED。不会复制活动预算/授权、交易、记忆或 visitor 身份，也不会删除
旧 scope/用户/SKU 映射。重复完成不再新增资源。

API 对 QUIESCING/RETIRED 范围的新业务写分别返回 409/410；产生新推荐凭据的 GET 也被阻止。
商家历史只读保留。scope-select 仍验证当前 CSRF，但允许从退役范围切走。
guard 是 API 入站写检查，不能抹除检查之前已入站的在途请求；后续复核和资源隔离仍必要。
成功证据保存原回执；失败单独生成文件，避免覆盖上次检查结果。

## 事务与消息边界

reset 重新验证 registry 的种子指纹、序号所确定的完整 manifest、用户/地址归属以及全部
SKU/库存行。存在普通用户购买该运行商品、该运行用户买入未注册 SKU 或其他资源映射缺口
时拒绝，不能通过退役隐藏交叉污染。检查只接受最多 32 个 branch 的本地运行。

同一 Java 数据库事务持有运行锁、原用户/商品行及已有交易行的锁，重新读取状态、水位，
停用旧用户、下架仍在售的旧商品，创建新资源，并写入 RETIRED 和 reset 回执。
并发 seed 不能给该旧 run 增加遗漏 branch。事务失败全部回滚；旧价格、库存、订单、支付、
退款、Outbox 及历史 manifest 不删除、不回填。提交后按确切旧 user ID 清理 Redis 当前会话；
若提交后清理失败，同一 reset 请求可恢复回执并重试清理。

协调器必须先在 Growth 持久退役旧 scope、阻止新流量/Agent/确认写入并等待原命令确定结果，
再调用 inspect/reset。收到新 manifest 后注册全新 Growth scope；旧 scope 永不重新启用，
旧资源到旧 scope 的映射保留。原预算账户和花费也保留，新模拟运行需要自己的显式商家授权。

SENT 只证明 Outbox 到 broker 的投递，不证明 Growth 已消费。协调器还须核对返回的
commerce `eventIds` 已到其账本水位；延迟超时队列可保留已知的旧订单 ID。
重投及迟到事件继续指向旧用户/SKU/订单，不能改变 replacement scope。

并发限制是明确的：现有 Java 订单准备阶段读取商品状态，但不持有商品行锁直到整个下单
完成；传统 Gateway 只查 Redis token，`cleanAllToken` 只清理 user ID 当前指向的 token。
因此该接口不能证明任意绕过协调器、已经通过准备的 Java 请求都已消失，也不宣称撤销了
所有历史并行 token。AI 身份内省会检查用户停用状态，Growth 退役禁止其后续写入；下架商品
阻止新的正常准备。已在途请求的停止/结果核对是协调器前置条件，水位 hash 本身不是写入屏障。
无论旧请求何时到达，独立资源 ID 和保留旧映射仍是隔离新运行的必要保障。

## 待验收证据

单测覆盖全 branch 退役/新资源/幂等、待支付/命令/Outbox 阻断、未知运行、错误密码、水位冲突、
manifest 归属缺口以及旧 run 的 seed 拒绝。它们使用 mock JDBC，只验证边界和 SQL 调用，
不能替代真实 MySQL 事务或消费投影验收。

F6 还须实际证明：未决操作拒绝且原状态不变；成功 reset 后旧资源停用、新资源独立；
同 request 重试不新增资源；原账本指纹保持；旧消息重投不会复活旧 scope 或污染新 scope。
