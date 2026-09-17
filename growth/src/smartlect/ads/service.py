"""Bounded Java observations around the durable advertising executor."""
import asyncio
from datetime import datetime, timezone
import time
from typing import Annotated, Literal

from pydantic import Field, model_validator

from smartlect.algo_version import content_hash
from smartlect.commerce import PRODUCT_SNAPSHOT_BATCH_PATH, STOCK_BATCH_PATH, CommerceError
from smartlect.state import StateError, _integer
from smartlect.tools import Arguments
from smartlect.catalog_gate import RecommendationRequest, constraints, eligible_skus, scope_filter
from smartlect.recommendation.service import rank_skus
from smartlect.recommendation.store import DEFAULT_STRATEGIES


Identifier = Annotated[str, Field(min_length=1, max_length=128)]
ProductId = Annotated[str, Field(min_length=1, max_length=64)]
Cents = Annotated[int, Field(ge=0, le=1_000_000_000_000)]
Version = Annotated[int, Field(ge=1, le=9223372036854775807)]
ActionType = Literal['activate_campaign', 'activate_creative', 'resume_campaign', 'resume_creative',
                     'pause_campaign', 'pause_creative', 'set_budget', 'replace_creative', 'set_recommendation_policy']


class CampaignRequest(Arguments):
    campaign_id: ProductId
    name: str = Field(min_length=1, max_length=200)
    product_id: ProductId
    sku_key: Identifier
    budget_cents: Cents
    cpc_cents: int = Field(ge=1, le=1_000_000_000_000)


class CreativeRequest(Arguments):
    creative_id: ProductId
    campaign_id: ProductId
    copy_text: str = Field(min_length=1, max_length=1000)


class GrantEnvelope(Arguments):
    objective: str = Field(min_length=1, max_length=1000)
    product_scope: list[ProductId] = Field(min_length=1, max_length=100)
    allowed_action_types: list[ActionType | Literal['set_recommendation_policy']] = Field(min_length=1, max_length=9)
    budget_cap_cents: Cents
    max_budget_change_cents: Cents
    valid_until: str = Field(min_length=1, max_length=64)
    recommendation_policy_range: dict = Field(default_factory=dict)


class GrantRequest(Arguments):
    grant_id: ProductId
    initial_plan_id: Identifier
    initial_plan_version: Version
    expected_campaign_versions: dict[ProductId, Version] = Field(max_length=100)
    expected_creative_versions: dict[ProductId, Version] = Field(max_length=100)
    envelope: GrantEnvelope
    merchant_plan_id: Identifier | None = None
    replaces_grant_id: ProductId | None = None


class PolicyRequest(Arguments):
    strategy_version: Identifier
    config: dict
    group: Literal['control', 'treatment', 'all']


class AdAction(Arguments):
    action_type: ActionType
    campaign_id: ProductId | None = None
    creative_id: ProductId | None = None
    expected_version: Version
    budget_cents: Cents | None = None
    copy_text: str | None = Field(default=None, min_length=1, max_length=1000)

    policy: PolicyRequest | None = None

    @model_validator(mode='after')
    def action_fields(self):
        if self.action_type == 'set_recommendation_policy':
            if self.policy is None or any(v is not None for v in (self.campaign_id,self.creative_id,self.budget_cents,self.copy_text)):
                raise ValueError('policy_action_fields_required')
            return self
        if self.policy is not None or self.campaign_id is None:
            raise ValueError('campaign_action_fields_required')
        if (self.creative_id is not None) != self.action_type.endswith('_creative'):
            raise ValueError('creative_id_required_only_for_creative_actions')
        if (self.budget_cents is not None) != (self.action_type == 'set_budget'):
            raise ValueError('budget_required_only_for_set_budget')
        if (self.copy_text is not None) != (self.action_type == 'replace_creative'):
            raise ValueError('copy_required_only_for_replace_creative')
        return self


