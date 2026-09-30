# -*- coding: utf-8 -*-
"""流式输出守卫单测：token 增量必须与 final text 同源脱敏。

背景：audit_output 只守卫最终回复，token.delta / TEXT_MESSAGE_CONTENT 会先一步
实时到达前端并写入 journal 回放——敏感内容一旦中途泄露，事后脱敏 final 无济于事。
"""
from types import SimpleNamespace

from agentscope.event import (
    ReplyEndEvent,
    ReplyStartEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import AssistantMsg
from ag_ui.core import RunAgentInput, TextMessageContentEvent

from app.application.agents.ag_ui_adapter import AGUIRunAdapter
from app.application.agents.orchestrator import MainAgentOrchestrator, SubmitIntentInput
from app.infrastructure.eventbus import TradeEventBus
from app.infrastructure.security.output_guard import StreamingMasker, _mask_text

# 敏感样例：会话 ID 跨 chunk 分裂 + 完整 API Key，两条路径都必须掩码
LEAKY_PARTS = [
    "内部排查信息 shopping_session_id: abc",
    "def-1234 与密钥 sk-abcdefghij0123456789zz 请勿外泄",
]
LEAKY_FULL = "".join(LEAKY_PARTS)


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


class _LeakyAgent:
    """按脚本把含敏感内容的文本增量分块吐出，模拟模型中途泄露。"""

    name = "LeakyAgent"

    def __init__(self):
        self.state = SimpleNamespace(summary=None, context=[])

    async def reply_stream(self, inputs, yield_final_msg=False):
        yield ReplyStartEvent(session_id="s-guard", reply_id="r1", name=self.name)
        yield TextBlockStartEvent(reply_id="r1", block_id="t1")
        for part in LEAKY_PARTS:
            yield TextBlockDeltaEvent(reply_id="r1", block_id="t1", delta=part)
        yield TextBlockEndEvent(reply_id="r1", block_id="t1")
        yield ReplyEndEvent(session_id="s-guard", reply_id="r1")
        yield AssistantMsg(self.name, "最终回复")


class TestStreamingMasker:
    def test_push_and_flush_concatenate_to_masked_full(self):
        masker = StreamingMasker()
        out = "".join(masker.push(part) for part in LEAKY_PARTS) + masker.flush()
        assert out == _mask_text(LEAKY_FULL)
        assert "shopping_session_id: abcdef-1234" not in out
        assert "sk-abcdefghij0123456789zz" not in out
        assert "[已脱敏]" in out

    def test_clean_text_passes_through_unchanged(self):
        masker = StreamingMasker()
        text = "这是一段正常回复，介绍商品、价格与配送方案，不包含任何敏感内容。" * 10
        chunks = [text[i : i + 7] for i in range(0, len(text), 7)]
        out = "".join(masker.push(chunk) for chunk in chunks) + masker.flush()
        assert out == text, "干净文本不得被改写或丢失"

    def test_clean_text_streams_immediately(self):
        """干净文本零扣留：每次 push 即时放行，不等 flush（不能破坏流式体验）。"""
        masker = StreamingMasker()
        emitted = [masker.push(chunk) for chunk in ["正在", "查找", "商品。"]]
        assert emitted == ["正在", "查找", "商品。"]
        assert masker.flush() == ""

    def test_partial_trigger_arrival_is_held_then_masked(self):
        """敏感字面前缀在途时只扣留在途部分；匹配完成即掩码并恢复放行。"""
        masker = StreamingMasker()
        assert masker.push("正常开头。shop") == "正常开头。", "触发串前缀（shop…）在途时扣留"
        assert masker.push("ping_session_id: abc") == "[已脱敏]", "匹配补全后整段掩码放行"
        assert masker.push("def-1234 结束") == " 结束", "后续值并入同一次掩码"
        assert masker.flush() == ""

    def test_split_secret_never_appears_in_any_partial_output(self):
        masker = StreamingMasker()
        partial_outputs = []
        # 按单字符推送，任何前缀的已放行输出都不得包含原始秘密
        for character in LEAKY_FULL:
            partial_outputs.append(masker.push(character))
        partial_outputs.append(masker.flush())
        for snapshot in partial_outputs:
            assert "shopping_session_id" not in snapshot or "[已脱敏]" in snapshot
            assert "sk-abcdefghij" not in snapshot
        assert "".join(partial_outputs) == _mask_text(LEAKY_FULL)


class TestOrchestratorStreamsMaskedDeltas:
    async def test_token_delta_events_are_masked(self):
        bus = TradeEventBus()
        agent = _LeakyAgent()
        orchestrator = MainAgentOrchestrator(_Sessions(agent), bus, _EmptyPreferences())
        queue = bus.subscribe("s-guard")
        try:
            result = await orchestrator.handle_intent(SubmitIntentInput(
                shopping_session_id="s-guard", buyer_id="b-guard",
                locale="zh-CN", currency="CNY", raw_query="查一下",
            ))
        finally:
            bus.unsubscribe("s-guard", queue)
        assert result.error is None

        deltas = [event.payload["token"] for event in _drain(queue) if event.type == "token.delta"]
        streamed = "".join(deltas)
        assert streamed == _mask_text(LEAKY_FULL)
        assert "shopping_session_id: abcdef-1234" not in streamed
        assert "sk-abcdefghij0123456789zz" not in streamed
        assert "[已脱敏]" in streamed


class TestAdapterMasksTextDeltas:
    def _adapter(self):
        emitted = []
        request = RunAgentInput.model_validate({
            "threadId": "t-guard", "runId": "r-guard", "state": {},
            "messages": [{"id": "u1", "role": "user", "content": "查一下"}],
            "tools": [], "context": [], "forwardedProps": {},
        })
        return AGUIRunAdapter(request, emitted.append), emitted

    def test_text_message_content_is_masked(self):
        adapter, emitted = self._adapter()
        adapter.on_agent_event(TextBlockStartEvent(reply_id="r1", block_id="t1"))
        for part in LEAKY_PARTS:
            adapter.on_agent_event(TextBlockDeltaEvent(reply_id="r1", block_id="t1", delta=part))
        adapter.on_agent_event(TextBlockEndEvent(reply_id="r1", block_id="t1"))

        contents = [event.delta for event in emitted if isinstance(event, TextMessageContentEvent)]
        streamed = "".join(contents)
        assert streamed == _mask_text(LEAKY_FULL)
        assert "sk-abcdefghij0123456789zz" not in streamed

    def test_interrupted_stream_flushes_masked_tail(self):
        adapter, emitted = self._adapter()
        adapter.on_agent_event(TextBlockStartEvent(reply_id="r1", block_id="t1"))
        for part in LEAKY_PARTS:
            adapter.on_agent_event(TextBlockDeltaEvent(reply_id="r1", block_id="t1", delta=part))
        # 不发 END，直接走中断收口：扣留尾部也必须先掩码再关闭
        adapter._close_streams()

        contents = [event.delta for event in emitted if isinstance(event, TextMessageContentEvent)]
        assert "".join(contents) == _mask_text(LEAKY_FULL)
        assert "shopping_session_id: abcdef-1234" not in "".join(contents)


def _drain(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events
