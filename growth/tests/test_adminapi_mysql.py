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
from smartlect.provider import Provider
from smartlect.events import canonical
from smartlect.state import SessionStore
import test_ledger_mysql
from test_ledger_mysql import csrf_headers


@unittest.skipUnless(os.getenv("SMARTLECT_RUN_MYSQL_TESTS") == "1", "set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL")
class AdminApiMySQLTests(unittest.TestCase):
    setUpClass = classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    def test_runs_browser_lists_scope_runs_and_debug_invoke_is_audited(self):
        asyncio.run(self.exercise())

    def test_publish_runs_async_index_job_to_published(self):
        asyncio.run(self.exercise_indexing())

    def test_product_knowledge_import_creates_auto_draft_and_publishes(self):
        asyncio.run(self.exercise_import())

    def test_prompt_templates_seed_edit_activate_and_resolve(self):
        asyncio.run(self.exercise_prompts())

    async def exercise_import(self):
        suffix = uuid.uuid4().hex
        origin = "http://smartlect.test"
        config = {"SMARTLECT_USER_PORT": "18105", "SMARTLECT_ORDER_PORT": "18104",
                  "SMARTLECT_PRODUCT_PORT": "18102", "SMARTLECT_STOCK_PORT": "18103",
                  "SMARTLECT_INTERNAL_TOKEN": "synthetic", "SMARTLECT_VISITOR_SECRET": "s" * 48,
                  "SMARTLECT_ALLOWED_ORIGINS": origin}

        def java(request):
            path = request.url.path
            if path == "/internal/identity/introspect":
                data = {"subjectType": "merchant", "actorId": "boss-" + suffix, "sessionId": "boss-session",
                        "permissions": ["admin:legacy", "shopping:read"]}
            elif path == "/internal/product/commerce/batchDetail":
                self.assertEqual(json.loads(request.content), {"productIds": ["p-imp-" + suffix]})
                data = [{"productId": "p-imp-" + suffix, "productName": "导入测试商品", "status": 1,
                         "minPrice": "10.00", "maxPrice": "20.00", "totalStock": 3, "inStock": True,
                         "description": "导入的商品描述，用于知识生成。",
                         "propertyValues": [{"propertyName": "品牌", "propertyValue": "Smartlect"}]}]
            else:
                raise AssertionError(path)
            return httpx.Response(200, json={"status": "success", "data": data})

        transport = httpx.MockTransport(java)

        def app():
            return create_app(Settings(), config=config, store=SessionStore(self.connect),
                              identity=IdentityBridge(config, transport=transport),
                              commerce=AsyncCommerceClient(config, transport=transport))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url=origin) as client:
            client.cookies.set("adminToken", "boss-" + suffix)
            headers = await csrf_headers(client, origin)

            imported = await client.post("/admin-api/assistant/knowledgeImport/products", headers=headers,
                                         json={"productIds": ["p-imp-" + suffix]})
            self.assertEqual(imported.status_code, 200, imported.text)
            summary = imported.json()
            if summary["imported"] != ["p-imp-" + suffix]: self.fail(repr(summary))

            documents = (await client.get("/admin-api/assistant/knowledge")).json()
            row = next(item for item in documents if item["doc_id"] == "product-p-imp-" + suffix)
            self.assertEqual(row["status"], "PUBLISHED")
            self.assertEqual(row["source_type"], "PRODUCT_AUTO")

            again = await client.post("/admin-api/assistant/knowledgeImport/products",
                                      headers=await csrf_headers(client, origin),
                                      json={"productIds": ["p-imp-" + suffix]})
            self.assertEqual(again.json()["imported"], ["p-imp-" + suffix])
            documents = (await client.get("/admin-api/assistant/knowledge")).json()
            versions = [item for item in documents if item["doc_id"] == "product-p-imp-" + suffix]
            published = [item for item in versions if item["status"] == "PUBLISHED"]
            self.assertEqual(len(published), 1)

    async def exercise_indexing(self):
        suffix = uuid.uuid4().hex
        origin = "http://smartlect.test"
        config = {"SMARTLECT_USER_PORT": "18105", "SMARTLECT_ORDER_PORT": "18104",
                  "SMARTLECT_PRODUCT_PORT": "18102", "SMARTLECT_STOCK_PORT": "18103",
                  "SMARTLECT_INTERNAL_TOKEN": "synthetic", "SMARTLECT_VISITOR_SECRET": "s" * 48,
                  "SMARTLECT_ALLOWED_ORIGINS": origin,
                  "SMARTLECT_EMBEDDING_API_KEY": "synthetic-embedding-key",
                  "SMARTLECT_EMBEDDING_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                  "SMARTLECT_EMBEDDING_MODEL": "text-embedding-v4"}

        def java(request):
            if request.url.path == "/internal/identity/introspect":
                data = {"subjectType": "merchant", "actorId": "boss-" + suffix, "sessionId": "boss-session",
                        "permissions": ["admin:legacy", "shopping:read"]}
                return httpx.Response(200, json={"status": "success", "data": data})
            if request.url.path.endswith("/embeddings"):
                return httpx.Response(200, json={"model": "text-embedding-v4",
                                                 "data": [{"index": 0, "embedding": [0.1] * 1024}],
                                                 "usage": {"prompt_tokens": 4, "total_tokens": 4}})
            raise AssertionError(request.url.path)

        transport = httpx.MockTransport(java)

        def app():
            return create_app(Settings(model_mode="live"), config=config, store=SessionStore(self.connect),
                              identity=IdentityBridge(config, transport=transport),
                              commerce=AsyncCommerceClient(config, transport=transport),
                              provider=Provider(config, transport=transport))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url=origin) as client:
            client.cookies.set("adminToken", "boss-" + suffix)
            headers = await csrf_headers(client, origin)
            draft = await client.post("/admin-api/assistant/knowledge", headers=headers, json={
                "doc_id": "ops-doc-" + suffix, "title": "运维测试文档", "body": "退款政策原文：七天内可退。" * 30,
                "source_uri": "test://ops/" + suffix, "acl": "MERCHANT",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "valid_until": "2030-01-01T00:00:00+00:00"})
            self.assertEqual(draft.status_code, 200, draft.text)
            version = draft.json()["version"]

            published = await client.post(f"/admin-api/assistant/knowledge/ops-doc-{suffix}/{version}/publish",
                                          headers=await csrf_headers(client, origin), json={})
            self.assertEqual(published.status_code, 200, published.text)
            job = published.json()
            self.assertIn(job["state"], ("PENDING", "RUNNING"))
            self.assertGreater(job["total_chunks"], 0)

            for _ in range(100):
                await asyncio.sleep(0.05)
                poll = await client.get(f"/admin-api/assistant/knowledgeIndex/jobs/{job['job_id']}")
                if poll.status_code != 200:
                    raise AssertionError(f"poll {poll.status_code}: {poll.text}")
                job = poll.json()
                if job["state"] in ("DONE", "FAILED"):
                    break
            self.assertEqual(job["state"], "DONE", job)
            self.assertEqual(job["processed_chunks"], job["total_chunks"])

            documents = (await client.get("/admin-api/assistant/knowledge")).json()
            row = next(item for item in documents if item["doc_id"] == "ops-doc-" + suffix)
            self.assertEqual(row["status"], "PUBLISHED")

            probe = await client.post("/admin-api/assistant/knowledgeIndex/searchProbe",
                                      headers=await csrf_headers(client, origin),
                                      json={"query": "退款政策"})
            self.assertEqual(probe.status_code, 200, probe.text)
            self.assertGreaterEqual(len(probe.json().get("citations", [])), 1)

            no_permission = await client.get("/admin-api/assistant/knowledgeIndex/jobs")
            self.assertEqual(no_permission.status_code, 200)  # same merchant, still admin:legacy

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
            headers = await csrf_headers(client, origin)

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

            write_attempt = await client.post("/admin-api/assistant/tools/invoke",
                                              headers=await csrf_headers(client, origin),
                                              json={"name": "propose_order", "arguments": {}})
            self.assertEqual(write_attempt.status_code, 422)

            listed = (await client.get("/admin-api/assistant/runs", params={"agent": "debug"})).json()
            # Both the successful call and the rejected write attempt leave an audit run.
            self.assertEqual({item["state"] for item in listed["items"]}, {"COMPLETED", "FAILED"})
            self.assertTrue(all(item["agent"] == "debug" for item in listed["items"]))

            no_csrf = await client.post("/admin-api/assistant/tools/invoke",
                                        json={"name": "get_product_offer", "arguments": {"productId": "p-debug"}})
            self.assertEqual(no_csrf.status_code, 403)



    async def exercise_prompts(self):
        from smartlect import prompts as prompt_registry
        suffix = uuid.uuid4().hex
        origin = "http://smartlect.test"
        config = {"SMARTLECT_USER_PORT": "18105", "SMARTLECT_INTERNAL_TOKEN": "synthetic",
                  "SMARTLECT_VISITOR_SECRET": "s" * 48, "SMARTLECT_ALLOWED_ORIGINS": origin}

        def java(request):
            if request.url.path == "/internal/identity/introspect":
                data = {"subjectType": "merchant", "actorId": "boss-" + suffix, "sessionId": "s",
                        "permissions": ["admin:legacy", "shopping:read"]}
                return httpx.Response(200, json={"status": "success", "data": data})
            raise AssertionError(request.url.path)

        transport = httpx.MockTransport(java)

        def app():
            return create_app(Settings(), config=config, store=SessionStore(self.connect),
                              identity=IdentityBridge(config, transport=transport),
                              commerce=AsyncCommerceClient(config, transport=transport))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url=origin) as client:
            client.cookies.set("adminToken", "boss-" + suffix)
            headers = await csrf_headers(client, origin)

            keys = (await client.get("/admin-api/assistant/prompts", params={"domain": "shopping"})).json()
            shopping_keys = keys["domains"]["shopping"]
            self.assertTrue(any(k["kind"] == "system_prompt" and k["active_count"] == 1 for k in shopping_keys))
            self.assertTrue(any(k["key"] == "support_policy" for k in shopping_keys))

            from smartlect.agents.shopping import PROMPT_VERSION
            from smartlect.prompts import _code_version
            seeded = _code_version(PROMPT_VERSION)
            versions = (await client.get("/admin-api/assistant/prompts/shopping/system_prompt/system/versions")).json()["items"]
            self.assertEqual(versions[0]["version"], seeded)  # continuity with the code label
            seeded_body = (await client.get(
                f"/admin-api/assistant/prompts/shopping/system_prompt/system/{seeded}")).json()["body"]

            edited = await client.post("/admin-api/assistant/prompts/shopping/system_prompt/system",
                                       headers=headers, json={"body": seeded_body + "\n补充规则：测试追加。"})
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(edited.json()["version"], seeded + 1)

            activated = await client.post(
                f"/admin-api/assistant/prompts/shopping/system_prompt/system/{seeded + 1}/activate",
                headers=await csrf_headers(client, origin), json={})
            self.assertEqual(activated.json()["status"], "active")

            body, label = prompt_registry.resolve_system(self.connect, "shopping", "DEFAULT", PROMPT_VERSION)
            self.assertIn("补充规则：测试追加。", body)
            self.assertEqual(label, f"shopping-react-v{seeded + 1}")

            bad = await client.post("/admin-api/assistant/prompts/shopping/skill/brand_new",
                                    headers=await csrf_headers(client, origin), json={"body": "{}"})
            self.assertEqual(bad.status_code, 422)


    def seed_scope_payment(self, suffix):
        """One attributed payment plus an unrelated refund in the default `store` scope."""
        with self.connect() as connection, connection.cursor() as cursor:
            for event_id, kind, amount, pay_order_id in (
                    ("evt-pay-" + suffix, "PAYMENT", 1000, "pay-" + suffix),
                    ("evt-refund-" + suffix, "REFUND", 200, "refund-" + suffix)):
                cursor.execute("""INSERT INTO commerce_event (event_id,idempotency_key,event_type,user_id,source,
                    pay_order_id,amount_cents,occurred_at,received_at,schema_version,raw_json,fingerprint,status)
                    VALUES (%s,%s,%s,'u1','test',%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),2,'{}',%s,'APPLIED')""",
                    (event_id, event_id, kind, pay_order_id, amount, "f" * 64))
                cursor.execute("""INSERT INTO commerce_attribution (event_id,execution_scope_id,category,
                    calculation_status,reason,rule_version,as_of) VALUES (%s,'store','NATURAL_VERIFIED',
                    'APPLIED','test_fixture','test-v1',UTC_TIMESTAMP(6))""", (event_id,))
            connection.commit()  # pymysql's connection context manager closes without committing

