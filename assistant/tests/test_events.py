import json
import unittest
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

from smartlect.events import Ledger, NONFINANCIAL_SCOPE_VERSION, parse_event, persist_then_ack


def outcome(kind="PAYMENT", pay="pay-1", item="item-1", amount="90.00", **changes):
    identifier = uuid.uuid4().hex
    event = {"eventId": "outcome_" + identifier, "idempotencyKey": "business_" + identifier,
             "eventType": kind, "userId": "user-1", "source": "PAYMENT" if kind == "PAYMENT" else "AFTER_SALES",
             "productId": "product-1", "skuKey": "sku-1", "orderId": "order-1", "requestId": None,
             "occurredAt": "2026-09-09T00:00:00Z", "payload": {"payOrderId": pay, "orderItemId": item,
             "currency": "CNY", "paidAmount" if kind != "REFUND" else "refundAmount": amount}}
    if kind == "REFUND":
        event["payload"]["refundStatus"] = "COMPLETED"
    event.update(changes)
    return event


def batch(*events):
    return json.dumps({"schema_version": 1, "events": list(events)}).encode()


class EventContractTests(unittest.TestCase):
    def test_financial_contract_and_repeat_has_no_income(self):
        paid = parse_event(outcome(amount=Decimal("0.29")))
        self.assertEqual(paid["amount_cents"], 29)
        self.assertEqual(paid["status"], "PENDING")
        repeat = parse_event(outcome("REPEAT_PURCHASE"))
        self.assertIsNone(repeat["amount_cents"])
        self.assertEqual(repeat["status"], "APPLIED")
        self.assertEqual(parse_event(outcome("FUTURE_EVENT"))["status"], "UNKNOWN")

    def test_incomplete_unconfirmed_and_fractional_money_are_rejected(self):
        for mutate in (lambda e: e["payload"].pop("payOrderId"),
                       lambda e: e["payload"].update(refundStatus="PENDING"),
                       lambda e: e["payload"].update(refundAmount="0.001"),
                       lambda e: e["payload"].update(refundAmount="1e1000000000"),
                       lambda e: e["payload"].update(refundAmount="1e-1000000000"),
                       lambda e: e.update(occurredAt="2026-09-09T00:00:00"),
                       lambda e: e["payload"].update(currency="USD")):
            event = outcome("REFUND")
            mutate(event)
            with self.assertRaises(ValueError):
                parse_event(event)

    def test_confirmed_free_item_refund_is_a_valid_zero_cent_fact(self):
        payment = parse_event(outcome("PAYMENT", amount="0.00"))
        refund = parse_event(outcome("REFUND", amount="0.00"))
        self.assertEqual((payment["amount_cents"], refund["amount_cents"]), (0, 0))
        self.assertEqual(refund["status"], "PENDING")

    def test_ack_happens_after_persistence_and_never_on_failure(self):
        calls = []
        ledger, channel = Mock(), Mock()
        ledger.ingest.side_effect = lambda body: calls.append("commit")
        channel.basic_ack.side_effect = lambda **kw: calls.append("ack")
        persist_then_ack(ledger, channel, 7, b"body")
        self.assertEqual(calls, ["commit", "ack"])
        ledger.ingest.side_effect = RuntimeError("database transaction rolled back")
        channel.reset_mock()
        with self.assertRaises(RuntimeError):
            persist_then_ack(ledger, channel, 8, b"body")
        channel.basic_ack.assert_not_called()

    def test_legacy_behavior_scope_is_frozen_from_registry_not_producer_hint(self):
        for kind in ('CANCEL', 'VIEW', 'REPEAT_PURCHASE', 'ADD_TO_CART', 'REVIEW', 'PAYMENT'):
            with self.subTest(kind=kind):
                connection, cursor = MagicMock(), MagicMock()
                connection.__enter__.return_value = connection
                connection.cursor.return_value.__enter__.return_value = cursor
                cursor.fetchall.return_value = []
                cursor.fetchone.return_value = {'execution_scope_id': 'registered-scope'}
                ledger = Ledger(lambda: connection)
                event = outcome(kind)
                event['payload']['executionScopeId'] = 'untrusted-producer-scope'
                with patch.object(ledger, '_reconcile'):
                    ledger.ingest(batch(event))
                inserts = [call for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO commerce_attribution_meta')]
                if kind == 'PAYMENT':
                    self.assertEqual(inserts, [], 'Legacy financial attribution must remain unchanged')
                else:
                    self.assertEqual(len(inserts), 1)
                    event_id, scope, encoded = inserts[0].args[1]
                    self.assertEqual((event_id, scope), (event['eventId'], 'registered-scope'))
                    self.assertEqual(json.loads(encoded), {'executionScopeId': 'registered-scope',
                        'scopeSource': 'registered_user_or_default_store', 'projectionVersion': NONFINANCIAL_SCOPE_VERSION,
                        'projectionSource': 'ledger_ingest', 'producerDeclaredScope': 'untrusted-producer-scope'})
                connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
