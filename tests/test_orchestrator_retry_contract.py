# -*- coding: utf-8 -*-
"""编排层整轮重试的 SDK 契约测试（D7）。

钉住的隐式契约：AgentScope 在首次模型调用前已把本轮 inputs 写入
state.context。`_reply_with_retry` 失败后以 inputs=[] 重入，正是依赖该
契约避免用户消息丢失或重复。SDK 升级若改变该行为，本测试先于线上失败。
"""
import pytest
from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import TextBlock
from agentscope.model import ChatResponse

import app.application.agents.orchestrator as orchestrator_module
from app.application.agents.orchestrator import MainAgentOrchestrator, SubmitIntentInput
from app.infrastructure.eventbus import TradeEventBus
from app.infrastructure.llm import ThrottledChatModel
from app.infrastructure.throttle import GatewayThrottle


class TransientThenOkModel(ThrottledChatModel):
    """第一次调用抛网关限流（编排层判瞬时），第二次成功。"""

    def __init__(self):
        super().__init__(
            credential=OpenAICredential(api_key="test", base_url="http://test/v1"),
            model="test", throttle=GatewayThrottle(3, 0), max_transient_retries=0,
        )
        self.calls = 0

    async def _invoke_upstream(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("429 Too Many Requests")
        return ChatResponse(content=[TextBlock(text="好的推荐")], is_last=True)


class _EmptyPreferences:
    async def list_by_buyer(self, buyer_id):
        return []


class _Sessions:
    def __init__(self, agent):
        self.agent = agent

    async def get_or_create(self, session_id):
        return self.agent

    async def persist(self, session_id):
        return True


async def test_transient_failure_retry_keeps_single_user_message(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_RETRY_BASE_SECONDS", 0.01)
    model = TransientThenOkModel()
    agent = Agent("test", "测试", model)
    orchestrator = MainAgentOrchestrator(_Sessions(agent), TradeEventBus(), _EmptyPreferences())
    try:
        result = await orchestrator.handle_intent(SubmitIntentInput(
            shopping_session_id="s-contract", buyer_id="buyer-contract",
            locale="zh-CN", currency="CNY", raw_query="推荐一个背包",
        ))
        assert result.error is None
        assert result.final_text == "好的推荐"
        assert model.calls == 2, "第二次模型调用应来自编排层重试"
        user_turns = [
            message for message in agent.state.context
            if getattr(message, "name", None) == "buyer-contract"
        ]
        assert len(user_turns) == 1, "重试不得丢失或复制用户消息（SDK 落 inputs 契约）"
    finally:
        await model.client.close()
