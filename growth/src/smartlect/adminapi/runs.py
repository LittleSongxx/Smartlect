"""Runs browser endpoints: list + detail over the audit tables, admin:legacy only."""
import asyncio

from fastapi import APIRouter, HTTPException, Request, Response

from .store import AdminRunStore


def build_router(*, actor_for, connect):
    router = APIRouter()
    admin_store = AdminRunStore(connect)

    @router.get("/admin-api/assistant/runs")
    async def list_runs(request: Request, response: Response, agent: str = None, state: str = None, limit: int = 50):
        actor = await actor_for(request, response, realm="merchant")
        actor.require("admin:legacy")
        return await asyncio.to_thread(admin_store.list_runs, actor, agent, state, limit)

    @router.get("/admin-api/assistant/runs/{run_id}")
    async def run_detail(run_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require("admin:legacy")
        try:
            return await asyncio.to_thread(admin_store.run_detail, actor, run_id)
        except Exception as error:
            code = getattr(error, "code", None)
            if code == "run_not_found":
                raise HTTPException(404, code) from None
            if code:
                raise HTTPException(getattr(error, "status", 400), code) from None
            raise

    return router
