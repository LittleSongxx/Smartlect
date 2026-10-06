"""Process-lifetime LangGraph compile (no checkpointer).

Nodes stay run-scoped via ContextVar. The graph object is compiled once.
无 checkpointer（2026-10-05 移除，ADR-0009 后记）：每个 run 独立执行、跨 run
不复用图状态（会话事实源是 MySQL：消息/任务槽/台账，每轮重建输入）；
不用 interrupt()（HITL 是跨请求持久化提案，ADR-0009 决定一）；崩溃恢复
走 run 租约与幂等台账，不从图状态续跑——checkpointer 写入因此无消费者。
"""
from __future__ import annotations

import contextvars
from typing import Any

shopping_session: contextvars.ContextVar[Any] = contextvars.ContextVar("shopping_session")

_shopping_graph = None


def shopping_graph():
    global _shopping_graph
    if _shopping_graph is None:
        from smartlect.agents.shopping import build_shopping_graph
        _shopping_graph = build_shopping_graph().compile()
    return _shopping_graph


def invoke_config():
    return {
        "recursion_limit": 25,
    }
