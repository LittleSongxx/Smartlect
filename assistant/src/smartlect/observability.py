"""Langfuse no-op without keys + OTEL gen_ai spans. No pretend traces.

Spans follow official GenAI operation names (chat / embeddings / execute_tool /
invoke_agent / retrieve). No exporter or no SDK provider → no-op. Message text
and tool arguments stay out of attributes.

LLM cost comes from provider usage tokens, not a hardcoded Beijing unit price.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from hashlib import sha256

_tracer = None
_langfuse = None
_langfuse_checked = False


def langfuse_enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return bool((env.get("LANGFUSE_PUBLIC_KEY") or env.get("SMARTLECT_LANGFUSE_PUBLIC_KEY") or "").strip()
                and (env.get("LANGFUSE_SECRET_KEY") or env.get("SMARTLECT_LANGFUSE_SECRET_KEY") or "").strip())


def otel_spans_enabled(env=None) -> bool:
    """True only when an exporter is configured and a real SDK provider is installed."""
    env = os.environ if env is None else env
    if not (env.get("SMARTLECT_OTEL_EXPORTER") or "").strip():
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        return isinstance(trace.get_tracer_provider(), TracerProvider)
    except Exception:
        return False


def _langfuse_client():
    global _langfuse, _langfuse_checked
    if _langfuse_checked:
        return _langfuse
    _langfuse_checked = True
    if not langfuse_enabled():
        return None
    try:
        from langfuse import Langfuse
        env = os.environ
        _langfuse = Langfuse(
            public_key=env.get("LANGFUSE_PUBLIC_KEY") or env.get("SMARTLECT_LANGFUSE_PUBLIC_KEY"),
            secret_key=env.get("LANGFUSE_SECRET_KEY") or env.get("SMARTLECT_LANGFUSE_SECRET_KEY"),
            host=env.get("LANGFUSE_HOST") or env.get("SMARTLECT_LANGFUSE_HOST") or "https://cloud.langfuse.com",
        )
    except Exception:
        _langfuse = None
    return _langfuse


def tracer():
    global _tracer
    if not otel_spans_enabled():
        return None
    if _tracer is None:
        try:
            from opentelemetry import trace
            _tracer = trace.get_tracer("smartlect.gen_ai")
        except Exception:
            _tracer = False
    return _tracer or None


def prometheus_counter(name, documentation, labelnames=()):
    """Reuse a collector if a failed or repeated import already registered it."""
    from prometheus_client import REGISTRY, Counter
    try:
        return Counter(name, documentation, labelnames=list(labelnames))
    except ValueError:
        family = name[:-6] if name.endswith("_total") else name
        return REGISTRY._names_to_collectors[family]


def reset_for_tests():
    global _tracer, _langfuse, _langfuse_checked
    _tracer = None
    _langfuse = None
    _langfuse_checked = False


@contextmanager
def gen_ai_span(name, *, kind="chat", attributes=None):
    """One span per LLM / tool / retrieval / agent invoke. No-op when OTEL is not live."""
    traced = tracer()
    attrs = {"gen_ai.operation.name": kind, **(attributes or {})}
    attrs.pop("gen_ai.system", None)
    if traced is None:
        yield None
        return
    with traced.start_as_current_span(name) as span:
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(key, value if isinstance(value, (bool, int, float, str)) else str(value))
        yield span


def record_generation(*, name, model, prompt_hash, usage=None, metadata=None):
    client = _langfuse_client()
    if client is None:
        return
    try:
        client.generation(
            name=name,
            model=model,
            metadata={"prompt_hash": prompt_hash, **(metadata or {})},
            usage=usage or {},
        )
    except Exception:
        return


def prompt_hash(*parts) -> str:
    joined = "\n".join("" if part is None else str(part) for part in parts)
    return sha256(joined.encode()).hexdigest()
