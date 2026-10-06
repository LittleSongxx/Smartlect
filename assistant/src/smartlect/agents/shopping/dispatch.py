"""SubAgent-as-Tool 并行派发：主 Agent 通过 task_dispatch 工具按需生成子智能体。

架构（ADR-0010 确立，本模块细化分型）：
- 主 Agent（Shopping，有界 ReAct）默认单干，仅在「可并行 / 需上下文隔离 / 调用链深」
  三判据满足其一时派发——不为多 Agent 而多 Agent。
- 派发前先做确定性路由（profiles.route_sub_agent）：每个任务按关键词信号归入
  retrieval-scout / order-reader / comparator 之一（订单信号优先于比较信号——
  comparator 没有订单工具），各自使用声明式 AgentProfile 收窄后的只读工具面
  与角色契约提示词；路由结果与理由随元数据回传（可解释路由）。
- 每个子智能体 = langgraph.prebuilt.create_react_agent（框架预构建 ReAct 循环），
  asyncio.gather 并发执行，只回传最终结论文本；中间工具事件不进入主上下文。
- 子工具调用走与主循环同一条 invoke() 路径（幂等台账 + RBAC + 范围闸 + span），
  子智能体没有第二条更弱的进工具的路。
- 派发是只读操作（is_concurrency_safe）：不产生交易副作用，提案仍归主 Agent。
"""
import asyncio
import logging
import time

from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from smartlect.agents.shopping.contract import BudgetExceeded
from smartlect.agents.shopping.model_adapter import ProviderChatModel
from smartlect.agents.shopping.profiles import render_profile, route_sub_agent
from smartlect.state import StateError
from smartlect.tools import REGISTRY

SUB_MODEL_ATTEMPT_LIMIT = 4
"""单子任务模型调用上限：子智能体只许在少量轮次内得出结论。全局 MODEL_CALL_LIMIT
是所有子任务共享的池，comparator 曾在 3 工具面里反复调用不收敛，13 次子调用
烧穿整池预算迫使主循环 rule-fallback 收口——25s 超时只止损不退预算，必须在
次数上独立设闸：超限按单任务失败降级，剩余预算留给主循环兜底。"""


def visible_sub_scope(profile_scope, allowed_outer):
    """子模型可见工具面 = 路由 profile 工具面 ∩ 主会话 skill 门控面。

    只在调用时拦截（sub_invoke 闸）会让子模型"看得见却调不动"，模型必然
    撞 tool_not_loaded 403；交集必须作为可见面下发。交集为空说明该 profile
    在当前会话没有任何可用工具，任务应显式失败而非让模型空转。
    """
    if allowed_outer is None:
        return tuple(profile_scope)
    scope = tuple(name for name in profile_scope if name in allowed_outer)
    if not scope:
        raise StateError("sub_agent_no_available_tools", 403)
    return scope

log = logging.getLogger(__name__)

SUB_AGENT_MAX_ITERS = 6
MAX_PARALLEL_DISPATCH = 3


class DispatchBudgetExceeded(Exception):
    pass


def structured_tools(invoke, allowed):
    """把 REGISTRY 中 allowed 名单内的工具包装为 LangChain StructuredTool。

    args_schema 复用既有 Pydantic strict 模型；allowed 即路由到的 profile 工具面。
    """
    result = []
    for name in allowed:
        tool = REGISTRY[name]

        async def runner(*_args, _name=name, **arguments):
            return await invoke(_name, arguments, allowed)
        runner.__name__ = name
        result.append(StructuredTool.from_function(
            coroutine=runner, name=name, description=tool.description,
            args_schema=tool.schema))
    return result


