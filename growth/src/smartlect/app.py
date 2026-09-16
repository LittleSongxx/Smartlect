"""Smartlect FastAPI, trusted sessions, durable proposals and read-only SSE replay."""
import argparse
import asyncio
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import Field, ValidationError
import uvicorn

from smartlect import __version__
from smartlect.auth import IdentityBridge
from smartlect.commerce import AsyncCommerceClient, CommerceError, CommerceRejected, ORDER_ACTION_STATUS_PATH
from smartlect.config import Settings
from prometheus_client import Counter as PrometheusCounter

from smartlect.events import Ledger, canonical

RUN_ADMISSION_REJECTIONS = PrometheusCounter("growth_run_admission_rejections_total",
                                             "New runs rejected by the concurrency admission gates", ["gate"])
from smartlect import mcp
from smartlect.state import SessionStore, StateError
from smartlect.tools import Arguments, invoke
from smartlect.worker import worker_health
from smartlect.agents.shopping import run_shopping
from smartlect.provider import IndexModelAudit, Provider, ProviderError, bounded
from smartlect.knowledge import KnowledgeStore
from smartlect.memory import MemoryStore
from smartlect.privacy import redact_text
from smartlect.documents import parse_document, MAX_INPUT_BYTES
from smartlect.attribution import AttributionStore
from smartlect.recommendation.service import RecommendationService, RecommendationRequest
from smartlect.recommendation.store import StrategyStore
from smartlect.ads.inference import sync_behavior_preferences
from smartlect.ads.service import (AdsService, CampaignRequest, CreativeRequest, GrantRequest,
                                  ActionRequest, RevokeRequest, AdExposureRequest, AdClickRequest)
from smartlect.ads.store import AdsStore
from smartlect.merchant.store import MerchantStore
from smartlect.merchant.service import (MerchantService, MerchantRunRequest, PlanExecuteRequest,
                                        ExperienceApproveRequest, ScopeSelectRequest)


async def db(function, *args, **kwargs):
    return await asyncio.to_thread(function, *args, **kwargs)


log = logging.getLogger(__name__)


class MessageRequest(Arguments):
    message_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8000)
    product_id: str | None = Field(default=None, max_length=64)
    sku_key: str | None = Field(default=None, max_length=256)


class ProposalRequest(Arguments):
    message_id: str = Field(min_length=1, max_length=128)
    action_type: Literal["order", "cancel", "refund"]
    parameters: dict


class ConfirmRequest(Arguments):
    proposal_version: int = Field(ge=1)
    approved: bool = True


class ValueRequest(Arguments):
    value: str | int | list[str]


class PaymentRequest(Arguments):
    expected_amount_cents: int = Field(ge=0)


class LandingRequest(Arguments):
    entry_id: str = Field(min_length=1, max_length=64)


class ExposureRequest(Arguments):
    positions: list[int] = Field(min_length=1, max_length=8)


class ClickRequest(Arguments):
    position: int = Field(ge=1, le=8)


class AttributionItem(Arguments):
    requestId: str = Field(min_length=1, max_length=128)
    productId: str = Field(min_length=1, max_length=64)
    skuKey: str | None = Field(default=None, max_length=128)
    position: int = Field(ge=1, le=20)


class AttributionBatch(Arguments):
    userId: str = Field(min_length=1, max_length=64)
    items: list[AttributionItem] = Field(min_length=1, max_length=100)


class TicketRequest(Arguments):
    action: Literal['take_over', 'reply', 'close']
    version: int = Field(ge=1)
    reply: str | None = Field(default=None, max_length=4000)


class KnowledgeRequest(Arguments):
    doc_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=40000)
    source_uri: str = Field(min_length=1, max_length=512)
    acl: Literal['PUBLIC', 'USER', 'MERCHANT', 'ACTOR']
    acl_actor_id: str | None = None
    valid_from: str
    valid_until: str
    language: Literal['zh-CN', 'en', 'mixed'] = 'zh-CN'
    product_ids: list[str] = Field(default_factory=list, max_length=100)
    category_ids: list[str] = Field(default_factory=list, max_length=100)
    facts: dict[str, str] = Field(default_factory=dict)


def health(settings):
    return {"service": "smartlect-growth", "version": __version__, "status": "ok",
            "phase": "F3" if settings.events_enabled else "P0", "model_mode": settings.model_mode}


