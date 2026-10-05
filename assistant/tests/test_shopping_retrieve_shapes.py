"""ShoppingRetrieve 形状回归（评测-修复循环的失败形状固化为永久测试）。

覆盖 v16→v18 各官方 run 定位的真实失败形状：合法空集不伪救援（d-13/64）、
词表惰性过滤（h4-04 范畴词）、发布门污染剥离之外 retrieval 层的使命合并行为。
FakeCommerce 按 Java ProductInternalService.snapshotBatch/searchOnSale 的
真实字段契约构造（product.status int / sku.price 元 / propertyValueIds '-'拼接）。
"""
import asyncio
import json
import unittest
from pathlib import Path

from smartlect.auth import ActorContext
from smartlect.catalog_gate import RecommendationRequest
from smartlect.shopping_mission import empty_mission
from smartlect.shopping_retrieve import ShoppingRetrieve

CATALOG = json.loads((Path(__file__).resolve().parents[2] / 'evals/quality-v2/shopping/catalog-snapshot.json').read_text())


def build_world():
    products, skus, values, stocks = [], [], [], []
    for s in CATALOG['skus']:
        pid, digest = s['product_id'], 'h' + s['sku_key'].split(':')[-1]
        products.append({'productId': pid, 'productName': s['productName'], 'status': s['status'],
                         'categoryId': s['categoryId'], 'catalogScope': 'store'})
        skus.append({'productId': pid, 'propertyValueIdHash': digest,
                     'propertyValueIds': 'v' + s['sku_key'].replace(':', '_').replace('-', ''),
                     'price': f"{s['price_cents'] / 100:.2f}", 'sort': 1})
        values.append({'productId': pid, 'propertyValueId': 'v' + s['sku_key'].replace(':', '_').replace('-', ''),
                       'propertyName': '规格', 'propertyValue': s['specification']})
        stocks.append({'productId': pid, 'propertyValueIdHash': digest, 'stock': s['stock']})
    return products, skus, values, stocks


class FakeCommerce:
    def __init__(self):
        self.products, self.skus, self.values, self.stocks = build_world()
        self.by_id = {p['productId']: p for p in self.products}
        self.sku_by_pid = {}
        for sku, value in zip(self.skus, self.values):
            self.sku_by_pid.setdefault(sku['productId'], []).append((sku, value))

    async def request(self, service, path, data=None, **_):
        data = data or {}
        if path.endswith('/searchOnSale'):
            keyword, rows = data.get('keyword') or '', []
            max_c = data.get('maxPriceCents')
            for pid, items in self.sku_by_pid.items():
                product = self.by_id[pid]
                if product['status'] != 1:
                    continue
                if max_c is not None and float(items[0][0]['price']) * 100 > float(max_c):
                    continue
                if keyword and keyword not in product['productName'] and not any(
                        keyword in v['propertyValue'] for _, v in items):
                    continue
                rows.append({'productId': pid})
            return rows[: data.get('limit', 20)]
        if path.endswith('/snapshotBatch'):
            ids = data.get('productIds') or []
            return {'products': [self.by_id[i] for i in ids if i in self.by_id],
                    'skus': [sku for pid in ids for sku, _ in self.sku_by_pid.get(pid, [])],
                    'propertyValues': [v for pid in ids for _, v in self.sku_by_pid.get(pid, [])],
                    'totalStocks': {}}
        if path.endswith('/getBatch'):
            out = []
            for row in data:
                match = next((s for s in self.stocks
                              if s['productId'] == row['productId'] and s['propertyValueIdHash'] == row['propertyValueIdHash']), None)
                if match:
                    out.append(match)
            return out
        raise AssertionError('unexpected path ' + path)


def run(coro):
    return asyncio.run(coro)


class RetrieveShapes(unittest.TestCase):
    def setUp(self):
        self.retrieve = ShoppingRetrieve(FakeCommerce())
        self.actor = ActorContext(subject_type='user', actor_id='u', permissions=('shopping:read',), session_id='s')
        self.scope = {'include': None, 'exclude': []}

    def recommend(self, params, mission=None):
        request = RecommendationRequest.model_validate(params)
        return run(self.retrieve.recommend(self.actor, request.model_dump(),
                                           mission=mission or empty_mission(),
                                           product_scope=self.scope))

    def test_honest_empty_when_only_match_over_budget(self):
        """d-13/d-64：唯一满足词的 SKU 超预算 → 诚实空集，不得伪救援成泛族。"""
        result = self.recommend({'query': '人体工学椅', 'required_terms': ['人体工学'], 'max_price_cents': 30000})
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics']['empty_reason'], 'hard_constraint_unsatisfied')

    def test_split_terms_over_budget_stay_honest(self):
        """d-64 变体：required 拆词（游戏+耳机）且唯一命中超预算 → 仍诚实空集。"""
        result = self.recommend({'query': '游戏耳机', 'required_terms': ['游戏', '耳机'], 'max_price_cents': 30000})
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics']['empty_reason'], 'hard_constraint_unsatisfied')

    def test_inert_category_term_relaxed(self):
        """h4-04：必含词全池零命中（音频设备）是词表错配 → 剔除并放宽。"""
        result = self.recommend({'query': '游戏耳机', 'required_terms': ['游戏', '音频设备']})
        names = [item['productName'] for item in result['items']]
        self.assertIn('游戏耳机', names)
        self.assertEqual(result['diagnostics']['route_errors'].get('required_terms_inert'), ['音频设备'])

    def test_inert_gift_term_relaxed_with_budget(self):
        """h4-06：礼物=词表错配；剩余硬约束（预算+排除）把候选收敛到正确集合。"""
        result = self.recommend({'query': '键盘 鼠标', 'required_terms': ['礼物'],
                                 'excluded_terms': ['黑色'], 'max_price_cents': 20000})
        self.assertTrue(result['items'])
        for item in result['items']:
            self.assertNotIn('黑色', item['specification'])

    def test_mesh_chair_within_budget_found(self):
        """d-68：网布真实命中（人体工学椅/网布）→ 正常返回，价格门内。"""
        result = self.recommend({'query': '网布椅', 'required_terms': ['网布'], 'max_price_cents': 90000})
        names = [item['productName'] for item in result['items']]
        self.assertIn('人体工学椅', names)

    def test_metal_keyboard_price_window_found(self):
        """d-76：多规格商品（金属机械键盘 399/459）价格窗 300–450 → 黑款 399 必须命中。"""
        result = self.recommend({'query': '金属键盘', 'required_terms': ['金属'],
                                 'min_price_cents': 30000, 'max_price_cents': 45000})
        names = [item['productName'] + '/' + item['specification'] for item in result['items']]
        self.assertTrue(any('金属' in n for n in names), names)


    def test_catalog_phrase_query_matches_only_family(self):
        """F2 空白归一：query 'USB 线' 命中 'USB线'。"""
        result = self.recommend({'query': 'USB 线'})
        self.assertTrue(result['items'])
        for item in result['items']:
            self.assertIn('USB线', item['productName'])


if __name__ == '__main__':
    unittest.main()
