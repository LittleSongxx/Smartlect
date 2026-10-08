"""Analytics endpoints: feedback summary, cost attribution, preference history.

admin:legacy / admin:trial only, scope-filtered like the run browser. Read-only.
"""
import asyncio

from fastapi import APIRouter, Request, Response

from .store import AdminRunStore


def build_router(*, actor_for, connect):
    router = APIRouter()
    admin_store = AdminRunStore(connect)

    @router.get("/admin-api/assistant/feedback-summary")
    async def feedback_summary(request: Request, response: Response, days: int = 30):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        return await asyncio.to_thread(admin_store.feedback_summary, actor, days)

    @router.get("/admin-api/assistant/cost-attribution")
    async def cost_attribution(request: Request, response: Response, days: int = 30, limit: int = 500):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        return await asyncio.to_thread(admin_store.cost_attribution, actor, days, limit)

    @router.get("/admin-api/assistant/preferences-history")
    async def preferences_history(request: Request, response: Response,
                                  actor_id: str = None, key: str = None, limit: int = 100):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        return await asyncio.to_thread(admin_store.preference_history, actor, actor_id, key, limit)

    return router
