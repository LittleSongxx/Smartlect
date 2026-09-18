"""Only persisted Java provider attempts can become nonfinancial failure observations."""
import copy
import hashlib
import json
import os
import unittest
import uuid

from smartlect.events import parse_event
import test_ledger_mysql


def payment_attempt(attempt_id='attempt-1', pay_id='pay-1', user_id='user-1'):
    digest = hashlib.sha256(('payment-attempt\0' + attempt_id).encode()).hexdigest()[:48]
    return {'eventId': 'outcome_' + digest, 'idempotencyKey': 'business_' + digest,
            'eventType': 'PAYMENT_ATTEMPT', 'source': 'PAYMENT_PROVIDER', 'userId': user_id,
            'requestId': None, 'productId': None, 'skuKey': None, 'orderId': 'order-1', 'position': None,
            'occurredAt': '2026-09-09T00:00:00.123Z', 'payload': {'attemptId': attempt_id,
                'payOrderId': pay_id, 'attemptStatus': 'DECLINED', 'reasonCode': 'MOCK_CHANNEL_DECLINED',
                'paymentMode': 'mock', 'attemptedAmountCents': 9000, 'currency': 'CNY'}}


class PaymentAttemptContractTests(unittest.TestCase):
    def test_decline_is_applied_nonfinancial_and_original_business_time_survives(self):
        fact = parse_event(payment_attempt(), 2)
        self.assertEqual((fact['status'], fact['pay_order_id']), ('APPLIED', 'pay-1'))
        self.assertIsNone(fact['amount_cents'])
        self.assertIsNone(fact['order_item_id'])
        self.assertEqual(fact['occurred_at'].isoformat(), '2026-09-09T00:00:00.123000')
        self.assertEqual(parse_event(payment_attempt(), 2)['fingerprint'], fact['fingerprint'])

    def test_unknown_cancel_timeout_live_label_and_forged_money_or_identity_are_rejected(self):
        mutations = [lambda e: e.update(source='ORDER'), lambda e: e.update(eventId='invented'),
                     lambda e: e.update(orderId=None), lambda e: e['payload'].update(payOrderId='p' * 33), lambda e: e.update(productId='fake-item'),
                     lambda e: e['payload'].update(paidAmount='90.00'),
                     lambda e: e['payload'].pop('attemptId'), lambda e: e['payload'].update(attemptId='different'),
                     lambda e: e['payload'].update(paymentMode='live'),
                     lambda e: e['payload'].update(reasonCode='PAYMENT_TIMEOUT'),
                     lambda e: e['payload'].update(reasonCode='USER_CANCEL')]
        mutations += [lambda e, value=value: e['payload'].update(attemptStatus=value)
                      for value in ('UNKNOWN', 'PENDING', 'CLOSED', 'FAILED', 'PAID')]
        mutations += [lambda e, value=value: e['payload'].update(attemptedAmountCents=value)
                      for value in (True, 0, -1, '9000', 90.1, 9223372036854775808)]
        for mutate in mutations:
            event = payment_attempt()
            mutate(event)
            with self.subTest(event=event), self.assertRaises(ValueError):
                parse_event(event, 2)
        with self.assertRaises(ValueError):
            parse_event(payment_attempt(), 1)


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS') == '1', 'requires dedicated MySQL')
class PaymentAttemptLedgerTests(unittest.TestCase):
    setUpClass = classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    def test_replayed_attempt_keeps_one_original_fact_and_zero_income(self):
        identifier = uuid.uuid4().hex
        pay_id = 'pay-' + identifier[:24]  # Java pay_order_id is at most 32 characters.
        event = payment_attempt(identifier, pay_id)
        body = json.dumps({'schema_version': 2, 'events': [event]}).encode()
        self.ledger.ingest(body)
        self.ledger.ingest(body)
        summary = self.ledger.summary(pay_id)
        self.assertEqual((summary['paidCents'], summary['refundedCents'], summary['paymentConversions']), (0, 0, 0))
        self.assertEqual(len(summary['events']), 1)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT raw_json,fingerprint,amount_cents,occurred_at FROM commerce_event WHERE event_id=%s', (event['eventId'],))
            row = cursor.fetchone()
            self.assertEqual(json.loads(row['raw_json']), event)
            self.assertIsNone(row['amount_cents'])
            self.assertEqual(row['occurred_at'].microsecond, 123000)
            cursor.execute('SELECT execution_scope_id FROM commerce_attribution_meta WHERE event_id=%s', (event['eventId'],))
            self.assertEqual(cursor.fetchone()['execution_scope_id'], 'store')
        altered = copy.deepcopy(event)
        altered['occurredAt'] = '2026-09-10T00:00:00Z'
        self.ledger.ingest(json.dumps({'schema_version': 2, 'events': [altered]}).encode())
        self.assertEqual(self.ledger.summary(pay_id)['events'], summary['events'])


if __name__ == '__main__':
    unittest.main()
