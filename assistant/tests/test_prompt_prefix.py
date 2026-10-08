"""前缀缓存三不变量（组件 8 / ADR-0014）。

注释会被无视，单测不会：上游前缀缓存按渲染后的稳定前缀精确匹配，任何
每轮可变内容（偏好/摘要/任务槽/焦点/澄清/Skill 预告/待决提案）一旦进入
system 段，tools+system 整段前缀的缓存就会被系统性打断（mewhelp ch07
实测：无摘要会话 cache_read=2048，摘要一进 system 掉到 0）。三条不变量：

1. system 逐字恒定且唯一——同一会话内不同轮的可变状态不改变 system 文本；
2. 可变载荷绝不出现在 system——只允许出现在「本轮材料」消息里；
3. ReAct 步间严格前缀——主路径上后一步的 prompt 以前一步的 prompt 为前缀
   （append-only；窗口未滑动的常规轮必须成立，滑动轮由 fail-closed 兜底）。
"""
import unittest

from smartlect.agents.shopping import session as shopping_session
from smartlect.agents.shopping.policy import SYSTEM_POLICY_BODY, dispatch_enabled, system_policy_body
from smartlect.business_skills import USER_SKILLS, catalog, render_loaded_skills
from smartlect.tools import REGISTRY, schemas


def _skills():
    return {name: {'skill_id': name, 'version': '1.0.0', 'instructions': '流程说明'}
            for name in USER_SKILLS}


def _actor():
    class _Actor:
        permissions = ('shopping:read', 'orders:read', 'orders:write')
        subject_type = 'user'

        def require(self, permission):
            pass
    return _Actor()


class StaticSystemTests(unittest.TestCase):
    def test_system_is_verbatim_stable_across_variable_turn_states(self):
        """不变量 1：偏好/焦点/澄清等每轮可变状态不改变 system 文本。"""
        base = dict(policy_body=system_policy_body(), skill_catalog=catalog(),
                    skills=_skills(), subject_type='user')
        first = shopping_session.assemble_static_system(**base)
        # 可变状态换一轮（不同偏好、不同焦点、待决提案、澄清命中）——system 不变
        turn_a = shopping_session.assemble_turn_context(
            suggestions=('shopping_advice',), clarify=True, clarify_reason='comparison_targets_missing',
            clarify_missing=['比较目标'],
            preferences=[{'preference_key': 'likes', 'value': ['轻便']}],
            summary={'kind': 'user_request_excerpts'}, mission={'budget_max_cents': 30000},
            focus_mode='PRODUCT', focus_product_id=1001, focus_sku_key=None, pending_proposals=2)
        turn_b = shopping_session.assemble_turn_context(
            preferences=[], summary=None, mission=None,
            focus_mode='GLOBAL', pending_proposals=0)
        second = shopping_session.assemble_static_system(**base)
        self.assertEqual(first, second)
        # 可变载荷只出现在本轮材料里
        self.assertIn('轻便', turn_a)
        self.assertIn('1001', turn_a)
        self.assertIn('待确认提案', turn_a)
        self.assertNotIn('轻便', first)
        self.assertNotIn('1001', first)
        self.assertNotIn('待确认提案', first)
        self.assertNotIn('待确认提案', turn_b)

    def test_system_contains_only_the_five_static_segments(self):
        system = shopping_session.assemble_static_system(
            policy_body=system_policy_body(), skill_catalog=catalog(),
            skills=_skills(), subject_type='visitor')
        self.assertEqual(system.count('\n主体类别：'), 1)
        self.assertTrue(system.endswith('主体类别：visitor'))
        # 禁的是动态载荷标记（预告/焦点/本轮材料头/只读上下文 JSON 键），
        # 不是静态契约里的中文词汇（"偏好/摘要/任务槽"是契约输入说明）。
        for banned in ('本轮Skill预告', '本轮焦点', shopping_session.TURN_CONTEXT_HEADER,
                       '"preferences"', '"summary"', '"mission"', '待确认提案'):
            self.assertNotIn(banned, system)


