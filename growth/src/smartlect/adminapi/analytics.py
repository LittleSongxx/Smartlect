"""Review analysis and growth report endpoints: deterministic data plus model narration."""
import asyncio

from fastapi import APIRouter, HTTPException, Request, Response

from smartlect import growth_report, review_analysis
from smartlect.state import StateError


def build_router(*, actor_for, store, commerce, attribution, provider, settings, ads=None):
    router = APIRouter()

    def translate(error):
        code = getattr(error, "code", None)
        if code:
            raise HTTPException(getattr(error, "status", 422), code) from None
        raise

    @router.get("/admin-api/assistant/reviewAnalysis")
    async def list_analyses(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        return {"items": await asyncio.to_thread(review_analysis.ReviewAnalysisStore(store.connect).list_, actor)}

    @router.get("/admin-api/assistant/reviewAnalysis/product/{product_id}")
    async def get_analysis(product_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        row = await asyncio.to_thread(review_analysis.ReviewAnalysisStore(store.connect).get, actor, product_id)
        if row is None:
            raise HTTPException(404, "analysis_not_found")
        return row

    @router.post("/admin-api/assistant/reviewAnalysis/product/{product_id}")
    async def run_analysis(product_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        try:
            return await review_analysis.analyze(actor, commerce, provider, product_id=product_id,
                                                 settings=settings, store_connect=store.connect)
        except StateError as error:
            translate(error)

    @router.get("/admin-api/assistant/growthReport")
    async def growth_report_view(request: Request, response: Response, limit: int = 10):
        actor = await actor_for(request, response, realm="merchant")
        actor.require_any("admin:legacy", "admin:trial")
        return {"latest": await asyncio.to_thread(growth_report.GrowthReportStore(store.connect).get, actor),
                "history": await asyncio.to_thread(growth_report.GrowthReportStore(store.connect).history, actor, limit)}

    @router.post("/admin-api/assistant/growthReport/generate")
    async def growth_report_generate(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant", write=True)
        actor.require("admin:legacy")
        try:
            return await growth_report.generate(actor, attribution, store, provider,
                                                settings=settings, ads=ads)
        except StateError as error:
            translate(error)

    return router