async def execute_proposal(proposal, actor, commerce, attribution=None):
    action = proposal["action_type"]
    if action == 'payment':
        if commerce.config.get('SMARTLECT_PAYMENT_MODE') != 'mock':
            raise CommerceRejected(403, 'mock_payment_disabled')
        params = proposal['parameters']
        query = {'actionType': 'PAYMENT', 'params': {'payOrderId': params['payOrderId']}}
        current = await commerce.request('order', ORDER_ACTION_STATUS_PATH, actor=actor, data=query)
        if current.get('amountCents') != params['expected_amount_cents']:
            raise CommerceRejected(409, 'RECONFIRM_REQUIRED')
        if current.get('paymentStatus') == 'PENDING':
            await commerce.request('pay', '/internal/pay/mock/complete', actor=actor,
                                   data={'payOrderId': params['payOrderId']}, key=proposal['idempotency_key'])
            current = await commerce.request('order', ORDER_ACTION_STATUS_PATH, actor=actor, data=query)
        return current
    kinds = {"order": "CREATE_ORDER", "cancel": "CANCEL_ORDER", "refund": "REFUND"}
    if action not in kinds:
        raise CommerceRejected(403, "action_not_allowed")
    params = proposal["parameters"]
    if proposal["recover_only"]:
        try:
            status = await commerce.request("order", ORDER_ACTION_STATUS_PATH, actor=actor, data={
                "actionType": kinds[action], "idempotencyKey": proposal["idempotency_key"],
                "params": {} if action == "order" else params})
        except CommerceRejected:
            # A rejected query says nothing about whether the prior write committed.
            raise CommerceError("commerce_outcome_unknown") from None
        if status.get("status") != "NOT_FOUND":
            return status
    if action == "order":
        optional = {}
        attribution_attached = False
        if attribution is not None:
            try:
                token = await asyncio.wait_for(db(attribution.freeze_context, actor, proposal['action_id']), .5)
                if token:
                    optional['attributionContextToken'] = token
                    attribution_attached = True
            except Exception:
                log.warning('attribution freeze failed for action_id=%s', proposal.get('action_id'), exc_info=True)
        result = await commerce.request("order", "/internal/order/commerce/v2/createConfirmed", actor=actor,
                                      key=proposal["idempotency_key"], data={
                                          "quoteId": proposal["quote_id"], "confirmedAmountCents": proposal["quote_total_cents"],
                                          "order": params, **optional})
        receipt = dict(result) if isinstance(result, dict) else {'data': result}
        receipt['attribution_attached'] = attribution_attached
        return receipt
    return await commerce.request("order", "/internal/order/commerce/v2/executeAction", actor=actor,
                                  key=proposal["idempotency_key"], data={"actionType": kinds[action], "params": params})


