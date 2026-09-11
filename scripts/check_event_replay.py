"""Replay only existing Java facts through a real unacked Rabbit delivery."""
import json
import argparse
import os
import subprocess
import base64
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pika
from smartlect.events import Ledger, QUEUE
from runtime import ROOT, ENV_FILE, parse_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=str, default="artifacts/amqp-replay.json")
    parser.add_argument('--schema-version', type=int, choices=(1, 2))
    parser.add_argument('--event-ids-file', type=Path, help='JSON array of 1–100 exact existing Java event IDs')
    args = parser.parse_args()
    env = parse_env(ENV_FILE)
    os.environ.update(env)
    ledger = Ledger()
    def queue_status():
        credentials = base64.b64encode((env["SMARTLECT_RABBIT_USER"] + ":" + env["SMARTLECT_RABBIT_PASSWORD"]).encode()).decode()
        request = Request("http://127.0.0.1:" + env["SMARTLECT_RABBIT_MANAGEMENT_PORT"]
                          + "/api/queues/smartlect/" + QUEUE,
                          headers={"Authorization": "Basic " + credentials})
        with urlopen(request, timeout=5) as response:
            return json.load(response)
    ack_before = queue_status().get("message_stats", {}).get("ack", 0)
    expected = ledger.summary()
    with ledger.connect() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT MAX(schema_version) AS version FROM commerce_event')
        version = args.schema_version or cursor.fetchone()['version']
        if args.event_ids_file:
            identifiers=json.loads(args.event_ids_file.read_text())
            if (not isinstance(identifiers,list) or not 1 <= len(identifiers) <= 100 or
                    any(not isinstance(value,str) or not value.strip() or len(value)>128 for value in identifiers) or
                    len(set(identifiers))!=len(identifiers)):
                raise ValueError('Use 1–100 distinct existing event IDs')
            cursor.execute('SELECT event_id,raw_json,status,schema_version FROM commerce_event WHERE event_id IN ('+
                           ','.join(['%s']*len(identifiers))+') ORDER BY event_id',tuple(identifiers))
            rows=list(cursor.fetchall())
            if {r['event_id'] for r in rows}!=set(identifiers) or any(r['schema_version']!=version or r['status']!='APPLIED' for r in rows):
                raise ValueError('Selected replay facts must all exist, be APPLIED and share the requested schema')
        else:
            cursor.execute('SELECT raw_json FROM commerce_event WHERE schema_version=%s ORDER BY event_id LIMIT 100', (version,))
            rows=list(cursor.fetchall())
        batch = {"schema_version": version, "events": [json.loads(row["raw_json"]) for row in rows]}
    if not batch['events']:
        raise RuntimeError('This check requires existing Java facts of the selected schema version')

    def projections():
        with ledger.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'commerce_attribution'")
            if not cursor.fetchone():
                return []
            ids = [event['eventId'] for event in batch['events']]
            cursor.execute('SELECT * FROM commerce_attribution WHERE event_id IN (' + ','.join(['%s'] * len(ids)) + ') ORDER BY event_id', ids)
            return list(cursor.fetchall())
    projected_before = projections()
    # The bundled growth Python omits pidfd APIs; keep process control on the
    # system interpreter already verified by the runtime entry point.
    runtime_import = "from runtime import *; env=parse_env(ENV_FILE); records=load_processes(); "
    subprocess.run(["/usr/bin/python3", "-c", runtime_import + "stop_process(records['growth-worker'])"],
                   cwd=ROOT / "scripts", check=True)
    transport = None
    try:
        transport = pika.BlockingConnection(pika.ConnectionParameters(
            host=env["SMARTLECT_RABBIT_HOST"], port=int(env["SMARTLECT_RABBIT_PORT"]),
            virtual_host=env["SMARTLECT_RABBIT_VHOST"],
            credentials=pika.PlainCredentials(env["SMARTLECT_RABBIT_USER"], env["SMARTLECT_RABBIT_PASSWORD"]),
            socket_timeout=5, blocked_connection_timeout=10))
        channel = transport.channel()
        if channel.queue_declare(queue=QUEUE, passive=True).method.message_count != 0:
            raise RuntimeError("Wait for the existing queue to drain before this isolated replay check")
        channel.confirm_delivery()
        channel.basic_publish("smartlect.commerce.outcome.exchange", "smartlect.commerce.outcome",
                              json.dumps(batch).encode(), mandatory=True,
                              properties=pika.BasicProperties(content_type="application/json", delivery_mode=2))
        delivery, _, body = channel.basic_get(QUEUE, auto_ack=False)
        assert delivery is not None
        ledger.ingest(body)  # Same durable transaction used by the production consumer.
        channel.close()     # Simulate a lost process/connection after commit, before ACK.
        channel = transport.channel()
        redelivery, _, _ = channel.basic_get(QUEUE, auto_ack=False)
        assert redelivery is not None and redelivery.redelivered
        channel.close()     # Leave delivery unacked for the restarted real consumer.
        transport.close()
        transport = None
    finally:
        if transport and transport.is_open:
            transport.close()
        subprocess.run(["/usr/bin/python3", "-c", runtime_import
                        + "start_app('growth-worker',env,records); wait_apps(['growth-worker'],records)"],
                       cwd=ROOT / "scripts", check=True)
    deadline = time.monotonic() + 20
    while True:
        with pika.BlockingConnection(pika.ConnectionParameters(
                host=env["SMARTLECT_RABBIT_HOST"], port=int(env["SMARTLECT_RABBIT_PORT"]),
                virtual_host=env["SMARTLECT_RABBIT_VHOST"],
                credentials=pika.PlainCredentials(env["SMARTLECT_RABBIT_USER"], env["SMARTLECT_RABBIT_PASSWORD"]))) as check:
            empty = check.channel().queue_declare(queue=QUEUE, passive=True).method.message_count == 0
        actual = ledger.summary()
        assert actual == expected, "Replay changed committed facts or accounting totals"
        assert projections() == projected_before, 'Replay changed frozen attribution'
        broker = queue_status()
        ack_after = broker.get("message_stats", {}).get("ack", 0)
        if empty and broker.get("messages_unacknowledged") == 0 and ack_after > ack_before:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("Restarted consumer did not drain redelivered facts")
        time.sleep(0.2)
    result = {"persisted_before_ack": True, "broker_redelivered": True, "consumer_restarted": True,
              "schema_version": version, 'replayed_event_count': len(batch['events']), 'attribution_unchanged': True,
              'replayed_event_ids':[event['eventId'] for event in batch['events']],
              "ledger_unchanged": True, "broker_ack_verified": True, "event_count": sum(row['count'] for row in actual['counts']),
              "paid_cents": actual["paidCents"], "refunded_cents": actual["refundedCents"],
              "payment_conversions": actual["paymentConversions"]}
    (ROOT / args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
