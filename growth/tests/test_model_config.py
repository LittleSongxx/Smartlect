"""Runtime model config: whitelist guard, env fallback, endpoint-family options, endpoint surface."""
import asyncio
import json
import unittest
import uuid
from unittest.mock import MagicMock, Mock

import httpx

from smartlect.auth import ActorContext
from smartlect.config import Settings
from smartlect.model_config import ModelConfigStore
from smartlect.provider import CHAT_MODEL_WHITELIST, Provider, ProviderError
from smartlect.state import StateError
from test_provider import CONFIG, completion

ACTOR = ActorContext(subject_type="merchant", actor_id="boss", session_id="s",
                     permissions=("admin:legacy",), execution_scope_id="scope")


def mock_connect():
    connection, cursor = MagicMock(), MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.rowcount = 1
    cursor.fetchone.return_value = {"role": "chat", "model_id": "qwen3.7-plus", "params": None,
                                    "note": None, "updated_by": "boss", "updated_at": "2026-09-16T00:00:00Z"}
    return Mock(return_value=connection), cursor


class ProviderRuntimeTests(unittest.TestCase):
    def test_runtime_override_applies_within_whitelist_and_falls_back_to_env(self):
        bodies = []

        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=completion())

        selection = {"chat_model_id": "qwen3.7-plus-2026-05-26"}
        provider = Provider(CONFIG, transport=httpx.MockTransport(handler),
                            runtime_loader=lambda: _async(selection))
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}], max_tokens=8, max_attempts=1))
        self.assertEqual(bodies[0]["model"], "qwen3.7-plus-2026-05-26")

        selection.clear()  # empty DB selection -> env snapshot
        provider.invalidate_runtime_cache()
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}], max_tokens=8, max_attempts=1))
        self.assertEqual(bodies[1]["model"], CONFIG.get("SMARTLECT_MODEL_ID", "qwen3.7-plus"))

    def test_loader_failure_keeps_last_known_state(self):
        def flaky():
            raise RuntimeError("db down")

        provider = Provider(CONFIG, runtime_loader=flaky)
        asyncio.run(provider._apply_runtime_config())
        self.assertIsNone(provider._runtime_model)  # no crash, env model stays effective
        self.assertIn(provider.model_id, CHAT_MODEL_WHITELIST)

    def test_endpoint_family_restricts_runtime_options(self):
        dashscope = Provider({**CONFIG, "SMARTLECT_MODEL_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1"})
        self.assertEqual(dashscope.runtime_chat_options(), ["qwen3.7-plus", "qwen3.7-plus-2026-05-26"])
        zhipu = Provider({**CONFIG, "SMARTLECT_MODEL_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
                          "SMARTLECT_MODEL_API_KEY": "k"})
        self.assertEqual(zhipu.runtime_chat_options(), ["glm-5.3"])


class ModelConfigStoreTests(unittest.TestCase):
    def test_save_validates_whitelist(self):
        connect, _ = mock_connect()
        store = ModelConfigStore(connect)
        with self.assertRaises(StateError):
            store.save_chat(ACTOR, "gpt-4o")
        row = store.save_chat(ACTOR, "qwen3.7-plus", note="默认")
        self.assertEqual(row["model_id"], "qwen3.7-plus")


def _async(value):
    async def call():
        if isinstance(value, Exception):
            raise value
        return value
    return call()


if __name__ == "__main__":
    unittest.main()
