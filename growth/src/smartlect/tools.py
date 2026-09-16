"""One role-restricted registry: read, propose, owned memory and handoff; never approve trades."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
import uuid
import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from smartlect.commerce import CommerceError, CommerceRejected, ORDER_ACTION_STATUS_PATH
from smartlect.ads.analytics import to_cents
from smartlect.business_skills import load_skill
from smartlect.knowledge import compose_search_query
from smartlect.provider import ProviderError
from smartlect.state import StateError
from smartlect.catalog_gate import RecommendationRequest, in_scope, scope_filter


class Arguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ProductArgs(Arguments):
    productId: str = Field(min_length=1, max_length=64)


class SearchArgs(RecommendationRequest):
    pass


class CompareArgs(Arguments):
    sku_keys: list[str] = Field(default_factory=list, max_length=4,
        description='2–4个sku_key对照；未填则用会话比较目标各检索一次')
    comparison_targets: list[str] = Field(default_factory=list, max_length=4,
        description='要对照的商品名或规格词，最多4个')
    query: str = Field(default='', max_length=200)
    product_id: str | None = Field(default=None, min_length=1, max_length=64)
    category_id: str | None = Field(default=None, min_length=1, max_length=64)
    max_price_cents: int | None = Field(default=None, ge=0, le=100000000)
    min_price_cents: int = Field(default=0, ge=0, le=100000000)
    quantity: int = Field(default=1, ge=1, le=999)
    required_terms: list[str] = Field(default_factory=list, max_length=16)
    excluded_terms: list[str] = Field(default_factory=list, max_length=20)
    excluded_product_ids: list[str] = Field(default_factory=list, max_length=64)
    excluded_sku_keys: list[str] = Field(default_factory=list, max_length=64)


class KnowledgeArgs(Arguments):
    query: str = Field(min_length=1, max_length=800)


class HandoffArgs(Arguments):
    answer: str = Field(min_length=1, max_length=4000,
        description='转交说明；附带政策答复须先检索并引用。不宣称人工已接管或交易已完成。')
    citation_chunk_ids: list[str] = Field(default_factory=list, max_length=4,
        description='仅本轮search_knowledge返回的chunk_id；纯转交无需检索，填空列表')


class SkillArgs(Arguments):
    skill_id: Literal["shopping_advice", "support_policy", "order_service"]


class MemoryArgs(Arguments):
    limit: int = Field(default=4, ge=1, le=8)


class PreferenceArgs(Arguments):
    key: Literal['purpose', 'budget_max_cents', 'likes', 'avoid', 'categories']
    text_value: str | None = Field(default=None, max_length=500)
    amount_cents: int | None = Field(default=None, ge=0, le=100000000)
    list_value: list[str] | None = Field(default=None, min_length=1, max_length=20)
    evidence_quote: str = Field(min_length=1, max_length=500)


class PaymentArgs(Arguments):
    payOrderId: str = Field(min_length=1, max_length=64)


class OrdersArgs(Arguments):
    limit: int = Field(default=10, ge=1, le=30)


class OrderArgs(Arguments):
    orderId: str = Field(min_length=1, max_length=64)


class RefundArgs(Arguments):
    orderItemId: str = Field(min_length=1, max_length=64)
    refundAmountCents: int = Field(ge=0, le=9223372036854775807)
    reason: str = Field(default="用户申请退款", max_length=500)


class OrderItem(Arguments):
    productId: str = Field(min_length=1, max_length=64)
    propertyValueIds: str = Field(min_length=1, max_length=256)
    buyCount: int = Field(ge=1, le=999)
    remark: str = Field(default="", max_length=500)


class CreateOrderArgs(Arguments):
    payMethod: Literal["mock"] = "mock"
    addressId: str = Field(min_length=1, max_length=64)
    orderFrom: int = Field(default=0, ge=0, le=1)
    orderList: list[OrderItem] = Field(min_length=1, max_length=20)
    userCouponId: str | None = Field(default=None, max_length=64)


class ToolReceipt(Arguments):
    schema_version: Literal['tool-receipt-v1'] = 'tool-receipt-v1'
    data: Any
    tool_succeeded: bool
    observed_at: str
    resource_version: str | int | None = None
    evidence_id: str
    command_status: Literal['command_accepted', 'business_pending', 'business_completed', 'rejected', 'unknown']


@dataclass(frozen=True)
class Tool:
    schema: type[Arguments]
    permission: str
    description: str
    kind: Literal["read", "proposal", "memory", "handoff"] = "read"
    output_schema: type[ToolReceipt] = ToolReceipt


REGISTRY = {
    "load_skill": Tool(SkillArgs, "shopping:read", "按当前任务加载已审核的业务Skill；只能缩小现有权限"),
    "request_handoff": Tool(HandoffArgs, "shopping:read", "用户请求人工或当前问题需人工核实时创建本地工单并结束本轮；必须单独调用。不是退款或交易授权。", "handoff"),
    "search_knowledge": Tool(KnowledgeArgs, "shopping:read", "检索已发布且有权限的政策/说明原文及引用"),
    "search_skus": Tool(SearchArgs, "shopping:read", "按关键字/预算从Java查询实际有货SKU；价格单位分"),
    "recommend_skus": Tool(SearchArgs, "shopping:read", "按用途/预算/硬约束推荐真实可售SKU，返回来源、策略和理由；价格单位分"),
    "compare_skus": Tool(CompareArgs, "shopping:read", "对照2–4个可售SKU或任务槽比较目标；缺目标只标不全，不用热销凑数"),
    "get_my_addresses": Tool(Arguments, "orders:read", "查询本人收货地址ID与默认标记，不返回电话或详细地址"),
    "get_payment_status": Tool(PaymentArgs, "orders:read", "核对本人付款意图及订单同步状态"),
    "get_conversation_memory": Tool(MemoryArgs, "shopping:read", "读取本人的当前会话摘要、近期原话与结构化偏好；不是交易事实"),
    "remember_preference": Tool(PreferenceArgs, "orders:write", "依据当前用户原话记录可审计的推断偏好，不覆盖显式设置", 'memory'),
    "get_product_offer": Tool(ProductArgs, "shopping:read", "查询Java商品级介绍；不是可售SKU列表，选规格/展示卡片请用recommend_skus"),
    "get_my_orders": Tool(OrdersArgs, "orders:read", "查询当前登录用户的订单"),
    "get_order_status": Tool(OrderArgs, "orders:read", "查询本人的订单及明细状态"),
    "get_refund_status": Tool(OrderArgs, "orders:read", "查询本人的退款业务状态，受理不等于完成"),
    "list_my_coupons": Tool(Arguments, "orders:read", "查询本人未使用优惠券，含券ID与门槛；成交价以报价为准"),
    "propose_order": Tool(CreateOrderArgs, "orders:write", "取得Java报价并生成等待用户确认的下单提案", "proposal"),
    "propose_cancel": Tool(OrderArgs, "orders:write", "生成等待用户确认的取消提案", "proposal"),
    "propose_refund": Tool(RefundArgs, "orders:write", "生成等待用户确认具体金额的退款提案", "proposal"),
}


def tool_schema(model):
    schema = model.model_json_schema()
    definitions = schema.get('$defs', {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            return expand(definitions[value['$ref'].split('/')[-1]])
        result = {key: expand(item) for key, item in value.items() if key not in {'$defs', 'title'} and not (key == 'default' and item is None)}
        if 'anyOf' in result:
            choices = [item for item in result['anyOf'] if item.get('type') != 'null']
            if len(choices) == 1:
                result.pop('anyOf')
                result.update(choices[0])
        return result

    # Optional fields can be omitted. Avoid nullable unions/$ref in provider tool arguments;
    # the provider's compatibility layer otherwise stringifies some integer arguments.
    return expand(schema)


def schemas(actor, allowed=None):
    return [{"type": "function", "function": {"name": name, "description": tool.description,
                                               "parameters": tool_schema(tool.schema)}}
            for name, tool in REGISTRY.items() if tool.permission in actor.permissions
            and (allowed is None or name in allowed)]


async def invoke(name, arguments, *, actor, commerce, store, lease, call_id=None, allowed=None,
                 knowledge=None, embed_query=None, memory=None, recommend=None, compare=None, product_scope=None,
                 observed_citations=None, user_utterance=None):
    tool = REGISTRY.get(name)
    if tool is None or (allowed is not None and name not in allowed):
        raise ValueError("tool_not_allowed")
    actor.require(tool.permission)
    params = tool.schema.model_validate(arguments).model_dump(exclude_none=True,
                    exclude_unset=name in {'search_skus', 'recommend_skus', 'compare_skus'})
    if name == 'request_handoff' and (len(set(params['citation_chunk_ids'])) != len(params['citation_chunk_ids'])
            or any(key not in (observed_citations or {}) for key in params['citation_chunk_ids'])):
        raise ValueError('unsupported_reference')
    targets = ([params['productId']] if name == 'get_product_offer' else
               [item['productId'] for item in params['orderList']] if name == 'propose_order' else [])
    if targets:
        permitted = scope_filter(product_scope)
        if any(not in_scope(identifier, permitted) for identifier in targets):
            raise StateError('product_scope_denied', 403)
    call_id = call_id or uuid.uuid4().hex
    prior = await asyncio.to_thread(store.start_tool_call, lease, call_id, name, params)
    if prior["outcome"] == "unknown":
        raise CommerceError("prior_tool_outcome_unknown")
    if prior["outcome"] == "rejected":
        raise CommerceRejected(409, "prior_tool_rejected")
    if prior["outcome"] != "started":
        return prior["receipt"]
    try:
        result = await asyncio.wait_for(_invoke(name, params, actor, commerce, store, lease, knowledge, embed_query, memory, recommend, compare, observed_citations, user_utterance),
                                        timeout=30 if name in {"search_knowledge", "search_skus", "recommend_skus", "compare_skus"} else 15)
        status = "command_accepted"
        if name == "get_refund_status":
            status = "business_completed" if result and all(item.get("status") == "COMPLETED" for item in result) else "business_pending"
        if name == "get_payment_status":
            status = result.get("commandStatus", "unknown")
        receipt = tool.output_schema.model_validate({"data": result, "tool_succeeded": True, "observed_at": datetime.now(timezone.utc).isoformat(),
                   "resource_version": None, "evidence_id": call_id,
                   "command_status": status}).model_dump()
        await asyncio.to_thread(store.finish_tool_call, lease, call_id, outcome=receipt["command_status"], receipt=receipt)
        return receipt
    except Exception as error:
        await asyncio.to_thread(store.finish_tool_call, lease, call_id,
                                outcome="unknown" if isinstance(error, (CommerceError, TimeoutError))
                                and not isinstance(error, CommerceRejected) else "rejected",
                                receipt={"error_type": type(error).__name__})
        raise


async def _invoke(name, params, actor, commerce, store, lease, knowledge=None, embed_query=None, memory=None, recommend=None, compare=None, observed_citations=None, user_utterance=None):
    if name == 'request_handoff':
        citations = [(observed_citations or {})[key] for key in params['citation_chunk_ids']]
        ticket = await asyncio.to_thread(memory.handoff, actor, lease['conversation_id'], 'model_requested_handoff',
                                         evidence=citations, cancel_running=False, lease=lease)
        return {'ticket': ticket, 'answer': params['answer'], 'citations': citations}
    if name == 'get_conversation_memory':
        data = await asyncio.to_thread(memory.context, actor, lease['conversation_id'])
        return {'preferences': data['preferences'], 'summary': data['summary'], 'mission': data.get('mission'),
                'memory_version': data['memory_version'],
                'messages': [{k: m[k] for k in ('message_id', 'role', 'content')} for m in data['messages'][-params['limit'] * 2:]]}
    if name == 'remember_preference':
        run = await asyncio.to_thread(store.get_run, actor, lease['agent_run_id'])
        data = await asyncio.to_thread(memory.context, actor, lease['conversation_id'])
        source = next((m for m in data['messages'] if m['message_id'] == run['message_id'] and m['role'] == 'user'), None)
        quote = params['evidence_quote'].strip()
        if not source or len(quote) < 2 or quote not in source['content']:
            raise ValueError('preference_requires_current_user_evidence:'
                             ' evidence_quote 必须逐字来自本轮用户原话')
        values = [params[key] for key in ('text_value', 'amount_cents', 'list_value') if key in params]
        if len(values) != 1:
            raise ValueError('exactly_one_preference_value_required:'
                             ' text_value/amount_cents/list_value 三选一且仅一个')
        value = values[0]
        if params['key'] == 'budget_max_cents':
            amounts = [int(Decimal(match.group(1)) * 100) for match in re.finditer(
                r'(?<![\d.,+\-])(\d+(?:\.\d{1,2})?)\s*(?:元|块|CNY|RMB)(?![A-Za-z])', source['content'], re.I)
                if match.group(0) in quote]
            if type(value) is not int or value not in amounts:
                raise ValueError('preference_budget_requires_explicit_currency:'
                                 ' 预算值必须等于引文中带元/块单位的金额×100（分）')
        elif not all(isinstance(item, str) and item in quote for item in (value if isinstance(value, list) else [value])):
            raise ValueError('preference_value_requires_verbatim_evidence:'
                             ' 偏好值必须逐字出现在 evidence_quote 引文内，不得改写或概括')
        try:
            return await asyncio.to_thread(memory.set_preference, actor, params['key'], value, source='inferred',
                evidence_ids=[source['message_id']], conversation_id=lease['conversation_id'], confidence=0.7, lease=lease)
        except StateError as error:
            if error.code == 'explicit_preference_has_priority':
                raise ValueError(error.code) from None
            raise
    if name == "load_skill":
        return load_skill(params["skill_id"])
    if name == "search_knowledge":
        if knowledge is None:
            raise ValueError("knowledge_unavailable")
        model_query = params["query"]
        submitted = compose_search_query(user_utterance or "", model_query)
        dense_error = None
        try:
            vectors = await embed_query(submitted) if embed_query else {}
        except ProviderError as error:
            vectors, dense_error = {}, error.code
        result = await asyncio.to_thread(knowledge.search, actor, submitted, utterance=user_utterance or "",
                                         model_query=model_query, **vectors)
        result.setdefault("retrieval", {})
        result["retrieval"]["submitted_query"] = submitted
        result["retrieval"]["model_query"] = model_query
        if dense_error:
            result['retrieval']['dense_error'] = dense_error
        return result
    if name in {'search_skus', 'recommend_skus'}:
        if recommend is None:
            raise ValueError('recommendation_service_unavailable')
        return await recommend(params)
    if name == 'compare_skus':
        if compare is None:
            raise ValueError('comparison_service_unavailable')
        return await compare(params)
    if name == "get_payment_status":
        return await commerce.request("order", ORDER_ACTION_STATUS_PATH, actor=actor,
                                      data={"actionType": "PAYMENT", "params": params})
    if name == "list_my_coupons":
        result = await commerce.request("coupon", "/internal/coupon/commerce/listUserCoupons", actor=actor, data={})
        items = result if isinstance(result, list) else []
        return [item for item in items if item.get("status") == 0]
    if name == "propose_order":
        quote = await commerce.request("order", "/internal/order/commerce/v2/quote", actor=actor, data=params)
        return await asyncio.to_thread(store.create_proposal, lease, action_type="order", parameters=quote["order"],
                                     expires_at=quote["expiresAt"], quote_id=quote["quoteId"],
                                     quote_total_cents=quote["totalAmountCents"])
    if name in {"propose_cancel", "propose_refund"}:
        path = "/getOrder" if name == "propose_cancel" else "/getOrderItem"
        fact = await commerce.request("order", "/internal/order/commerce" + path, actor=actor,
                                      data={key: value for key, value in params.items() if key in {"orderId", "orderItemId"}})
        if not fact:
            raise CommerceRejected(404, "resource_not_found")
        if name == "propose_refund":
            remaining = to_cents(str(fact["paidAmount"])) - to_cents(str(fact.get("refundedAmount") or "0"))
            if params["refundAmountCents"] != remaining:
                raise CommerceRejected(409, "RECONFIRM_REQUIRED")
        return await asyncio.to_thread(store.create_proposal, lease, action_type="cancel" if name == "propose_cancel" else "refund",
                                     parameters=params, expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    service, path = {
        "get_product_offer": ("product", "/internal/product/commerce/getDetail"),
        "get_my_addresses": ("user", "/internal/user/commerce/listAddresses"),
        "get_my_orders": ("order", "/internal/order/commerce/listOrders"),
        "get_order_status": ("order", "/internal/order/commerce/getOrder"),
        "get_refund_status": ("order", "/internal/order/commerce/refundStatus"),
    }[name]
    return await commerce.request(service, path, actor=actor, data=params)
