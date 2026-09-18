"""Tool debug console: single-tool invocation with a full audit trail, no write surface.

Debuggable tools are the read-only REGISTRY entries without attribution side effects, plus
one debug-only probe `catalog_search` that runs ShoppingRetrieve directly. search_skus /
recommend_skus / compare_skus stay off this surface for the same reason they stay off MCP:
going through the recommendation service would write exposure receipts into the attribution
ledger that no real display surface will ever report. Every debug call still creates an
agent_run (message_id `debug:*`) and reuses tools.invoke, so it shows up in the runs
browser with the same receipts and idempotency as an agent call — there is no second,
weaker path into the tools.
"""
import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from smartlect.events import canonical
from smartlect.tools import REGISTRY, invoke, tool_schema

# Read tools whose execution writes nothing beyond the debug run itself.
DEBUG_TOOLS = frozenset({"search_knowledge", "get_product_offer"})


class CatalogSearchArgs(BaseModel):
    query: str | None = None
    keyword: str | None = None
    max_price_cents: int | None = None
    min_price_cents: int | None = None
    category_id: str | None = None
    limit: int | None = None


def catalog():
    items = [
        {
            "name": name,
            "description": tool.description,
            "permission": tool.permission,
            "kind": tool.kind,
            "debuggable": name in DEBUG_TOOLS,
        }
        for name, tool in sorted(REGISTRY.items())
    ]
    items.append({
        "name": "catalog_search",
        "description": "调试专用：直接运行购物检索层（关键字/预算/硬约束），返回候选、资格过滤与诊断；"
                       "不写推荐回执、不污染归因账本。",
        "permission": "admin:legacy",
        "kind": "read",
        "debuggable": True,
        "debug_only": True,
        "inputSchema": tool_schema(CatalogSearchArgs),
    })
    return {"tools": items}


def build_router(*, actor_for, store, commerce, knowledge, shopping_retrieve, attribution, provider, config, settings):
    router = APIRouter()

    @router.get("/admin-api/assistant/tools/catalog")
    async def tool_catalog(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        return catalog()

    async def embed_query(query):
        if not config.get("SMARTLECT_EMBEDDING_API_KEY") or settings.model_mode != "live":
            return {}
        result = await provider.embed([query], cacheable=True)
        meta = result["metadata"]
        return {"query_vector": result["embeddings"][0], "embedding_model": meta["model_id"],
                "index_version": f"{meta['model_id']}:d{meta['dimensions']}:v1"}

    @router.post("/admin-api/assistant/tools/invoke")
    async def invoke_tool(payload: dict, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        name = payload.get("name") if isinstance(payload, dict) else None
        arguments = payload.get("arguments") or {} if isinstance(payload, dict) else {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise HTTPException(422, "invalid_debug_request")

        conversation = await asyncio.to_thread(store.create_conversation, actor, identity_key="admin-tool-debug")
        run = await asyncio.to_thread(store.create_run, actor, conversation["conversation_id"],
                                      "debug:" + uuid.uuid4().hex,
                                      canonical({"debug": name, "arguments": arguments}),
                                      model_mode="rule-fallback")
        lease = await asyncio.to_thread(store.claim_run, actor, run["agent_run_id"],
                                        owner="admin-debug", ttl_seconds=60)
        try:
            if name == "catalog_search":
                scope = await asyncio.to_thread(attribution.product_scope, actor)
                receipt = {"data": await shopping_retrieve.recommend(actor, arguments, product_scope=scope)}
            elif name in DEBUG_TOOLS:
                scope = await asyncio.to_thread(attribution.product_scope, actor)
                receipt = await invoke(name, arguments, actor=actor, commerce=commerce, store=store, lease=lease,
                                       knowledge=knowledge, embed_query=embed_query, allowed=DEBUG_TOOLS,
                                       product_scope=scope)
            else:
                raise HTTPException(422, "tool_not_debuggable")
            await asyncio.to_thread(store.finish_run, lease, state="COMPLETED",
                                    result={"receipt": receipt, "debug": True})
            return {"run_id": run["agent_run_id"], "receipt": receipt}
        except HTTPException:
            await asyncio.to_thread(store.finish_run, lease, state="FAILED", result={"error": "tool_not_debuggable"})
            raise
        except Exception as error:
            await asyncio.to_thread(store.finish_run, lease, state="FAILED",
                                    result={"error_type": type(error).__name__, "error": getattr(error, "code", None),
                                            "debug": True})
            raise

    return router
