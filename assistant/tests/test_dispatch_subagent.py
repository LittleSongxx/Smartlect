"""SubAgent-as-Tool 并行派发契约测试：分型路由 + create_react_agent 子智能体 +
asyncio.gather 并发 + 确定性组装（Composer）。"""
import asyncio
import unittest

from smartlect.agents.shopping import dispatch
from smartlect.agents.shopping.model_adapter import ProviderChatModel, from_openai_message, to_openai_messages
from smartlect.agents.shopping.profiles import COMPARATOR, RETRIEVAL_SCOUT, SUB_AGENT_TOOLS
from smartlect.tools import REGISTRY


class _ScriptedProvider:
    """奇数次调用调工具、偶数次调用给结论——可被多个子智能体共享。

    忠实模拟 Provider 的预算闸协议：调用方传入 before_attempt 时，
    每次尝试前先过闸（拒绝即抛，与真实 Provider._complete_request 一致）。
    """

    def __init__(self, tool_name, tool_args, answer):
        self._tool_name = tool_name
        self._tool_args = tool_args
        self._answer = answer
        self.calls = 0

    async def chat(self, messages, **kwargs):
        before_attempt = kwargs.get('before_attempt')
        if before_attempt is not None:
            await before_attempt()
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

    def test_structured_tools_narrow_to_profile_scope(self):
        seen = []

        async def invoke(name, args, allowed=None):
            seen.append((name, tuple(allowed or ())))
            return {"items": []}

        tools = dispatch.structured_tools(invoke, COMPARATOR.tool_scope)
        self.assertEqual({t.name for t in tools}, set(COMPARATOR.tool_scope))
        for tool in tools:
            self.assertIn(tool.name, REGISTRY)
        # 运行期 invoke 收到的 allowed 与 profile 声明一致
        asyncio.run(tools[0].ainvoke({}))
        self.assertEqual(seen[0][0], COMPARATOR.tool_scope[0])
        self.assertEqual(set(seen[0][1]), set(COMPARATOR.tool_scope))

    def test_union_subset_stays_readonly(self):
        for name in SUB_AGENT_TOOLS:
            self.assertIn(name, REGISTRY)
            self.assertEqual(REGISTRY[name].kind, 'read')


class DispatchTests(unittest.TestCase):
    def test_parallel_sub_agents_run_and_merge(self):
        calls = []

        async def invoke(name, args, allowed=None):
            calls.append(name)
            return {"items": [{"productId": "p1"}]}

        shared = _ScriptedProvider("search_skus", '{"query": "x"}', "结论")
        result = asyncio.run(dispatch.dispatch(
            ["任务A：查键盘", "任务B：对比A和B"], model=ProviderChatModel(provider=shared), invoke=invoke))
        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(result["parallel"])
        self.assertTrue(all(r["status"] == "succeeded" for r in result["results"]))
        self.assertGreaterEqual(result["elapsed_ms"], 0)
        # 分型路由元数据随结果回传（可解释路由）
        self.assertEqual([r["profile"] for r in result["results"]], ['retrieval-scout', 'comparator'])
        # 组装层产物
        self.assertTrue(result["all_succeeded"])
        self.assertIn("merge_instruction", result)
        self.assertIn("路由=", result["summary"])

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


class ComposerTests(unittest.TestCase):
    """确定性组装层：部分失败必须显式可见，不得包装成完整证据。"""

    def test_all_succeeded_summary(self):
        results = [
            {"task": "查A", "status": "succeeded", "answer": "A可售", "profile": "retrieval-scout"},
            {"task": "查B", "status": "succeeded", "answer": "B可售", "profile": "retrieval-scout"},
        ]
        payload = dispatch.compose_results(results, 12.5)
        self.assertTrue(payload["all_succeeded"])
        self.assertEqual(payload["succeeded_count"], "2/2")
        self.assertNotIn("incomplete_tasks", payload)
        self.assertIn("✓", payload["summary"])
        self.assertNotIn("缺失", payload["merge_instruction"])  # 全成功时不强制披露

    def test_partial_failure_is_disclosed(self):
        results = [
            {"task": "查A", "status": "succeeded", "answer": "A可售", "profile": "retrieval-scout"},
            {"task": "查B", "status": "timeout", "answer": "子智能体在时限内未完成"},
        ]
        payload = dispatch.compose_results(results, 30.0)
        self.assertFalse(payload["all_succeeded"])
        self.assertEqual(payload["incomplete_tasks"], ["查B"])
        self.assertIn("✗(timeout)", payload["summary"])
        self.assertIn("缺失", payload["merge_instruction"])

    def test_router_reason_recorded_per_task(self):
        results = [{"task": "对比A和B", "status": "succeeded", "answer": "B更省电",
                    "profile": COMPARATOR.name, "routing_reason": "compare_signal"}]
        payload = dispatch.compose_results(results, 5.0)
        self.assertEqual(payload["results"][0]["routing_reason"], "compare_signal")
        self.assertEqual(payload["results"][0]["profile"], COMPARATOR.name)


