"""Process-lifetime LangGraph compile + checkpointer.

Nodes stay run-scoped via ContextVar. The graph object is compiled once.
thread_id = conversation_id; checkpoint_ns = agent_run_id so turns do not collide.
MySQL lease remains mutual exclusion; checkpoint is the graph state of record.
"""
from __future__ import annotations

import contextvars
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from smartlect.postgres import dsn_from_env

shopping_session: contextvars.ContextVar[Any] = contextvars.ContextVar("shopping_session")
merchant_session: contextvars.ContextVar[Any] = contextvars.ContextVar("merchant_session")

_checkpointer = None
_shopping_graph = None
_merchant_graph = None
_postgres_setup_done = False


def checkpointer():
    """MemorySaver when Postgres is unset; PostgresSaver when DSN is present."""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    dsn = dsn_from_env()
    if not dsn:
        _checkpointer = MemorySaver()
        return _checkpointer
    from langgraph.checkpoint.postgres import PostgresSaver
    try:
        from psycopg_pool import ConnectionPool
        pool = ConnectionPool(conninfo=dsn, kwargs={"autocommit": True}, min_size=1, max_size=4)
        _checkpointer = PostgresSaver(pool)
    except Exception:
        saver = PostgresSaver.from_conn_string(dsn)
        _checkpointer = saver.__enter__() if hasattr(saver, "__enter__") else saver
    return _checkpointer


def ensure_postgres_tables():
    global _postgres_setup_done
    if _postgres_setup_done or not dsn_from_env():
        return
    saver = checkpointer()
    setup = getattr(saver, "setup", None)
    if callable(setup):
        setup()
    _postgres_setup_done = True


def reset_for_tests(saver=None):
    global _checkpointer, _shopping_graph, _merchant_graph, _postgres_setup_done
    _checkpointer = saver
    _shopping_graph = None
    _merchant_graph = None
    _postgres_setup_done = False


def shopping_graph():
    global _shopping_graph
    if _shopping_graph is None:
        from smartlect.agents.shopping import build_shopping_graph
        _shopping_graph = build_shopping_graph().compile(checkpointer=checkpointer())
    return _shopping_graph


def merchant_graph():
    global _merchant_graph
    if _merchant_graph is None:
        from smartlect.agents.merchant import build_merchant_graph
        _merchant_graph = build_merchant_graph().compile(checkpointer=checkpointer())
    return _merchant_graph


def invoke_config(conversation_id, run_id):
    return {
        "configurable": {
            "thread_id": conversation_id,
            "checkpoint_ns": run_id,
        },
        "recursion_limit": 25,
    }
