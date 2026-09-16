"""Model runtime config endpoints: which whitelisted chat model is active, plus a probe.

Keys never move: the console shows only presence badges read from the environment, and
switching is restricted to models the configured endpoint family can serve.
"""
import asyncio
import time

from fastapi import APIRouter, HTTPException, Request, Response

from smartlect.model_config import ModelConfigStore
from smartlect.provider import ProviderError


def build_router(*, actor_for, connect, provider, config):
    router = APIRouter()
    store = ModelConfigStore(connect)

    @router.get("/admin-api/assistant/models")
    async def models(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require("admin:legacy")
        selected = await asyncio.to_thread(store.chat_config)
        return {
            "chat": {
                "model_id": provider.effective_chat_model(),
                "runtime_selected": (selected or {}).get("model_id"),
                "env_model_id": provider.model_id,
                "options": provider.runtime_chat_options(),
                "updated_by": (selected or {}).get("updated_by"),
                "updated_at": (selected or {}).get("updated_at"),
                "note": (selected or {}).get("note"),
            },
            "env": {
                "chat_key_configured": bool(config.get("SMARTLECT_MODEL_API_KEY")),
                "chat_base_url": bool(config.get("SMARTLECT_MODEL_BASE_URL")),
                "embedding_key_configured": bool(config.get("SMARTLECT_EMBEDDING_API_KEY")),
                "embedding_model": config.get("SMARTLECT_EMBEDDING_MODEL"),
                "model_mode": config.get("SMARTLECT_MODEL_MODE", "mock"),
            },
        }

    @router.post("/admin-api/assistant/models/chat")
    async def save_chat(payload: dict, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        body = payload if isinstance(payload, dict) else {}
        model_id = body.get("model_id")
        options = provider.runtime_chat_options()
        if model_id not in options:
            # Distinguish "not whitelisted at all" from "whitelisted but wrong endpoint family".
            raise HTTPException(422, "model_not_allowed_for_endpoint" if model_id else "invalid_model_id")
        row = await asyncio.to_thread(store.save_chat, actor, model_id, body.get("note"))
        provider.invalidate_runtime_cache()
        return row

    @router.post("/admin-api/assistant/models/testConnection")
    async def test_connection(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        started = time.monotonic()
        try:
            message = await provider.chat([{"role": "user", "content": "连接测试，请只回复：OK"}],
                                          max_tokens=8, max_attempts=1, prompt_version="model-config-probe-v1")
            return {"ok": True, "model_id": provider.effective_chat_model(),
                    "latency_ms": round((time.monotonic() - started) * 1000), "reply": str(message)[:64]}
        except ProviderError as error:
            return {"ok": False, "model_id": provider.effective_chat_model(),
                    "latency_ms": round((time.monotonic() - started) * 1000), "error": error.code}
        except Exception as error:
            return {"ok": False, "model_id": provider.effective_chat_model(),
                    "latency_ms": round((time.monotonic() - started) * 1000), "error": type(error).__name__}

    return router

