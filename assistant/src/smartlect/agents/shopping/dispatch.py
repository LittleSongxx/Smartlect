"""SubAgent-as-Tool 并行派发：主 Agent 通过 task_dispatch 工具按需生成子智能体。

架构（对齐参考项目 multi-agent/smartlect 与 LangGraph supervisor 模式）：
- 主 Agent（Shopping，有界 ReAct）默认单干，仅在「可并行 / 需上下文隔离 / 调用链深」
  三判据满足其一时派发——不为多 Agent 而多 Agent。
- 每个子智能体 = langgraph.prebuilt.create_react_agent（框架预构建 ReAct 循环），
  工具面收窄为只读检索系（StructuredTool 包装既有 REGISTRY），独立上下文、
  asyncio.gather 并发执行，只回传最终结论文本；中间工具事件不进入主上下文。
- 派发是只读操作（is_concurrency_safe）：不产生交易副作用，提案仍归主 Agent。
"""
import asyncio
import logging
import time

from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from smartlect.agents.shopping.model_adapter import ProviderChatModel
from smartlect.tools import REGISTRY

log = logging.getLogger(__name__)

SUB_AGENT_TOOLS = ("search_knowledge", "search_skus", "recommend_skus",
                   "compare_skus", "get_product_offer", "get_my_orders", "get_order_status")
SUB_AGENT_MAX_ITERS = 6
MAX_PARALLEL_DISPATCH = 3
SUB_AGENT_PROMPT = (
    "你是导购主智能体派发的只读检索子智能体。只使用被授予的工具完成任务，"
    "以简明中文结论作答：给出可售 SKU 的 productId/规格/价格结论与依据（引用 chunk_id 或 Java 查询），"
    "查不到就如实说查不到。不要提议下单，不要请求人工，不要执行任何写操作。"
)


class DispatchBudgetExceeded(Exception):
    pass


def structured_tools(invoke):
    """把 REGISTRY 子集包装为 LangChain StructuredTool（args_schema 复用 Pydantic strict 模型）。"""
    result = []
    for name in SUB_AGENT_TOOLS:
        tool = REGISTRY[name]
        async def runner(*_args, _name=name, **arguments):
            return await invoke(_name, arguments)
        runner.__name__ = name
        result.append(StructuredTool.from_function(
            coroutine=runner, name=name, description=tool.description,
            args_schema=tool.schema))
    return result


async def run_sub_agent(model: ProviderChatModel, task: str, invoke) -> str:
    """单个子智能体执行：create_react_agent 一次性 invoke（MemorySaver 进程内检查点）。"""
    agent = create_react_agent(model, structured_tools(invoke),
                               prompt=SUB_AGENT_PROMPT)
    result = await agent.ainvoke(
        {"messages": [("user", task)]},
        config={"recursion_limit": SUB_AGENT_MAX_ITERS * 2})
    messages = result["messages"]
    final = messages[-1]
    content = getattr(final, "content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content or "").strip() or "子智能体未得出结论"


async def dispatch(tasks: list[str], *, model: ProviderChatModel, invoke) -> list[dict]:
    """并行派发入口：asyncio.gather 并发子智能体；单失败不拖垮整批（结果内标注）。"""
    if not 1 <= len(tasks) <= MAX_PARALLEL_DISPATCH:
        raise DispatchBudgetExceeded("dispatch_tasks_1_to_3")
    started = time.monotonic()

    async def one(task: str) -> dict:
        try:
            answer = await asyncio.wait_for(
                run_sub_agent(model, task, invoke), timeout=25)
            return {"task": task, "status": "succeeded", "answer": answer}
        except asyncio.TimeoutError:
            return {"task": task, "status": "timeout", "answer": "子智能体在时限内未完成"}
        except Exception as error:  # 单子智能体失败降级为该任务的结果标注
            log.warning("sub-agent dispatch failed: %s", error, exc_info=True)
            return {"task": task, "status": "failed",
                    "answer": f"子智能体执行失败：{type(error).__name__}"}

    results = await asyncio.gather(*(one(task) for task in tasks))
    return {"results": list(results), "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "parallel": len(tasks) > 1}
