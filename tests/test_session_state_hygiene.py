# -*- coding: utf-8 -*-
"""会话级状态治理单测（B4）：锁修剪、Agent 实例 LRU 上限。

背景：orchestrator._session_locks / SessionRegistry._agents 只增不减，
legacy 意图路径下每个会话的 Agent 连同完整 AgentState 常驻内存。
"""
import asyncio
from types import SimpleNamespace

from app.application.agents.main_agent import SessionRegistry
from app.infrastructure.context import ShoppingContext, ShoppingContextSnapshot


class _Factory:
    skill_catalog_mode = "legacy"
    capability_registry = None

    def __init__(self):
        self.built = 0

    def build(self, restored):
        self.built += 1
        state = SimpleNamespace()
        state.model_dump_json = lambda: "{}"
        return SimpleNamespace(state=state)


class _MemoryStore:
    def __init__(self):
        self.states: dict[str, str | None] = {}

    async def claim(self, session_id, buyer_id, enforce_owner=True):
        claim = SimpleNamespace(
            session_id=session_id, fence=1, revision=1,
            state_json=self.states.get(session_id),
        )
        return claim

    async def save_claim(self, claim, state_json):
        self.states[claim.session_id] = state_json
        claim.revision += 1
        return claim


def _context(session_id: str):
    return ShoppingContext.set(ShoppingContextSnapshot(
        shopping_session_id=session_id, buyer_id="b1", locale="zh-CN", currency="CNY",
    ))


class TestSessionRegistryLRU:
    async def test_evicts_oldest_beyond_limit(self):
        factory, store = _Factory(), _MemoryStore()
        registry = SessionRegistry(factory, store, agent_cache_limit=2)
        for session_id in ("s1", "s2", "s3"):
            token = _context(session_id)
            try:
                await registry.get_or_create(session_id)
            finally:
                ShoppingContext.reset(token)

        assert "s1" not in registry._agents and "s1" not in registry._claims, "超限后最旧会话被逐出"
        assert set(registry._agents) == {"s2", "s3"}
        assert factory.built == 3

    async def test_access_refreshes_recency(self):
        factory, store = _Factory(), _MemoryStore()
        registry = SessionRegistry(factory, store, agent_cache_limit=2)
        for session_id in ("s1", "s2"):
            token = _context(session_id)
            try:
                await registry.get_or_create(session_id)
            finally:
                ShoppingContext.reset(token)
        # 复访 s1 把 s2 挤成最旧
        token = _context("s1")
        try:
            await registry.get_or_create("s1")
        finally:
            ShoppingContext.reset(token)
        token = _context("s3")
        try:
            await registry.get_or_create("s3")
        finally:
            ShoppingContext.reset(token)
        assert "s2" not in registry._agents and "s1" in registry._agents

    async def test_persist_returns_false_for_evicted_session(self):
        factory, store = _Factory(), _MemoryStore()
        registry = SessionRegistry(factory, store, agent_cache_limit=1)
        token = _context("s1")
        try:
            await registry.get_or_create("s1")
            assert await registry.persist("s1") is True
        finally:
            ShoppingContext.reset(token)
        token = _context("s2")
        try:
            await registry.get_or_create("s2")  # 逐出 s1
        finally:
            ShoppingContext.reset(token)
        assert await registry.persist("s1") is False, "已逐出会话的 persist 应返回 False"


class TestOrchestratorLockPruning:
    async def test_lock_pruned_after_turn_completes(self):
        from tests.test_ag_ui import make_orchestrator, request_data
        from app.presentation.ag_ui import parse_intent
        from ag_ui.core import RunAgentInput

        orchestrator, agent, sessions = make_orchestrator()
        body = RunAgentInput.model_validate(request_data())
        result = await orchestrator.handle_intent(parse_intent(body), use_semantic_cache=False)
        assert result.error is None
        assert "session-test" not in orchestrator._session_locks, "turn 结束后锁应被回收"

    async def test_concurrent_turns_still_serialized_after_pruning(self):
        from tests.test_ag_ui import make_orchestrator, request_data
        from app.presentation.ag_ui import parse_intent
        from ag_ui.core import RunAgentInput

        orchestrator, agent, sessions = make_orchestrator()
        body = RunAgentInput.model_validate(request_data())
        first = asyncio.ensure_future(orchestrator.handle_intent(parse_intent(body), use_semantic_cache=False))
        await asyncio.sleep(0.01)
        second = asyncio.ensure_future(orchestrator.handle_intent(parse_intent(body), use_semantic_cache=False))
        await asyncio.gather(first, second)
        assert agent.peak == 1, "同会话两轮不得并发执行（修剪不得破坏串行化）"
        assert "session-test" not in orchestrator._session_locks
