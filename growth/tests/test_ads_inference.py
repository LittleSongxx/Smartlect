"""Behavior-derived inferred preferences; no MySQL."""
from types import SimpleNamespace
from copy import deepcopy
import unittest
from unittest.mock import Mock

from smartlect.ads.inference import derive_inferred_preferences, sync_behavior_preferences
from smartlect.commerce import CommerceError


SNACK = {
    'productId': 'snack-1',
    'productName': '旺旺雪饼厚烧海苔原味零食膨化休闲食品饼干糕点',
    'categoryId': '20022',
}


class FakeCommerce:
    def __init__(self, *, browse=None, orders=None, products=None, error=None):
        self.browse = browse or []
        self.orders = orders or []
        self.products = products or {}
        self.error = error
        self.calls = []

    async def request(self, service, path, *, data=None, **kwargs):
        self.calls.append((service, path, deepcopy(data)))
        if self.error:
            raise self.error
        if path.endswith('/browseHistoryIds'):
            return list(self.browse)
        if path.endswith('/listOrders'):
            return deepcopy(self.orders)
        if path.endswith('/snapshotBatch'):
            keys = data['productIds']
            return {'products': [deepcopy(self.products[key]) for key in keys if key in self.products]}
        raise AssertionError('Unexpected Java endpoint ' + path)


class Memory:
    def __init__(self, *, explicit=None):
        self.explicit = set(explicit or ())
        self.calls = []
        self.rows = {key: {'source': 'explicit', 'value': ['手工']} for key in self.explicit}

    def apply_behavior_inference(self, actor, values, *, product_ids=()):
        self.calls.append((dict(values), list(product_ids)))
        written = []
        for key, value in values.items():
            if key in self.explicit:
                continue
            self.rows[key] = {'source': 'inferred', 'value': value}
            written.append(key)
        return written


class AdsInferenceTests(unittest.IsolatedAsyncioTestCase):
    def test_snack_browse_derives_snack_likes_and_category(self):
        derived = derive_inferred_preferences([SNACK])
        self.assertIn('零食', derived['likes'])
        self.assertIn('零食', derived['categories'])
        self.assertIn('零食', derived['purpose'])

    def test_empty_history_derives_nothing(self):
        self.assertEqual(derive_inferred_preferences([]), {})

    async def test_sync_writes_inferred_likes_from_browse_snapshot(self):
        commerce = FakeCommerce(browse=['snack-1'], products={'snack-1': SNACK})
        memory = Memory()
        actor = SimpleNamespace(subject_type='user', actor_id='alice')
        written = await sync_behavior_preferences(commerce, memory, actor)
        self.assertIn('likes', written)
        self.assertIn('零食', memory.calls[0][0]['likes'])
        self.assertEqual(memory.calls[0][1], ['snack-1'])

    async def test_sync_does_not_overwrite_explicit_keys(self):
        commerce = FakeCommerce(browse=['snack-1'], products={'snack-1': SNACK})
        memory = Memory(explicit={'likes'})
        actor = SimpleNamespace(subject_type='user', actor_id='alice')
        await sync_behavior_preferences(commerce, memory, actor)
        self.assertEqual(memory.rows['likes'], {'source': 'explicit', 'value': ['手工']})
        self.assertEqual(memory.rows['likes']['source'], 'explicit')

    async def test_sync_swallows_commerce_errors(self):
        commerce = FakeCommerce(error=CommerceError('down'))
        memory = Memory()
        actor = SimpleNamespace(subject_type='user', actor_id='alice')
        self.assertEqual(await sync_behavior_preferences(commerce, memory, actor), [])
        self.assertEqual(memory.calls, [])

    async def test_visitors_are_not_inferred(self):
        memory = Mock()
        actor = SimpleNamespace(subject_type='visitor', actor_id='guest')
        self.assertEqual(await sync_behavior_preferences(FakeCommerce(), memory, actor), [])
        memory.apply_behavior_inference.assert_not_called()


if __name__ == '__main__':
    unittest.main()
