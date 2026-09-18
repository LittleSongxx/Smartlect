"""The structured final-answer contract and its control-flow exceptions."""
import json
import re

from pydantic import Field
from typing import Literal

from smartlect.tools import Arguments, tool_schema

class FinalAnswer(Arguments):
    answer: str = Field(min_length=1, max_length=4000)
    # The model states the request type. The controller compiles answer_status and tickets.
    request_kind: Literal['inquire_fact', 'request_service', 'request_exception', 'request_handoff', 'clarify'] = Field(
        description='用户这次诉求的类型，不是你有没有写出答复。'
                    'inquire_fact=询问已发布事实（含已写明的否定承诺）。问规则、范围或「是什么」用此项。'
                    'request_service=现在要求办理本轮资料未发布的服务（如请现在帮我预约）。'
                    'request_exception=要求破例、免审或人工裁决。'
                    'request_handoff=明确要求转交人工。'
                    'clarify=需要用户补充信息才能继续。'
                    '同时问了已发布事实又要求转交时，request_kind仍用inquire_fact，转交意图填handoff_requested。')
    handoff_requested: bool = Field(
        description='用户本轮是否明确要求转交人工。问接管规则、工单流程或「可以提交工单」的手续不是转交。'
                    '用户已经要求转交时，即使同时还问了政策或条件，这里也是true；不要再请用户确认一次才建单。')
    grounding: Literal['store_policy', 'user_facts', 'no_business_claim'] = Field(
        description='本次答复依据：store_policy=引用本轮检索到的店铺规则，凡是陈述本店怎么做、要求什么、'
                    '能不能做（含以隐私或权限为由说明做不到）都属于此项，必须先search_knowledge并附chunk_id；'
                    'user_facts=依据本轮工具查到的本人订单/地址/商品事实（含规格、价格、库存）；'
                    'no_business_claim=仅限寒暄、请用户补充信息、说明你自己能做什么，正文不含任何关于本店的结论。')
    citation_chunk_ids: list[str] = Field(default_factory=list, max_length=4,
        description="仅search_knowledge本轮返回的chunk_id；其它工具的call_id/evidence_id不能填，未检索时必须空列表")
    selected_sku_keys: list[str] = Field(default_factory=list, max_length=8,
        description="本轮 recommend_skus 或 compare_skus 返回的 sku_key；商品级信息不能当可售SKU，下单/规格选购前先查")
    requires_clarification: bool = False


class BudgetExceeded(RuntimeError):
    pass


class GuardViolation(ValueError):
    # A deterministic guard rejection with its own single repair round. Budgeted
    # apart from answer_repairs so a guard trigger cannot spend the one schema
    # repair allowance a later contract violation still needs.
    pass


def final_answer_schema():
    """Legacy tool schema kept for test fakes. Live tools no longer advertise finish_answer."""
    schema = tool_schema(FinalAnswer)
    schema['required'] = list(schema['properties'])
    return {'type':'function','function':{'name':'finish_answer',
        'description':'已停用。终答改为结构化 JSON。',
        'parameters':schema}}


def final_answer_response_format():
    schema = tool_schema(FinalAnswer)
    schema['required'] = list(schema['properties'])
    schema['additionalProperties'] = False
    return {'type': 'json_schema', 'json_schema': {
        'name': 'shopping_final_answer', 'strict': True, 'schema': schema}}


def extract_streamed_answer(buffer):
    """Pull the JSON `answer` field from a partial structured-output stream."""
    if not buffer:
        return None
    stripped = buffer.lstrip()
    if not stripped.startswith('{'):
        return stripped
    match = re.search(r'"answer"\s*:\s*"', buffer)
    if not match:
        return None
    start = match.end()
    out, index = [], start
    while index < len(buffer):
        char = buffer[index]
        if char == '\\' and index + 1 < len(buffer):
            out.append(buffer[index:index + 2])
            index += 2
            continue
        if char == '"':
            try:
                return json.loads('"' + ''.join(out) + '"')
            except json.JSONDecodeError:
                return ''.join(out).replace('\\n', '\n').replace('\\"', '"')
        out.append(char)
        index += 1
    try:
        return json.loads('"' + ''.join(out) + '"')
    except json.JSONDecodeError:
        return ''.join(out).replace('\\n', '\n').replace('\\"', '"')
