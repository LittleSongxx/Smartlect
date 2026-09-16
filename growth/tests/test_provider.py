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




class GlmProviderTests(unittest.IsolatedAsyncioTestCase):
    GLM_CONFIG = {"SMARTLECT_MODEL_API_KEY": "test-secret-do-not-log",
                  "SMARTLECT_MODEL_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
                  "SMARTLECT_MODEL_ID": "glm-5.3"}

    async def test_glm_model_and_endpoints_authorized(self):
        provider = Provider(self.GLM_CONFIG)
        self.assertEqual(provider.model_id, "glm-5.3")
        base, _key, region = provider._endpoint("MODEL")
        self.assertEqual(base, "https://open.bigmodel.cn/api/paas/v4")
        self.assertEqual(region, "cn-zhipu")
        intl = Provider({**self.GLM_CONFIG,
                         "SMARTLECT_MODEL_BASE_URL": "https://api.z.ai/api/paas/v4"})
        self.assertEqual(intl._endpoint("MODEL")[2], "intl-zhipu")

    async def test_glm_uses_openai_protocol_body(self):
        bodies = []

        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={
                "model": "glm-5.3",
                "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}})

        provider = Provider(self.GLM_CONFIG, transport=httpx.MockTransport(handler))
        await provider.chat(MESSAGES, max_tokens=64)
        self.assertEqual(bodies[0]["max_tokens"], 64)
        self.assertNotIn("max_completion_tokens", bodies[0])
        self.assertNotIn("enable_thinking", bodies[0])
        self.assertNotIn("enable_search", bodies[0])
        def dashscope_handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=completion())

        dashscope = Provider(CONFIG, transport=httpx.MockTransport(dashscope_handler))
        await dashscope.chat(MESSAGES, max_tokens=64)
        self.assertIn("enable_thinking", bodies[1])
        self.assertIn("max_completion_tokens", bodies[1])

    async def test_glm_wrong_path_or_host_rejected(self):
        for url in ("https://open.bigmodel.cn/compatible-mode/v1",
                    "https://evil.bigmodel.cn/api/paas/v4",
                    "https://open.bigmodel.cn/api/paas/v4/../v4"):
            bad = Provider({**self.GLM_CONFIG, "SMARTLECT_MODEL_BASE_URL": url})
            with self.assertRaisesRegex(ProviderError, "model_endpoint_not_authorized"):
                await bad.chat(MESSAGES)


class ResilienceTests(unittest.IsolatedAsyncioTestCase):
    """Circuit breaker, connection reuse and the embedding cache added 2026-09-15."""

    async def test_breaker_opens_fast_fails_and_half_open_probe_recovers(self):
        state, calls = {"mode": "fail"}, []

        def handler(request):
            calls.append(request)
            if state["mode"] == "fail":
                return httpx.Response(503, text="SECRET")
            return httpx.Response(200, json=completion())

        config = {**CONFIG, "SMARTLECT_MODEL_BREAKER_FAILURES": "2", "SMARTLECT_MODEL_BREAKER_COOLDOWN_S": "1"}
        provider = Provider(config, transport=httpx.MockTransport(handler))
        for _ in range(2):  # each chat exhausts its own retry, then counts as one breaker failure
            with self.assertRaises(ProviderError):
                await provider.chat(MESSAGES)
        with self.assertRaises(ProviderError) as tripped:
            await provider.chat(MESSAGES)
        self.assertEqual(tripped.exception.code, "model_circuit_open")
        self.assertEqual(len(calls), 4)  # fast-fail issued no new HTTP request
        await asyncio.sleep(1.05)  # cooldown expires; the next call is the half-open probe
        state["mode"] = "ok"
        self.assertEqual((await provider.chat(MESSAGES))["message"]["content"], "ok")
        self.assertEqual((await provider.chat(MESSAGES))["message"]["content"], "ok")

    async def test_breakers_are_scoped_per_endpoint(self):
        def handler(request):
            if request.url.path.endswith("/embeddings"):
                return httpx.Response(200, json={"model": "text-embedding-v4",
                    "data": [{"index": 0, "embedding": [0.25] * 64}], "usage": {"total_tokens": 3}})
            return httpx.Response(503)

        config = {**CONFIG, "SMARTLECT_MODEL_BREAKER_FAILURES": "2", "SMARTLECT_MODEL_BREAKER_COOLDOWN_S": "60"}
        provider = Provider(config, transport=httpx.MockTransport(handler))
        for _ in range(2):
            with self.assertRaises(ProviderError):
                await provider.chat(MESSAGES)
        with self.assertRaisesRegex(ProviderError, "model_circuit_open"):
            await provider.chat(MESSAGES)
        self.assertEqual(len((await provider.embed(["退款政策"]))["embeddings"][0]), 64)  # chat breaker stays open

    async def test_identical_single_text_embedding_is_cached_without_budget_or_http(self):
        calls, budget = [], []

        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            return httpx.Response(200, json={"model": "text-embedding-v4",
                "data": [{"index": i, "embedding": [0.25] * 64} for i in range(len(body["input"]))],
                "usage": {"prompt_tokens": 3, "total_tokens": 3}})

        async def before_attempt():
            budget.append(1)

        provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
        first = await provider.embed(["退款政策"], before_attempt=before_attempt, cacheable=True)
        second = await provider.embed(["退款政策"], before_attempt=before_attempt, cacheable=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["embeddings"], second["embeddings"])
        self.assertFalse(first["metadata"].get("cache_hit", False))
        self.assertTrue(second["metadata"]["cache_hit"])
        self.assertEqual(len(budget), 1)  # the cached call consumed neither a slot nor the run budget
        await provider.embed(["第一句", "第二句"], cacheable=True)  # batches are the indexing path and stay uncached
        await provider.embed(["全新的单句"])  # without the flag nothing is cached either
        self.assertEqual(len(calls), 3)

    async def test_http_client_is_created_once_and_reused(self):
        provider = Provider(CONFIG, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=completion())))
        await provider.chat(MESSAGES)
        client = provider._client
        self.assertIsNotNone(client)
        await provider.chat(MESSAGES)
        self.assertIs(provider._client, client)


if __name__ == "__main__":
    unittest.main()
