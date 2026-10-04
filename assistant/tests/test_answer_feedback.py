"""HTTP contract for answer feedback: ownership, CSRF, idempotent re-rating with real MySQL."""
import asyncio
import os
import unittest
import uuid

import httpx

from smartlect.app import create_app
from smartlect.auth import ActorContext, IdentityBridge
from smartlect.commerce import AsyncCommerceClient
from smartlect.config import Settings
from smartlect.db import canonical
from smartlect.state import SessionStore
import test_mysql_base
from test_mysql_base import csrf_headers


@unittest.skipUnless(os.getenv("SMARTLECT_RUN_MYSQL_TESTS") == "1", "set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL")
class AnswerFeedbackMySQLTests(unittest.TestCase):
    setUpClass = classmethod(test_mysql_base.DisposableMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_mysql_base.DisposableMySQLTests.tearDownClass.__func__)

    def test_feedback_write_requires_csrf_owned_run_and_upserts(self):
        asyncio.run(self.exercise())

    async def exercise(self):
        suffix = uuid.uuid4().hex
        origin = "http://smartlect.test"

        def java(request):
            path = request.url.path
            if path.endswith("/identity/introspect"):
                actor = request.headers["cookie"].split("=", 1)[1]
                return httpx.Response(200, json={"status": "success", "data": {
                    "subjectType": "user", "actorId": actor, "sessionId": actor + "-session",
                    "permissions": ["shopping:read", "orders:read", "orders:write"]}})
            raise AssertionError(path)

        config = {"SMARTLECT_USER_PORT": "18105", "SMARTLECT_ORDER_PORT": "18104",
                  "SMARTLECT_INTERNAL_TOKEN": "synthetic", "SMARTLECT_VISITOR_SECRET": "s" * 48,
                  "SMARTLECT_ALLOWED_ORIGINS": origin}
        transport = httpx.MockTransport(java)

        def app():
            return create_app(Settings(), config=config, store=SessionStore(self.connect),
                              identity=IdentityBridge(config, transport=transport),
                              commerce=AsyncCommerceClient(config, transport=transport))

        # Seed one completed run owned by alice straight through the store.
        alice = ActorContext(subject_type="user", actor_id="alice-" + suffix,
                             permissions=("shopping:read", "orders:read", "orders:write"),
                             session_id="alice-session")
        seeded = SessionStore(self.connect)
        conversation = seeded.create_conversation(alice)
        run = seeded.create_run(alice, conversation["conversation_id"], "seed-" + suffix,
                                canonical({"text": "怎么退货"}), model_mode="mock")
        lease = seeded.claim_run(alice, run["agent_run_id"], owner="seed", ttl_seconds=30)
        seeded.finish_run(lease, state="COMPLETED", result={"answer": "按售后政策办理"})
        run_id = run["agent_run_id"]
        feedback_path = f"/api/assistant/runs/{run_id}/feedback"

        def rows():
            with self.connect() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT rating,reason_code,reason_text FROM answer_feedback WHERE agent_run_id=%s", (run_id,))
                return cursor.fetchall()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url=origin) as client:
            client.cookies.set("token", "alice-" + suffix)
            headers = await csrf_headers(client, origin, "/api/assistant/session")

            # 1. Fresh thumbs-up lands in the DB.
            up = await client.post(feedback_path, json={"rating": "up"}, headers=headers)
            self.assertEqual(up.status_code, 200, up.text)
            self.assertEqual(up.json(), {"agent_run_id": run_id, "rating": "up", "updated": False})
            self.assertEqual(rows(), [{"rating": "up", "reason_code": None, "reason_text": None}])

            # 5. Same actor re-rates thumbs-down: update in place, still one row.
            down = await client.post(feedback_path, headers=await csrf_headers(client, origin, "/api/assistant/session"),
                                     json={"rating": "down", "reason_code": "outdated", "reason_text": "政策已更新"})
            self.assertEqual(down.status_code, 200, down.text)
            self.assertEqual(down.json(), {"agent_run_id": run_id, "rating": "down", "updated": True})
            stored = rows()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["rating"], "down")
            self.assertEqual(stored[0]["reason_code"], "outdated")

            # 6/7. Validation: oversized reason_text and unknown rating are 422s, no extra rows.
            long = await client.post(feedback_path, headers=await csrf_headers(client, origin, "/api/assistant/session"),
                                     json={"rating": "down", "reason_text": "x" * 2001})
            self.assertEqual(long.status_code, 422)
            bad_rating = await client.post(feedback_path, headers=await csrf_headers(client, origin, "/api/assistant/session"),
                                           json={"rating": "meh"})
            self.assertEqual(bad_rating.status_code, 422)
            bad_reason = await client.post(feedback_path, headers=await csrf_headers(client, origin, "/api/assistant/session"),
                                           json={"rating": "down", "reason_code": "spite"})
            self.assertEqual(bad_reason.status_code, 422)
            self.assertEqual(len(rows()), 1)

            # 3. Unknown run id is a 404 even with full auth.
            missing = await client.post(f"/api/assistant/runs/{'0' * 32}/feedback",
                                        headers=await csrf_headers(client, origin, "/api/assistant/session"),
                                        json={"rating": "up"})
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()["error"], "run_not_found")

            # 2. A write without Origin/nonce never reaches the store.
            self.assertEqual((await client.post(feedback_path, json={"rating": "up"})).status_code, 403)

            # 4. Another user's session cannot rate alice's run.
            client.cookies.set("token", "bob-" + suffix)
            foreign = await client.post(feedback_path,
                                        headers=await csrf_headers(client, origin, "/api/assistant/session"),
                                        json={"rating": "up"})
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(len(rows()), 1)


if __name__ == "__main__":
    unittest.main()
