"""Closed shopping-slot extractor: cover, merge order, and reversal."""
import unittest

from smartlect.shopping_mission import (empty_mission, extract_mission, has_hard_constraints,
                                        ground_tool_params, merge_mission, mission_retrieve_params, requirement_slots,
                                        retrieval_variants, retrieve_matches_mission, shopping_request,
                                        shopping_turn_changed, _unique)


class ShoppingMissionTests(unittest.TestCase):
    def test_extracts_budget_exclusion_comparison_and_reversal(self):
        extracted = extract_mission('预算200元，不要红色，键盘和鼠标比较一下')
        self.assertEqual(extracted['budget_max_cents'], 20000)
        self.assertEqual(extracted['excluded_terms'], ['红色'])
        self.assertEqual(extracted['comparison_targets'], ['键盘', '鼠标'])
        self.assertTrue(extracted['comparison_required'])
        self.assertEqual(extracted['required_terms'], [])
        reversed_turn = extract_mission('其实红色可以，可以要金属')
        self.assertEqual(reversed_turn['reversed_terms'], ['红色', '金属'])
        self.assertEqual(extract_mission('红色也行')['reversed_terms'], ['红色'])

    def test_tool_args_beat_utterance_and_new_budget_replaces_old(self):
        previous = merge_mission(empty_mission(), extract_mission('预算100元，不要红色'))
        self.assertEqual(previous['budget_max_cents'], 10000)
        extracted = extract_mission('预算300元，不要塑料')
        merged = merge_mission(previous, extracted, {'budget_max_cents': 15000})
        self.assertEqual(merged['budget_max_cents'], 15000)
        self.assertEqual(merged['excluded_terms'], ['红色', '塑料'])
        reversed_merge = merge_mission(merged, extract_mission('其实红色可以'))
        self.assertEqual(reversed_merge['excluded_terms'], ['塑料'])
        self.assertEqual(reversed_merge['budget_max_cents'], 15000)

    def test_preference_avoid_is_not_a_hard_shopping_slot(self):
        request = shopping_request({'query': '键盘'}, empty_mission())
        self.assertEqual(request['excluded_terms'], [])
        self.assertFalse(has_hard_constraints(request, empty_mission()))
        mission = merge_mission(empty_mission(), extract_mission('不要红色'))
        constrained = shopping_request({'query': '键盘'}, mission)
        self.assertEqual(constrained['excluded_terms'], ['红色'])
        self.assertTrue(has_hard_constraints(constrained, mission))

    def test_variants_are_query_required_terms_and_single_target(self):
        mission = {'comparison_targets': ['鼠标'], 'comparison_required': True}
        variants = retrieval_variants({'query': '键盘', 'required_terms': ['轻便']}, mission)
        self.assertEqual(variants, ['键盘', '轻便', '鼠标'])
        self.assertEqual(retrieval_variants({'query': ''}, empty_mission()), [])

    def test_requirement_slots_are_closed_and_do_not_harvest_purpose_words(self):
        self.assertEqual(requirement_slots('要金属键盘'), ['金属', '键盘'])
        self.assertEqual(requirement_slots('100元以内的金属机械键盘'), ['金属', '键盘'])
        self.assertEqual(requirement_slots('办公用、200元以内的键盘'), ['键盘'])
        self.assertEqual(requirement_slots('不要塑料'), [])
        self.assertEqual(requirement_slots('可以要金属'), [])
        self.assertEqual(requirement_slots('只要轻便键盘黑色这款'), ['轻便', '黑色'])
        self.assertEqual(requirement_slots('50元以内的USB线'), ['USB'])
        self.assertEqual(requirement_slots('预算800元的键盘'), ['键盘'])
        self.assertEqual(requirement_slots('不要塑料的键盘'), [])
        self.assertEqual(requirement_slots('其实预算150元'), [])
        self.assertEqual(requirement_slots('办公用、预算200元的键盘'), ['键盘'])
        carried = merge_mission(
            merge_mission(empty_mission(), extract_mission('预算800元的键盘'),
                          {'required_terms': requirement_slots('预算800元的键盘'), 'query': '键盘'}),
            extract_mission('其实预算150元'))
        self.assertEqual(carried['required_terms'], ['键盘'])
        self.assertEqual(carried['budget_max_cents'], 15000)
        self.assertEqual(carried['query'], '键盘')

    def test_query_stays_soft_and_retrieve_must_match_mission(self):
        previous = merge_mission(empty_mission(), {}, {'query': '键盘', 'budget_max_cents': 80000})
        follow = merge_mission(previous, extract_mission('其实预算150元'))
        self.assertEqual(follow['query'], '键盘')
        self.assertEqual(follow['budget_max_cents'], 15000)
        request = shopping_request({'max_price_cents': 15000}, follow)
        self.assertEqual(request['query'], '键盘')
        self.assertEqual(request['required_terms'], [])
        self.assertTrue(shopping_turn_changed(extract_mission('其实预算150元')))
        self.assertFalse(shopping_turn_changed(extract_mission('谢谢')))
        self.assertFalse(retrieve_matches_mission({}, follow))
        self.assertFalse(retrieve_matches_mission(
            {'max_price_cents': 80000, 'query': '键盘'}, follow))
        self.assertTrue(retrieve_matches_mission(
            {'max_price_cents': 15000, 'query': '键盘'}, follow))
        self.assertEqual(mission_retrieve_params(follow)['query'], '键盘')
        self.assertEqual(mission_retrieve_params(follow)['max_price_cents'], 15000)
        soft = shopping_request({}, merge_mission(empty_mission(), {}, {'query': '键盘'}))
        self.assertEqual(soft['query'], '键盘')
        self.assertFalse(has_hard_constraints(soft, merge_mission(empty_mission(), {}, {'query': '键盘'})))

    def test_extracts_category_floor_price_and_顿号_comparison(self):
        desk = extract_mission('desk类目200元以内')
        self.assertEqual(desk['category_id'], 'desk')
        self.assertEqual(desk['budget_max_cents'], 20000)
        self.assertEqual(extract_mission('300元以上的键盘')['min_price_cents'], 30000)
        three = extract_mission('比较轻便键盘、金属机械键盘和入门耳机')
        self.assertEqual(three['comparison_targets'], ['轻便键盘', '金属机械键盘', '入门耳机'])
        self.assertTrue(three['comparison_required'])
        mission = merge_mission(empty_mission(), desk)
        request = shopping_request({'query': 'desk'}, mission)
        self.assertEqual(request['category_id'], 'desk')
        self.assertEqual(request['max_price_cents'], 20000)

    def test_chinese_colloquial_price_and_category_shapes(self):
        # v11 shop-d-52..64: 以下/以下无货币/中文数字/区间、中文类目词、疑问词尾巴。
        audio = extract_mission('音频类两百以内的都看看')
        self.assertEqual(audio['category_id'], 'audio')
        self.assertEqual(audio['budget_max_cents'], 20000)
        self.assertEqual(extract_mission('300 块以下的游戏耳机')['budget_max_cents'], 30000)
        self.assertEqual(extract_mission('两百块以上的键盘有哪些')['min_price_cents'], 20000)
        window = extract_mission('50元到150元之间的键盘')
        self.assertEqual((window['min_price_cents'], window['budget_max_cents']), (5000, 15000))
        self.assertEqual(extract_mission('桌面这个类目都有什么，先看看')['category_id'], 'desk')
        self.assertEqual(requirement_slots('两百块以上的键盘有哪些'), ['键盘'])
        # 数量短语与数量区间绝不能被解析成价格。
        self.assertIsNone(extract_mission('买2到3个键盘')['budget_max_cents'])
        self.assertIsNone(extract_mission('推荐三个以内的耳机')['budget_max_cents'])
        self.assertEqual(extract_mission('帮我买6个桌面音箱')['quantity'], 6)
        metal = merge_mission(empty_mission(), extract_mission('要金属键盘'),
                              {'required_terms': requirement_slots('要金属键盘')})
        self.assertEqual(shopping_request({'query': '金属键盘'}, metal)['required_terms'], ['金属', '键盘'])
        incomplete = merge_mission(empty_mission(), extract_mission('只要缺货色的轻便键盘'),
                                   {'required_terms': _unique(['轻便', *requirement_slots('只要缺货色的轻便键盘')], 16)})
        self.assertIn('缺货', incomplete['required_terms'])
        self.assertIn('键盘', incomplete['required_terms'])


