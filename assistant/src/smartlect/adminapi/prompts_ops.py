"""Prompt & skill template management: versions, activation (rollback), body access.

Editing is text-only and limited to the packaged skill set; structural changes still ship
with code. Activation is one atomic switch per (domain, kind, key) and lands in the next
agent run through the runtime resolver.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request, Response

from smartlect.prompts import PromptStore
from smartlect.state import StateError


def build_router(*, actor_for, connect):
    router = APIRouter()
    store = PromptStore(connect)

    @router.get("/admin-api/assistant/prompts")
    async def prompt_keys(request: Request, response: Response, domain: str = None):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        try:
            # Idempotent; also heals a startup whose seeding window hit a brief DB outage.
            await asyncio.to_thread(store.seed_defaults)
        except Exception:
            pass
        domains = [domain] if domain in ("shopping", "merchant") else ["shopping", "merchant"]
        result = {}
        for name in domains:
            keys = await asyncio.to_thread(store.keys, name)
            for key in keys:
                key["domain"] = name
            result[name] = keys
        return {"domains": result}

    @router.get("/admin-api/assistant/prompts/{domain}/{kind}/{key}/versions")
    async def prompt_versions(domain: str, kind: str, key: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        try:
            return {"items": await asyncio.to_thread(store.versions, domain, kind, key)}
        except StateError as error:
            raise HTTPException(422, error.code) from None

    @router.get("/admin-api/assistant/prompts/{domain}/{kind}/{key}/{version}")
    async def prompt_body(domain: str, kind: str, key: str, version: int,
                          request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        try:
            return await asyncio.to_thread(store.body_of, domain, kind, key, version)
        except StateError as error:
            raise HTTPException(404, error.code) from None

    @router.post("/admin-api/assistant/prompts/{domain}/{kind}/{key}")
    async def create_prompt_version(domain: str, kind: str, key: str, payload: dict,
                                    request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        body = payload.get("body") if isinstance(payload, dict) else None
        if not isinstance(body, str) or not body.strip():
            raise HTTPException(422, "invalid_prompt_body")
        try:
            return await asyncio.to_thread(store.create_version, actor, domain, kind, key, body,
                                           payload.get("meta") if isinstance(payload, dict) else None)
        except StateError as error:
            raise HTTPException(422, error.code) from None

    @router.post("/admin-api/assistant/prompts/{domain}/{kind}/{key}/{version}/activate")
    async def activate_prompt(domain: str, kind: str, key: str, version: int,
                              request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        try:
            return await asyncio.to_thread(store.activate, actor, domain, kind, key, version)
        except StateError as error:
            raise HTTPException(404 if error.code == "prompt_version_not_found" else 422, error.code) from None

    return router
