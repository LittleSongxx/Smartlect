"""Homepage A/B uses StrategyStore control/treatment; treatment must call semantic_rerank."""
from types import SimpleNamespace
import unittest

from smartlect.recommendation.service import RecommendationService
from smartlect.recommendation.store import DEFAULT_STRATEGIES
from test_recommendation import FakeCommerce, FakeStrategies


class HomepageAbWiringTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(subject_type='user', actor_id='alice', execution_scope_id='isolated',
                                     permissions=('shopping:read',))
        self.scope = {'include': ['content', 'popular', 'new', 'paired', 'seed'], 'exclude': ['outside']}
        self.commerce = FakeCommerce()

    async def test_control_does_not_enter_semantic_rerank(self):
        called = []

        async def rerank(payload):
            called.append(payload)
            return {'sku_keys': [item['sku_key'] for item in payload['candidates']]}

        result = await RecommendationService(self.commerce, FakeStrategies('rules-v1')).recommend(
            self.actor, {'query': '轻便键盘', 'limit': 4}, seed_product_id='seed',
            product_scope=self.scope, semantic_rerank=rerank)
        self.assertEqual(result['ranking_mode'], 'rule')
        self.assertEqual(called, [])

    async def test_treatment_walks_rerank_and_differs_from_control(self):
        called = []

        async def reverse(payload):
            called.append(True)
            keys = [item['sku_key'] for item in payload['candidates']]
            return {'sku_keys': list(reversed(keys))}

        control = await RecommendationService(self.commerce, FakeStrategies('rules-v1')).recommend(
            self.actor, {'query': '轻便键盘', 'limit': 4}, seed_product_id='seed',
            product_scope=self.scope, semantic_rerank=reverse)
        treatment = await RecommendationService(FakeCommerce(), FakeStrategies('content-v1')).recommend(
            self.actor, {'query': '轻便键盘', 'limit': 4}, seed_product_id='seed',
            product_scope=self.scope, semantic_rerank=reverse)
        self.assertEqual(control['ranking_mode'], 'rule')
        self.assertEqual(treatment['ranking_mode'], 'content_llm')
        self.assertTrue(called)
        self.assertNotEqual([item['sku_key'] for item in control['items']],
                            [item['sku_key'] for item in treatment['items']])

    async def test_treatment_rerank_failure_falls_back_without_raising(self):
        async def boom(payload):
            raise RuntimeError('semantic_rerank_unavailable')

        result = await RecommendationService(self.commerce, FakeStrategies('content-v1')).recommend(
            self.actor, {'query': '轻便键盘', 'limit': 4}, seed_product_id='seed',
            product_scope=self.scope, semantic_rerank=boom)
        self.assertEqual(result['ranking_mode'], 'content_rule_fallback')
        self.assertEqual(result['diagnostics']['rerank_error'], 'semantic_rerank_unavailable_or_invalid')
        self.assertTrue(result['items'])

    def test_strategy_store_keeps_control_and_treatment(self):
        self.assertEqual(DEFAULT_STRATEGIES['rules-v1']['ranking'], 'rule')
        self.assertEqual(DEFAULT_STRATEGIES['content-v1']['ranking'], 'content')


if __name__ == '__main__':
    unittest.main()