class GroundingAndBuyFrameTests(unittest.TestCase):
    def test_buy_frames_harvest_product_terms_with_quantifier_stripped(self):
        self.assertEqual(requirement_slots('帮我买6个桌面音箱，预算1000元'), ['桌面', '音箱'])
        self.assertEqual(requirement_slots('买键盘'), ['键盘'])
        self.assertEqual(requirement_slots('购买人体工学椅'), ['人体', '学椅'])
        self.assertEqual(requirement_slots('我想买一台台灯'), ['台灯'])

    def test_trailing_count_phrase_is_not_a_product_term(self):
        # Buy frames ending in count+measure with no noun must not backtrack the
        # quantity phrase into required_terms ("买一把"/"要买三个呢" poisoned every
        # retrieval in v11 shop-d-58 / sup-d-50 / shop-d-49 t1).
        self.assertEqual(requirement_slots('人体工学椅还有吗？我买一把'), [])
        self.assertEqual(requirement_slots('那我这次要买三个呢？'), [])
        self.assertEqual(requirement_slots('买一台'), [])
        self.assertEqual(requirement_slots('买键盘呢'), ['键盘'])
        self.assertEqual(requirement_slots('要两台音箱'), ['音箱'])

    def test_negated_and_interrogative_buy_stay_outside(self):
        self.assertEqual(requirement_slots('买不到键盘'), [])
        self.assertEqual(requirement_slots('灰色下架键盘也能买吗，按可售来'), [])
        self.assertEqual(requirement_slots('不买塑料的'), [])

    def test_markerless_amount_grounds_model_budget_declaration(self):
        # v12 shop-d-50: "300 买不到就 600 吧" - the marker-less raise must ground
        # the model's 60000 instead of letting the stale mission 30000 win.
        filtered, dropped = ground_tool_params(
            {'max_price_cents': 60000}, '300 买不到就 600 吧', {'budget_max_cents': 30000})
        self.assertEqual(filtered.get('max_price_cents'), 60000)
        self.assertNotIn('max_price_cents', dropped)
        filtered, dropped = ground_tool_params(
            {'max_price_cents': 60000}, '三百不行就六百吧', {'budget_max_cents': 30000})
        self.assertEqual(filtered.get('max_price_cents'), 60000)
        # Count frames never mention amounts, whatever the spacing.
        for utterance in ('帮我买 2 个键盘', '买2个键盘', '来三把人体工学椅'):
            filtered, dropped = ground_tool_params({'max_price_cents': 200}, utterance, {})
            self.assertIsNone(filtered.get('max_price_cents'), utterance)
        # Numbers the user never said stay dropped.
        filtered, dropped = ground_tool_params({'max_price_cents': 99000}, '预算300元', {})
        self.assertIsNone(filtered.get('max_price_cents'))

    def test_ground_tool_params_demotes_untraceable_hard_slots(self):
        mission = {'required_terms': ['金属'], 'category_id': None,
                   'budget_max_cents': 30000, 'min_price_cents': None,
                   'excluded_terms': ['塑料']}
        filtered, dropped = ground_tool_params(
            {'query': '音箱', 'required_terms': ['Type-C'], 'excluded_terms': ['塑料'],
             'category_id': 'desk', 'max_price_cents': 99900, 'quantity': 6,
             'excluded_product_ids': ['kb-plastic']},
            '帮我买6个桌面音箱，预算1000元', mission)
        self.assertEqual(filtered.get('category_id'), None)
        self.assertIsNone(filtered.get('max_price_cents'))
        self.assertEqual(dropped['category_id'], 'desk')
        self.assertEqual(dropped['max_price_cents'], 99900)
        self.assertEqual(dropped['required_terms'], ['Type-C'])  # not in this utterance
        self.assertEqual(filtered['excluded_terms'], ['塑料'])       # grounded in utterance
        self.assertEqual(filtered['excluded_product_ids'], ['kb-plastic'])  # catalog-grounded, exempt

    def test_ground_tool_params_keeps_traceable_and_mission_slots(self):
        mission = {'required_terms': [], 'category_id': None, 'budget_max_cents': 80000,
                   'min_price_cents': None, 'excluded_terms': []}
        filtered, dropped = ground_tool_params(
            {'required_terms': ['Type-C'], 'category_id': None, 'max_price_cents': 3000},
            'Type-C的线，30元以内', mission)
        self.assertEqual(filtered['required_terms'], ['Type-C'])
        self.assertEqual(filtered['max_price_cents'], 3000)
        self.assertEqual(dropped, {})
        carried = ground_tool_params({'max_price_cents': 80000}, '再看看键盘', mission)[0]
        self.assertEqual(carried['max_price_cents'], 80000)  # mission budget survives later turns

    def test_ground_tool_params_matches_category_from_utterance(self):
        filtered, dropped = ground_tool_params({'category_id': 'desk'}, 'desk类目200元以内',
                                               {'category_id': None, 'required_terms': [],
                                                'excluded_terms': [], 'budget_max_cents': None,
                                                'min_price_cents': None})
        self.assertEqual(filtered['category_id'], 'desk')
        self.assertEqual(dropped, {})



