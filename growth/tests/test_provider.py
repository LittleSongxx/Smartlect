"""Provider protocol, retry, disclosure and total-concurrency checks; no live keys."""

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import httpx

from smartlect.provider import IndexModelAudit, Provider, ProviderError, index_trace
from smartlect.state import StateError


CONFIG = {"SMARTLECT_MODEL_API_KEY": "test-secret-do-not-log",
          "SMARTLECT_MODEL_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
          "SMARTLECT_MODEL_ID": "qwen3.7-plus", "SMARTLECT_EMBEDDING_API_KEY": "embedding-test-secret",
          "SMARTLECT_EMBEDDING_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
          "SMARTLECT_EMBEDDING_MODEL": "text-embedding-v4", "SMARTLECT_EMBEDDING_DIMENSIONS": "64"}
MESSAGES = [{"role": "user", "content": "Hello"}]


def completion(content="ok", **extra):
    return {"model": "qwen3.7-plus", "choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": content, **extra}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_index_trace_metadata_allowlist_and_admission_permissions(self):
        record = {"status": "failed", "provider": "aliyun-bailian", "model_id": "text-embedding-v4",
            "reasoning_content": "HIDDEN", "body": "DOCUMENT", "headers": {"Authorization": "SECRET"},
            "request_parameters": {"dimensions": 64, "input": "DOCUMENT", "response_format_type": {"secret": "SECRET"}},
            "usage": {"input_tokens": 10, "output_tokens": None, "secret": "SECRET"},
            "skill_versions": {"injected": "HIDDEN"}, "cost_estimate_cny": float('nan')}
        safe = index_trace(record)
        self.assertEqual(safe["usage"]["input_tokens"], 10)
        self.assertIsNone(safe["usage"]["output_tokens"])
        self.assertIsNone(safe["cost_estimate_cny"])
        self.assertEqual(safe["purpose"], "knowledge_index")
        self.assertEqual(safe["skill_versions"], {})
        self.assertTrue(all(text not in json.dumps(safe) for text in ("HIDDEN", "DOCUMENT", "SECRET")))
        with self.assertRaises(StateError):
            IndexModelAudit(Mock(), SimpleNamespace(subject_type="user", actor_id="user", permissions=(),
                execution_scope_id="test"), "document", 1, "p" * 32, 0)

    async def test_admin_publish_records_each_attempt_before_http_and_replay_avoids_new_calls(self):
        from smartlect.app import create_app
        from smartlect.auth import ActorContext
        from smartlect.config import Settings

        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.rowcount = 1
        connect = Mock(return_value=connection)
        actor = ActorContext(subject_type="merchant", actor_id="admin", session_id="synthetic",
                             permissions=("admin:legacy",), execution_scope_id="test-index")
        class Identity:
            async def authenticate(self, *args, **kwargs):
                return actor  # Only endpoint/audit wiring is tested, not authentication.
            def require_csrf(self, *args):
                pass
        knowledge = Mock()
        knowledge.get_document.return_value = {"status": "DRAFT"}
        knowledge.draft_chunks.return_value = [{"chunk_id": "chunk", "content": "synthetic policy text"}]
        knowledge.publish.return_value = {"status": "PUBLISHED"}
        requests = []
        def handler(request):
            requests.append(request)
            inserted = [c for c in cursor.execute.call_args_list if "INSERT INTO knowledge_index_attempt" in c.args[0]]
            self.assertEqual(len(inserted), len(requests))
            if len(requests) == 1:
                return httpx.Response(503, text="SECRET_FAILURE_BODY")
            if len(requests) == 2:
                return httpx.Response(200, json={"model": "text-embedding-v4", "data": [{"index": 0, "embedding": [0.1] * 64}],
                    "usage": {"prompt_tokens": 4, "total_tokens": 4}})
            return httpx.Response(401, text="SECRET_FAILURE_BODY")
        provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
        app = create_app(Settings(model_mode="live"), config=CONFIG, store=SimpleNamespace(connect=connect),
            knowledge=knowledge, identity=Identity(), provider=provider,
            attribution=SimpleNamespace(resolve_actor=lambda actor:actor,assert_scope_writable=lambda actor:None),
            merchant=SimpleNamespace(store=SimpleNamespace(selected_actor=lambda actor: actor)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://smartlect.test") as client:
            path = "/admin-api/assistant/knowledge/document/1/publish"
            response = await client.post(path, json={})
            self.assertEqual(response.status_code, 200, response.text)
            updates = [c for c in cursor.execute.call_args_list if "UPDATE knowledge_index_attempt" in c.args[0]]
            traces = [json.loads(c.args[1][1]) for c in updates]
            self.assertEqual([t["status"] for t in traces], ["failed", "succeeded"])
            self.assertEqual([t["attempt"] for t in traces], [1, 2])
            self.assertEqual(traces[-1]["usage"]["input_tokens"], 4)
            self.assertTrue(all(t["prompt_version"] == "knowledge-index-v1" for t in traces))
            self.assertNotIn("synthetic policy text", json.dumps(traces))
            self.assertNotIn("SECRET_FAILURE_BODY", json.dumps(traces))
            knowledge.get_document.return_value = {"status": "PUBLISHED"}
            self.assertEqual((await client.post(path, json={})).status_code, 200)
            self.assertEqual(len(requests), 2)
            knowledge.get_document.return_value = {"status": "DRAFT"}
            before = knowledge.publish.call_count
            response = await client.post(path, json={})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(knowledge.publish.call_count, before)
            last = [c for c in cursor.execute.call_args_list if "UPDATE knowledge_index_attempt" in c.args[0]][-1]
            failed = json.loads(last.args[1][1])
            self.assertEqual((failed["status"], failed["http_status"]), ("failed", 401))
            self.assertIsNone(failed["usage"]["total_tokens"])
            self.assertEqual(len(requests), 3)

    async def test_required_tool_choice_is_explicit_and_rejects_unregistered_modes(self):
        bodies = []
        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=completion())
        provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
        tool = {'type': 'function', 'function': {'name': 'finish_answer', 'parameters': {'type': 'object'}}}
        result = await provider.chat(MESSAGES, tools=[tool], tool_choice='required')
        self.assertEqual(bodies[-1]['tool_choice'], 'required')
        self.assertEqual(result['metadata']['request_parameters']['tool_choice'], 'required')
        for params in ({'tool_choice': 'required'}, {'tools': [tool], 'tool_choice': 'anything'}):
            with self.assertRaises(ValueError):
                await provider.chat(MESSAGES, **params)
        self.assertEqual(len(bodies), 1)

    async def test_retry_budget_metadata_and_redaction(self):
        bodies, traces, admitted = [], [], []

        def handler(request):
            bodies.append(json.loads(request.content))
            if len(bodies) == 1:
                return httpx.Response(503, json={"error": CONFIG["SMARTLECT_MODEL_API_KEY"]})
            return httpx.Response(200, json=completion(reasoning_content="hidden reasoning"))

        provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
        result = await provider.chat(MESSAGES, on_trace=traces.append, before_attempt=lambda: admitted.append(1))
        self.assertEqual(len(admitted), 2)
        self.assertEqual([t["status"] for t in traces], ["failed", "succeeded"])
        self.assertIsNone(traces[0]["usage"]["input_tokens"])
        self.assertEqual(result["usage"]["total_tokens"], 12)
        self.assertEqual(result["metadata"]["attempts"], 2)
        self.assertGreater(result["metadata"]["cost_estimate_cny"], 0)
        for body in bodies:
            self.assertFalse(body["enable_thinking"])
            self.assertFalse(body["enable_search"])
            self.assertEqual(body["model"], "qwen3.7-plus")
            self.assertEqual(body["max_completion_tokens"], 1024)
        encoded = json.dumps(result)
        self.assertNotIn("hidden reasoning", encoded)
        self.assertNotIn(CONFIG["SMARTLECT_MODEL_API_KEY"], encoded)

        before = len(bodies)
        async def denied():
            raise RuntimeError("budget_exhausted")
        with self.assertRaisesRegex(RuntimeError, "budget_exhausted"):
            await provider.chat(MESSAGES, before_attempt=denied)
        self.assertEqual(len(bodies), before)

    async def test_fail_closed_without_retries_for_auth_format_and_output_limit(self):
        for response, code in [(httpx.Response(401, text="secret body"), "model_http_error"),
                               (httpx.Response(200, text="not-json"), "model_invalid_response"),
                               (httpx.Response(200, json={"choices": [{"finish_reason": "length"}]}),
                                "model_incomplete_response"),
                               (httpx.Response(200, json={**completion(), "model": "unapproved-model"}),
                                "model_response_id_mismatch")]:
            calls = []
            def handler(request):
                calls.append(1)
                return response
            provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
            with self.assertRaises(ProviderError) as raised:
                await provider.chat(MESSAGES)
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(raised.exception.attempts), 1)
            self.assertNotIn("secret body", str(raised.exception))

    async def test_transport_timeout_has_at_most_two_attempts_and_unknown_usage(self):
        calls = []
        def handler(request):
            calls.append(1)
            raise httpx.ReadTimeout("secret transport detail", request=request)
        provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
        with self.assertRaises(ProviderError) as raised:
            await provider.chat(MESSAGES)
        self.assertEqual(raised.exception.code, "model_timeout")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(t["usage"]["total_tokens"] is None for t in raised.exception.attempts))

    async def test_stream_text_tools_usage_and_incomplete_fail_closed(self):
        chunks = [
            {"model": "qwen3.7-plus", "choices": [{"delta": {"reasoning_content": "never expose"}}]},
            {"choices": [{"delta": {"content": "hello "}}]},
            {"choices": [{"delta": {"content": "world", "tool_calls": [{"index": 0, "id": "call1", "type": "function",
                              "function": {"name": "lookup", "arguments": "{\"q\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"sku\"}"}}]},
                          "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}},
        ]
        payload = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
        deltas = []
        provider = Provider(CONFIG, transport=httpx.MockTransport(lambda req: httpx.Response(
            200, text=payload + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})))
        result = await provider.chat(MESSAGES, stream=True, on_delta=deltas.append)
        self.assertEqual("".join(deltas), "hello world")
        self.assertEqual(result["message"]["tool_calls"][0]["function"]["arguments"], '{"q":"sku"}')
        self.assertEqual(result["usage"]["total_tokens"], 10)
        self.assertNotIn("never expose", json.dumps(result))
        calls = []
        def broken(request):
            calls.append(1)
            return httpx.Response(200, text=payload)
        provider = Provider(CONFIG, transport=httpx.MockTransport(broken))
        with self.assertRaisesRegex(ProviderError, "model_stream_incomplete"):
            await provider.chat(MESSAGES, stream=True)
        self.assertEqual(len(calls), 1)

    async def test_chat_embedding_share_two_slots_and_validate_vectors(self):
        active, peak = 0, 0
        async def handler(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            if request.url.path.endswith("/embeddings"):
                return httpx.Response(200, json={"model": "text-embedding-v4", "data": [
                    {"index": 1, "embedding": [0.2] * 64}, {"index": 0, "embedding": [0.1] * 64}],
                    "usage": {"prompt_tokens": 4, "total_tokens": 4}})
            return httpx.Response(200, json=completion())
        provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
        results = await asyncio.gather(*(provider.chat(MESSAGES) for _ in range(3)),
                                       provider.embed(["policy", "refund"]))
        self.assertEqual(peak, 2)
        self.assertEqual(results[-1]["embeddings"][0], [0.1] * 64)
        self.assertIsNone(results[-1]["usage"]["output_tokens"])
        # Raw bytes allow testing malformed provider JSON that httpx's encoder correctly refuses.
        invalid = Provider(CONFIG, transport=httpx.MockTransport(lambda req: httpx.Response(
            200, content=json.dumps({"data": [{"index": 0, "embedding": [float("nan")] * 64}]}))))
        with self.assertRaisesRegex(ProviderError, "embedding_invalid_response"):
            await invalid.embed(["policy"])

    async def test_total_stream_deadline_does_not_restart_after_emitting_text(self):
        class EndlessStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    yield b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'
                    await asyncio.sleep(0.005)
        calls, deltas = [], []
        def handler(request):
            calls.append(1)
            return httpx.Response(200, stream=EndlessStream())
        provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
        timeout = asyncio.timeout
        def short_timeout(seconds):
            self.assertEqual(seconds, 25)
            return timeout(0.02)
        with patch("smartlect.provider.asyncio.timeout", short_timeout):
            with self.assertRaisesRegex(ProviderError, "model_timeout"):
                await provider.chat(MESSAGES, stream=True, on_delta=deltas.append)
        self.assertEqual(len(calls), 1)
        self.assertGreater(len(deltas), 1)

    async def test_unapproved_model_destination_tools_and_reasoning_replay_rejected(self):
        with self.assertRaisesRegex(ValueError, "model_id_not_authorized"):
            Provider({**CONFIG, "SMARTLECT_MODEL_ID": "unapproved-model"})
        provider = Provider(CONFIG, transport=httpx.MockTransport(lambda req: self.fail("must not call")))
        for tool_type in ("web_search", "browser", "code_interpreter"):
            with self.assertRaisesRegex(ValueError, "only_registered_function_tools_allowed"):
                await provider.chat(MESSAGES, tools=[{"type": tool_type}])
        with self.assertRaisesRegex(ValueError, "invalid_model_message"):
            await provider.chat([{"role": "assistant", "content": "ok", "reasoning_content": "hidden"}])
        with self.assertRaisesRegex(ValueError, "model_attempt_limit"):
            await provider.chat(MESSAGES, max_attempts=3)
        for url in ("http://127.0.0.1/compatible-mode/v1", "https://dashscope.aliyuncs.com/compatible-mode/v1?key=bad"):
            bad = Provider({**CONFIG, "SMARTLECT_MODEL_BASE_URL": url})
            with self.assertRaisesRegex(ProviderError, "model_endpoint_not_authorized"):
                await bad.chat(MESSAGES)


if __name__ == "__main__":
    unittest.main()
