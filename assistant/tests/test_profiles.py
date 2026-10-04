"""AgentProfile 声明式角色契约测试：单一事实源驱动提示词、工具面与路由。

对齐 EchoMind 的 profile 契约测试模式：每个角色的契约互不相同且可被断言，
新增角色不需要改渲染器或分发器。
"""
import unittest

from smartlect.agents.shopping.policy import BOOTSTRAP_TOOLS
from smartlect.agents.shopping.profiles import (COMPARATOR, ORDER_READER, RETRIEVAL_SCOUT,
                                                SHOPPING_MAIN, SUB_AGENT_TOOLS, SUB_PROFILES,
                                                render_profile, route_sub_agent)
from smartlect.tools import REGISTRY

WRITE_TOOLS = {'remember_preference', 'propose_order', 'propose_cancel', 'propose_refund',
               'request_handoff'}


class ProfileContractTests(unittest.TestCase):
    def test_main_profile_matches_bootstrap_tool_surface(self):
        self.assertEqual(set(SHOPPING_MAIN.tool_scope), set(BOOTSTRAP_TOOLS))

    def test_sub_profiles_have_distinct_and_narrow_tool_scopes(self):
        scopes = {profile.name: set(profile.tool_scope) for profile in SUB_PROFILES}
        self.assertEqual(len(scopes), 3)
        names = list(scopes)
        for index, name in enumerate(names):
            for other in names[index + 1:]:
                self.assertNotEqual(scopes[name], scopes[other],
                                    f'{name} 与 {other} 工具面不得相同')
        for profile in SUB_PROFILES:
            self.assertTrue(profile.tool_scope)
            self.assertTrue(set(profile.tool_scope) <= set(SUB_AGENT_TOOLS))

    def test_sub_agent_union_excludes_write_and_handoff_tools(self):
        self.assertEqual(set(SUB_AGENT_TOOLS) & WRITE_TOOLS, set())
        self.assertNotIn('task_dispatch', SUB_AGENT_TOOLS)  # 子智能体不能嵌套派发

    def test_every_profile_tool_exists_in_registry(self):
        for profile in (SHOPPING_MAIN, *SUB_PROFILES):
            for name in profile.tool_scope:
                self.assertIn(name, REGISTRY, f'{profile.name} 声明了未注册工具 {name}')

    def test_render_contains_contract_sections(self):
        text = render_profile(RETRIEVAL_SCOUT)
        for marker in ('[角色契约]', '角色：', '任务：', '输入契约：', '输出契约：',
                       '工具面：', '边界（不做什么）：', '预算：'):
            self.assertIn(marker, text)
        self.assertIn('search_knowledge', text)
        self.assertIn('不虚构库存', text)

    def test_main_render_carries_budget_facts(self):
        text = render_profile(SHOPPING_MAIN)
        self.assertIn('answer_status', text)          # 输出契约：模型不填写编译字段
        self.assertIn('task_dispatch', text)          # 派发边界
        self.assertIn('90 秒', text)                  # 预算硬界


class SubAgentRoutingTests(unittest.TestCase):
    def test_compare_signal_routes_to_comparator(self):
        profile, reason = route_sub_agent('比较机械键盘 A 和 B 哪个更适合办公')
        self.assertIs(profile, COMPARATOR)
        self.assertEqual(reason, 'compare_signal')

    def test_order_signal_routes_to_order_reader(self):
        profile, reason = route_sub_agent('查询我的订单 O1 的物流发货状态')
        self.assertIs(profile, ORDER_READER)
        self.assertEqual(reason, 'order_facts_signal')

    def test_default_routes_to_retrieval_scout(self):
        profile, reason = route_sub_agent('店内有哪些 200 元以内的静音鼠标有货')
        self.assertIs(profile, RETRIEVAL_SCOUT)
        self.assertEqual(reason, 'default_knowledge_and_catalog')

    def test_order_signal_wins_over_compare_words(self):
        # 订单信号优先：comparator 的工具面没有订单工具，「对比两笔订单」
        # 必须先由 order-reader 取到事实，比较叙述由主智能体合并。
        profile, reason = route_sub_agent('对比两笔订单的退款进度')
        self.assertIs(profile, ORDER_READER)
        self.assertEqual(reason, 'order_facts_signal')


if __name__ == '__main__':
    unittest.main()
