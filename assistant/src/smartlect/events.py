"""Durable commerce facts. Growth owns these tables, never Java transaction tables."""

import argparse
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import pika
import pymysql

from smartlect.money import to_cents

QUEUE = "smartlect.growth.commerce.queue"
BEHAVIORS = {"REPEAT_PURCHASE", "ADD_TO_CART", "REVIEW", "CANCEL", "VIEW", "PAYMENT_ATTEMPT"}
NONFINANCIAL_SCOPE_VERSION = 'nonfinancial-scope-v1'
log = logging.getLogger(__name__)

def required_env(name):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is required for commerce event consumption")
    return value


def _new_connection():
    database = required_env("SMARTLECT_GROWTH_MYSQL_DATABASE")
    user = required_env("SMARTLECT_GROWTH_MYSQL_USER")
    if database != "smartlect_growth" or user != "smartlect_growth":
        raise ValueError("Growth must use its dedicated smartlect_growth database and identity")
    return pymysql.connect(host=required_env("SMARTLECT_MYSQL_HOST"),
                           port=int(required_env("SMARTLECT_MYSQL_PORT")), user=user,
                           password=required_env("SMARTLECT_GROWTH_MYSQL_PASSWORD"), database=database,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                           autocommit=False, connect_timeout=5, read_timeout=10, write_timeout=10,
                           # MySQL is loopback-only for growth. pymysql's PREFERRED mode would
                           # build a fresh TLS context (full system CA load) per connection —
                           # hundreds of ms CPU each — which flattened concurrency to ~3 rps.
                           ssl_disabled=os.getenv("SMARTLECT_GROWTH_MYSQL_SSL", "0") != "1",
                           init_command="SET time_zone = '+00:00'")


_local = threading.local()


def connect_from_env():
    """One long-lived connection per worker thread instead of one per transaction.

    Every db() hop runs on asyncio.to_thread's small persistent pool, so thread-local
    reuse caps connections at ~12 per process while removing the per-transaction TCP +
    auth handshake. pymysql's ``with conn:`` still commits/rolls back per transaction;
    ping(reconnect=True) heals idle drops (wait_timeout)."""
    connection = getattr(_local, "connection", None)
    if connection is not None:
        try:
            connection.ping(reconnect=True)
            return connection
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            _local.connection = None
    connection = _new_connection()
    _local.connection = connection
    return connection


def canonical(value):
    def decimal_json(item):
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError("unsupported JSON value")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=decimal_json)


def text_field(event, name, limit=64, required=False):
    value = event.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {name}")
    return value