class ActionRequest(Arguments):
    action_id: ProductId
    idempotency_key: Identifier
    grant_id: ProductId
    plan_id: Identifier
    plan_version: Version
    reason_code: str = Field(min_length=1, max_length=128)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    agent_run_id: Identifier | None = None
    round_id: Identifier | None = None
    actions: list[AdAction] = Field(min_length=1, max_length=8)


class RevokeRequest(Arguments):
    action_id: ProductId
    idempotency_key: Identifier
    expected_version: Version
    reason_code: str = Field(min_length=1, max_length=128)


class AdExposureRequest(Arguments):
    exposure_id: ProductId
    creative_id: ProductId
    expected_campaign_version: Version | None = None
    expected_creative_version: Version | None = None


class AdClickRequest(Arguments):
    click_id: ProductId
    exposure_id: ProductId


AD_RANKING_VERSION = content_hash({
    'ranker': 'relevance_fatigue_pacing',
    'fatigue': 'impressions_24h',
})


def rank_ads(pairs):
    """Order eligible ads by relevance, this viewer's 24h fatigue, and budget pacing.

    A slot for one merchant's own campaigns has no auction to win, so bid ordering would be
    meaningless here. Fatigue is N impressions in the last 24 hours: more recent exposure
    pushes a creative down. A prior click is not immunity. Relevance only scales the score
    and never zeroes a candidate, so an eligible ad stays eligible.
    """
    scored = []
    for card, candidate in pairs:
        relevance = .4 + .6 * min(max(card.get('rule_score') or 0, 0), 1)
        seen = max(int(candidate.get('viewer_impressions') or 0), 0)
        fatigue = 1 / (1 + seen)
        budget = max(int(candidate.get('budget_cents') or 0), 0)
        spent = min(max(int(candidate.get('spent_cents') or 0), 0), budget)
        pacing = (budget - spent) / budget if budget else 0.0
        scored.append((card, candidate, round(relevance * fatigue * (.5 + .5 * pacing), 6)))
    return sorted(scored, key=lambda row: (-row[2], row[1]['campaign_id'], row[1]['creative_id']))


