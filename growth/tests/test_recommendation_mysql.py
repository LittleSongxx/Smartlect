"""Serial opt-in checks for persisted assignment/configuration; no real model calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import asyncio
import os
from types import SimpleNamespace
import unittest
import uuid

from smartlect.recommendation.service import RecommendationService
from smartlect.recommendation.store import DEFAULT_STRATEGIES, StrategyStore
from smartlect.state import StateError
from test_recommendation import FakeCommerce
import test_ledger_mysql as ledger_tests


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS') == '1', 'set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL')
class RecommendationMySQLTests(unittest.TestCase):
    setUpClass = classmethod(ledger_tests.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(ledger_tests.LedgerMySQLTests.tearDownClass.__func__)

    def setUp(self):
        self.scope = 'rec-' + uuid.uuid4().hex
        self.user = SimpleNamespace(subject_type='user', actor_id='user', execution_scope_id=self.scope, permissions=('shopping:read',))
        self.visitor = SimpleNamespace(subject_type='visitor', actor_id='visitor', execution_scope_id=self.scope, permissions=('shopping:read',))
        self.admin = SimpleNamespace(subject_type='merchant', actor_id='admin', execution_scope_id=self.scope, permissions=('admin:legacy',))
        self.store = StrategyStore(self.connect)

    def test_concurrent_assignment_restart_and_trusted_browser_binding_do_not_jump_group(self):
        subject = 'trusted-browser-' + uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as executor:
            assignments = list(executor.map(lambda _: self.store.assign(self.visitor, subject_key=subject), range(2)))
        self.assertEqual(assignments[0], assignments[1])
        restarted = StrategyStore(self.connect)
        self.assertEqual(restarted.assign(self.user, subject_key=subject), assignments[0])
        self.assertEqual(restarted.assign(self.visitor, subject_key=subject), assignments[0])
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS count FROM recommendation_assignment WHERE execution_scope_id=%s', (self.scope,))
            self.assertEqual(cursor.fetchone()['count'], 1)
            cursor.execute('SELECT salt FROM recommendation_experiment WHERE execution_scope_id=%s', (self.scope,))
            salt = cursor.fetchone()['salt']
        restarted.assign(self.user, subject_key=subject)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT salt FROM recommendation_experiment WHERE execution_scope_id=%s', (self.scope,))
            self.assertEqual(cursor.fetchone()['salt'], salt)
        self.user.execution_scope_id += '-separate'
        self.assertNotEqual(restarted.assign(self.user, subject_key=subject)['assignment_id'], assignments[0]['assignment_id'])

    def test_strategy_versions_are_immutable_and_configuration_changes_actual_business_path(self):
        initial = self.store.assign(self.user)
        custom = deepcopy(DEFAULT_STRATEGIES['content-v1'])
        custom['weights']['content'] = 10
        self.store.put_strategy(self.admin, 'content-custom-v1', custom)
        self.assertEqual(self.store.put_strategy(self.admin, 'content-custom-v1', custom)['config'], custom)
        with self.assertRaisesRegex(StateError, 'strategy_version_immutable'):
            self.store.put_strategy(self.admin, 'content-custom-v1', DEFAULT_STRATEGIES['rules-v1'])
        configured = self.store.configure_experiment(self.admin, control_version='rules-v1', treatment_version='rules-v1', expected_revision=1)
        commerce = FakeCommerce()
        product_scope = {'include': ['content', 'popular', 'new', 'paired', 'seed'], 'exclude': ['outside']}
        service = RecommendationService(commerce, self.store)
        rule = asyncio.run(service.recommend(self.user, {'query': '轻便键盘'}, product_scope=product_scope))
        self.store.configure_experiment(self.admin, control_version='content-custom-v1', treatment_version='content-custom-v1',
                                        expected_revision=configured['revision'])
        content = asyncio.run(service.recommend(self.user, {'query': '轻便键盘'}, product_scope=product_scope))
        self.assertEqual((rule['ranking_mode'], content['ranking_mode']), ('rule', 'content_rule'))
        self.assertEqual((rule['items'][0]['productId'], content['items'][0]['productId']), ('popular', 'content'))
        self.assertEqual(rule['assignment_id'], content['assignment_id'])
        self.assertEqual(initial['group'], content['assignment']['group'])
        self.assertEqual(content['strategy_version'], 'content-custom-v1')
        self.assertEqual(rule['strategy_version'], 'rules-v1')
        with self.assertRaisesRegex(StateError, 'experiment_revision_conflict'):
            self.store.configure_experiment(self.admin, control_version='rules-v1', treatment_version='rules-v1', expected_revision=1)
        with self.assertRaisesRegex(StateError, 'permission_denied'):
            self.store.put_strategy(self.user, 'forbidden', custom)


if __name__ == '__main__':
    unittest.main()
