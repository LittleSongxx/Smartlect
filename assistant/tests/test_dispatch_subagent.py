"""SubAgent-as-Tool 并行派发契约测试：create_react_agent 子智能体 + asyncio.gather 并发。"""
import asyncio
import unittest
from unittest.mock import AsyncMock

from smartlect.agents.shopping import dispatch
from smartlect.agents.shopping.model_adapter import ProviderChatModel, from_openai_message, to_openai_messages
from smartlect.tools import REGISTRY


class _ScriptedProvider:
    """奇数次调用调工具、偶数次调用给结论——可被多个子智能体共享。"""

    def __init__(self, tool_name, tool_args, answer):
        self._tool_name = tool_name
        self._tool_args = tool_args
        self._answer = answer
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.calls % 2 == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"c{self.calls}", "type": "function",
                 "function": {"name": self._tool_name, "arguments": self._tool_args}}]}
        else:
            message = {"role": "assistant", "content": self._answer}
        return {"message": message, "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class AdapterTests(unittest.TestCase):
    def test_openai_message_roundtrip_preserves_tool_calls(self):
        wire = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "search_skus", "arguments": '{"query": "键盘"}'}}]}
        message = from_openai_message(wire)
        self.assertEqual(message.tool_calls[0]["name"], "search_skus")
        self.assertEqual(message.tool_calls[0]["args"], {"query": "键盘"})
        back = to_openai_messages([message])
        self.assertEqual(back[0]["tool_calls"][0]["function"]["name"], "search_skus")
        self.assertIn("键盘", back[0]["tool_calls"][0]["function"]["arguments"])

    def test_structured_tools_expose_readonly_subset(self):
        tools = dispatch.structured_tools(lambda name, args: None)
        self.assertEqual({t.name for t in tools}, set(dispatch.SUB_AGENT_TOOLS))
        for tool in tools:
            self.assertIn(tool.name, REGISTRY)


class DispatchTests(unittest.TestCase):
    def test_parallel_sub_agents_run_and_merge(self):
        async def invoke(name, args):
            self.assertEqual(name, "search_skus")
            return {"items": [{"productId": "p1"}]}

        providers = [_ScriptedProvider("search_skus", '{"query": "键盘"}', "键盘A可售"),
                     _ScriptedProvider("search_skus", '{"query": "鼠标"}', "鼠标B可售"),
                     _ScriptedProvider("search_skus", '{"query": "垫子"}', "垫子C可售")]
        models = [ProviderChatModel(provider=p) for p in providers]
        # 每个任务用各自的模型：通过闭包区分
        index = {"i": 0}

        async def model_for(task):
            model = models[index["i"] % len(models)]
            index["i"] += 1
            return model

        # dispatch 接口是单一 model；这里用共享 provider 验证并发与合并语义
        shared = _ScriptedProvider("search_skus", '{"query": "x"}', "结论")
        result = asyncio.run(dispatch.dispatch(
            ["任务A", "任务B"], model=ProviderChatModel(provider=shared), invoke=invoke))
        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(result["parallel"])
        self.assertTrue(all(r["status"] == "succeeded" for r in result["results"]))
        self.assertGreaterEqual(result["elapsed_ms"], 0)

    def test_dispatch_rejects_out_of_band_task_counts(self):
        from smartlect.agents.shopping.dispatch import DispatchBudgetExceeded
        with self.assertRaises(DispatchBudgetExceeded):
            asyncio.run(dispatch.dispatch([], model=None, invoke=None))
        with self.assertRaises(DispatchBudgetExceeded):
            asyncio.run(dispatch.dispatch(["a"] * 4, model=None, invoke=None))

    def test_registry_entry_is_read_only_kind(self):
        tool = REGISTRY["task_dispatch"]
        self.assertEqual(tool.kind, "read")
        self.assertEqual(tool.permission, "shopping:read")
        parsed = tool.schema.model_validate(
            {"tasks": ["比较A和B"], "reason": "parallel"})
        self.assertEqual(parsed.reason, "parallel")


if __name__ == "__main__":
    unittest.main()
