"""Opt-in HTTP contract for the admin runs browser and tool debug console (real MySQL)."""
import asyncio
import json
import os
import unittest
import uuid

import httpx

from smartlect.app import create_app
from smartlect.auth import ActorContext, IdentityBridge
from smartlect.commerce import AsyncCommerceClient
from smartlect.config import Settings
from smartlect.events import canonical
from smartlect.state import SessionStore
import test_ledger_mysql


@unittest.skipUnless(os.getenv("SMARTLECT_RUN_MYSQL_TESTS") == "1", "set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL")
class AdminApiMySQLTests(unittest.TestCase):
    setUpClass = classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    def test_runs_browser_lists_scope_runs_and_debug_invoke_is_audited(self):
        asyncio.run(self.exercise())

    async def exercise(self):
        suffix = uuid.uuid4().hex
        origin = "http://smartlect.test"
        config = {"SMARTLECT_USER_PORT": "18105", "SMARTLECT_ORDER_PORT": "18104",
                  "SMARTLECT_PRODUCT_PORT": "18102", "SMARTLECT_STOCK_PORT": "18103",
                  "SMARTLECT_INTERNAL_TOKEN": "synthetic", "SMARTLECT_VISITOR_SECRET": "s" * 48,
                  "SMARTLECT_ALLOWED_ORIGINS": origin}

        def java(request):
            path = request.url.path
            if path == "/internal/identity/introspect":
                # realm merchant comes from the adminToken cookie; user realm seeds a shopping run.
                realm = json.loads(request.content)["realm"]
                if realm == "merchant":
                    data = {"subjectType": "merchant", "actorId": "boss-" + suffix, "sessionId": "boss-session",
                            "permissions": ["admin:legacy", "shopping:read"]}
                else:
                    data = {"subjectType": "user", "actorId": "alice-" + suffix, "sessionId": "alice-session",
                            "permissions": ["shopping:read", "orders:read", "orders:write"]}
            elif path == "/internal/product/commerce/getDetail":
                self.assertEqual(json.loads(request.content), {"productId": "p-debug"})
                data = {"productId": "p-debug", "productName": "调试商品", "status": 1}
            else:
                raise AssertionError(path)
            return httpx.Response(200, json={"status": "success", "data": data})

        transport = httpx.MockTransport(java)

        def app():
            return create_app(Settings(), config=config, store=SessionStore(self.connect),
                              identity=IdentityBridge(config, transport=transport),
                              commerce=AsyncCommerceClient(config, transport=transport))

        # Seed one user shopping run in the same execution scope ('store') straight through the store.
        seeded = SessionStore(self.connect)
        alice = ActorContext(subject_type="user", actor_id="alice-" + suffix,
                             permissions=("shopping:read", "orders:read", "orders:write"),
                             session_id="alice-session")
        conversation = seeded.create_conversation(alice)
        run = seeded.create_run(alice, conversation["conversation_id"], "seed-" + suffix,
                                canonical({"text": "hello"}), model_mode="mock")
        lease = seeded.claim_run(alice, run["agent_run_id"], owner="seed", ttl_seconds=30)
        seeded.finish_run(lease, state="COMPLETED", result={"decision": {"answer_status": "answered"}})

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url=origin) as client:
            # A plain user session must not reach the admin surface.
            client.cookies.set("token", "alice-" + suffix)
            self.assertEqual((await client.get("/admin-api/assistant/runs")).status_code, 401)

            client.cookies.delete("token")
            client.cookies.set("adminToken", "boss-" + suffix)
            session = (await client.get("/admin-api/assistant/session")).json()
            self.assertEqual(session["actor"]["subject_type"], "merchant")
            headers = {"Origin": origin, "X-CSRF-Token": session["csrf_token"]}

            listed = (await client.get("/admin-api/assistant/runs")).json()
            seeded_row = next(item for item in listed["items"] if item["agent_run_id"] == run["agent_run_id"])
            self.assertEqual(seeded_row["agent"], "shopping")
            self.assertFalse(seeded_row["context_empty"] is None)
            self.assertEqual(seeded_row["result"]["decision"]["answer_status"], "answered")

            detail = (await client.get(f"/admin-api/assistant/runs/{run['agent_run_id']}")).json()
            self.assertEqual(detail["agent"], "shopping")
            self.assertIn("tool_calls", detail)
            self.assertIn("events", detail)
            self.assertNotIn("content", json.dumps(detail))  # message bodies never leave this surface

            catalog = (await client.get("/admin-api/assistant/tools/catalog")).json()
            self.assertTrue(all("name" in item for item in catalog["tools"]))

            # Debug invoke: read-only tool, real Java read, audited as its own run.
            debugged = await client.post("/admin-api/assistant/tools/invoke", headers=headers,
                                         json={"name": "get_product_offer", "arguments": {"productId": "p-debug"}})
            self.assertEqual(debugged.status_code, 200, debugged.text)
            body = debugged.json()
            self.assertEqual(body["receipt"]["data"]["productName"], "调试商品")

            write_attempt = await client.post("/admin-api/assistant/tools/invoke", headers=headers,
                                              json={"name": "propose_order", "arguments": {}})
            self.assertEqual(write_attempt.status_code, 422)

            listed = (await client.get("/admin-api/assistant/runs", params={"agent": "debug"})).json()
            # Both the successful call and the rejected write attempt leave an audit run.
            self.assertEqual({item["state"] for item in listed["items"]}, {"COMPLETED", "FAILED"})
            self.assertTrue(all(item["agent"] == "debug" for item in listed["items"]))

            no_csrf = await client.post("/admin-api/assistant/tools/invoke",
                                        json={"name": "get_product_offer", "arguments": {"productId": "p-debug"}})
            self.assertEqual(no_csrf.status_code, 403)


if __name__ == "__main__":
    unittest.main()
