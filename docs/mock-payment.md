# Smartlect mock payment

`SMARTLECT_PAYMENT_MODE=mock` is the default. Place orders with `payMethod=mock`.
The existing order service calculates and persists order amounts, creates the
`pay_trade_record` intent through its internal API, and then requests payment
information. The mock channel returns `smartlect-mock:<payOrderId>` and the
persisted amount; a caller-supplied amount does not determine settlement.

## Complete a simulated payment

Send `POST /internal/pay/mock/complete` directly to the Smartlect pay service,
with `X-Internal-Token: <SMARTLECT_INTERNAL_TOKEN>` and JSON:

```json
{"payOrderId": "<existing Java payment intent>"}
```

Only the payment ID is an input. User ID, amount, original order and channel come
from the stored intent. Unknown intents, non-mock channels, malformed amounts and
closed payments are rejected. The common internal authentication filter protects
this endpoint; no public mock callback or real-provider verification bypass is
registered. Response `data` contains `userId`, `payOrderId`, `amount`,
`channelOrderId` and `tradeStatus` (1 paid, 3 fully refunded).

The channel commits the simulated charge with the existing pending-to-success
compare-and-set and a stable channel ID. It then calls the existing order
`paySuccess` operation. The charge remains queryable if the order notification
fails, and repeating the trigger retries that notification without another charge.
Order's existing payment lock, state transitions and stable outcome IDs handle
duplicate delivery. Payment does not deduct stock again. A refunded intent is not
reopened by a later trigger.

## Refunds and cancellation

Users request refunds through the existing order API and ownership checks. Order
persists `RefundRequest` from the item's remaining actual paid amount, then calls
the existing protected `POST /internal/pay/channel/refund` with its saved
`sourcePayOrderId`, `refundOrderId`, `refundAmount` and `payChannel=mock`. This is an
internal Java command, not a new simulator API accepting arbitrary user amounts.

The mock channel reads the source payment intent, locks that payment row, validates
positive whole-cent amounts and persists confirmation in `pay_mock_refund`.
`refund_order_id` is unique: an identical retry has no additional effect; a changed
amount/source for the same ID is rejected. Cumulative refunds cannot exceed the
stored payment amount, including concurrent different refund IDs. Full refunds
mark the payment refunded; partial refunds leave it paid. After the channel
returns, the existing order refund Saga confirms the refund and performs its
idempotent inventory-restoration/message flow.

Cancellation uses the existing channel close operation. Only pending intents can
transition to closed; a concurrent successful payment prevents cancellation from
claiming the charge was closed.

The mock channel contains no real provider client. Default mock mode rejects
Alipay operations before resolving a provider bean. Existing Alipay certificate,
signature, identity and amount validation code remains intact. No real payment or
refund was initiated during this work.

## Verification

- Pay-focused reactor unit command: `mvn -B -f backend/pom.xml -pl smartlect-pay/app -am -Dtest=PayChannel4MockTest,PayChannel4AliPayTest,PayTradeRecordServiceImplTest,AlipayNotifyValidationServiceTest -Dsurefire.failIfNoSpecifiedTests=false test`.
- Initial run: 15 tests passed (7 new mock tests plus 8 retained payment tests).
- MySQL integration command: the same selection with `-Pintegration -Dit.test=PayChannel4MockIT -Dfailsafe.failIfNoSpecifiedTests=false verify`.
- The first integration attempt found an overloaded-method ambiguity in test setup;
  explicitly typing the Mockito argument fixed it. Final `verify` returned exit 0:
  15 unit tests and 3 MySQL integration tests passed, with no failures or skips.
  The integration checks cover persisted duplicate refund replay, changed-amount
  conflicts, full refund totals, concurrent distinct refund IDs competing for one
  payment, and rejection of unpaid/fractional-cent refunds.
  Logs: `/tmp/smartlect-pay-tests.log` and `/tmp/smartlect-pay-integration.log`.

The integration test uses its own Testcontainers MySQL database and the actual
pay migration, JDBC transactions and constraints. Order callbacks are mocked in
these focused tests; full cross-service order/payment/refund/stock verification
remains the P1 runtime gate, and these tests alone do not claim it passed.
