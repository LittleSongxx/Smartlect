"""A/B 消融开关契约：SMARTLECT_DISPATCH_ENABLED=false 时 task_dispatch 结构性不可见。

消融实验的公平性依赖单一架构差异——B 臂（单 Agent）与 A 臂（Supervisor-Workers）
在代码、模型、预算、其余工具与提示词正文上完全一致，差异只有三处联动：
可见工具面剔除、系统提示词剔除派发条款（prompt 版本 -nd）、allowed 闸拒绝。
"""
import unittest

from smartlect.agents.shopping import policy
from smartlect.agents.shopping.policy import (SYSTEM_POLICY_BODY, gate_allowed, prompt_version_label,
                                              system_policy_body)
from smartlect.tools import REGISTRY, schemas


class _Actor:
    permissions = ('shopping:read', 'orders:read')
    subject_type = 'user'

    def require(self, permission):
        pass


class DispatchAblationSwitchTests(unittest.TestCase):
    BASE = {'task_dispatch', 'search_knowledge', 'recommend_skus', 'compare_skus'}

    def test_gate_removes_dispatch_when_disabled(self):
        gated = gate_allowed(set(self.BASE), enabled=False)
        self.assertNotIn('task_dispatch', gated)
        self.assertEqual(gated, {'search_knowledge', 'recommend_skus', 'compare_skus'})

    def test_gate_keeps_everything_when_enabled(self):
        self.assertEqual(gate_allowed(set(self.BASE), enabled=True), set(self.BASE))

    def test_b_arm_schemas_structurally_exclude_dispatch(self):
        visible = {item['function']['name'] for item in schemas(_Actor(), gate_allowed(set(self.BASE) | set(REGISTRY), enabled=False))}
        self.assertNotIn('task_dispatch', visible)
        visible_a = {item['function']['name'] for item in schemas(_Actor(), gate_allowed(set(self.BASE) | set(REGISTRY), enabled=True))}
        self.assertIn('task_dispatch', visible_a)

    def test_prompt_label_and_body_differ_only_in_dispatch_clause(self):
        self.assertEqual(prompt_version_label(enabled=True), policy.PROMPT_VERSION)
        self.assertEqual(prompt_version_label(enabled=False), policy.PROMPT_VERSION + '-nd')
        body_a, body_b = system_policy_body(enabled=True), system_policy_body(enabled=False)
        self.assertIn('task_dispatch', body_a)
        self.assertNotIn('task_dispatch', body_b)
        # 正文其余逐字相同：B 臂 = A 臂去掉派发一句
        self.assertEqual(body_b, SYSTEM_POLICY_BODY.replace(policy._DISPATCH_CLAUSE, '', 1))

    def test_env_flag_parses_off_values(self):
        import os
        old = os.environ.get('SMARTLECT_DISPATCH_ENABLED')
        try:
            for raw in ('false', '0', 'off', 'NO'):
                os.environ['SMARTLECT_DISPATCH_ENABLED'] = raw
                self.assertFalse(policy.dispatch_enabled())
            for raw in ('true', '1', 'yes', ''):
                os.environ['SMARTLECT_DISPATCH_ENABLED'] = raw
                self.assertTrue(policy.dispatch_enabled())
            del os.environ['SMARTLECT_DISPATCH_ENABLED']
            self.assertTrue(policy.dispatch_enabled())  # 默认开
        finally:
            if old is None:
                os.environ.pop('SMARTLECT_DISPATCH_ENABLED', None)
            else:
                os.environ['SMARTLECT_DISPATCH_ENABLED'] = old


if __name__ == '__main__':
    unittest.main()
