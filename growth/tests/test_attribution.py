import base64
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import unittest

from smartlect.attribution import context_token, event_metadata, select_attribution
from smartlect.events import parse_event
from test_events import outcome


class AttributionContractTests(unittest.TestCase):
    def touch(self, kind, at, identifier='a', **fields):
        return {'touch_id': identifier, 'kind': kind, 'occurred_at': at, 'product_id': None, 'sku_key': None,
                'traffic_channel': 'NATURAL' if kind == 'NATURAL_VISIT' else 'AD_SIMULATED', **fields}

    def test_ad_a_b_and_independent_sku_click_windows_are_inclusive(self):
        now = datetime(2026, 9, 9)
        ad = self.touch('AD_CLICK', now - timedelta(days=7), campaign_id='campaign-A', product_id='B')
        rec = self.touch('REC_CLICK', now - timedelta(hours=24), 'b', product_id='B', sku_key='B-standard',
                         recommendation_id='recommend-B', assignment_id='assignment', strategy_version='rules-v1')
        natural = self.touch('NATURAL_VISIT', now, 'c')
        result = select_attribution([ad, rec, natural], now, 'B', 'B-standard')
        self.assertEqual((result['category'], result['campaign_id'], result['recommendation_id'], result['traffic_channel']),
                         ('AD_ATTRIBUTED', 'campaign-A', 'recommend-B', 'NATURAL'))
        mismatched = self.touch('AD_CLICK', now - timedelta(days=1), 'd', campaign_id='campaign-A', product_id='A')
        self.assertIsNone(select_attribution([mismatched, rec, natural], now, 'B', 'B-standard')['campaign_id'])
        for delta in (timedelta(microseconds=1), timedelta(days=1)):
            aged = select_attribution([ad, rec, natural], now + delta, 'B', 'B-standard')
            self.assertEqual(aged['category'], 'NATURAL_VERIFIED')
            self.assertIsNone(aged['recommendation_click_id'])

    def test_future_touch_cross_sku_and_impression_cannot_be_click_conversion(self):
        now = datetime(2026, 9, 9)
        future = self.touch('AD_CLICK', now + timedelta(microseconds=1))
        wrong = self.touch('REC_CLICK', now, 'b', product_id='B', sku_key='other-size')
        impression = self.touch('REC_IMPRESSION', now, 'c', product_id='B', sku_key='B-standard')
        result = select_attribution([future, wrong, impression], now, 'B', 'B-standard')
        self.assertEqual(result['category'], 'UNKNOWN_CONTEXT')
        self.assertEqual(result['recommendation_assist_id'], 'c')
        self.assertIsNone(result['recommendation_click_id'])
        tied = [self.touch('AD_CLICK', now, x, campaign_id=x, product_id='B') for x in ('b', 'a')]
        self.assertEqual(select_attribution(tied, now, 'B', 'B-standard')['campaign_id'], 'b')

    def test_signed_context_and_bad_optional_source_do_not_change_money(self):
        row = {'context_id': 'a'*32, 'snapshot_version': 1, 'snapshot_hash': 'b'*64, 'user_id': 'alice',
               'execution_scope_id': 'store', 'captured_at': datetime(2026,9,9), 'expires_at': datetime(2026,9,9,0,5)}
        secret = 'synthetic-context-test-secret-only-1234567890'
        encoded, signature = context_token(row, secret).split('.')
        self.assertEqual(signature, hmac.new(secret.encode(), ('smartlect-attribution-v1:'+encoded).encode(), hashlib.sha256).hexdigest())
        payload = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        self.assertEqual(payload['expires_at']-payload['issued_at'], 300)
        self.assertEqual(payload['snapshot_hash'], 'b'*64)
        self.assertIsNone(context_token(row, None))
        event = outcome(amount='0.29')
        event['payload']['attribution'] = {'contextStatus': 'VERIFIED', 'contextId': 'forged'}
        self.assertEqual(event_metadata(event)['contextStatus'], 'UNKNOWN_CONTEXT')
        self.assertEqual(parse_event(event, 2)['amount_cents'], 29)


if __name__ == '__main__':
    unittest.main()