def create_app(settings=None, *, config=None, store=None, ledger=None, identity=None, commerce=None,
               knowledge=None, memory=None, provider=None, attribution=None, recommendations=None, ads=None, merchant=None):
    settings = settings or Settings.from_env()
    config = dict(os.environ) if config is None else config
    if settings.events_enabled:
        store = store or SessionStore()
        ledger = ledger or Ledger()
    if identity is None and config.get("SMARTLECT_VISITOR_SECRET"):
        identity = IdentityBridge(config)
    commerce = commerce or AsyncCommerceClient(config)
    knowledge = knowledge or (KnowledgeStore(store.connect) if store else None)
    memory = memory or (MemoryStore(store.connect) if store else None)
    from smartlect.model_config import ModelConfigStore
    provider = provider or Provider(config, runtime_loader=ModelConfigStore(store.connect).loader() if store else None)
    attribution = attribution or (AttributionStore(store.connect, secret=config.get('SMARTLECT_ATTRIBUTION_SECRET')) if store else None)
    recommendations = recommendations or (RecommendationService(commerce, StrategyStore(store.connect)) if store else None)
    ads = ads or (AdsService(commerce, AdsStore(store.connect)) if store else None)
    merchant = merchant or (MerchantService(MerchantStore(store.connect),ads,provider,config) if store else None)
    tasks = {}
    task_owners = {}  # run_id -> (subject_type, actor_id); admission counts live executors, not stale DB rows
    actor_run_limit = bounded(config.get("SMARTLECT_GROWTH_RUNS_PER_ACTOR"), 3, 1, 64)
    global_run_limit = bounded(config.get("SMARTLECT_GROWTH_RUNS_GLOBAL"), 24, 1, 512)

    @asynccontextmanager
    async def lifespan(app):
        if store is not None:
            await db(store.initialize)
        if indexing is not None:
            await indexing.resume_stale()
        yield
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        if indexing is not None:
            indexing.shutdown()

    app = FastAPI(title="Smartlect AI API", version=__version__, lifespan=lifespan)

    async def admit_runs(actor):
        """Two gates before a new run starts executing: per-actor and global live-run
        counts. Idempotent replays of an already-running run never pass through here."""
        owner = (actor.subject_type, actor.actor_id)
        if sum(1 for held in task_owners.values() if held == owner) >= actor_run_limit:
            RUN_ADMISSION_REJECTIONS.labels("actor").inc()
            raise StateError("actor_run_limit", 429)
        if len(tasks) >= global_run_limit:
            RUN_ADMISSION_REJECTIONS.labels("global").inc()
            raise StateError("assistant_busy", 429)
    Instrumentator().instrument(app).expose(app, include_in_schema=False)

    # OTel 追踪（T1-7）：仅在显式配置端点且依赖可用时启用——未装包/未配置的
    # 环境（本地测试、CI）自动跳过，零影响。W3C traceparent 由 FastAPI/httpx
    # 插桩自动提取/注入，与 Java 侧 OTel javaagent 打通。
    def _instrument_otel():
        endpoint = config.get("SMARTLECT_OTEL_EXPORTER")
        if not endpoint:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            return
        provider = TracerProvider(resource=Resource.create({"service.name": "smartlect-growth"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider,
                                            excluded_urls="health,metrics")
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    _instrument_otel()

    @app.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        return response

    @app.exception_handler(StateError)
    async def state_error(request, error):
        return JSONResponse(status_code=error.status, content={"error": error.code})

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        # Rejected input may contain credentials. Return field locations only.
        return JSONResponse(status_code=422, content={"error": "invalid_request",
                            "fields": [list(item["loc"]) for item in error.errors()]})

    @app.exception_handler(CommerceRejected)
    async def commerce_rejected(request, error):
        return JSONResponse(status_code=409, content={"error": error.reason})

    @app.exception_handler(CommerceError)
    async def commerce_unknown(request, error):
        return JSONResponse(status_code=503, content={"error": "commerce_outcome_unknown"})

    @app.exception_handler(ProviderError)
    async def provider_error(request, error):
        return JSONResponse(status_code=503, content={'error': error.code})

    async def actor_for(request, response, *, write=False, user=False, realm="user"):
        if identity is None or store is None:
            raise HTTPException(503, "assistant_not_configured")
        actor = await identity.authenticate(request, response, realm=realm)
        if attribution is not None:
            actor = await db(attribution.resolve_actor, actor)
        if merchant is not None and actor.subject_type=='merchant':
            actor = await db(merchant.store.selected_actor,actor)
        if user:
            if actor.subject_type != "user":
                raise HTTPException(401, "login_required")
            actor.require("orders:write")
        if write:
            identity.require_csrf(request, actor)
            if attribution is not None and actor.execution_scope_id!='store':
                await db(attribution.assert_scope_writable,actor)
        return actor

    @app.get("/health")
    def get_health():
        result = health(settings)
        if settings.events_enabled:
            result["consumer"] = worker_health()
            if not result["consumer"]["connected"]:
                result["status"] = "degraded"
        return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=result)

    @app.get("/internal/ledger/summary")
    def summary(request: Request, payOrderId: str | None = None):
        expected = config.get("SMARTLECT_INTERNAL_TOKEN", "")
        supplied = request.headers.get("x-internal-token", "")
        if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
            raise HTTPException(401, "invalid_internal_token")
        if ledger is None:
            raise HTTPException(503, "commerce_ledger_disabled")
        try:
            return ledger.summary(payOrderId)
        except ValueError:
            raise HTTPException(400, "invalid_ledger_query") from None
        except Exception:
            raise HTTPException(503, "commerce_ledger_unavailable") from None

    @app.post('/internal/attribution/validateBatch')
    async def attribution_batch(payload: AttributionBatch, request: Request):
        expected = config.get('SMARTLECT_INTERNAL_TOKEN', '')
        if not expected or not hmac.compare_digest(expected.encode(), request.headers.get('x-internal-token', '').encode()):
            raise HTTPException(401, 'invalid_internal_token')
        result = await db(attribution.validate_batch, payload.userId, [item.model_dump() for item in payload.items])
        return {'status': 'success', 'code': 200, 'data': result}

    @app.get('/admin-api/assistant/attribution')
    async def attribution_report(request: Request, response: Response, payOrderId: str | None = None):
        return await db(attribution.summary, await actor_for(request, response, realm='merchant'), payOrderId)

    @app.get("/api/assistant/session")
    async def session(request: Request, response: Response):
        actor = await actor_for(request, response)
        return {"actor": actor.model_dump(), "csrf_token": identity.csrf_token(actor), 'model_mode': settings.model_mode}

    @app.get("/api/assistant/catalog/scope")
    async def catalog_scope(request: Request, response: Response):
        actor = await actor_for(request, response)
        if attribution is None:
            raise HTTPException(503, 'attribution_unavailable')
        return await db(attribution.product_scope, actor)

    @app.get("/admin-api/assistant/session")
    async def merchant_session(request: Request, response: Response):
        actor = await actor_for(request, response, realm="merchant")
        return {"actor": actor.model_dump(), "csrf_token": identity.csrf_token(actor)}

    async def ads_merchant(request, response, *, write=False):
        actor = await actor_for(request, response, realm='merchant', write=write)
        actor.require('admin:legacy')
        if ads is None:
            raise HTTPException(503, 'ads_not_configured')
        return actor

    @app.get('/admin-api/assistant/ads')
    async def ad_snapshot(request: Request, response: Response):
        actor = await ads_merchant(request, response)
        return await db(ads.store.snapshot, actor)

    @app.get('/admin-api/assistant/scopes')
    async def merchant_scopes(request: Request,response: Response):
        actor=await ads_merchant(request,response)
        return await db(merchant.store.scopes,actor)

    @app.post('/admin-api/assistant/scopes/select')
    async def merchant_select_scope(payload: ScopeSelectRequest,request: Request,response: Response):
        actor=await ads_merchant(request,response)
        identity.require_csrf(request,actor)
        selected=await db(merchant.store.select_scope,actor,payload.execution_scope_id)
        return {'actor':selected.model_dump(),'csrf_token':identity.csrf_token(selected)}

    @app.get('/admin-api/assistant/ads/catalog')
    async def ad_catalog(request: Request,response: Response):
        return await merchant.catalog(await ads_merchant(request,response))

    @app.get('/admin-api/assistant/merchant')
    async def merchant_snapshot(request: Request,response: Response):
        return await db(merchant.store.merchant_snapshot,await ads_merchant(request,response))

    @app.post('/admin-api/assistant/merchant/runs')
    async def merchant_create_run(payload: MerchantRunRequest,request: Request,response: Response):
        actor=await ads_merchant(request,response,write=True)
        await admit_runs(actor)
        run,lease=await merchant.prepare_run(actor,payload.model_dump(exclude_none=True))
        if lease is not None:
            task=asyncio.create_task(merchant.run(actor,run,lease))
            key='merchant:'+run['agent_run_id']
            owner=(actor.subject_type,actor.actor_id)
            tasks[key]=task
            task_owners[key]=owner
            task.add_done_callback(lambda completed:(tasks.pop(key,None),task_owners.pop(key,None)))
        return run

    @app.get('/admin-api/assistant/merchant/runs/{run_id}')
    async def merchant_get_run(run_id: str,request: Request,response: Response):
        actor=await ads_merchant(request,response)
        await db(merchant.store.get_merchant_context,actor,run_id)
        return await db(merchant.store.get_run,actor,run_id)

    @app.post('/admin-api/assistant/merchant/plans/{plan_id}/execute')
    async def merchant_execute(plan_id: str,payload: PlanExecuteRequest,request: Request,response: Response):
        return await merchant.execute_plan(await ads_merchant(request,response,write=True),plan_id,payload.expected_version)

    @app.post('/admin-api/assistant/merchant/memories/{memory_id}/approve')
    async def merchant_approve_memory(memory_id: str,payload: ExperienceApproveRequest,request: Request,response: Response):
        return await db(merchant.store.approve_experience,await ads_merchant(request,response,write=True),memory_id,payload.expected_version,payload.reviewed_content)

    @app.post('/admin-api/assistant/ads/campaigns')
    async def ad_campaign(payload: CampaignRequest, request: Request, response: Response):
        actor = await ads_merchant(request, response, write=True)
        return await ads.create_campaign(actor, payload.model_dump(exclude_none=True))

    @app.post('/admin-api/assistant/ads/creatives')
    async def ad_creative(payload: CreativeRequest, request: Request, response: Response):
        actor = await ads_merchant(request, response, write=True)
        return await db(ads.store.create_creative, actor, payload.model_dump(exclude_none=True))

    @app.post('/admin-api/assistant/ads/grants')
    async def ad_grant(payload: GrantRequest, request: Request, response: Response):
        actor = await ads_merchant(request, response, write=True)
        return await db(ads.store.approve_grant, actor, payload.model_dump(exclude_none=True))

    @app.post('/admin-api/assistant/ads/grants/{grant_id}/revoke')
    async def ad_revoke(grant_id: str, payload: RevokeRequest, request: Request, response: Response):
        actor = await ads_merchant(request, response, write=True)
        return await db(ads.store.revoke_grant, actor, grant_id, payload.model_dump(exclude_none=True))

    @app.post('/admin-api/assistant/ads/actions')
    async def ad_action(payload: ActionRequest, request: Request, response: Response):
        actor = await ads_merchant(request, response, write=True)
        return await ads.execute_action(actor, payload.model_dump(exclude_none=True))

    @app.get('/admin-api/assistant/ads/actions/{action_id}')
    async def ad_action_receipt(action_id: str, request: Request, response: Response):
        actor = await ads_merchant(request, response)
        return await db(ads.store.get_action, actor, action_id)

    @app.get('/api/assistant/ads/recommendations')
    async def ad_recommendations(request: Request, response: Response, limit: int = 2):
        actor = await actor_for(request, response)
        actor.require('shopping:read')
        if ads is None:
            raise HTTPException(503, 'ads_not_configured')
        if actor.subject_type == 'user' and memory:
            await sync_behavior_preferences(commerce, memory, actor)
            preferences = await db(memory.preferences, actor)
        else:
            preferences = []
        return await ads.recommend(actor, limit=limit, preferences=preferences)

    @app.post('/api/assistant/ads/exposures')
    async def ad_exposure(payload: AdExposureRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True)
        actor.require('shopping:read')
        if ads is None:
            raise HTTPException(503, 'ads_not_configured')
        return await ads.expose(actor, payload.model_dump(exclude_none=True))

    @app.post('/api/assistant/ads/clicks')
    async def ad_click(payload: AdClickRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True)
        actor.require('shopping:read')
        if ads is None:
            raise HTTPException(503, 'ads_not_configured')
        return await ads.click(actor, payload.model_dump())

    @app.post("/api/assistant/conversations")
    async def create_conversation(request: Request, response: Response, payload: Arguments):
        actor = await actor_for(request, response, write=True)
        return await db(store.create_conversation, actor)

    @app.post('/api/assistant/traffic/landing')
    async def landing(payload: LandingRequest, request: Request, response: Response):
        return await db(attribution.landing, await actor_for(request, response, write=True), payload.entry_id)

    @app.post('/api/assistant/traffic/bind')
    async def bind_visitor(payload: Arguments, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        if not actor.visitor_id:
            return {'bound': False, 'conversation_ids': [], 'assignment_conflict': False}
        try:
            return await db(attribution.bind_visitor, actor)
        except StateError as error:
            if error.code not in {'visitor_already_bound_to_another_account', 'visitor_scope_conflict'}:
                raise
            result = JSONResponse(status_code=409, content={'error': error.code})
            result.delete_cookie('smartlect_visitor')
            return result

    @app.get('/api/assistant/recommendations')
    async def recommend(request: Request, response: Response, query: str = '', max_price_cents: int | None = None,
                        category_id: str | None = None, product_id: str | None = None, limit: int = 4):
        actor = await actor_for(request, response)
        await db(attribution.assert_scope_writable,actor)
        params = RecommendationRequest(query=query, max_price_cents=max_price_cents, category_id=category_id, product_id=product_id, limit=limit)
        preferences = await db(memory.preferences, actor) if actor.subject_type == 'user' else []
        seed = None
        if actor.subject_type == 'user':
            try:
                latest = await commerce.request('user', '/internal/user/commerce/latestBrowseProductId', actor=actor, data={})
                seed = latest.get('productId') if latest else None
            except CommerceError:
                pass
        result = await recommendations.recommend(actor, params, preferences=preferences, seed_product_id=seed,
            subject_key=actor.recommendation_subject_key, product_scope=await db(attribution.product_scope, actor))
        return await db(attribution.save_recommendation, actor, result)

    @app.post('/api/assistant/recommendations/{recommendation_id}/exposures')
    async def exposures(recommendation_id: str, payload: ExposureRequest, request: Request, response: Response):
        return await db(attribution.interact, await actor_for(request, response, write=True), recommendation_id, payload.positions)

    @app.post('/api/assistant/recommendations/{recommendation_id}/clicks')
    async def recommendation_click(recommendation_id: str, payload: ClickRequest, request: Request, response: Response):
        return await db(attribution.interact, await actor_for(request, response, write=True), recommendation_id, [payload.position], clicked=True)

    @app.get('/api/assistant/conversations')
    async def conversations(request: Request, response: Response):
        return await db(store.list_conversations, await actor_for(request, response))

    @app.get("/api/assistant/conversations/{conversation_id}")
    async def conversation(conversation_id: str, request: Request, response: Response):
        actor = await actor_for(request, response)
        result = await db(store.get_conversation, actor, conversation_id)
        result['handoff'] = await db(memory.handoff_state, actor, conversation_id)
        return result

    @app.post("/api/assistant/conversations/{conversation_id}/messages")
    async def message(conversation_id: str, payload: MessageRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True)
        text = redact_text(payload.text, request.cookies.values())
        run = await db(store.create_run, actor, conversation_id, payload.message_id, text, model_mode=settings.model_mode)
        # create_run checks exact idempotency before rejecting new messages under human control.
        run = await db(memory.recover_handoff_run, actor, run['agent_run_id']) or run
        if run['state'] in {'CREATED', 'RUNNING'} and run['agent_run_id'] not in tasks:
            await admit_runs(actor)
            try:
                lease = await db(store.claim_run, actor, run['agent_run_id'], owner='shopping-api', ttl_seconds=90)
            except StateError as error:
                if error.code in {'conversation_busy', 'run_deadline_exceeded'}:
                    return await db(store.get_run, actor, run['agent_run_id'])
                raise
            run = await db(store.get_run, actor, run['agent_run_id'])
            focus = {}
            product_id = (payload.product_id or '').strip()
            sku_key = (payload.sku_key or '').strip()
            if product_id:
                focus['focus_product_id'] = product_id
            if sku_key:
                focus['focus_sku_key'] = sku_key
            if focus:
                context = dict(run.get('context') or {})
                context.update(focus)
                await db(store.save_context, lease, context)
                run = {**run, 'context': context}

            async def execute():
                try:
                    await run_shopping(actor=actor, run=run, lease=lease, store=store, commerce=commerce,
                                       knowledge=knowledge, memory=memory, provider=provider,
                                       mode=settings.model_mode, config=config, recommendations=recommendations, attribution=attribution)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    try:
                        await db(store.append_event, lease, 'error', {'error_type': type(error).__name__})
                        await db(store.finish_run, lease, state='FAILED', result={'error_type': type(error).__name__,
                                 'error': getattr(error, 'code', 'assistant_failed'), 'model_mode': settings.model_mode})
                    except StateError:
                        pass  # A handoff/clear already fenced and cancelled this run.
            task = asyncio.create_task(execute())
            tasks[run['agent_run_id']] = task
            task_owners[run['agent_run_id']] = (actor.subject_type, actor.actor_id)
            task.add_done_callback(lambda _: (tasks.pop(run['agent_run_id'], None),
                                              task_owners.pop(run['agent_run_id'], None)))
        return run

    @app.post('/api/assistant/conversations/{conversation_id}/mcp')
    async def mcp_endpoint(conversation_id: str, payload: dict, request: Request, response: Response):
        """MCP Streamable HTTP for the read-only tools, scoped to one conversation.

        The conversation is in the path rather than in the tool arguments so every MCP call
        lands in the same run/receipt trail as an agent call, with the same idempotency and
        permission checks. There is no second, weaker path into the tools.
        """
        actor = await actor_for(request, response)
        requested = (payload.get('params') or {}).get('protocolVersion') if isinstance(payload, dict) else None
        # initialize carries the version in params; later requests carry it in the header.
        negotiated = mcp.negotiate(requested or request.headers.get('mcp-protocol-version'))
        response.headers['MCP-Protocol-Version'] = negotiated

        async def call_tool(name, arguments):
            if memory and await db(memory.handoff_state, actor, conversation_id):
                raise StateError('human_control_active', 409)
            # Every call gets its own run id. Retrying a read costs a second read rather than
            # replaying a stale receipt, and only read tools are reachable here.
            run = await db(store.create_run, actor, conversation_id, 'mcp:' + uuid.uuid4().hex,
                           canonical({'mcp': name, 'arguments': arguments}), model_mode='rule-fallback')
            if run['state'] not in {'CREATED', 'RUNNING'}:
                raise StateError('run_not_resumable', 409)
            lease = await db(store.claim_run, actor, run['agent_run_id'], owner='mcp', ttl_seconds=30)
            try:
                receipt = await invoke(name, arguments, actor=actor, commerce=commerce, store=store, lease=lease,
                                       knowledge=knowledge, memory=memory,
                                       allowed=set(mcp.exposed_tools(actor)),
                                       product_scope=await db(attribution.product_scope, actor) if attribution is not None else None)
                await db(store.finish_run, lease, state='COMPLETED', result={'receipt': receipt})
                return receipt
            except Exception as error:
                await db(store.finish_run, lease, state='FAILED', result={'error_type': type(error).__name__})
                raise

        try:
            result = await mcp.handle(payload, actor=actor, call_tool=call_tool)
        except mcp.JsonRpcError as error:
            return JSONResponse(status_code=200, content=mcp.response(payload, error=error))
        if result is None:
            return Response(status_code=202)
        return mcp.response(payload, result=result)

    @app.post("/api/assistant/conversations/{conversation_id}/proposals")
    async def propose(conversation_id: str, payload: ProposalRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        if memory and await db(memory.handoff_state, actor, conversation_id):
            raise StateError('human_control_active', 409)
        run = await db(store.create_run, actor, conversation_id, payload.message_id,
                       canonical(payload.model_dump()), model_mode="rule-fallback")
        if run["state"] not in {"CREATED", "RUNNING"}:
            return run
        lease = await db(store.claim_run, actor, run["agent_run_id"], owner="api", ttl_seconds=30)
        try:
            name = "propose_" + payload.action_type
            await db(store.append_event, lease, "tool_started", {"name": name})
            receipt = await invoke(name, payload.parameters, actor=actor, commerce=commerce, store=store, lease=lease,
                                   product_scope=await db(attribution.product_scope, actor))
            proposal = receipt["data"]
            await db(store.append_event, lease, "proposal_required", {"proposal": proposal})
            return await db(store.finish_run, lease, state="WAIT_USER", result={"proposal": proposal})
        except Exception as error:
            await db(store.append_event, lease, "error", {"error_type": type(error).__name__})
            await db(store.finish_run, lease, state="FAILED", result={"error_type": type(error).__name__})
            raise

    @app.get("/api/assistant/proposals/{proposal_id}")
    async def proposal(proposal_id: str, request: Request, response: Response):
        return await db(store.get_proposal, await actor_for(request, response), proposal_id)

    @app.get('/api/assistant/proposals/{proposal_id}/display')
    async def proposal_display(proposal_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, user=True)
        current = await db(store.get_proposal, actor, proposal_id)
        params = current['parameters']
        if current['action_type'] == 'refund':
            item = await commerce.request('order', '/internal/order/commerce/getOrderItem', actor=actor,
                                          data={'orderItemId': params['orderItemId']})
            if not item:
                raise HTTPException(404, 'order_item_not_found')
            return {'order': {'orderId': item['orderId'], 'items': [item]}}
        if current['action_type'] == 'cancel':
            order = await commerce.request('order', '/internal/order/commerce/getOrder', actor=actor,
                                           data={'orderId': params['orderId']})
            if not order:
                raise HTTPException(404, 'order_not_found')
            return {'order': order}
        raise HTTPException(422, 'proposal_has_no_existing_order')

    @app.post("/api/assistant/proposals/{proposal_id}/confirm")
    async def confirm(proposal_id: str, payload: ConfirmRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        return await confirm_owned(actor, proposal_id, payload)

    async def confirm_owned(actor, proposal_id, payload):
        current = await db(store.get_proposal, actor, proposal_id)
        if memory and await db(memory.handoff_state, actor, current['conversation_id']):
            raise StateError('human_control_active', 409)
        proposal = await db(store.confirm_proposal, actor, proposal_id, payload.proposal_version, approved=payload.approved)
        if proposal["status"] in {"REJECTED", "SUCCEEDED", "FAILED"}:
            return {"proposal": proposal}
        # Each HTTP invocation gets its own deadline; the confirmed proposal/action key stays unchanged.
        run = await db(store.create_run, actor, proposal["conversation_id"], f"confirm:{proposal_id}:{uuid.uuid4().hex}",
                       "用户确认已保存的交易提案", parent_run_id=proposal["agent_run_id"], model_mode="rule-fallback")
        lease = await db(store.claim_run, actor, run["agent_run_id"], owner="api", ttl_seconds=30)
        try:
            proposal = await db(store.begin_action, lease, proposal_id)
        except StateError as error:
            await db(store.finish_run, lease, state="FAILED", result={"error": error.code})
            raise
        if proposal["status"] in {"SUCCEEDED", "FAILED"}:
            return await db(store.finish_run, lease, state="COMPLETED", result={"proposal": proposal})
        try:
            receipt = await execute_proposal(proposal, actor, commerce, attribution)
            outcome = receipt.get("commandStatus", "unknown")
            if outcome not in {"business_completed", "business_pending", "command_accepted", "rejected", "unknown"}:
                outcome = "unknown"
        except CommerceRejected as error:
            outcome, receipt = "rejected", {"error": error.reason}
        except (CommerceError, TimeoutError):
            outcome, receipt = "unknown", {"error": "commerce_outcome_unknown"}
        proposal = await db(store.record_action_result, lease, proposal_id, outcome=outcome, receipt=receipt)
        terminal = proposal["status"] in {"SUCCEEDED", "FAILED"}
        await db(store.append_event, lease, "completed" if terminal else "operation_pending", {"proposal": proposal})
        return await db(store.finish_run, lease, state="COMPLETED" if terminal else "WAIT_OUTCOME", result={"proposal": proposal})

    @app.get('/api/assistant/payments/{pay_id}')
    async def payment_status(pay_id: str, request: Request, response: Response):
        actor = await actor_for(request, response, user=True)
        result = await commerce.request('order', ORDER_ACTION_STATUS_PATH, actor=actor,
                                        data={'actionType': 'PAYMENT', 'params': {'payOrderId': pay_id}})
        return {**result, 'amount_cents': result.get('amountCents')}

    @app.post('/api/assistant/payments/{pay_id}/complete')
    async def complete_payment(pay_id: str, payload: PaymentRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        current = await commerce.request('order', ORDER_ACTION_STATUS_PATH, actor=actor,
                                         data={'actionType': 'PAYMENT', 'params': {'payOrderId': pay_id}})
        if current.get('amountCents') != payload.expected_amount_cents:
            raise HTTPException(409, 'RECONFIRM_REQUIRED')
        conversation = await db(store.create_conversation, actor, identity_key='payment:' + pay_id)
        conversation = await db(store.get_conversation, actor, conversation['conversation_id'])
        proposals = [p for p in conversation['proposals'] if p['action_type'] == 'payment'
                     and p['status'] not in {'EXPIRED', 'REJECTED', 'FAILED'}]
        if proposals:
            proposal = proposals[0]
        else:
            run = await db(store.create_run, actor, conversation['conversation_id'], 'payment:' + uuid.uuid4().hex,
                           '用户点击确认模拟付款', model_mode='rule-fallback')
            lease = await db(store.claim_run, actor, run['agent_run_id'], owner='payment-api')
            proposal = await db(store.create_proposal, lease, action_type='payment',
                               parameters={'payOrderId': pay_id, 'expected_amount_cents': payload.expected_amount_cents},
                               expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
            await db(store.finish_run, lease, state='WAIT_USER', result={'proposal': proposal})
        confirmed = await confirm_owned(actor, proposal['proposal_id'], ConfirmRequest(
            proposal_version=proposal.get('decision_version') or proposal['version']))
        final = confirmed.get('proposal') or confirmed['result']['proposal']
        receipt = final.get('receipt') or {}
        return {**receipt, 'commandStatus': receipt.get('commandStatus', 'unknown'),
                'amount_cents': receipt.get('amountCents'), 'proposal_id': final['proposal_id']}

    @app.get('/api/assistant/preferences')
    async def preferences(request: Request, response: Response):
        return await db(memory.preferences, await actor_for(request, response, user=True))

    @app.put('/api/assistant/preferences/{key}')
    async def preference_update(key: str, payload: ValueRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, user=True)
        values = payload.value if isinstance(payload.value, list) else [payload.value]
        if any(isinstance(value, str) and redact_text(value, request.cookies.values()) != value for value in values):
            raise HTTPException(422, 'preference_contains_credentials')
        return await db(memory.set_preference, actor, key, payload.value)

    @app.delete('/api/assistant/preferences/{key}')
    async def preference_delete(key: str, request: Request, response: Response):
        return await db(memory.delete_preference, await actor_for(request, response, write=True, user=True), key)

    @app.delete('/api/assistant/memory')
    async def clear_memory(request: Request, response: Response):
        return await db(memory.clear, await actor_for(request, response, write=True))

    @app.post('/api/assistant/conversations/{conversation_id}/handoff')
    async def handoff(conversation_id: str, request: Request, response: Response, payload: Arguments):
        actor = await actor_for(request, response, write=True)
        return await db(memory.handoff, actor, conversation_id, 'user_requested')

    @app.get('/api/assistant/knowledge/{doc_id}/{version}')
    async def reference(doc_id: str, version: int, request: Request, response: Response):
        return await db(knowledge.read_published_document, await actor_for(request, response), doc_id, version)

    @app.get('/admin-api/assistant/knowledge')
    async def documents(request: Request, response: Response):
        return await db(knowledge.list_documents, await actor_for(request, response, realm='merchant'))

    @app.get('/admin-api/assistant/knowledge/{doc_id}/{version}')
    async def knowledge_document(doc_id: str, version: int, request: Request, response: Response):
        return await db(knowledge.get_document, await actor_for(request, response, realm='merchant'), doc_id, version)

    @app.get('/admin-api/assistant/support')
    async def tickets(request: Request, response: Response):
        return await db(memory.list_tickets, await actor_for(request, response, realm='merchant'))

    @app.get('/admin-api/assistant/support/{ticket_id}')
    async def ticket_detail(ticket_id: str, request: Request, response: Response, before_sequence: int | None = None):
        actor = await actor_for(request, response, realm='merchant')
        return await db(memory.get_ticket, actor, ticket_id, before_sequence=before_sequence)

    @app.patch('/admin-api/assistant/support/{ticket_id}')
    async def ticket_update(ticket_id: str, payload: TicketRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, realm='merchant')
        return await db(memory.manage_ticket, actor, ticket_id, **payload.model_dump(exclude_none=True))

    @app.post('/admin-api/assistant/knowledge')
    async def draft(payload: KnowledgeRequest, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, realm='merchant')
        if redact_text(payload.body, request.cookies.values()) != payload.body:
            raise HTTPException(422, 'document_contains_credentials')
        return await db(knowledge.create_draft, actor, payload.model_dump(exclude_none=True))

    @app.post('/admin-api/assistant/knowledge/parse')
    async def parse_file(filename: str, request: Request, response: Response):
        actor = await actor_for(request, response, write=True, realm='merchant')
        actor.require('admin:legacy')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_INPUT_BYTES:
                raise HTTPException(413, 'document_input_too_large')
        result = await db(parse_document, filename, bytes(data))
        if redact_text(result['body'], request.cookies.values()) != result['body']:
            raise HTTPException(422, 'document_contains_credentials')
        return result

    @app.post('/admin-api/assistant/knowledge/{doc_id}/{version}/publish')
    async def publish(doc_id: str, version: int, request: Request, response: Response, payload: Arguments):
        actor = await actor_for(request, response, write=True, realm='merchant')
        document = await db(knowledge.get_document, actor, doc_id, version)
        if document['status'] == 'PUBLISHED':
            return await db(knowledge.publish, actor, doc_id, version)
        if document['status'] != 'DRAFT':
            raise HTTPException(409, 'document_not_draft')
        if indexing is not None and indexing.embedding_enabled():
            # Embedding runs as an async index job (smartlect/indexing.py): the request returns
            # a job immediately; progress is on /knowledgeIndex/jobs, publish happens when the
            # last batch lands. Without an embedding key the publish stays synchronous and
            # retrieval falls back to BM25-only, exactly as before.
            return await indexing.submit(actor, doc_id, version)
        return await db(knowledge.publish, actor, doc_id, version)

    @app.post('/admin-api/assistant/knowledge/{doc_id}/{version}/withdraw')
    async def withdraw(doc_id: str, version: int, request: Request, response: Response, payload: Arguments):
        return await db(knowledge.withdraw, await actor_for(request, response, write=True, realm='merchant'), doc_id, version)

    @app.get("/api/assistant/runs/{run_id}")
    async def run_status(run_id: str, request: Request, response: Response):
        return await db(store.get_run, await actor_for(request, response), run_id)

    async def event_records(run_id: str, request: Request, response: Response):
        actor = await actor_for(request, response)
        await db(store.get_run, actor, run_id)
        try:
            after = int(request.headers.get("last-event-id", "0"))
            if after < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "invalid_event_cursor") from None
        return actor, run_id, after, request

    @app.get("/api/assistant/runs/{run_id}/events", response_class=EventSourceResponse)
    async def events(parameters=Depends(event_records)) -> AsyncIterable[ServerSentEvent]:
        # Auth/ownership/cursor validation runs as a dependency before streaming headers.
        # Reconnection only replays persisted events, never starts or confirms a run.
        actor, run_id, after, request = parameters
        deadline = time.monotonic() + 95
        while time.monotonic() < deadline and not await request.is_disconnected():
            for event in await db(store.events, actor, run_id, after):
                after = event['sequence']
                yield ServerSentEvent(data=event, event=event['event_type'], id=str(after))
            run = await db(store.get_run, actor, run_id)
            if run['state'] not in {'CREATED', 'RUNNING'}:
                break
            await asyncio.sleep(0.5)

    indexing = None
    if store is not None:
        # Admin ops surface (runs browser, tool debug, index ops) lives in its own package;
        # app.py stays the composition root and only wires dependencies here.
        from smartlect import adminapi
        from smartlect.indexing import IndexingService
        from smartlect.shopping_retrieve import ShoppingRetrieve
        indexing = IndexingService(store.connect, knowledge, provider, settings=settings, config=config)
        adminapi.register(app, actor_for=actor_for, store=store, commerce=commerce, knowledge=knowledge,
                          attribution=attribution, provider=provider, config=config, settings=settings,
                          shopping_retrieve=ShoppingRetrieve(commerce), indexing=indexing)

    return app


def main():
    parser = argparse.ArgumentParser(description="Smartlect AI API")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.check:
        print(json.dumps(health(settings)))
        return
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, ws="none", access_log=False)


if __name__ == "__main__":
    main()
