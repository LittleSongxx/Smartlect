"""Knowledge index ops endpoints: async job progress and a retrieval probe.

The probe runs the exact production search path (same ACL, same ranking, same cache) under
the requesting merchant's own visibility, so tuning decisions made on this screen transfer
one-to-one to what users see.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request, Response

from smartlect.indexing import JOB_STATES


def build_router(*, actor_for, indexing, knowledge, provider, config, settings, commerce, projection=None):
    router = APIRouter()

    @router.post("/admin-api/assistant/knowledgeImport/products")
    async def import_product_knowledge(payload: dict, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        body = payload if isinstance(payload, dict) else {}
        product_ids = body.get("productIds")
        if product_ids is not None and (not isinstance(product_ids, list) or not product_ids
                                        or len(product_ids) > 200
                                        or any(not isinstance(item, str) or not item for item in product_ids)):
            raise HTTPException(422, "invalid_product_ids")
        if projection is None:
            raise HTTPException(503, "product_projection_unavailable")
        return await projection.import_catalog(actor, None if product_ids is None else product_ids)

    @router.get("/admin-api/assistant/productProjection/{product_id}")
    async def product_projection_status(product_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        if projection is None:
            raise HTTPException(503, "product_projection_unavailable")
        return await asyncio.to_thread(projection.status, actor, product_id)

    @router.post("/admin-api/assistant/productProjection/{product_id}/retry")
    async def product_projection_retry(product_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        if projection is None:
            raise HTTPException(503, "product_projection_unavailable")
        return await asyncio.to_thread(projection.retry, actor, product_id)

    @router.get("/admin-api/assistant/knowledgeIndex/jobs")
    async def index_jobs(request: Request, response: Response, limit: int = 20):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        return {"items": await asyncio.to_thread(indexing.jobs.list_jobs, actor, limit), "states": list(JOB_STATES)}

    @router.get("/admin-api/assistant/knowledgeIndex/jobs/{job_id}")
    async def index_job(job_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        try:
            return await asyncio.to_thread(indexing.jobs.get_job, actor, job_id)
        except Exception as error:
            if getattr(error, "code", None) == "index_job_not_found":
                raise HTTPException(404, "index_job_not_found") from None
            raise

    @router.post("/admin-api/assistant/knowledgeIndex/searchProbe")
    async def search_probe(payload: dict, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require("admin:legacy")
        query = payload.get("query") if isinstance(payload, dict) else None
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise HTTPException(422, "invalid_query")

        async def embed_query(text):
            if not config.get("SMARTLECT_EMBEDDING_API_KEY") or settings.model_mode != "live":
                return {}
            result = await provider.embed([text], cacheable=True)
            meta = result["metadata"]
            return {"query_vector": result["embeddings"][0], "embedding_model": meta["model_id"],
                    "index_version": f"{meta['model_id']}:d{meta['dimensions']}:v1"}

        try:
            vectors = await embed_query(query)
        except Exception as error:
            vectors = {"dense_error": getattr(error, "code", type(error).__name__)}
        result = await asyncio.to_thread(knowledge.search, actor, query, utterance=query, **{
            key: value for key, value in vectors.items() if key != "dense_error"})
        result.setdefault("retrieval", {})
        if "dense_error" in vectors:
            result["retrieval"]["dense_error"] = vectors["dense_error"]
        result["retrieval"]["submitted_query"] = query
        return result

    return router