class QuantityIntentTests(unittest.TestCase):
    def test_quantity_extracts_from_buy_frames_only(self):
        self.assertEqual(extract_mission('帮我买6个桌面音箱，预算1000元')['quantity'], 6)
        self.assertEqual(extract_mission('来两台音箱')['quantity'], 2)
        self.assertEqual(extract_mission('买十二个')['quantity'], 12)
        self.assertEqual(extract_mission('购买二十件')['quantity'], 20)
        self.assertIsNone(extract_mission('灰色下架键盘也能买吗，按可售来')['quantity'])
        self.assertIsNone(extract_mission('100元以内有什么')['quantity'])
        self.assertIsNone(extract_mission('推荐3个键盘')['quantity'])  # result count, not buy count

    def test_quantity_merges_persists_and_fills_request(self):
        mission = merge_mission(empty_mission(), extract_mission('帮我买6个桌面音箱'))
        self.assertEqual(mission['quantity'], 6)
        carried = merge_mission(mission, extract_mission('还有别的吗'))
        self.assertEqual(carried['quantity'], 6)
        replaced = merge_mission(mission, extract_mission('买3个吧'))
        self.assertEqual(replaced['quantity'], 3)
        request = shopping_request({'query': '音箱'}, carried)
        self.assertEqual(request['quantity'], 6)
        self.assertTrue(has_hard_constraints(request, carried))
        self.assertFalse(retrieve_matches_mission({'quantity': 1, 'max_price_cents': None}, carried))
        self.assertEqual(mission_retrieve_params(carried)['quantity'], 6)
        self.assertTrue(shopping_turn_changed(extract_mission('帮我买6个桌面音箱')))

    def test_ground_tool_params_demotes_quantity_drift(self):
        mission = merge_mission(empty_mission(), extract_mission('帮我买6个桌面音箱'))
        kept, dropped = ground_tool_params({'quantity': 6}, '帮我买6个桌面音箱', mission)
        self.assertEqual(kept.get('quantity'), 6)
        self.assertNotIn('quantity', dropped)
        shrunk, drift = ground_tool_params({'quantity': 1}, '帮我买6个桌面音箱', mission)
        self.assertNotIn('quantity', shrunk)  # mission refills the request with 6
        self.assertEqual(drift['quantity'], 1)
        later, carried = ground_tool_params({'quantity': 6}, '再看看别的', mission)
        self.assertEqual(later.get('quantity'), 6)  # mission-grounded survives later turns
        self.assertNotIn('quantity', carried)

    def test_bare_attributive_noun_phrase_harvests_head_only(self):
        # The head noun phrase becomes an explicit required term; colour qualifiers
        # stay with the model (v14 shop-d-34 under-reported the head and a white
        # wireless headset slipped in). Tool-arg union tops the gate up.
        self.assertEqual(requirement_slots('白色的入门耳机'), ['入门', '耳机'])
        self.assertEqual(requirement_slots('黑色的金属机械键盘'), ['金属', '键盘'])
        self.assertEqual(requirement_slots('粉色的便携鼠标'), ['便携', '鼠标'])
        # Interrogatives, negations, reversals, multi-clause and policy turns stay out.
        self.assertEqual(requirement_slots('有没有统一的七天无理由退货'), [])
        self.assertEqual(requirement_slots('当前聊天里说的预算和历史偏好哪个优先'), [])
        self.assertEqual(requirement_slots('资料里的操作说明是不是等于已经下单了'), [])
        self.assertEqual(requirement_slots('不要塑料的键盘'), [])
        self.assertEqual(requirement_slots('白色耳机没有的话黑色也行'), [])
        self.assertEqual(requirement_slots('头戴的也可以，预算 500 以内'), [])
        self.assertEqual(requirement_slots('Type-C的线，30元以内'), [])

    def test_rollback_authorization_extracts_and_persists(self):
        # Availability-over-qualifiers grants are sticky for the conversation;
        # an empty set under authorization must be substituted, not re-asked.
        self.assertTrue(extract_mission('灰色下架键盘也能买吗，按可售来')['rollback_authorized'])
        self.assertTrue(extract_mission('金属机械键盘买不起就算了，塑料薄膜的也行')['rollback_authorized'])
        self.assertTrue(extract_mission('白色耳机没有的话黑色也行')['rollback_authorized'])
        self.assertFalse(extract_mission('白色的入门耳机')['rollback_authorized'])
        self.assertFalse(extract_mission('预算150以内的入门耳机')['rollback_authorized'])
        mission = merge_mission(empty_mission(), extract_mission('灰色下架键盘也能买吗，按可售来'))
        self.assertTrue(mission['rollback_authorized'])
        later = merge_mission(mission, extract_mission('再看看别的'))
        self.assertTrue(later['rollback_authorized'])


if __name__ == '__main__':
    unittest.main()
