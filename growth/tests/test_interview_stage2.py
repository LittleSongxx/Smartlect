"""Stage 2+ wiring that must stay honest: no empty signboards."""
import base64
import hashlib
import hmac
import inspect
import json
import os
import time
import unittest
from pathlib import Path

from smartlect.agents.shopping import (BOOTSTRAP_TOOLS, extract_streamed_answer, final_answer_response_format,
                                       route_shopping_model)
from smartlect.graph_runtime import checkpointer, invoke_config, reset_for_tests
from smartlect.auth import IdentityBridge
from smartlect.csrf_store import consume
from smartlect.guest_token import issue_visitor_jwt, verify_visitor_jwt
from smartlect.knowledge import compose_search_query, parallel_queries, rank_chunks
from smartlect.observability import (gen_ai_span, langfuse_enabled, otel_spans_enabled, prompt_hash,
                                     record_generation, reset_for_tests as reset_observability)
from smartlect.postgres import dsn_from_env
from smartlect.rerank_client import RerankError, configured, rerank_texts
from smartlect.tokenizer import count_tokens, truncate_tokens


class InterviewStage2Tests(unittest.IsolatedAsyncioTestCase):
    def test_compose_replaces_instead_of_concatenating(self):
        self.assertEqual(compose_search_query('全国包邮吗', '配送政策'), '配送政策')
        self.assertEqual(parallel_queries('全国包邮吗', '配送政策'), ['配送政策', '全国包邮吗'])

    def test_rank_chunks_need_ann_hits_not_mysql_json(self):
        row = {'doc_id': 'd', 'version': 1, 'chunk_id': 'c1', 'heading': '政策',
               'content': '退款需要确认。', 'title': '政策', 'vector_json': [1, 0],
               'embedding_model': 'one', 'embedding_dimensions': 2, 'index_version': 'one:d2:v1'}
        ranked, metadata = rank_chunks([row], 'unmatched', query_vector=[1, 0],
                                       embedding_model='one', index_version='one:d2:v1')
        self.assertEqual(metadata['dense_matches'], 0)
        self.assertEqual(metadata['vector_backend'], 'unused')
        ranked, metadata = rank_chunks(
            [row], 'unmatched', query_vector=[1, 0], embedding_model='one', index_version='one:d2:v1',
            dense_hits=[{'doc_id': 'd', 'version': 1, 'chunk_id': 'c1', 'score': 0.9}],
            vector_backend='pgvector_hnsw')
        self.assertEqual(metadata['dense_matches'], 1)
        self.assertEqual(ranked[0]['doc_id'], 'd')

    def test_tokenizer_is_tiktoken_not_cjk_times_two(self):
        self.assertGreater(count_tokens('退款政策说明'), 1)
        self.assertTrue(truncate_tokens('abcdef', 2))

    def test_bootstrap_tools_do_not_include_finish_answer(self):
        self.assertIn('load_skill', BOOTSTRAP_TOOLS)
        self.assertIn('search_knowledge', BOOTSTRAP_TOOLS)
        self.assertNotIn('finish_answer', BOOTSTRAP_TOOLS)
        self.assertNotIn('recommend_skus', BOOTSTRAP_TOOLS)
        self.assertEqual(final_answer_response_format()['type'], 'json_schema')

    def test_route_and_stream_extract(self):
        self.assertEqual(route_shopping_model({'response': {}}), 'answer')
        self.assertEqual(route_shopping_model({'response': {'tool_calls': [
            {'function': {'name': 'search_knowledge'}}]}}), 'tools')
        self.assertEqual(extract_streamed_answer('{"answer": "你好'), '你好')
        self.assertEqual(extract_streamed_answer('{"answer": "完"}'), '完')

    def test_visitor_jwt_and_one_time_csrf(self):
        secret = b's' * 48
        token = issue_visitor_jwt(secret, 'ab' * 16)
        payload = verify_visitor_jwt(secret, token)
        self.assertEqual(payload['sub'], 'ab' * 16)
        self.assertIn('jti', payload)
        self.assertEqual(token.count('.'), 2)

    def test_visitor_jwt_accepts_legacy_compact_and_rejects_expired(self):
        secret = b's' * 48
        now = int(time.time())
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps({
            "sub": "ab" * 16, "iat": now, "exp": now + 60, "jti": "a" * 16, "purpose": "visitor",
        }, separators=(",", ":")).encode()).decode().rstrip("=")
        signature = base64.urlsafe_b64encode(
            hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
        legacy = f"{header}.{payload}.{signature}"
        self.assertEqual(verify_visitor_jwt(secret, legacy)["sub"], "ab" * 16)
        expired = base64.urlsafe_b64encode(json.dumps({
            "sub": "ab" * 16, "iat": now - 120, "exp": now - 60, "jti": "b" * 16, "purpose": "visitor",
        }, separators=(",", ":")).encode()).decode().rstrip("=")
        bad_sig = base64.urlsafe_b64encode(
            hmac.new(secret, f"{header}.{expired}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
        with self.assertRaises(ValueError):
            verify_visitor_jwt(secret, f"{header}.{expired}.{bad_sig}")
        self.assertTrue(consume(None, 'jti-1', actor_id='a', session_id='s'))
        self.assertFalse(consume(None, 'jti-1', actor_id='a', session_id='s'))
        self.assertTrue(consume(lambda: None, 'jti-none-connect', actor_id='a', session_id='s'))
        self.assertFalse(consume(lambda: None, 'jti-none-connect', actor_id='a', session_id='s'))
        self.assertFalse(consume(lambda: (_ for _ in ()).throw(RuntimeError('down')), 'jti-down', actor_id='a', session_id='s'))
        bridge = IdentityBridge({'SMARTLECT_USER_PORT': '1', 'SMARTLECT_INTERNAL_TOKEN': 't',
                                 'SMARTLECT_VISITOR_SECRET': 's' * 48,
                                 'SMARTLECT_ALLOWED_ORIGINS': 'http://smartlect.test'})
        actor = type('A', (), {
            'actor_id': 'a', 'subject_type': 'visitor', 'session_id': 's', 'execution_scope_id': 'store'
        })()
        proof = bridge.csrf_token(actor)
        from fastapi import Request
        request = Request({'type': 'http', 'method': 'POST', 'headers': [
            (b'origin', b'http://smartlect.test'), (b'x-csrf-token', proof.encode())]})
        bridge.require_csrf(request, actor)
        with self.assertRaises(Exception):
            bridge.require_csrf(request, actor)

    def test_langfuse_noop_without_keys(self):
        self.assertFalse(langfuse_enabled({}))
        record_generation(name='x', model='m', prompt_hash=prompt_hash('a'))
        self.assertIsNone(dsn_from_env({}))

    def test_gen_ai_span_is_noop_without_exporter(self):
        os.environ.pop("SMARTLECT_OTEL_EXPORTER", None)
        reset_observability()
        self.assertFalse(otel_spans_enabled({}))
        with gen_ai_span("chat m", kind="chat") as span:
            self.assertIsNone(span)

    def test_gen_ai_span_uses_official_attributes_when_sdk_ready(self):
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        os.environ["SMARTLECT_OTEL_EXPORTER"] = "http://127.0.0.1:4318/v1/traces"
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        if not isinstance(trace.get_tracer_provider(), TracerProvider):
            trace.set_tracer_provider(provider)
        else:
            # Suite already installed an SDK provider; attach the exporter there.
            current = trace.get_tracer_provider()
            current.add_span_processor(SimpleSpanProcessor(exporter))
        reset_observability()
        try:
            self.assertTrue(otel_spans_enabled())
            with gen_ai_span("chat m", kind="chat", attributes={
                "gen_ai.request.model": "m",
                "gen_ai.system": "must-not-appear",
            }) as span:
                self.assertIsNotNone(span)
            spans = exporter.get_finished_spans()
            self.assertGreaterEqual(len(spans), 1)
            attrs = dict(spans[-1].attributes)
            self.assertEqual(attrs["gen_ai.operation.name"], "chat")
            self.assertEqual(attrs["gen_ai.request.model"], "m")
            self.assertNotIn("gen_ai.system", attrs)
        finally:
            os.environ.pop("SMARTLECT_OTEL_EXPORTER", None)
            reset_observability()

    def test_gen_ai_span_is_wired_on_runtime_paths(self):
        from smartlect.provider import Provider
        from smartlect.tools import invoke
        from smartlect.knowledge import KnowledgeStore
        from smartlect import app
        from smartlect.merchant import service as merchant_service
        self.assertIn("gen_ai_span", inspect.getsource(Provider._request))
        self.assertIn("execute_tool", inspect.getsource(invoke))
        self.assertIn("retrieve knowledge", inspect.getsource(KnowledgeStore.search))
        app_src = Path(app.__file__).read_text()
        merchant_src = Path(merchant_service.__file__).read_text()
        self.assertIn("invoke_agent shopping", app_src)
        self.assertIn("invoke_agent merchant", merchant_src)

    def test_checkpointer_is_memory_without_dsn(self):
        reset_for_tests()
        saver = checkpointer()
        self.assertEqual(type(saver).__name__, 'InMemorySaver')
        config = invoke_config('conv', 'run')
        self.assertEqual(config['configurable']['thread_id'], 'conv')
        self.assertEqual(config['configurable']['checkpoint_ns'], 'run')
        reset_for_tests()

    async def test_rerank_without_key_is_explicit_error(self):
        self.assertFalse(configured({}))
        with self.assertRaises(RerankError):
            await rerank_texts('q', ['d'], env={})


if __name__ == '__main__':
    unittest.main()
