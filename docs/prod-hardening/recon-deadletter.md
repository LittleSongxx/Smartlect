# T1-6 对账自动化 + 死信告警

日期：2026-09-14 ｜ 状态：**已完成** ｜ 组件：`/opt/backups/bin/recon.sh`（本地副本 `run/cloud/recon.sh`，cron `/etc/cron.d/smartlect-recon` 每日 04:10，晚于 03:30 备份）；审计文件 `/opt/smartlect/run/recon/recon-*.txt`（保留 30 天）；死信运行时告警 = T0-1 的 `SmartlectDeadLetter` 规则

## 对账口径（两侧对称，单位分）

| 侧 | 字段 | 来源 |
|---|---|---|
| Java 权威 | paid = `SUM(pay_amount)*100 WHERE trade_status IN (1,3)`；refunded = `SUM(refund_amount)*100 FROM pay_mock_refund` | smartlect_pay（只读 SQL） |
| growth 账本 | paidCents / refundedCents（APPLIED 的 PAYMENT/REFUND 事件） | 官方接口 `GET /internal/ledger/summary`（x-internal-token，hmac 比对） |
| 交叉校验 | conversions：Java 已付笔数 vs growth paymentConversions；CANCEL：trade_status=2 笔数 vs CANCEL 事件数；commerce_exception 计数；死信队列水位入日报 | — |

**枚举语义**（查代码确认）：`trade_status` 1=已付、3=已退款（先付后退，故计入 paid 且退款额走 pay_mock_refund）、2=关闭（对应 growth CANCEL 事件，非资金移动）。全链路整数分（Java 侧 decimal*100 取整）。

## 怎么验证的

```text
# 首跑（19:31:33）：天然全平
java_paid_cents=184780  growth_paid_cents=184780  (conversions: java=29 growth=29)
java_refund_cents=0  growth_refund_cents=0
cancel: java=1 growth=1   growth_exceptions=0   dead_queue_messages=0
verdict=OK

# 不平演练（19:31:58）：注入 1 分钱 drill 假账（event_id=recon-drill-20260914）
java_paid_cents=184780  growth_paid_cents=184781   ← 差 1 分被抓住
verdict=MISMATCH → ALERT-SENT
Alertmanager: active SmartlectReconMismatch | 每日对账不平: MISMATCH（邮件通道）

# 回退：DELETE drill 事件 + POST endsAt 标记 resolved（邮件收恢复通知）
# 复验：java_paid=184780 = growth_paid=184780，verdict=OK
```

告警注入方式：recon 脚本直接 `POST /api/v2/alerts`（SmartlectReconMismatch, critical），走 Alertmanager 既有邮件路由——不新增告警链路。

## 死信告警（运行时）

T0-1 已上线：`SmartlectDeadLetter`（任何 `*dead*` 队列 ready>0 持续 5m，critical，邮件通道）。本项补充：死信水位写入每日对账日报留痕（`dead_queue_messages`），双保险——运行时 5 分钟级 + 每日审计级。

## 遇到的坑

1. `trade_status=2` 的语义差点搞错：不是「已退款」而是「已关闭」（代码里 `STATUS_REFUNDED = 3`）——若把 2 当退款，对账会永久误报 71.75 元。口径必须查代码不能猜。
2. commerce_event 的 NOT NULL 列比 SELECT 出来的多（idempotency_key/fingerprint/raw_json/schema_version 等），注入 drill 数据要按建表语句补齐。
3. Alertmanager 注入式告警若不补 `endsAt`，会活到 GC 超时——演练回退时要显式 POST resolved，否则邮箱里只有告警没有恢复。

## 面试一句话

建立「Java 支付权威 vs growth 事件账本」的每日自动对账（分单位、含退款/转化/取消三组交叉校验 + 死信水位留痕），不平即经 Alertmanager 邮件告警；用一次 1 分钱注入演练证明端到端闭环——25 秒内从「账不平」到「告警到达」再到「回退复平」，全程审计文件留痕。
