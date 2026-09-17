"""Opt-in real MySQL checks, owning one disposable Smartlect-only container."""
import concurrent.futures
import hashlib
import json
import os
import secrets
import subprocess
import time
import unittest
import uuid
from unittest.mock import patch

import pymysql

from smartlect.attribution import AttributionStore
from smartlect.auth import ActorContext
from smartlect.events import Ledger, NONFINANCIAL_SCOPE_VERSION, canonical, parse_event
from smartlect.merchant.store import MerchantStore
from smartlect.migrate import migrate, migration_files
from test_events import batch, outcome


async def csrf_headers(client, origin, path='/admin-api/assistant/session'):
    """One-time CSRF: every write must mint a fresh token from the session endpoint."""
    session = (await client.get(path)).json()
    return {'Origin': origin, 'X-CSRF-Token': session['csrf_token']}


@unittest.skipUnless(os.getenv("SMARTLECT_RUN_MYSQL_TESTS") == "1", "set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL")
class LedgerMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name = "smartlect-growth-it-" + uuid.uuid4().hex[:12]
        cls.label = "com.smartlect.test=commerce-ledger"
        cls.container = None
        password = secrets.token_hex(16)
        try:
            cls.container = subprocess.check_output([
                "docker", "run", "-d", "--rm", "--name", cls.name, "--label", cls.label,
                "--memory", "512m", "--cpus", "1", "-p", "127.0.0.1::3306", "-e", "MYSQL_ROOT_PASSWORD=" + secrets.token_hex(16),
                "-e", "MYSQL_DATABASE=smartlect_growth", "-e", "MYSQL_USER=smartlect_growth",
                "-e", "MYSQL_PASSWORD=" + password, "mysql:8.4.11"], text=True, timeout=30).strip()
            info = json.loads(subprocess.check_output(["docker", "inspect", cls.container], text=True))[0]
            port = int(info["NetworkSettings"]["Ports"]["3306/tcp"][0]["HostPort"])
            cls.connect = staticmethod(lambda: pymysql.connect(host="127.0.0.1", port=port, user="smartlect_growth",
                    password=password, database="smartlect_growth", charset="utf8mb4", autocommit=False,
                    cursorclass=pymysql.cursors.DictCursor, connect_timeout=2))
            deadline = time.monotonic() + 60
            while True:
                try:
                    with cls.connect() as connection:
                        break
                except pymysql.MySQLError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.5)
            cls.ledger = Ledger(cls.connect)
            cls.ledger.initialize()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        if cls.container:
            info = json.loads(subprocess.check_output(["docker", "inspect", cls.container], text=True))[0]
            if info["Name"] != "/" + cls.name or info["Config"]["Labels"].get("com.smartlect.test") != "commerce-ledger":
                raise RuntimeError("refusing to remove unowned test container")
            subprocess.run(["docker", "rm", "-f", cls.container], check=True, capture_output=True, text=True)

    def setUp(self):
        self.pay = "it-" + uuid.uuid4().hex
        self.item = "item-" + uuid.uuid4().hex

    def scope_metadata(self, event_id):
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT * FROM commerce_attribution_meta WHERE event_id=%s', (event_id,))
            return cursor.fetchone()

    def test_v1_cancel_and_view_freeze_registered_scope_for_merchant_observation(self):
        scope, other_scope = 'scope-' + uuid.uuid4().hex, 'scope-' + uuid.uuid4().hex
        owner, other = 'user-' + uuid.uuid4().hex, 'user-' + uuid.uuid4().hex
        store = MerchantStore(self.connect)
        store.register_scope(scope, scenario_run_id=scope, branch_id='contract', users=[owner], products=['product-' + scope])
        store.register_scope(other_scope, scenario_run_id=other_scope, branch_id='contract', users=[other], products=['product-' + other_scope])
        merchant = ActorContext(subject_type='merchant', actor_id='admin', session_id='synthetic', permissions=('admin:legacy',), execution_scope_id=scope)
        before = store.observation(merchant)
        cancel = outcome('CANCEL', userId=owner, source='ORDER', productId='product-' + scope,
            payload={'orderStatus': 'CANCELLED', 'reasonCode': 'USER_CANCEL', 'executionScopeId': other_scope})
        view = outcome('VIEW', userId=owner, source='PRODUCT', productId='product-' + scope, payload={})
        self.ledger.ingest(batch(cancel, view))
        for event in (cancel, view):
            meta = self.scope_metadata(event['eventId'])
            self.assertEqual(meta['execution_scope_id'], scope)
            projection = json.loads(meta['metadata_json'])
            self.assertEqual((projection['projectionVersion'], projection['projectionSource']), (NONFINANCIAL_SCOPE_VERSION, 'ledger_ingest'))
            with self.connect() as connection, connection.cursor() as cursor:
                cursor.execute('SELECT raw_json,fingerprint,amount_cents FROM commerce_event WHERE event_id=%s', (event['eventId'],))
                row = cursor.fetchone()
            self.assertEqual(row['raw_json'], canonical(event))
            self.assertEqual(row['fingerprint'], hashlib.sha256(canonical(event).encode()).hexdigest())
            self.assertIsNone(row['amount_cents'])
        observation = store.observation(merchant)
        self.assertNotEqual(observation['watermark'], before['watermark'])
        self.assertEqual((observation['summary']['cancelled_orders'], observation['summary']['payment_failures'],
                          observation['summary']['paid_cents'], observation['summary']['refunded_cents']), (1, 0, 0, 0))
        fact = next(f for f in observation['facts'] if f['metric'] == 'cancelled_orders')
        self.assertEqual(fact['source_ids'], [cancel['eventId']])
        self.assertEqual(store.observation(merchant.model_copy(update={'execution_scope_id': other_scope}))['summary']['cancelled_orders'], 0)
        self.ledger.ingest(batch(cancel, view))
        self.assertEqual(store.observation(merchant), observation)

    def test_default_nonfinancial_scope_does_not_follow_later_registration_or_replay(self):
        owner, scope = 'late-' + uuid.uuid4().hex, 'late-scope-' + uuid.uuid4().hex
        original = outcome('CANCEL', userId=owner, source='ORDER', payload={'executionScopeId': scope})
        self.ledger.ingest(batch(original))
        before = self.scope_metadata(original['eventId'])
        self.assertEqual(before['execution_scope_id'], 'store')
        store = MerchantStore(self.connect)
        store.register_scope(scope, scenario_run_id=scope, branch_id='late', users=[owner], products=['product-' + scope])
        self.ledger.ingest(batch(original))
        self.assertEqual(self.scope_metadata(original['eventId']), before)
        merchant = ActorContext(subject_type='merchant', actor_id='admin', session_id='synthetic', permissions=('admin:legacy',), execution_scope_id=scope)
        self.assertEqual(store.observation(merchant)['summary']['cancelled_orders'], 0)
        new = outcome('CANCEL', userId=owner, source='ORDER', payload={})
        self.ledger.ingest(batch(new))
        self.assertEqual(self.scope_metadata(new['eventId'])['execution_scope_id'], scope)
        fact = next(f for f in store.observation(merchant)['facts'] if f['metric'] == 'cancelled_orders')
        self.assertEqual((fact['value'], fact['source_ids']), (1, [new['eventId']]))

    def test_out_of_order_refund_and_duplicates_reconcile_to_one_payment(self):
        refund = outcome("REFUND", self.pay, self.item)
        paid = outcome("PAYMENT", self.pay, self.item)
        self.ledger.ingest(batch(refund))
        pending = self.ledger.summary(self.pay)
        self.assertEqual((pending["paidCents"], pending["refundedCents"], pending["paymentConversions"]), (0, 0, 0))
        self.assertEqual(pending["events"][0]["status"], "PENDING")
        self.ledger.ingest(batch(paid))
        self.ledger.ingest(batch(paid, refund, outcome("REPEAT_PURCHASE", self.pay, self.item)))
        summary = self.ledger.summary(self.pay)
        self.assertEqual((summary["paidCents"], summary["refundedCents"], summary["netCents"], summary["paymentConversions"]), (9000, 9000, 0, 1))
        self.assertTrue(all(event["status"] == "APPLIED" for event in summary["events"]))

    def test_multiple_items_count_one_conversion_and_identity_replays_add_nothing(self):
        first = outcome("PAYMENT", self.pay, self.item)
        second = outcome("PAYMENT", self.pay, self.item + "b", amount="10.00")
        self.ledger.ingest(batch(first, second))
        duplicate = {**first, "eventId": "replayed-" + uuid.uuid4().hex}
        self.ledger.ingest(batch(duplicate))
        summary = self.ledger.summary(self.pay)
        self.assertEqual((summary["paidCents"], summary["paymentConversions"]), (10000, 1))
        self.assertEqual(len(summary["events"]), 2)

    def test_rollback_preserves_no_partial_fact_or_accounting_effect(self):
        event = outcome("PAYMENT", self.pay, self.item)
        with patch.object(self.ledger, "_reconcile", side_effect=RuntimeError("injected transaction failure")):
            with self.assertRaises(RuntimeError):
                self.ledger.ingest(batch(event))
        self.assertEqual(self.ledger.summary(self.pay)["events"], [])
        self.ledger.ingest(batch(event))
        self.assertEqual(self.ledger.summary(self.pay)["paidCents"], 9000)

    def test_concurrent_refunds_cannot_exceed_the_paid_item(self):
        self.ledger.ingest(batch(outcome("PAYMENT", self.pay, self.item)))
        messages = [batch(outcome("REFUND", self.pay, self.item, amount="60.00")) for _ in range(2)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(self.ledger.ingest, messages))
        summary = self.ledger.summary(self.pay)
        self.assertEqual(summary["refundedCents"], 6000)
        self.assertEqual(sum(event["status"] == "INVALID" for event in summary["events"]), 1)

    def test_unknown_and_malformed_messages_are_preserved(self):
        self.ledger.ingest(batch(outcome("UNKNOWN", self.pay, self.item)))
        raw = b"\xffinvalid-json"
        self.ledger.ingest(raw)
        self.ledger.ingest(raw)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT raw_body,occurrences FROM commerce_exception WHERE message_hash=%s", (hashlib.sha256(raw).hexdigest(),))
            row = cursor.fetchone()
        self.assertEqual((row["raw_body"], row["occurrences"]), (raw, 2))
        summary = self.ledger.summary(self.pay)
        self.assertEqual(summary["events"][0]["status"], "UNKNOWN")
        self.assertEqual(summary["paidCents"], 0)


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS') == '1', 'requires dedicated MySQL migration fixture')
class LegacyNonfinancialScopeMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old = [entry for entry in migration_files() if entry[0][:4] < '0010']
        with patch('smartlect.migrate.migration_files', return_value=old):
            LedgerMySQLTests.setUpClass.__func__(cls)

    tearDownClass = classmethod(LedgerMySQLTests.tearDownClass.__func__)
    scope_metadata = LedgerMySQLTests.scope_metadata

    def test_forward_backfill_preserves_facts_existing_meta_and_financial_attribution(self):
        owner, late = 'historical-' + uuid.uuid4().hex, 'unregistered-' + uuid.uuid4().hex
        scope = 'historical-scope-' + uuid.uuid4().hex
        store = AttributionStore(self.connect)
        store.register_scope(scope, scenario_run_id=scope, branch_id='migration', users=[owner], products=['product-' + scope])
        legacy = [outcome(kind, userId=user, source='ORDER', payload={'executionScopeId': 'untrusted-hint'})
                  for kind, user in [('CANCEL', owner), ('VIEW', owner), ('CANCEL', late), ('VIEW', owner)]]
        # Model the actual <=0009 ledger shape: valid persisted v1 behaviors had no metadata.
        with self.connect() as connection, connection.cursor() as cursor:
            for event in legacy:
                fact = parse_event(event, 1)
                cursor.execute('INSERT INTO commerce_event (' + ','.join(fact) + ') VALUES (' + ','.join(['%s'] * len(fact)) + ')', tuple(fact.values()))
            cursor.execute('INSERT INTO commerce_attribution_meta VALUES (%s,%s,%s)',
                           (legacy[-1]['eventId'], 'store', canonical({'preexisting': 'must remain byte-for-byte unchanged'})))
            connection.commit()
        pay, item = uuid.uuid4().hex, uuid.uuid4().hex
        financial = [outcome('PAYMENT', pay, item, userId=owner), outcome('REFUND', pay, item, userId=owner)]
        self.ledger.ingest(batch(*financial))
        modern = outcome('PAYMENT', uuid.uuid4().hex, uuid.uuid4().hex, userId=owner)
        self.ledger.ingest(canonical({'schema_version': 2, 'events': [modern]}).encode())
        unknown = outcome('UNKNOWN', userId=owner)
        self.ledger.ingest(batch(unknown))
        def snapshot():
            with self.connect() as connection, connection.cursor() as cursor:
                cursor.execute('SELECT * FROM commerce_event ORDER BY event_id'); facts = list(cursor.fetchall())
                cursor.execute('SELECT * FROM commerce_attribution ORDER BY event_id'); projections = list(cursor.fetchall())
                cursor.execute('SELECT * FROM commerce_attribution_meta ORDER BY event_id'); metadata = list(cursor.fetchall())
                return facts, projections, metadata
        before_facts, before_financial, before_meta = snapshot()
        self.assertEqual({r['category'] for r in before_financial}, {'LEGACY_UNKNOWN', 'UNKNOWN_CONTEXT'})
        migrate(self.connect)
        after_facts, after_financial, after_meta = snapshot()
        self.assertEqual(after_facts, before_facts)
        self.assertEqual(after_financial, before_financial)
        self.assertTrue(all(row in after_meta for row in before_meta))
        self.assertEqual(len(after_meta), len(before_meta) + 3)
        for event, expected_scope in zip(legacy[:3], (scope, scope, 'store')):
            row = self.scope_metadata(event['eventId']); self.assertEqual(row['execution_scope_id'], expected_scope)
            self.assertEqual(json.loads(row['metadata_json']), {'executionScopeId': expected_scope,
                'scopeSource': 'registered_user_or_default_store', 'projectionVersion': NONFINANCIAL_SCOPE_VERSION,
                'projectionSource': 'migration_0010', 'producerDeclaredScope': 'untrusted-hint'})
        self.assertIsNone(self.scope_metadata(unknown['eventId']))
        for event in financial: self.assertIsNone(self.scope_metadata(event['eventId']))
        frozen = snapshot()
        migrate(self.connect)
        self.assertEqual(snapshot(), frozen)
        late_scope = 'later-scope-' + uuid.uuid4().hex
        store.register_scope(late_scope, scenario_run_id=late_scope, branch_id='later', users=[late], products=['product-' + late_scope])
        self.ledger.ingest(batch(*legacy))
        self.assertEqual(snapshot(), frozen)
        # Also replay the owned DML itself: a retry cannot overwrite any existing frozen mapping.
        migration = next(m for m in migration_files() if m[0] == '0010_nonfinancial_scope.sql')
        with self.connect() as connection, connection.cursor() as cursor:
            for statement in migration[2].split('\n-- statement-break\n'):
                if statement.strip(): cursor.execute(statement)
            connection.commit()
        self.assertEqual(snapshot(), frozen)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS count FROM schema_migration WHERE name=%s', (migration[0],))
            self.assertEqual(cursor.fetchone()['count'], 1)


if __name__ == "__main__":
    unittest.main()