class AdsService:
    def __init__(self, commerce, store):
        self.commerce, self.store = commerce, store

    async def recommend(self, actor, *, limit=2, preferences=()):
        """Preview eligible ads; visibility and clicks remain separate persisted commands."""
        _integer(limit, 'limit', 1, 4)
        candidates = await asyncio.to_thread(self.store.delivery_candidates, actor)
        if not candidates:
            return {'items': [], 'ranking_mode': 'rule', 'observed_at': datetime.now(timezone.utc).isoformat()}
        products = sorted({row['product_id'] for row in candidates})
        request = constraints(RecommendationRequest().model_dump(exclude_unset=True), preferences)
        snapshot = await self.commerce.request('product', PRODUCT_SNAPSHOT_BATCH_PATH, data={'productIds': products})
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('skus'), list):
            raise CommerceError('commerce_outcome_unknown')
        stocks = await self.commerce.request('stock', STOCK_BATCH_PATH, data=[
            {'productId': product, 'propertyValueIdHash': sku}
            for product, sku in sorted({(row['product_id'], row['sku_key']) for row in candidates})])
        if not isinstance(stocks, list):
            raise CommerceError('commerce_outcome_unknown')
        scope = scope_filter(await asyncio.to_thread(self.store.product_scope, actor))
        allowed = {row['product_id'] + ':' + row['sku_key'] for row in candidates}
        cards, _ = eligible_skus(snapshot, stocks, request, product_scope=scope, allowed_sku_keys=allowed)
        ranked = rank_skus(cards, request, {}, DEFAULT_STRATEGIES['content-v1']['weights'], preferences)
        # Re-read eligibility after Java I/O so revoked grants and edits cannot be advertised as current.
        current = {row['creative_id']: row for row in await asyncio.to_thread(self.store.delivery_candidates, actor)}
        pairs = []
        for card in ranked:
            for candidate in candidates:
                if (candidate['product_id'] + ':' + candidate['sku_key'] != card['sku_key']
                        or current.get(candidate['creative_id']) != candidate):
                    continue
                pairs.append((card, candidate))
        items = [{**{key: card[key] for key in ('productId', 'propertyValueIds', 'productName',
            'cover', 'price_cents', 'stock', 'specification', 'reasons')}, **candidate,
            'ad_label': '推广', 'ad_mode': 'simulated_cpc', 'ad_rank_score': score}
            for card, candidate, score in rank_ads(pairs)[:limit]]
        return {'items': items, 'ranking_mode': AD_RANKING_VERSION,
                'observed_at': datetime.now(timezone.utc).isoformat()}

    async def create_campaign(self, actor, request):
        snapshot = await self.commerce.request('product', PRODUCT_SNAPSHOT_BATCH_PATH,
                                               data={'productIds': [request['product_id']]})
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('skus'), list):
            raise CommerceError('commerce_outcome_unknown')
        matches = [row for row in snapshot['skus'] if isinstance(row, dict)
                   and row.get('productId') == request['product_id'] and row.get('propertyValueIdHash') == request['sku_key']]
        if len(matches) != 1:
            raise StateError('advertised_sku_not_found', 422)
        return await asyncio.to_thread(self.store.create_campaign, actor, request)

    async def observe(self, actor, target):
        """No DB transaction is held during Java HTTP; finishing commits stockout protection."""
        started = time.monotonic()
        ticket = await asyncio.to_thread(self.store.begin_observation, actor, target['product_id'], target['sku_key'])
        stock = None
        try:
            rows = await asyncio.wait_for(self.commerce.request('stock', STOCK_BATCH_PATH, data=[{
                'productId': target['product_id'], 'propertyValueIdHash': target['sku_key']}]), timeout=.9)
            if isinstance(rows, list):
                matches = [row for row in rows if isinstance(row, dict) and row.get('productId') == target['product_id']
                           and row.get('propertyValueIdHash') == target['sku_key']]
                if (len(matches) == 1 and type(matches[0].get('stock')) is int
                        and 0 <= matches[0]['stock'] <= 2147483647):
                    stock = matches[0]['stock']
        except (CommerceError, TimeoutError):
            pass  # Missing/failed authority is unknown, never positive inventory.
        elapsed_ms = (time.monotonic() - started) * 1000
        if elapsed_ms > 1000 and stock != 0:
            stock = None  # An old zero still protects; an old positive cannot authorize delivery.
        return await asyncio.to_thread(self.store.finish_observation, actor, ticket, stock,
                                       datetime.now(timezone.utc).isoformat(), elapsed_ms)

    async def execute_action(self, actor, request):
        previous = await asyncio.to_thread(self.store.action_replay, actor, request)
        if previous is not None:
            return previous
        targets = await asyncio.to_thread(self.store.action_targets, actor, request)
        observations = await asyncio.gather(*(self.observe(actor, target) for target in targets))
        return await asyncio.to_thread(self.store.execute_action, actor, request, list(observations))

    async def expose(self, actor, request):
        target = await asyncio.to_thread(self.store.exposure_target, actor, request)
        observation = await self.observe(actor, target)
        try:
            return await asyncio.to_thread(self.store.expose, actor, request, observation)
        except StateError:
            await asyncio.to_thread(self.store.record_inventory_rejection,actor,'exposure',request,observation)
            raise

    async def click(self, actor, request):
        previous = await asyncio.to_thread(self.store.click_replay, actor, request)
        if previous is not None:
            return previous
        target = await asyncio.to_thread(self.store.click_target, actor, request)
        observation = await self.observe(actor, target)
        try:
            return await asyncio.to_thread(self.store.click, actor, request, observation)
        except StateError:
            await asyncio.to_thread(self.store.record_inventory_rejection,actor,'click',request,observation)
            raise
