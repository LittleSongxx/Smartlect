"""Opt-in real MySQL base: one disposable Smartlect-only container per test class.

2026-10 收敛重构：从 test_ledger_mysql.py 拆出容器/迁移基础设施；
commerce ledger 断言随 worker 线退役删除，state/maintenance/scope_reset
契约测试继续复用这套一次性 MySQL。
"""
import json
import os
import secrets
import subprocess
import time
import unittest
import uuid

import pymysql

from smartlect.migrate import migrate, migration_files


@unittest.skipUnless(os.getenv("SMARTLECT_RUN_MYSQL_TESTS") == "1", "set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL")
class DisposableMySQLTests(unittest.TestCase):
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
                        connection.cursor().execute("SELECT 1")
                    break
                except Exception:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.5)
            with cls.connect() as connection:
                migrate(cls.connect)
        except Exception:
            tearDownClass = cls.tearDownClass
            tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        if cls.container:
            info = json.loads(subprocess.check_output(["docker", "inspect", cls.container], text=True))[0]
            if info["Name"] != "/" + cls.name or info["Config"]["Labels"].get("com.smartlect.test") != "commerce-ledger":
                raise RuntimeError("refusing to remove unowned test container")
            subprocess.run(["docker", "rm", "-f", cls.container], check=True, capture_output=True, text=True)


async def csrf_headers(client, origin, path='/admin-api/assistant/session'):
    """One-time CSRF: every write must mint a fresh token from the session endpoint."""
    session = (await client.get(path)).json()
    return {'Origin': origin, 'X-CSRF-Token': session['csrf_token']}


def outcome(kind="PAYMENT", pay="pay-1", item="item-1", amount="90.00", **changes):
    import uuid
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
    import json
    return json.dumps({"schema_version": 1, "events": list(events)}).encode()
