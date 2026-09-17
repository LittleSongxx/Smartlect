"""Bounded, ordinary model HTTP calls; no vendor-hosted tools or hidden reasoning logs."""

import asyncio
from datetime import datetime, timezone
import inspect
import json
import math
import random
import re
import threading
import time
import uuid
from urllib.parse import urlsplit

import httpx
from prometheus_client import Counter

from smartlect.cache import TtlCache
from smartlect.state import SessionStore, StateError, _actor, _integer, _json, _text

MODEL_BREAKER_REJECTIONS = Counter("growth_model_breaker_rejections_total",
                                    "Fast-fails served while a model endpoint circuit was open", ["endpoint"])
EMBEDDING_CACHE_REQUESTS = Counter("growth_embedding_cache_requests_total",
                                    "Query-embedding cache outcomes", ["outcome"])


class ProviderError(RuntimeError):
    def __init__(self, code, *, retryable=False, http_status=None, attempts=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status
        self.attempts = attempts or []


def bounded(raw, default, low, high):
    """Env knobs are strings; clamp to a sane range and fall back on garbage."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return low if value < low else high if value > high else value


class _Breaker:
    """Consecutive-failure circuit. While open, every call fails fast with
    model_circuit_open. After cooldown, exactly one probe is admitted (half-open);
    other callers stay rejected until that probe succeeds (close) or fails (re-open)."""

    def __init__(self, failures, cooldown_s, endpoint):
        self.failures, self.cooldown_s = failures, cooldown_s
        self.endpoint = endpoint
        self._consecutive, self._opened_until = 0, 0.0
        self._half_open_inflight = False
        self._lock = threading.Lock()

    def check(self):
        with self._lock:
            if self._consecutive < self.failures:
                return
            if time.monotonic() < self._opened_until or self._half_open_inflight:
                MODEL_BREAKER_REJECTIONS.labels(self.endpoint).inc()
                raise ProviderError("model_circuit_open", retryable=False)
            self._half_open_inflight = True

    def record(self, succeeded):
        with self._lock:
            if succeeded:
                self._consecutive = 0
                self._opened_until = 0.0
                self._half_open_inflight = False
                return
            self._consecutive += 1
            self._half_open_inflight = False
            if self._consecutive >= self.failures:
                self._opened_until = time.monotonic() + self.cooldown_s


async def _callback(callback, *args):
    if callback is not None:
        result = callback(*args)
        if inspect.isawaitable(result):
            await result


def index_trace(record):
    """Allow only provider metadata, including inside nested objects; never document text."""
    if (not isinstance(record, dict) or not isinstance(record.get("status"), str)
            or record["status"] not in {"started", "succeeded", "failed", "cancelled"}):
        raise StateError("invalid_index_model_trace", 422)
    safe = {"purpose": "knowledge_index", "status": record["status"], "skill_versions": {}}
    for key in ("provider", "model_id", "model_mode", "region", "prompt_version", "schema_version",
                "price_version", "returned_model", "resolved_snapshot", "error_code", "started_at"):
        value = record.get(key)
        safe[key] = value if isinstance(value, str) and len(value) <= 160 and not any(ord(c) < 32 for c in value) else None
    for key in ("http_status", "attempt", "retry_count", "latency_ms", "first_delta_ms", "cost_estimate_cny"):
        value = record.get(key)
        safe[key] = value if type(value) in {int, float} and 0 <= value <= 10**18 and math.isfinite(value) else None
    for key in ("enable_thinking", "enable_search", "stream"):
        safe[key] = record.get(key) if type(record.get(key)) is bool else None
    usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    safe["usage"] = {key: usage.get(key) if type(usage.get(key)) is int and usage[key] >= 0 else None
                     for key in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens")}
    params = record.get("request_parameters") if isinstance(record.get("request_parameters"), dict) else {}
    safe["request_parameters"] = {key: params.get(key) if type(params.get(key)) in {int, float}
        and 0 <= params[key] <= 10**18 and math.isfinite(params[key]) else None
        for key in ("temperature", "max_completion_tokens", "function_tool_count", "dimensions")}
    format_type = params.get("response_format_type")
    safe["request_parameters"]["response_format_type"] = format_type if (
        isinstance(format_type, str) and format_type in {"json_object", "json_schema"}) else None
    return safe


class IndexModelAudit(SessionStore):
    """One indexing batch, not an Agent run. Admission survives a process crash."""
    def __init__(self, connect, actor, doc_id, version, publication_id, batch_index):
        super().__init__(connect)
        kind, self.actor_id, self.scope = _actor(actor)
        if kind != "merchant" or "admin:legacy" not in actor.permissions:
            raise StateError("permission_denied", 403)
        self.doc_id = _text(doc_id, "doc_id", 128)
        self.version = _integer(version, "version", 1, 2147483647)
        self.publication_id = _text(publication_id, "publication_id", 32)
        self.batch_index = _integer(batch_index, "batch_index", 0, 3)
        self.attempt, self.call_id = 0, None

    def start(self):
        attempt = _integer(self.attempt + 1, "model_attempt", 1, 2)
        call_id = uuid.uuid4().hex
        trace = index_trace({"status": "started", "model_mode": "live", "model_id": "text-embedding-v4",
                             "prompt_version": "knowledge-index-v1", "schema_version": "embedding-v1",
                             "attempt": attempt, "retry_count": attempt - 1})
        with self._transaction() as cursor:
            cursor.execute("""INSERT INTO knowledge_index_attempt (call_id,publication_id,execution_scope_id,
                actor_id,doc_id,document_version,batch_index,attempt,status,trace_json,started_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'started',%s,UTC_TIMESTAMP(6))""",
                (call_id, self.publication_id, self.scope, self.actor_id, self.doc_id, self.version,
                 self.batch_index, attempt, _json(trace)))
        self.call_id, self.attempt = call_id, attempt

    def finish(self, record):
        trace = index_trace(record)
        if trace["status"] == "started" or self.call_id is None:
            raise StateError("index_model_attempt_not_started")
        with self._transaction() as cursor:
            cursor.execute("""UPDATE knowledge_index_attempt SET status=%s,trace_json=%s,completed_at=UTC_TIMESTAMP(6)
                WHERE call_id=%s AND publication_id=%s AND actor_id=%s AND execution_scope_id=%s AND status='started'""",
                (trace["status"], _json(trace), self.call_id, self.publication_id, self.actor_id, self.scope))
            if cursor.rowcount != 1:
                raise StateError("index_model_attempt_not_started")


def _usage(value):
    value = value if isinstance(value, dict) else {}
    count = lambda v: v if type(v) is int and v >= 0 else None
    details = value.get("prompt_tokens_details") or {}
    return {"input_tokens": count(value.get("prompt_tokens")),
            "output_tokens": count(value.get("completion_tokens")),
            "total_tokens": count(value.get("total_tokens")),
            "cached_input_tokens": count(details.get("cached_tokens")) if isinstance(details, dict) else None}


def _message(value):
    if not isinstance(value, dict) or value.get("role") != "assistant":
        raise ProviderError("model_invalid_response")
    content = value.get("content")
    if content is not None and not isinstance(content, str):
        raise ProviderError("model_invalid_response")
    message = {"role": "assistant", "content": content}
    calls = value.get("tool_calls") or []
    if not isinstance(calls, list) or len(calls) > 10:
        raise ProviderError("model_invalid_tool_calls")
    normalized = []
    for call in calls:
        if not isinstance(call, dict) or call.get("type") != "function":
            raise ProviderError("model_invalid_tool_calls")
        fn = call.get("function")
        if (not isinstance(fn, dict) or not isinstance(call.get("id"), str)
                or not call["id"] or not isinstance(fn.get("name"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fn["name"])
                or not isinstance(fn.get("arguments"), str)):
            raise ProviderError("model_invalid_tool_calls")
        normalized.append({"id": call["id"], "type": "function",
                           "function": {"name": fn["name"], "arguments": fn["arguments"]}})
    if len({call["id"] for call in normalized}) != len(normalized):
        raise ProviderError("model_invalid_tool_calls")
    if normalized:
        message["tool_calls"] = normalized
    if not content and not normalized:
        raise ProviderError("model_empty_response")
    return message


CHAT_MODEL_WHITELIST = ("qwen3.7-plus", "qwen3.7-plus-2026-05-26", "glm-5.3")


class Provider:
    """Reuse one instance per API process: chat and embeddings share two request slots."""

    ZHIPU_HOSTS = {"open.bigmodel.cn": "cn-zhipu", "api.z.ai": "intl-zhipu"}

    def __init__(self, config, *, transport=None, runtime_loader=None):
        self.model_id = config.get("SMARTLECT_MODEL_ID", "qwen3.7-plus")
        if self.model_id not in CHAT_MODEL_WHITELIST:
            raise ValueError("model_id_not_authorized")
        # Runtime model switching (admin console): an async loader reads the DB-backed
        # selection every few seconds; env stays the fallback and the only key source.
        self._runtime_loader = runtime_loader
        self._runtime_model = None
        self._runtime_loaded_at = 0.0
        self._config = {k: v for k, v in config.items() if k.startswith((
            "SMARTLECT_MODEL_", "SMARTLECT_EMBEDDING_"))}
        self._transport = transport
        # The two slots are the deliberate cost valve: concurrency beyond this queues
        # in front of the provider instead of multiplying paid model calls.
        self._slots = asyncio.Semaphore(bounded(config.get("SMARTLECT_MODEL_CONCURRENCY"), 2, 1, 8))
        self._client = None  # shared per process; created lazily inside the running loop
        self._breakers = {prefix: _Breaker(bounded(config.get("SMARTLECT_MODEL_BREAKER_FAILURES"), 4, 2, 50),
                                           bounded(config.get("SMARTLECT_MODEL_BREAKER_COOLDOWN_S"), 30, 1, 600),
                                           prefix.lower())
                          for prefix in ("MODEL", "EMBEDDING")}
        self._embedding_cache = TtlCache(512, 1800)

    def _endpoint(self, prefix):
        key = self._config.get(f"SMARTLECT_{prefix}_API_KEY")
        base = self._config.get(f"SMARTLECT_{prefix}_BASE_URL", "").rstrip("/")
        parsed = urlsplit(base)
        if not key or not base:
            raise ProviderError("model_not_configured" if prefix == "MODEL" else "embedding_not_configured")
        zhipu = parsed.hostname in self.ZHIPU_HOSTS
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.port not in {None, 443}
                or parsed.path != ("/api/paas/v4" if zhipu else "/compatible-mode/v1")
                or not (zhipu or re.fullmatch(r"(?:dashscope(?:-intl|-us)?\.aliyuncs\.com|llm-[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com)", parsed.hostname or ""))):
            raise ProviderError("model_endpoint_not_authorized")
        host = parsed.hostname
        region = (self.ZHIPU_HOSTS[host] if zhipu else
                  host.split(".")[1] if ".maas.aliyuncs.com" in host else
                  {"dashscope.aliyuncs.com": "cn-beijing", "dashscope-intl.aliyuncs.com": "ap-southeast-1",
                   "dashscope-us.aliyuncs.com": "us-east-1"}.get(host, "unknown"))
        return base, key, region

    async def _apply_runtime_config(self):
        if self._runtime_loader is None:
            return
        if time.monotonic() - self._runtime_loaded_at < 5:
            return
        try:
            override = await self._runtime_loader()
        except Exception:
            return  # a DB hiccup falls back to the env snapshot; the next call retries
        self._runtime_loaded_at = time.monotonic()
        model_id = (override or {}).get("chat_model_id")
        self._runtime_model = model_id if model_id in CHAT_MODEL_WHITELIST else None

    def effective_chat_model(self):
        return self._runtime_model or self.model_id

    def invalidate_runtime_cache(self):
        self._runtime_loaded_at = 0.0

    def runtime_chat_options(self):
        """Models the configured endpoint family can actually serve; switching across
        vendors would need a different BASE_URL, which stays environment-managed."""
        host = urlsplit(self._config.get("SMARTLECT_MODEL_BASE_URL", "")).hostname or ""
        if host in self.ZHIPU_HOSTS:
            return ["glm-5.3"]
        return ["qwen3.7-plus", "qwen3.7-plus-2026-05-26"]

    async def chat(self, messages, *, tools=None, tool_choice=None, response_format=None, stream=False, on_delta=None,
                   on_trace=None, before_attempt=None, max_attempts=2, prompt_version="unknown",
                   skill_versions=None, schema_version="unknown", max_tokens=1024):
        if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
            raise ValueError("invalid_model_output_limit")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages_required")
        await self._apply_runtime_config()
        # Permit only the chat protocol; reasoning and vendor extensions cannot be replayed.
        clean_messages = []
        for message in messages:
            if (not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}
                    or set(message) - {"role", "content", "tool_calls", "tool_call_id"}
                    or (message.get("content") is not None and not isinstance(message["content"], str))):
                raise ValueError("invalid_model_message")
            clean_messages.append(message)
        base = self._config.get("SMARTLECT_MODEL_BASE_URL", "")
        dashscope = "aliyuncs.com" in base
        body = {"model": self.effective_chat_model(), "messages": clean_messages, "stream": stream,
                "temperature": 0,
                ("max_completion_tokens" if dashscope else "max_tokens"): max_tokens}
        if dashscope:
            # Vendor-specific switches; the Zhipu endpoint takes the plain OpenAI protocol.
            body["enable_thinking"] = False
            body["enable_search"] = False
        if tools:
            if (not isinstance(tools, list) or len(tools) > 32 or any(
                    not isinstance(t, dict) or t.get("type") != "function"
                    or set(t) - {"type", "function"} or not isinstance(t.get("function"), dict)
                    for t in tools)):
                raise ValueError("only_registered_function_tools_allowed")
            body["tools"] = tools
        if tool_choice is not None:
            if isinstance(tool_choice, str) and tool_choice in {'auto', 'none', 'required'}:
                if tool_choice != 'none' and not tools:
                    raise ValueError('tool_choice_requires_registered_tools')
                body['tool_choice'] = tool_choice
            elif (isinstance(tool_choice, dict) and tool_choice.get('type') == 'function'
                  and isinstance((tool_choice.get('function') or {}).get('name'), str) and tools):
                name = tool_choice['function']['name']
                if not any((item.get('function') or {}).get('name') == name for item in tools):
                    raise ValueError('tool_choice_requires_registered_tools')
                body['tool_choice'] = tool_choice
            else:
                raise ValueError('tool_choice_requires_registered_tools')
        if response_format is not None:
            if not isinstance(response_format, dict) or response_format.get("type") not in {"json_object", "json_schema"}:
                raise ValueError("invalid_response_format")
            body["response_format"] = response_format
        if stream:
            body["stream_options"] = {"include_usage": True}
        return await self._request("MODEL", "/chat/completions", body, stream=stream,
                                   on_delta=on_delta, on_trace=on_trace, before_attempt=before_attempt,
                                   max_attempts=max_attempts, prompt_version=prompt_version,
                                   skill_versions=skill_versions, schema_version=schema_version)

    async def embed(self, texts, *, on_trace=None, before_attempt=None, max_attempts=2,
                    prompt_version="embedding-v1", skill_versions=None, schema_version="embedding-v1",
                    cacheable=False):
        if (not isinstance(texts, list) or not 1 <= len(texts) <= 10
                or any(not isinstance(t, str) or not t.strip() or len(t) > 8000 for t in texts)):
            raise ValueError("embedding_batch_requires_1_to_10_nonempty_texts_max_8000_chars")
        model = self._config.get("SMARTLECT_EMBEDDING_MODEL")
        if model != "text-embedding-v4":
            raise ProviderError("embedding_model_not_verified")
        dimensions = int(self._config.get("SMARTLECT_EMBEDDING_DIMENSIONS", "1024"))
        if dimensions not in {64, 128, 256, 512, 768, 1024, 1536, 2048}:
            raise ValueError("invalid_embedding_dimensions")
        # Retrieval re-embeds the same user utterances constantly, so the query path opts in;
        # one-shot knowledge indexing stays uncached (a re-publish must really call the model).
        cache_key = (model, dimensions, texts[0]) if cacheable and len(texts) == 1 else None
        if cache_key is not None:
            cached = self._embedding_cache.get(cache_key)
            if cached is not None:
                EMBEDDING_CACHE_REQUESTS.labels("hit").inc()
                return {**cached, "metadata": {**cached["metadata"], "cache_hit": True}}
            EMBEDDING_CACHE_REQUESTS.labels("miss").inc()
        result = await self._request("EMBEDDING", "/embeddings", {"model": model, "input": texts,
                                   "dimensions": dimensions, "encoding_format": "float"},
                                   on_trace=on_trace, before_attempt=before_attempt, max_attempts=max_attempts,
                                   prompt_version=prompt_version, skill_versions=skill_versions, schema_version=schema_version)
        if cache_key is not None and isinstance(result, dict):
            self._embedding_cache.put(cache_key, result)
        return result

    async def _request(self, prefix, path, body, *, stream=False, on_delta=None, on_trace=None,
                       before_attempt=None, max_attempts=2, prompt_version, skill_versions, schema_version):
        from smartlect.observability import gen_ai_span
        operation = "chat" if prefix == "MODEL" else "embeddings"
        span_cm = gen_ai_span(
            f"{operation} {body.get('model')}",
            kind=operation,
            attributes={
                "gen_ai.operation.name": operation,
                "gen_ai.provider.name": "alibaba.cloud.bailian",
                "gen_ai.request.model": body.get("model"),
            },
        )
        span = span_cm.__enter__()
        try:
            result = await self._complete_request(
                prefix, path, body, stream=stream, on_delta=on_delta, on_trace=on_trace,
                before_attempt=before_attempt, max_attempts=max_attempts,
                prompt_version=prompt_version, skill_versions=skill_versions,
                schema_version=schema_version, span=span)
        except BaseException as error:
            span_cm.__exit__(type(error), error, error.__traceback__)
            raise
        else:
            span_cm.__exit__(None, None, None)
            return result

    async def _complete_request(self, prefix, path, body, *, stream, on_delta, on_trace,
                                before_attempt, max_attempts, prompt_version, skill_versions,
                                schema_version, span):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
            raise ValueError("model_attempt_limit_must_be_1_or_2")
        base, key, region = self._endpoint(prefix)
        self._breakers[prefix].check()
        attempts = []
        overall_start = time.monotonic()
        for attempt in range(1, max_attempts + 1):
            async with self._slots:
                await _callback(before_attempt)
                started = time.monotonic()
                trace = {"provider": "aliyun-bailian", "model_id": body["model"], "model_mode": "live",
                         "region": region, "enable_thinking": False if prefix == "MODEL" else None,
                         "enable_search": False, "stream": stream, "prompt_version": prompt_version,
                         "skill_versions": skill_versions or {}, "schema_version": schema_version,
                         "attempt": attempt, "retry_count": attempt - 1, "status": "started",
                         "started_at": datetime.now(timezone.utc).isoformat(), "http_status": None,
                         "usage": _usage(None), "cost_estimate_cny": None, "price_version": None,
                         "returned_model": None, "resolved_snapshot": None, "first_delta_ms": None}
                trace["request_parameters"] = {"temperature": body.get("temperature"),
                    "max_completion_tokens": body.get("max_completion_tokens", body.get("max_tokens")),
                    "response_format_type": (body.get("response_format") or {}).get("type"),
                    "function_tool_count": len(body.get("tools", [])), "tool_choice": body.get("tool_choice"),
                    "dimensions": body.get("dimensions")}
                emitted = False

                async def delta(text):
                    nonlocal emitted
                    emitted = True
                    if trace["first_delta_ms"] is None:
                        trace["first_delta_ms"] = round((time.monotonic() - started) * 1000, 2)
                    await _callback(on_delta, text)

                error = None
                try:
                    # asyncio enforces a total attempt deadline, including a slowly arriving stream.
                    async with asyncio.timeout(25):
                        if self._client is None:
                            self._client = httpx.AsyncClient(transport=self._transport, timeout=25,
                                                             trust_env=False, follow_redirects=False)
                        async with self._client.stream("POST", base + path, json=body,
                                                       headers={"Authorization": "Bearer " + key}) as response:
                            trace["http_status"] = response.status_code
                            if response.status_code != 200:
                                raise ProviderError("model_http_error", http_status=response.status_code,
                                                    retryable=response.status_code == 429 or response.status_code >= 500)
                            if stream:
                                result = await self._stream(response, delta)
                            else:
                                result = json.loads(await response.aread())
                            if not isinstance(result, dict):
                                raise ProviderError("model_invalid_response")
                            trace["usage"] = _usage(result.get("usage"))
                            returned_model = result.get("model")
                            allowed_returned = ({self.model_id, "qwen3.7-plus", "qwen3.7-plus-2026-05-26"}
                                                if prefix == "MODEL" else {body["model"]})
                            if returned_model is not None and returned_model not in allowed_returned:
                                raise ProviderError("model_response_id_mismatch")
                            trace["returned_model"] = returned_model
                            if prefix == "MODEL":
                                if returned_model == "qwen3.7-plus-2026-05-26":
                                    trace["resolved_snapshot"] = returned_model
                                self._price(trace)
                                choices = result.get("choices")
                                if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                                    raise ProviderError("model_invalid_response")
                                finish_reason = choices[0].get("finish_reason")
                                if finish_reason == "length":
                                    raise ProviderError("model_output_truncated", retryable=True)
                                if finish_reason not in {"stop", "tool_calls"}:
                                    raise ProviderError("model_incomplete_response")
                                output = {"message": _message(choices[0].get("message"))}
                            else:
                                data = result.get("data")
                                if not isinstance(data, list) or len(data) != len(body["input"]):
                                    raise ProviderError("embedding_invalid_response")
                                if any(not isinstance(item, dict) or type(item.get("index")) is not int for item in data):
                                    raise ProviderError("embedding_invalid_response")
                                data = sorted(data, key=lambda item: item["index"])
                                vectors = [item.get("embedding") for item in data]
                                if ([item["index"] for item in data] != list(range(len(data)))
                                        or any(not isinstance(v, list) or len(v) != body["dimensions"]
                                               or any(type(x) not in {int, float} or not math.isfinite(x) for x in v)
                                               or not any(v) for v in vectors)):
                                    raise ProviderError("embedding_invalid_response")
                                output = {"embeddings": vectors}
                            trace["status"] = "succeeded"
                except ProviderError as exc:
                    error = exc
                except (httpx.TimeoutException, TimeoutError):
                    error = ProviderError("model_timeout", retryable=True)
                except httpx.HTTPError:
                    error = ProviderError("model_transport_error", retryable=True)
                except (ValueError, TypeError, KeyError, IndexError):
                    error = ProviderError("model_invalid_response")
                except asyncio.CancelledError:
                    trace["status"] = "cancelled"
                    raise
                finally:
                    if error:
                        trace.update(status="failed", error_code=error.code)
                    trace["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
                    attempts.append(trace)
                    await _callback(on_trace, dict(trace))
            if error:
                error.attempts = attempts
                if not error.retryable or emitted or attempt == max_attempts:
                    self._breakers[prefix].record(False)
                    raise error from None
                if error.code == "model_output_truncated":
                    key = "max_completion_tokens" if "max_completion_tokens" in body else "max_tokens"
                    body[key] = min(4096, max(int(body.get(key) or 1024) * 2, 1))
                await asyncio.sleep(min(0.2 * (2 ** (attempt - 1)), 2.0) + random.uniform(0, 0.1))
                continue
            self._breakers[prefix].record(True)
            metadata = {**trace, "attempts": len(attempts),
                        "latency_ms": round((time.monotonic() - overall_start) * 1000, 2)}
            if prefix == "EMBEDDING":
                metadata["dimensions"] = body["dimensions"]
            from smartlect.observability import prompt_hash, record_generation
            record_generation(
                name=prefix.lower(), model=body.get("model"),
                prompt_hash=prompt_hash(prompt_version, schema_version, body.get("model")),
                usage=trace.get("usage"), metadata={"prompt_version": prompt_version})
            if span is not None:
                usage = trace.get("usage") or {}
                if usage.get("input_tokens") is not None:
                    span.set_attribute("gen_ai.usage.input_tokens", usage["input_tokens"])
                if usage.get("output_tokens") is not None:
                    span.set_attribute("gen_ai.usage.output_tokens", usage["output_tokens"])
            return {**output, "usage": trace["usage"], "metadata": metadata, "attempts": attempts}

    @staticmethod
    def _price(trace):
        usage = trace["usage"]
        if trace["region"] != "cn-beijing" or usage["input_tokens"] is None or usage["output_tokens"] is None:
            return
        input_price, output_price = (2, 8) if usage["input_tokens"] <= 256000 else (6, 24)
        # List-price estimate excludes account discounts and cache discounts; never an invoice.
        trace["cost_estimate_cny"] = round((usage["input_tokens"] * input_price + usage["output_tokens"] * output_price) / 1000000, 8)
        trace["price_version"] = "aliyun-qwen3.7-plus-cn-beijing-2026-09-09-no-discounts"

    @staticmethod
    async def _stream(response, on_delta):
        result = {"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": None}]}
        calls = {}
        done = False
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                done = True
                break
            chunk = json.loads(raw)
            if not isinstance(chunk, dict) or "error" in chunk:
                raise ProviderError("model_stream_error")
            if chunk.get("usage"):
                result["usage"] = chunk["usage"]
            if chunk.get("model"):
                result["model"] = chunk["model"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ProviderError("model_invalid_response")
            choice = choices[0]
            current = result["choices"][0]
            if choice.get("finish_reason"):
                current["finish_reason"] = choice["finish_reason"]
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise ProviderError("model_invalid_response")
            content = delta.get("content")
            if content:
                if not isinstance(content, str):
                    raise ProviderError("model_invalid_response")
                current["message"]["content"] += content
                await _callback(on_delta, content)
            for fragment in delta.get("tool_calls") or []:
                if not isinstance(fragment, dict) or not isinstance(fragment.get("function") or {}, dict):
                    raise ProviderError("model_invalid_tool_calls")
                index = fragment.get("index")
                if type(index) is not int or not 0 <= index < 10:
                    raise ProviderError("model_invalid_tool_calls")
                call = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if fragment.get("id"):
                    call["id"] += fragment["id"]
                if fragment.get("type") not in {None, "function"}:
                    raise ProviderError("model_invalid_tool_calls")
                for field in ("name", "arguments"):
                    call["function"][field] += (fragment.get("function") or {}).get(field) or ""
        if not done:
            raise ProviderError("model_stream_incomplete")
        if calls:
            result["choices"][0]["message"]["tool_calls"] = [calls[i] for i in sorted(calls)]
        return result