async def run_sub_agent(model: ProviderChatModel, task: str, invoke) -> dict:
    """单个子智能体执行：路由 → profile 契约提示词 + 收窄工具面 → 一次性 ainvoke。

    子模型继承主模型的 before_attempt/on_trace 预算与审计钩子：子智能体的
    模型调用计入主会话同一 MODEL_CALL_LIMIT 并落 model_attempts——预算
    单一事实源对 dispatch 路径同样成立，不存在绕过闸的第二条模型路径。
    """
    profile, reason = route_sub_agent(task)
    scope = visible_sub_scope(profile.tool_scope, getattr(invoke, 'allowed_outer', None))
    main_before = model.before_attempt
    spent = {'count': 0}

    async def before_with_sub_limit():
        spent['count'] += 1
        if spent['count'] > SUB_MODEL_ATTEMPT_LIMIT:
            raise BudgetExceeded('sub_agent_model_limit')
        if main_before is not None:
            return await main_before()

    sub_model = ProviderChatModel(provider=model.provider,
                                  prompt_version=f'sub-{profile.name}-v1',
                                  max_tokens=profile.max_tokens,
                                  before_attempt=before_with_sub_limit,
                                  on_trace=model.on_trace,
                                  max_attempts=model.max_attempts)
    agent = create_react_agent(sub_model, structured_tools(invoke, scope),
                               prompt=render_profile(profile))
    result = await agent.ainvoke(
        {"messages": [("user", task)]},
        config={"recursion_limit": SUB_AGENT_MAX_ITERS * 2})
    messages = result["messages"]
    final = messages[-1]
    content = getattr(final, "content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    answer = str(content or "").strip() or "子智能体未得出结论"
    return {"answer": answer, "profile": profile.name, "routing_reason": reason}


def compose_results(results: list[dict], elapsed_ms: float) -> dict:
    """派发结果的确定性组装（不烧模型调用）：分行结论 + 完整性汇总 + 合并指导。

    部分失败（timeout/failed）显式标注并要求主答复披露——Supervisor 合并多个
    子智能体结论时的诚实边界：不完整的批次不能被包装成完整证据。
    """
    succeeded = [row for row in results if row["status"] == "succeeded"]
    incomplete = [row for row in results if row["status"] != "succeeded"]
    lines = []
    for index, row in enumerate(results, start=1):
        marker = '✓' if row["status"] == 'succeeded' else f'✗({row["status"]})'
        lines.append(f'{index}. [{marker} 路由={row.get("profile", "-")}] {row["task"]}：{row["answer"]}')
    payload = {
        "results": results,
        "summary": '\n'.join(lines),
        "all_succeeded": not incomplete,
        "succeeded_count": f"{len(succeeded)}/{len(results)}",
        "elapsed_ms": elapsed_ms,
        "parallel": len(results) > 1,
        "merge_instruction": (
            '以上为各子任务的独立结论，请逐条核对后合并进最终答复：结论间冲突时如实呈现差异，'
            + ('不得遗漏任何一条。' if not incomplete else
               '带 ✗ 标记的任务未完成，最终答复必须向用户披露这部分信息缺失。')),
    }
    if incomplete:
        payload["incomplete_tasks"] = [row["task"] for row in incomplete]
    return payload


async def dispatch(tasks: list[str], *, model: ProviderChatModel, invoke) -> dict:
    """并行派发入口：路由分型 → asyncio.gather 并发 → 确定性组装。

    单个子智能体失败不拖垮整批（结果内标注），组装层保证部分失败可见。
    """
    if not 1 <= len(tasks) <= MAX_PARALLEL_DISPATCH:
        raise DispatchBudgetExceeded("dispatch_tasks_1_to_3")
    started = time.monotonic()

    async def one(task: str) -> dict:
        try:
            outcome = await asyncio.wait_for(
                run_sub_agent(model, task, invoke), timeout=25)
            return {"task": task, "status": "succeeded", **outcome}
        except asyncio.TimeoutError:
            return {"task": task, "status": "timeout", "answer": "子智能体在时限内未完成"}
        except Exception as error:  # 单子智能体失败降级为该任务的结果标注
            log.warning("sub-agent dispatch failed: %s", error, exc_info=True)
            detail = type(error).__name__
            if getattr(error, "code", None):
                detail = f"{detail}:{error.code}"  # StateError 带 code（如 tool_not_loaded）一并披露
            return {"task": task, "status": "failed",
                    "answer": f"子智能体执行失败：{detail}"}

    results = await asyncio.gather(*(one(task) for task in tasks))
    return compose_results(list(results), round((time.monotonic() - started) * 1000, 2))