class TaskDispatchThroughInvokeTests(unittest.TestCase):
    """task_dispatch 分支的端到端回归：必须走完整 invoke()（台账/RBAC/范围闸）。

    背景：该分支曾有闭包引用了 _invoke 不存在的参数（product_scope）导致
    NameError，而分派单测全部绕过 invoke() 直接调 dispatch()，没有覆盖到。
    本测试用脚本化 Provider 驱动子智能体真实调用一次工具（get_my_orders），
    锁死「子工具调用进台账 + 工具面求交」两条语义。
    """

    def test_dispatch_runs_sub_tools_through_the_ledgered_invoke_path(self):
        import asyncio
        from smartlect import tools

        class _Actor:
            permissions = ('shopping:read', 'orders:read')
            subject_type = 'user'

            def require(self, permission):
                assert permission in self.permissions

            def is_trial_user(self):
                return False

        class _Store:
            def __init__(self):
                self.calls = []

            def start_tool_call(self, lease, call_id, name, params):
                self.calls.append(name)
                return {'outcome': 'started'}

            def finish_tool_call(self, lease, call_id, outcome=None, receipt=None):
                pass

        class _Commerce:
            async def request(self, service, path, *, actor, data):
                assert service == 'order' and path.endswith('listOrders')
                return [{'orderId': 'O1', 'status': 'PAID'}]

        # 子智能体：第一轮调 get_my_orders，第二轮给结论
        provider = _ScriptedProvider('get_my_orders', '{"limit": 5}', '订单O1已支付')
        store = _Store()
        receipt = asyncio.run(tools.invoke(
            'task_dispatch', {'tasks': ['查询我的订单'], 'reason': 'parallel'},
            actor=_Actor(), commerce=_Commerce(), store=store,
            lease={'conversation_id': 'c1', 'agent_run_id': 'r1'},
            allowed={'task_dispatch', 'get_my_orders'}, provider=provider))
        # 台账：主调用 task_dispatch + 子智能体的 get_my_orders 都落账
        self.assertEqual(store.calls, ['task_dispatch', 'get_my_orders'])
        summary = receipt['data']['summary']
        self.assertIn('订单O1已支付', summary)
        self.assertIn('order-reader', summary)  # 路由元数据随组装回传

    def test_sub_tool_outside_main_allowed_surface_is_rejected(self):
        import asyncio
        from smartlect import tools

        class _Actor:
            permissions = ('shopping:read', 'orders:read')
            subject_type = 'user'

            def require(self, permission):
                pass

            def is_trial_user(self):
                return False

        class _Store:
            def __init__(self):
                self.calls = []

            def start_tool_call(self, lease, call_id, name, params):
                self.calls.append(name)
                return {'outcome': 'started'}

            def finish_tool_call(self, lease, call_id, outcome=None, receipt=None):
                pass

        class _Commerce:
            async def request(self, service, path, *, actor, data):
                return []

        # 主面不含 get_my_orders（Skill 门控未启用该工具）：即使子 profile 声明了它，
        # 求交后也不可见。拒绝发生在 allowed 闸（台账之前，与主路径 tool_not_loaded
        # 同一语义），子智能体按单任务失败降级——组装层把失败显式标注为不完整。
        provider = _ScriptedProvider('get_my_orders', '{"limit": 5}', 'fallback')
        store = _Store()
        receipt = asyncio.run(tools.invoke(
            'task_dispatch', {'tasks': ['查询我的订单'], 'reason': 'parallel'},
            actor=_Actor(), commerce=_Commerce(), store=store,
            lease={'conversation_id': 'c1', 'agent_run_id': 'r1'},
            allowed={'task_dispatch'}, provider=provider))
        self.assertEqual(store.calls, ['task_dispatch'])  # 子调用被 allowed 闸拦下，未进台账
        row = receipt['data']['results'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertIn('StateError', row['answer'])
        self.assertFalse(receipt['data']['all_succeeded'])


class SubModelAttemptLimitTests(unittest.TestCase):
    """单子任务模型调用上限：comparator 式不收敛循环不许烧穿全局预算。
    live 调优（tuneA-v1，2026-10-06）曾观测到 13 次子调用耗尽整池、
    主循环被迫 rule-fallback 收口——本测试锁定"超限按单任务失败降级"。"""

    def test_runaway_sub_agent_fails_at_limit_not_beyond(self):
        async def scenario():
            provider = _LoopyProvider('compare_skus', '{"productIdList": ["9300000001", "9300000002"]}')
            model = ProviderChatModel(provider=provider, before_attempt=None)

            async def invoke(*_a, **_k):
                return {'items': []}

            with self.assertRaises(dispatch.BudgetExceeded):
                await dispatch.run_sub_agent(model, '比较两个商品', invoke)
            # 子任务自身上限先于任何全局预算触发：第 LIMIT+1 次尝试被闸下，未发出请求
            self.assertEqual(provider.calls, dispatch.SUB_MODEL_ATTEMPT_LIMIT)

        asyncio.run(scenario())


class _LoopyProvider:
    """永远要求调工具、永不给结论——模拟不收敛的子智能体。"""

    def __init__(self, tool_name, tool_args):
        self._tool = {"id": "c1", "type": "function",
                      "function": {"name": tool_name, "arguments": tool_args}}
        self.calls = 0

    async def chat(self, messages, **kwargs):
        before_attempt = kwargs.get('before_attempt')
        if before_attempt is not None:
            await before_attempt()
        self.calls += 1
        return {"message": {"role": "assistant", "content": None, "tool_calls": [dict(self._tool, id=f"c{self.calls}")]},
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class VisibleSubScopeTests(unittest.TestCase):
    """子模型可见工具面 = profile 面 ∩ 主会话 skill 门控面；交集为空显式失败。
    live 路径曾把完整 profile 面下发给子模型、仅在调用时拦截，导致模型必然
    撞 tool_not_loaded——本组测试锁定"可见即可调"的契约。"""

    def test_outer_none_keeps_full_scope(self):
        self.assertEqual(dispatch.visible_sub_scope(('a', 'b'), None), ('a', 'b'))

    def test_intersection_only(self):
        self.assertEqual(dispatch.visible_sub_scope(('a', 'b', 'c'), {'b', 'c', 'x'}), ('b', 'c'))

    def test_empty_intersection_raises_state_error(self):
        with self.assertRaises(dispatch.StateError) as ctx:
            dispatch.visible_sub_scope(('a',), {'b'})
        self.assertEqual(ctx.exception.code, 'sub_agent_no_available_tools')


class BindToolsWireContractTests(unittest.TestCase):
    """bind_tools 必须产出 OpenAI wire dict：provider.chat 对 tools 逐项做
    dict/type/function 严格校验，StructuredTool 对象透传会在 live 路径被
    only_registered_function_tools_allowed 拒绝（scripted 假 Provider 不校验，
    曾因此漏测——本测试锁定 wire 契约本身）。"""

    def test_structured_tool_converted_to_wire_dict(self):
        tool = dispatch.structured_tools(lambda *a, **k: None, ("search_knowledge",))[0]
        bound = ProviderChatModel(provider=object()).bind_tools([tool])
        self.assertEqual(len(bound.tools_wire), 1)
        entry = bound.tools_wire[0]
        self.assertIsInstance(entry, dict)
        self.assertEqual(entry.get("type"), "function")
        self.assertIn("name", entry.get("function") or {})
        self.assertFalse(set(entry) - {"type", "function"})

    def test_openai_dict_passthrough_unchanged(self):
        raw = {"type": "function", "function": {"name": "search_knowledge", "parameters": {}}}
        bound = ProviderChatModel(provider=object()).bind_tools([raw])
        self.assertEqual(bound.tools_wire, [raw])


class SubAgentBudgetTests(unittest.TestCase):
    """预算单一事实源对 dispatch 路径成立：子智能体的模型调用与工具调用
    必须经 sub_agent_budget 钩子（before_attempt / tool_tick）计数——
    不存在绕过主会话预算闸的第二条路径（审计：model_attempts 完整覆盖）。"""

    def _fixtures(self):
        from types import SimpleNamespace

        class _Actor:
            permissions = ('shopping:read', 'orders:read')
            subject_type = 'user'

            def require(self, permission):
                pass

            def is_trial_user(self):
                return False

        class _Store:
            def __init__(self):
                self.calls = []

            def start_tool_call(self, lease, call_id, name, params):
                self.calls.append(name)
                return {'outcome': 'started'}

            def finish_tool_call(self, lease, call_id, outcome=None, receipt=None):
                pass

        class _Commerce:
            async def request(self, service, path, *, actor, data):
                return [{'orderId': 'O1', 'status': 'PAID'}]

        return _Actor(), _Store(), _Commerce(), SimpleNamespace

    def test_budget_hooks_fire_for_sub_model_and_sub_tool(self):
        import asyncio
        from smartlect import tools

        actor, store, commerce, SimpleNamespace = self._fixtures()
        attempts, ticks = [], []

        async def before_attempt():
            attempts.append(len(attempts) + 1)

        async def on_trace(record):
            pass

        async def tool_tick():
            ticks.append(len(ticks) + 1)

        provider = _ScriptedProvider('get_my_orders', '{"limit": 5}', '订单O1已支付')
        receipt = asyncio.run(tools.invoke(
            'task_dispatch', {'tasks': ['查询我的订单'], 'reason': 'parallel'},
            actor=actor, commerce=commerce, store=store,
            lease={'conversation_id': 'c1', 'agent_run_id': 'r1'},
            allowed={'task_dispatch', 'get_my_orders'}, provider=provider,
            sub_agent_budget=SimpleNamespace(before_attempt=before_attempt, on_trace=on_trace,
                                             tool_tick=tool_tick)))
        # 子智能体模型调用两次（工具轮 + 结论轮），每次都过 before_attempt 预算闸
        self.assertEqual(len(attempts), 2)
        # 子工具调用一次，过 tool_tick 工具预算闸
        self.assertEqual(len(ticks), 1)
        self.assertEqual(receipt['data']['results'][0]['status'], 'succeeded')

    def test_model_budget_exhausted_fails_only_that_task(self):
        import asyncio
        from smartlect import tools
        from smartlect.agents.shopping.contract import BudgetExceeded

        actor, store, commerce, SimpleNamespace = self._fixtures()

        async def deny():
            raise BudgetExceeded('model_call_or_time_limit')

        async def noop():
            pass

        async def tool_tick():
            pass

        provider = _ScriptedProvider('get_my_orders', '{"limit": 5}', '不应到达')
        receipt = asyncio.run(tools.invoke(
            'task_dispatch', {'tasks': ['查询我的订单'], 'reason': 'parallel'},
            actor=actor, commerce=commerce, store=store,
            lease={'conversation_id': 'c1', 'agent_run_id': 'r1'},
            allowed={'task_dispatch', 'get_my_orders'}, provider=provider,
            sub_agent_budget=SimpleNamespace(before_attempt=deny, on_trace=noop,
                                             tool_tick=tool_tick)))
        row = receipt['data']['results'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertFalse(receipt['data']['all_succeeded'])
        self.assertIn('BudgetExceeded', row['answer'])

    def test_tool_budget_exhausted_fails_only_that_task(self):
        import asyncio
        from smartlect import tools
        from smartlect.agents.shopping.contract import BudgetExceeded

        actor, store, commerce, SimpleNamespace = self._fixtures()

        async def before_attempt():
            pass

        async def noop():
            pass

        async def deny_tool():
            raise BudgetExceeded('tool_call_limit')

        provider = _ScriptedProvider('get_my_orders', '{"limit": 5}', '不应到达')
        receipt = asyncio.run(tools.invoke(
            'task_dispatch', {'tasks': ['查询我的订单'], 'reason': 'parallel'},
            actor=actor, commerce=commerce, store=store,
            lease={'conversation_id': 'c1', 'agent_run_id': 'r1'},
            allowed={'task_dispatch', 'get_my_orders'}, provider=provider,
            sub_agent_budget=SimpleNamespace(before_attempt=before_attempt, on_trace=noop,
                                             tool_tick=deny_tool)))
        row = receipt['data']['results'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertIn('BudgetExceeded', row['answer'])
        # 子工具被 tool_tick 拦下：台账只有主调用
        self.assertEqual(store.calls, ['task_dispatch'])


if __name__ == "__main__":
    unittest.main()