class TurnContextPositionTests(unittest.TestCase):
    def test_turn_context_inserted_after_last_user_message(self):
        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': '第一轮问题'},
            {'role': 'assistant', 'content': '第一轮答复'},
            {'role': 'user', 'content': '本轮问题'},
        ]
        result = shopping_session.with_turn_context(messages, '[本轮服务端材料] 只读上下文…')
        self.assertEqual(len(result), len(messages) + 1)
        self.assertEqual(result[-2], {'role': 'user', 'content': '本轮问题'})
        self.assertEqual(result[-1]['role'], 'user')
        self.assertIn('只读上下文', result[-1]['content'])
        # 入参不被修改
        self.assertEqual(len(messages), 4)

    def test_empty_turn_context_returns_unchanged_copy(self):
        messages = [{'role': 'system', 'content': 'sys'}, {'role': 'user', 'content': 'q'}]
        result = shopping_session.with_turn_context(messages, '')
        self.assertEqual(result, messages)
        self.assertIsNot(result, messages)

    def test_turn_context_header_declares_data_not_user_speech(self):
        turn = shopping_session.assemble_turn_context(preferences=[], summary=None, mission=None)
        self.assertTrue(turn.startswith(shopping_session.TURN_CONTEXT_HEADER))


class ReActPrefixTests(unittest.TestCase):
    def test_step_two_prompt_is_strict_prefix_of_step_three(self):
        """不变量 3：工具往返只追加消息——窗口未滑动时后一步 prompt 严格包含前一步。"""
        system = shopping_session.assemble_static_system(
            policy_body=system_policy_body(), skill_catalog=catalog(),
            skills=_skills(), subject_type='user')
        turn = shopping_session.assemble_turn_context(
            preferences=[{'preference_key': 'likes', 'value': ['轻便']}],
            summary=None, mission={'budget_max_cents': 30000})
        step1 = shopping_session.with_turn_context(
            [{'role': 'system', 'content': system},
             {'role': 'user', 'content': '300 元以内的轻便背包'},
             {'role': 'assistant', 'content': '好的，为您检索。'}], turn)
        # 模型第一步：带工具调用
        step2 = [*step1, {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'c1', 'function': {'name': 'recommend_skus', 'arguments': '{}'}}]}]
        # 工具回执之后
        step3 = [*step2, {'role': 'tool', 'tool_call_id': 'c1', 'content': '{"items": []}'}]
        tool_schemas = schemas(_actor(), None)
        trimmed1, _ = shopping_session.bounded_messages(step1, tool_schemas, '300 元以内的轻便背包')
        trimmed3, _ = shopping_session.bounded_messages(step3, tool_schemas, '300 元以内的轻便背包')
        self.assertEqual(trimmed3[:len(trimmed1)], trimmed1)

    def test_single_system_message_on_main_path(self):
        system = shopping_session.assemble_static_system(
            policy_body=system_policy_body(), skill_catalog=catalog(),
            skills=_skills(), subject_type='user')
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': 'q'}]
        messages = shopping_session.with_turn_context(
            messages, shopping_session.assemble_turn_context(preferences=[], summary=None, mission=None))
        system_messages = [m for m in messages if m['role'] == 'system']
        self.assertEqual(len(system_messages), 1)
        self.assertEqual(messages[0]['role'], 'system')


class ToolSchemaOrderTests(unittest.TestCase):
    def test_schema_order_is_pinned_to_registry_declaration_order(self):
        """工具 schema 顺序 = REGISTRY 声明序（确定性）：顺序漂移会静默击穿缓存前缀。"""
        order = [schema['function']['name'] for schema in schemas(_actor(), None)]
        expected = [name for name, tool in REGISTRY.items()
                    if tool.permission in _actor().permissions]
        self.assertEqual(order, expected)
        # 两次调用逐字节一致
        self.assertEqual(order, [schema['function']['name'] for schema in schemas(_actor(), None)])


class PolicyArmTests(unittest.TestCase):
    def test_ab_arm_changes_policy_body_but_not_assembly_contract(self):
        """A/B 臂只改 policy_body 文本本身（预期失效），装配契约不随臂别改变。"""
        enabled = dispatch_enabled()
        body_a = system_policy_body(enabled)
        body_b = system_policy_body(not enabled)
        self.assertNotEqual(body_a, body_b)
        sys_a = shopping_session.assemble_static_system(body_a, catalog(), _skills(), 'user')
        sys_b = shopping_session.assemble_static_system(body_b, catalog(), _skills(), 'user')
        self.assertNotEqual(sys_a, sys_b)
        # 但同臂同输入恒定
        self.assertEqual(sys_a, shopping_session.assemble_static_system(body_a, catalog(), _skills(), 'user'))
        self.assertIn(SYSTEM_POLICY_BODY if enabled else '', sys_a)


if __name__ == '__main__':
    unittest.main()
