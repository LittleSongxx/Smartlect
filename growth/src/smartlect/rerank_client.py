"""Vendor rerank HTTP. Missing key or HTTP failure is an explicit fallback, not a silent formula.

Configured via SMARTLECT_RERANK_API_KEY / BASE_URL / MODEL. This is not a local
cross-encoder unless that model is what the vendor endpoint serves.
"""
from __future__ import annotations

import os

import httpx

from smartlect.algo_version import content_hash

RERANK_ALGO = content_hash({"channel": "vendor_http", "role": "cross_encoder_or_vendor_rerank"})


class RerankError(RuntimeError):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def configured(env=None) -> bool:
    env = os.environ if env is None else env
    return bool((env.get("SMARTLECT_RERANK_API_KEY") or "").strip())


async def rerank_texts(query, documents, *, env=None, client=None, top_n=None):
    """Return permutation of document indexes, best first. Raises RerankError on failure."""
    env = os.environ if env is None else env
    key = (env.get("SMARTLECT_RERANK_API_KEY") or "").strip()
    if not key:
        raise RerankError("rerank_not_configured")
    if not documents:
        return []
    base = (env.get("SMARTLECT_RERANK_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-api/v1").rstrip("/")
    model = env.get("SMARTLECT_RERANK_MODEL") or "gte-rerank-v2"
    limit = top_n or len(documents)
    body = {
        "model": model,
        "query": query,
        "documents": list(documents),
        "top_n": min(limit, len(documents)),
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False)
    try:
        response = await client.post(f"{base}/reranks", json=body, headers=headers)
        if response.status_code >= 400:
            raise RerankError("rerank_http_error", f"status={response.status_code}")
        payload = response.json()
        results = payload.get("results") or payload.get("output", {}).get("results") or []
        order = []
        for item in results:
            if isinstance(item, dict) and "index" in item:
                order.append(int(item["index"]))
        if not order:
            raise RerankError("rerank_empty_result")
        seen = set(order)
        for index in range(len(documents)):
            if index not in seen:
                order.append(index)
        return order[:len(documents)]
    except RerankError:
        raise
    except Exception as error:
        raise RerankError("rerank_unavailable", type(error).__name__) from error
    finally:
        if own_client:
            await client.aclose()
