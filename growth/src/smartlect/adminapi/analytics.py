"""Retired review-analysis and growth-report endpoints. They refuse after auth."""
from fastapi import APIRouter, Request, Response

from smartlect.disabled_features import reject


def build_router(*, actor_for, store, commerce, attribution, provider, settings, ads=None):
    router = APIRouter()

    @router.get("/admin-api/assistant/reviewAnalysis")
    async def list_analyses(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        reject("review_analysis")

    @router.get("/admin-api/assistant/reviewAnalysis/product/{product_id}")
    async def get_analysis(product_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        reject("review_analysis")

    @router.post("/admin-api/assistant/reviewAnalysis/product/{product_id}")
    async def run_analysis(product_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        reject("review_analysis")

    @router.get("/admin-api/assistant/growthReport")
    async def growth_report_view(request: Request, response: Response, limit: int = 10):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        reject("growth_report")

    @router.post("/admin-api/assistant/growthReport/generate")
    async def growth_report_generate(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        reject("growth_report")

    return router
