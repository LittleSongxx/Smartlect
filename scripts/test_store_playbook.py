"""Pure local checks for the default-store playbook; no services or databases."""
import unittest
from datetime import datetime, timedelta, timezone

import seed_store_playbook as playbook


class StorePlaybookTests(unittest.TestCase):
    def test_ids_are_stable_hex_and_do_not_include_policy_actions(self):
        first = playbook.playbook_id('campaign', '065293686460191')
        self.assertEqual(first, playbook.playbook_id('campaign', '065293686460191'))
        self.assertNotEqual(first, playbook.playbook_id('creative', '065293686460191'))
        self.assertEqual(len(first), 32)
        self.assertTrue(int(first, 16) >= 0)
        envelope = playbook.grant_envelope(['065293686460191'], 10000)
        self.assertNotIn('set_recommendation_policy', envelope['allowed_action_types'])
        self.assertEqual(set(envelope['allowed_action_types']), set(playbook.ALLOWED_ACTIONS))

    def test_playbook_does_not_write_explicit_preferences_and_expands_the_ad_pool(self):
        self.assertFalse(hasattr(playbook, 'PREFERENCES'))
        self.assertGreaterEqual(len(playbook.PREFERRED_PRODUCTS), 8)
        self.assertLessEqual(len(playbook.PREFERRED_PRODUCTS), 12)
        self.assertEqual(len(playbook.PERSONAS), 4)
        self.assertTrue(all(row['user_index'] in range(4) for row in playbook.PERSONAS))

    def test_catalog_picker_skips_fixture_skus_and_keeps_one_stable_sku_per_product(self):
        items = [
            {'product_id': '910000000000000', 'sku_key': 'fixture', 'stock': 99, 'sku_name': '标准'},
            {'product_id': '930000000000001', 'sku_key': 'scenario', 'stock': 99, 'sku_name': '标准'},
            {'product_id': '065293686460191', 'sku_key': 'snow-b', 'stock': 10, 'sku_name': '雪饼B', 'product_name': '旺旺雪饼'},
            {'product_id': '065293686460191', 'sku_key': 'snow-a', 'stock': 50, 'sku_name': '雪饼A', 'product_name': '旺旺雪饼'},
            {'product_id': '622491960431656', 'sku_key': 'toy', 'stock': 8, 'sku_name': '公仔', 'product_name': '公仔'},
            {'product_id': '111111111111111', 'sku_key': 'extra-z', 'stock': 3, 'sku_name': '其它', 'product_name': '其它'},
            {'product_id': '222222222222222', 'sku_key': 'gone', 'stock': 0, 'sku_name': '售罄', 'product_name': '售罄'},
        ]
        picked = playbook.pick_catalog_skus(items, min_count=2, max_count=3)
        self.assertEqual([row['product_id'] for row in picked],
                         ['065293686460191', '622491960431656', '111111111111111'])
        self.assertEqual(picked[0]['sku_key'], 'snow-a')
        self.assertTrue(all(not playbook.is_isolated_product(row['product_id']) for row in picked))
        with self.assertRaises(AssertionError):
            playbook.pick_catalog_skus([items[0], items[1]], min_count=2)

    def test_planned_resources_reuse_an_existing_campaign_sku(self):
        skus = [{'product_id': '065293686460191', 'sku_key': 'new-hash', 'sku_name': '新规格',
                 'product_name': '旺旺雪饼', 'stock': 9}]
        campaign_id = playbook.playbook_id('campaign', '065293686460191')
        snapshot = {'campaigns': [{'campaign_id': campaign_id, 'sku_key': 'old-hash'}]}
        planned = playbook.planned_resources(skus, snapshot)
        self.assertEqual(planned[0]['sku_key'], 'old-hash')
        self.assertEqual(planned[0]['campaign_id'], campaign_id)

    def test_grant_versions_only_cover_product_scope_and_cap_counts_all_campaigns(self):
        snapshot = {
            'account': {'spent_cents': 40, 'budget_cap_cents': 100},
            'campaigns': [
                {'campaign_id': 'c1', 'owner_id': 'admin', 'product_id': 'p1', 'version': 2, 'budget_cents': 1000},
                {'campaign_id': 'c2', 'owner_id': 'admin', 'product_id': '910000000000000', 'version': 3, 'budget_cents': 100},
                {'campaign_id': 'c3', 'owner_id': 'other', 'product_id': 'p1', 'version': 9, 'budget_cents': 50},
            ],
            'creatives': [
                {'creative_id': 'cr1', 'owner_id': 'admin', 'campaign_id': 'c1', 'version': 4},
                {'creative_id': 'cr2', 'owner_id': 'admin', 'campaign_id': 'c2', 'version': 5},
            ],
        }
        campaigns, creatives = playbook.grant_versions(snapshot, ['p1'], 'admin')
        self.assertEqual(campaigns, {'c1': 2})
        self.assertEqual(creatives, {'cr1': 4})
        self.assertEqual(playbook.budget_cap_cents(snapshot, extra=1000), 10000)
        self.assertEqual(playbook.budget_cap_cents({
            'account': {'spent_cents': 40},
            'campaigns': [{'budget_cents': 20000}, {'budget_cents': 100}],
        }, extra=1000), 21100)

    def test_delivery_ready_requires_active_catalog_ads_and_rejects_fixture_competition(self):
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        planned = [{'campaign_id': 'c1', 'creative_id': 'cr1', 'product_id': 'p1'}]
        grant = {'grant_id': 'g1', 'envelope': {'product_scope': ['p1']},
                 'valid_until': (now + timedelta(days=30)).isoformat(), 'revoked_at': None}
        snapshot = {
            'account': {'grant_id': 'g1'},
            'grants': [grant],
            'campaigns': [{'campaign_id': 'c1', 'owner_id': 'admin', 'product_id': 'p1', 'status': 'ACTIVE'}],
            'creatives': [{'creative_id': 'cr1', 'status': 'ACTIVE'}],
        }
        self.assertTrue(playbook.playbook_delivery_ready(snapshot, planned, 'admin', now=now))
        snapshot['campaigns'].append(
            {'campaign_id': 'c-fix', 'owner_id': 'admin', 'product_id': '910000000000000', 'status': 'ACTIVE'})
        self.assertFalse(playbook.playbook_delivery_ready(snapshot, planned, 'admin', now=now))
        snapshot['campaigns'].pop()
        grant['valid_until'] = (now - timedelta(hours=1)).isoformat()
        self.assertFalse(playbook.grant_is_current(snapshot, ['p1'], now=now))

    def test_plaza_rush_coupon_covers_now_and_is_idempotent_by_name(self):
        now = datetime(2026, 9, 11, 12, 0, tzinfo=playbook.SHANGHAI)
        payload = playbook.plaza_rush_coupon_payload(now)
        self.assertEqual(payload['couponName'], playbook.PLAYBOOK_COUPON_NAME)
        self.assertEqual(payload['couponType'], 3)
        self.assertEqual(payload['rushingstatus'], 1)
        self.assertEqual(payload['rushingStartTime'], '2026-09-11 11:00:00')
        self.assertEqual(payload['validEndTime'], '2027-09-11 12:00:00')
        rows = [{'couponName': '其它券'}, {'couponName': playbook.PLAYBOOK_COUPON_NAME, 'couponId': 'c1'}]
        self.assertEqual(playbook.existing_plaza_coupon(rows)['couponId'], 'c1')
        self.assertIsNone(playbook.existing_plaza_coupon([]))

    def test_walkthrough_is_skipped_only_when_a_paid_order_and_open_ticket_already_exist(self):
        done = {'walkthrough': {'payment_status': 'PAID'}, 'ticket': {'status': 'TAKEN_OVER'}}
        self.assertTrue(playbook.should_skip_walkthrough(True, False, {}))
        self.assertFalse(playbook.should_skip_walkthrough(False, True, done))
        self.assertTrue(playbook.should_skip_walkthrough(False, False, done))
        self.assertFalse(playbook.should_skip_walkthrough(False, False, {'walkthrough': {'payment_status': 'PAID'}}))
        self.assertFalse(playbook.should_skip_walkthrough(False, False, {}))


if __name__ == '__main__':
    unittest.main()
