"""轮级 token 预算分层（组件 12）：档位判定与提示注入的确定性契约。"""
import unittest
from unittest.mock import patch

from smartlect.agents.shopping.policy import TURN_BUDGET_HINTS, turn_budget_tier


class TurnBudgetTierTests(unittest.TestCase):
    def test_tier_thresholds(self):
        budget = 100000
        cases = [(0, 'main'), (49999, 'main'), (50000, 'lite'), (79999, 'lite'),
                 (80000, 'minimal'), (94999, 'minimal'), (95000, 'fallback'),
                 (999999, 'fallback')]
        for used, expected in cases:
            with self.subTest(used=used):
                self.assertEqual(turn_budget_tier(used, budget), expected)

    def test_zero_budget_disables_tiering(self):
        # SMARTLECT_TURN_TOKEN_BUDGET=0 关闭分层：恒 main，不干预任何行为
        self.assertEqual(turn_budget_tier(999999999, 0), 'main')
        self.assertEqual(turn_budget_tier(0, 0), 'main')

    def test_none_and_negative_used_are_main(self):
        self.assertEqual(turn_budget_tier(None, 1000), 'main')
        self.assertEqual(turn_budget_tier(-5, 1000), 'main')

    def test_hints_exist_for_lite_and_minimal_only(self):
        # main 不提示；fallback 不提示（直接抛 BudgetExceeded 走降级链）
        self.assertEqual(set(TURN_BUDGET_HINTS), {'lite', 'minimal'})
        for text in TURN_BUDGET_HINTS.values():
            self.assertIn('收口', text)

    def test_env_budget_follows_configuration(self):
        with patch.dict('os.environ', {'SMARTLECT_TURN_TOKEN_BUDGET': '1000'}):
            import importlib
            import smartlect.agents.shopping.policy as policy
            importlib.reload(policy)
            self.assertEqual(policy.TURN_TOKEN_BUDGET, 1000)
            self.assertEqual(policy.turn_budget_tier(900, None), 'minimal')
            self.assertEqual(policy.turn_budget_tier(600, None), 'lite')
        import importlib
        import smartlect.agents.shopping.policy as policy
        importlib.reload(policy)


if __name__ == '__main__':
    unittest.main()