def parse_event(event, schema_version=1):
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    result = {
        "event_id": text_field(event, "eventId", 128, True),
        "idempotency_key": text_field(event, "idempotencyKey", 128, True),
        "event_type": text_field(event, "eventType", 32, True),
        "user_id": text_field(event, "userId", 64, True),
        "source": text_field(event, "source", 64, True),
        "product_id": text_field(event, "productId"), "sku_key": text_field(event, "skuKey", 128),
        "order_id": text_field(event, "orderId"), "request_id": text_field(event, "requestId", 128),
    }
    occurred = datetime.fromisoformat(text_field(event, "occurredAt", 64, True).replace("Z", "+00:00"))
    if occurred.tzinfo is None:
        raise ValueError("occurredAt must include a timezone")
    if occurred.year < 1000:
        raise ValueError("occurredAt is outside MySQL datetime range")
    result["occurred_at"] = occurred.astimezone(timezone.utc).replace(tzinfo=None)
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    financial = result["event_type"] in {"PAYMENT", "REFUND"}
    result["pay_order_id"] = text_field(payload, "payOrderId", required=financial)
    result["order_item_id"] = text_field(payload, "orderItemId", required=financial)
    result["amount_cents"] = None
    if result['event_type'] == 'PAYMENT_ATTEMPT':
        if (schema_version != 2 or result['source'] != 'PAYMENT_PROVIDER'
                or set(payload) != {'attemptId', 'payOrderId', 'attemptStatus', 'reasonCode',
                                    'paymentMode', 'attemptedAmountCents', 'currency'}):
            raise ValueError('payment attempts require the v2 provider contract')
        attempt_id = text_field(payload, 'attemptId', 64, True)
        text_field(payload, 'payOrderId', 32, True)
        if ('\0' in attempt_id or payload['attemptStatus'] != 'DECLINED'
                or payload['reasonCode'] != 'MOCK_CHANNEL_DECLINED' or payload['paymentMode'] != 'mock'
                or payload['currency'] != 'CNY' or type(payload['attemptedAmountCents']) is not int
                or not 0 < payload['attemptedAmountCents'] <= 9223372036854775807
                or not result['order_id'] or any(result[key] is not None for key in ('product_id', 'sku_key', 'request_id'))
                or event.get('position') is not None):
            raise ValueError('invalid simulated payment attempt fact')
        digest = hashlib.sha256(('payment-attempt\0' + attempt_id).encode()).hexdigest()[:48]
        if result['event_id'] != 'outcome_' + digest or result['idempotency_key'] != 'business_' + digest:
            raise ValueError('payment attempt identity does not match attemptId')
    if financial:
        if not all(result[key] for key in ("product_id", "sku_key", "order_id")) or payload.get("currency") != "CNY":
            raise ValueError("financial events require product/SKU/order and CNY currency")
        value = payload.get("paidAmount" if result["event_type"] == "PAYMENT" else "refundAmount")
        if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
            raise ValueError("financial amount must be an exact decimal")
        try:
            decimal_value = Decimal(str(value))
        except InvalidOperation as error:
            raise ValueError("financial amount must be a valid decimal") from error
        if not decimal_value.is_finite() or not 0 <= decimal_value <= Decimal("92233720368547758.07"):
            raise ValueError("financial amount exceeds ledger range")
        digits = decimal_value.as_tuple()
        if digits.exponent < -2 and any(digits.digits[digits.exponent + 2:]):
            raise ValueError("financial amount must be in whole cents")
        result["amount_cents"] = to_cents(str(value))
        if result["event_type"] == "REFUND" and payload.get("refundStatus") != "COMPLETED":
            raise ValueError("refund must be confirmed COMPLETED")
    result["raw_json"] = canonical(event)
    result["fingerprint"] = hashlib.sha256(result["raw_json"].encode()).hexdigest()
    result["status"] = "PENDING" if financial else "APPLIED" if result["event_type"] in BEHAVIORS else "UNKNOWN"
    result["reason"] = "unsupported event type" if result["status"] == "UNKNOWN" else None
    result["schema_version"] = schema_version
    result["received_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    return result


def _lock_ledger(cursor, *, body=None, fact=None):
    """Lock by pay_order_id when known; otherwise a batch/global key. Never one row for the whole table."""
    keys = []
    if fact and fact.get("pay_order_id"):
        keys.append("pay:" + str(fact["pay_order_id"]))
    elif body:
        try:
            batch = json.loads(body)
            for event in (batch.get("events") or []):
                payload = event.get("payload") or {}
                pay = payload.get("payOrderId") or payload.get("pay_order_id")
                if pay:
                    keys.append("pay:" + str(pay))
        except Exception:
            keys = []
    if not keys:
        keys = ["ledger:global"]
    cursor.execute("""CREATE TABLE IF NOT EXISTS commerce_ledger_lock_key (
        lock_key VARCHAR(64) PRIMARY KEY,
        touched_at DATETIME(6) NOT NULL
    )""")
    for key in sorted(set(keys)):
        cursor.execute(
            """INSERT INTO commerce_ledger_lock_key (lock_key, touched_at)
               VALUES (%s, UTC_TIMESTAMP(6))
               ON DUPLICATE KEY UPDATE touched_at=UTC_TIMESTAMP(6)""",
            (key[:64],),
        )
        cursor.execute("SELECT lock_key FROM commerce_ledger_lock_key WHERE lock_key=%s FOR UPDATE", (key[:64],))


class Ledger:
    def __init__(self, connect=connect_from_env):
        self.connect = connect

    def initialize(self):
        from smartlect.migrate import migrate
        migrate(self.connect)
        self.replay_pending()

    def ingest(self, body: bytes):
        """Return only after facts, exceptions and their accounting state commit together."""
        with self.connect() as connection, connection.cursor() as cursor:
            try:
                _lock_ledger(cursor, body=body)
                try:
                    batch = json.loads(body, parse_float=Decimal,
                                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
                    if not isinstance(batch, dict) or type(batch.get("schema_version")) is not int or batch["schema_version"] not in {1, 2}:
                        raise ValueError("unsupported or missing schema_version")
                    if not isinstance(batch.get("events"), list) or not 1 <= len(batch["events"]) <= 100:
                        raise ValueError("events must contain 1 to 100 objects")
                except (ValueError, UnicodeError) as error:
                    self._exception(cursor, body, str(error))
                else:
                    for event in batch["events"]:
                        try:
                            fact = parse_event(event, batch['schema_version'])
                        except (ValueError, TypeError, OverflowError) as error:
                            self._exception(cursor, canonical({"schema_version": batch['schema_version'], "events": [event]}).encode(), str(error))
                            continue
                        cursor.execute("SELECT event_id,idempotency_key,fingerprint FROM commerce_event WHERE event_id=%s OR idempotency_key=%s",
                                       (fact["event_id"], fact["idempotency_key"]))
                        prior = cursor.fetchall()
                        if prior:
                            if len(prior) != 1 or any(prior[0][key] != fact[key] for key in ("event_id", "idempotency_key", "fingerprint")):
                                self._exception(cursor, canonical({"schema_version": batch['schema_version'], "events": [event]}).encode(), "event/idempotency identity conflict")
                            continue
                        names = list(fact)
                        cursor.execute("INSERT INTO commerce_event (" + ",".join(names) + ") VALUES (" + ",".join(["%s"] * len(names)) + ")",
                                       tuple(fact[name] for name in names))
                        if batch['schema_version'] == 2 or fact['event_type'] in BEHAVIORS:
                            from smartlect.attribution import AttributionStore, event_metadata
                            scope = AttributionStore._scope(cursor, fact['user_id'])
                            metadata = event_metadata(event)
                            if fact['event_type'] not in {'PAYMENT', 'REFUND'}:
                                metadata = {'executionScopeId': scope, 'scopeSource': 'registered_user_or_default_store',
                                            'projectionVersion': NONFINANCIAL_SCOPE_VERSION, 'projectionSource': 'ledger_ingest',
                                            'producerDeclaredScope': event.get('payload', {}).get('executionScopeId')}
                            cursor.execute('INSERT INTO commerce_attribution_meta VALUES (%s,%s,%s)',
                                           (fact['event_id'], scope, canonical(metadata)))
                    self._reconcile(cursor)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _exception(cursor, body, reason):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cursor.execute("""INSERT INTO commerce_exception (message_hash,raw_body,reason,received_at,last_seen_at)
            VALUES (%s,%s,%s,%s,%s) AS incoming
            ON DUPLICATE KEY UPDATE occurrences=commerce_exception.occurrences+1,
            last_seen_at=incoming.last_seen_at""",
                       (hashlib.sha256(body).hexdigest(), body, reason[:500], now, now))

    def _reconcile(self, cursor):
        cursor.execute("SELECT * FROM commerce_event WHERE status='PENDING' ORDER BY event_type='PAYMENT' DESC,received_at,event_id")
        for fact in cursor.fetchall():
            kind = fact["event_type"]
            cursor.execute("SELECT * FROM commerce_event WHERE order_item_id=%s AND event_type='PAYMENT' AND status='APPLIED'",
                           (fact["order_item_id"],))
            payment = cursor.fetchone()
            status, reason = "APPLIED", None
            identity = ("pay_order_id", "order_id", "user_id", "product_id", "sku_key")
            if kind == "PAYMENT":
                cursor.execute("SELECT user_id FROM commerce_event WHERE pay_order_id=%s AND event_type='PAYMENT' AND status='APPLIED' LIMIT 1",
                               (fact["pay_order_id"],))
                owner = cursor.fetchone()
                if owner and owner["user_id"] != fact["user_id"]:
                    status, reason = "INVALID", "payment order owner conflict"
                elif payment:
                    same = all(payment[key] == fact[key] for key in (*identity, "amount_cents"))
                    status, reason = ("DUPLICATE", "payment item already accounted") if same else ("INVALID", "payment item conflict")
            elif not payment:
                status, reason = "PENDING", "awaiting payment item"
            elif any(payment[key] != fact[key] for key in identity):
                status, reason = "INVALID", "refund/payment identity mismatch"
            else:
                cursor.execute("SELECT COALESCE(SUM(amount_cents),0) AS cents FROM commerce_event WHERE order_item_id=%s AND event_type='REFUND' AND status='APPLIED'",
                               (fact["order_item_id"],))
                if cursor.fetchone()["cents"] + fact["amount_cents"] > payment["amount_cents"]:
                    status, reason = "INVALID", "refund exceeds paid item amount"
            cursor.execute("UPDATE commerce_event SET status=%s,reason=%s WHERE event_id=%s", (status, reason, fact["event_id"]))
        from smartlect.attribution import project_pending
        project_pending(cursor)

    def replay_pending(self):
        with self.connect() as connection, connection.cursor() as cursor:
            _lock_ledger(cursor)
            self._reconcile(cursor)
            connection.commit()

    def replay_exception(self, message_hash):
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT raw_body FROM commerce_exception WHERE message_hash=%s", (message_hash,))
            row = cursor.fetchone()
        if not row:
            raise ValueError("exception not found")
        self.ingest(row["raw_body"])

    def summary(self, pay_order_id=None):
        if pay_order_id is not None and (not pay_order_id or len(pay_order_id) > 64):
            raise ValueError("invalid payOrderId")
        where, args = (" WHERE pay_order_id=%s", (pay_order_id,)) if pay_order_id else ("", ())
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT event_type,status,COUNT(*) AS count FROM commerce_event" + where + " GROUP BY event_type,status", args)
            counts = list(cursor.fetchall())
            cursor.execute("""SELECT COALESCE(SUM(CASE WHEN event_type='PAYMENT' AND status='APPLIED' THEN amount_cents ELSE 0 END),0) AS paid,
                COALESCE(SUM(CASE WHEN event_type='REFUND' AND status='APPLIED' THEN amount_cents ELSE 0 END),0) AS refunded,
                COUNT(DISTINCT CASE WHEN event_type='PAYMENT' AND status='APPLIED' THEN pay_order_id END) AS conversions
                FROM commerce_event""" + where, args)
            totals = cursor.fetchone()
            cursor.execute("SELECT event_id,event_type,status,reason,pay_order_id,order_item_id,user_id,product_id,sku_key,source,amount_cents,occurred_at,received_at FROM commerce_event"
                           + where + " ORDER BY received_at,event_id LIMIT 1000", args)
            events = list(cursor.fetchall())
            cursor.execute("SELECT COUNT(*) AS count FROM commerce_exception")
            exceptions = cursor.fetchone()["count"]
        for event in events:
            for key in ("occurred_at", "received_at"):
                event[key] = event[key].isoformat() + "Z"
        paid, refunded = int(totals["paid"]), int(totals["refunded"])
        return {"payOrderId": pay_order_id, "paidCents": paid, "refundedCents": refunded,
                "netCents": paid - refunded, "paymentConversions": totals["conversions"],
                "counts": counts, "events": events, "exceptionMessages": exceptions}


def persist_then_ack(ledger, channel, delivery_tag, body):
    ledger.ingest(body)
    channel.basic_ack(delivery_tag=delivery_tag)


def consume(ledger, stop, status):
    while not stop.is_set():
        connection = None
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=required_env("SMARTLECT_RABBIT_HOST"), port=int(required_env("SMARTLECT_RABBIT_PORT")),
                virtual_host=required_env("SMARTLECT_RABBIT_VHOST"),
                credentials=pika.PlainCredentials(required_env("SMARTLECT_RABBIT_USER"), required_env("SMARTLECT_RABBIT_PASSWORD")),
                heartbeat=60, blocked_connection_timeout=10, socket_timeout=5))
            channel = connection.channel()
            # Java owns the durable queue and dead-letter policy; passive declare avoids mismatched arguments.
            channel.queue_declare(queue=QUEUE, passive=True)
            channel.basic_qos(prefetch_count=1)
            status.update(connected=True, error=None)
            for method, properties, body in channel.consume(QUEUE, auto_ack=False, inactivity_timeout=1):
                if stop.is_set():
                    break
                if method:
                    persist_then_ack(ledger, channel, method.delivery_tag, body)
        except Exception as error:
            status.update(connected=False, error=type(error).__name__)
            log.warning("Commerce consumer retry after %s", type(error).__name__)
        finally:
            status["connected"] = False
            if connection is not None and connection.is_open:
                try:
                    connection.close()  # Unacked deliveries return after rollback/connection loss.
                except pika.exceptions.AMQPError:
                    pass
        stop.wait(2)


def main():
    parser = argparse.ArgumentParser(description="Smartlect commerce ledger replay")
    parser.add_argument("--replay-exception", metavar="MESSAGE_HASH")
    args = parser.parse_args()
    ledger = Ledger()
    ledger.initialize()
    if args.replay_exception:
        ledger.replay_exception(args.replay_exception)
    else:
        ledger.replay_pending()
    print(json.dumps(ledger.summary()))


if __name__ == "__main__":
    main()