if __name__ == "__main__":
    unittest.main()



    async def exercise_prompts(self):
        from smartlect import prompts as prompt_registry
        suffix = uuid.uuid4().hex
        origin = "http://smartlect.test"
        config = {"SMARTLECT_USER_PORT": "18105", "SMARTLECT_INTERNAL_TOKEN": "synthetic",
                  "SMARTLECT_VISITOR_SECRET": "s" * 48, "SMARTLECT_ALLOWED_ORIGINS": origin}

        def java(request):
            if request.url.path == "/internal/identity/introspect":
                data = {"subjectType": "merchant", "actorId": "boss-" + suffix, "sessionId": "s",
                        "permissions": ["admin:legacy", "shopping:read"]}
                return httpx.Response(200, json={"status": "success", "data": data})
            raise AssertionError(request.url.path)

        transport = httpx.MockTransport(java)

        def app():
            return create_app(Settings(), config=config, store=SessionStore(self.connect),
                              identity=IdentityBridge(config, transport=transport),
                              commerce=AsyncCommerceClient(config, transport=transport))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url=origin) as client:
            client.cookies.set("adminToken", "boss-" + suffix)
            headers = await csrf_headers(client, origin)

            keys = (await client.get("/admin-api/assistant/prompts", params={"domain": "shopping"})).json()
            shopping_keys = keys["domains"]["shopping"]
            self.assertTrue(any(k["kind"] == "system_prompt" and k["active_count"] == 1 for k in shopping_keys))
            self.assertTrue(any(k["key"] == "support_policy" for k in shopping_keys))

            from smartlect.agents.shopping import PROMPT_VERSION
            from smartlect.prompts import _code_version
            seeded = _code_version(PROMPT_VERSION)
            versions = (await client.get("/admin-api/assistant/prompts/shopping/system_prompt/system/versions")).json()["items"]
            self.assertEqual(versions[0]["version"], seeded)  # continuity with the code label
            seeded_body = (await client.get(
                f"/admin-api/assistant/prompts/shopping/system_prompt/system/{seeded}")).json()["body"]

            edited = await client.post("/admin-api/assistant/prompts/shopping/system_prompt/system",
                                       headers=headers, json={"body": seeded_body + "\n补充规则：测试追加。"})
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(edited.json()["version"], seeded + 1)

            activated = await client.post(
                f"/admin-api/assistant/prompts/shopping/system_prompt/system/{seeded + 1}/activate",
                headers=await csrf_headers(client, origin), json={})
            self.assertEqual(activated.json()["status"], "active")

            body, label = prompt_registry.resolve_system(self.connect, "shopping", "DEFAULT", PROMPT_VERSION)
            self.assertIn("补充规则：测试追加。", body)
            self.assertEqual(label, f"shopping-react-v{seeded + 1}")

            # Structural edits stay code-owned: unknown skill ids and broken JSON are rejected.
            bad = await client.post("/admin-api/assistant/prompts/shopping/skill/brand_new",
                                    headers=await csrf_headers(client, origin), json={"body": "{}"})
            self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
