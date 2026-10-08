"""查询理解收口（组件 3）：指代补全与独立问句透传的 20 例契约。

正例（指代式短问句 → 补全）与负例（独立问句 → 原样透传）同等重要：
负例防的是「过度改写」——把订单号/商品名塞进通用政策问句会让政策检索失配。
"""
import unittest

from smartlect.query_understanding import anaphora_expand, looks_anaphoric


class AnaphoraExpandTests(unittest.TestCase):
    def test_anaphoric_short_questions_expand_with_mission_terms(self):
        mission = {'required_terms': ['键盘'], 'comparison_targets': ['人体工学椅', '折叠桌'],
                   'query': '轻便背包'}
        cases = [
            ('那这个保修多久', '（指代对象：人体工学椅、折叠桌、键盘）'),
            ('这个能退吗', '（指代对象：人体工学椅、折叠桌、键盘）'),
            ('它有货吗', '（指代对象：人体工学椅、折叠桌、键盘）'),
            ('这台多少钱', '（指代对象：人体工学椅、折叠桌、键盘）'),
            ('刚说的那个还有吗', '（指代对象：人体工学椅、折叠桌、键盘）'),
            ('那件怎么退', '（指代对象：人体工学椅、折叠桌、键盘）'),
        ]
        for question, suffix in cases:
            with self.subTest(question=question):
                expanded = anaphora_expand(question, mission)
                self.assertTrue(expanded.startswith(question))
                self.assertTrue(expanded.endswith(suffix))

    def test_required_terms_used_when_no_comparison_targets(self):
        mission = {'required_terms': ['不锈钢', '保温杯'], 'comparison_targets': []}
        expanded = anaphora_expand('这个 dishwasher 安全吗', mission)
        self.assertEqual(expanded, '这个 dishwasher 安全吗（指代对象：不锈钢、保温杯）')

    def test_query_used_as_last_resort(self):
        mission = {'query': '露营 轻便', 'required_terms': [], 'comparison_targets': []}
        expanded = anaphora_expand('那这个保修多久', mission)
        self.assertEqual(expanded, '那这个保修多久（指代对象：露营 轻便）')

    def test_no_mission_context_falls_back_to_original(self):
        # 回落契约：无可补全上下文 = 原句（等价于改造前的行为，改写是增益不是依赖）
        self.assertEqual(anaphora_expand('那这个保修多久', None), '那这个保修多久')
        self.assertEqual(anaphora_expand('那这个保修多久', {}), '那这个保修多久')
        self.assertEqual(anaphora_expand('这个多少钱', {'query': '', 'required_terms': []}), '这个多少钱')

    def test_independent_questions_pass_through_untouched(self):
        """负例：独立完整问句必须原样透传（防止过度改写污染政策检索）。"""
        mission = {'required_terms': ['键盘'], 'comparison_targets': ['人体工学椅'], 'query': '订单 10086'}
        independent = [
            '全国包邮吗',
            '退款政策是什么',
            '支持哪些支付方式',
            '七天无理由退货的条件',
            '帮我查订单 10086 的物流',
            '键盘和人体工学椅哪个更适合办公',   # 自包含比较问句（有明确对象名）
            '发票怎么开',
            '会员有什么权益',
            '你们的退换货流程是怎样的，需要哪些凭证，多久能处理完',  # 长问句自包含
        ]
        for question in independent:
            with self.subTest(question=question):
                self.assertEqual(anaphora_expand(question, mission), question)

    def test_long_question_with_anaphora_word_passes_through(self):
        # 超过 60 字符的长问句即使含指代词也透传：长问句通常自包含
        long_question = ('我想了解一下你们店里目前在售商品的完整售后服务政策，'
                         '包括但不限于保修期限的具体计算方式、退换货条件和运费承担方式，'
                         '另外这个商品的配件能不能单独购买，需要提供什么凭证？')
        self.assertGreater(len(long_question), 60)
        self.assertEqual(anaphora_expand(long_question, {'query': '键盘'}), long_question)

    def test_empty_and_whitespace_inputs(self):
        self.assertEqual(anaphora_expand('', {'query': '键盘'}), '')
        self.assertEqual(anaphora_expand('   ', {'query': '键盘'}), '')
        self.assertEqual(anaphora_expand(None), '')

    def test_terms_deduplicated_and_capped_at_three(self):
        mission = {'comparison_targets': ['A', 'B'], 'required_terms': ['C', 'D', 'E']}
        expanded = anaphora_expand('这个多少钱', mission)
        self.assertTrue(expanded.endswith('（指代对象：A、B、C）'))

    def test_looks_anaphoric_boundaries(self):
        self.assertTrue(looks_anaphoric('这个多少钱'))
        self.assertFalse(looks_anaphoric('全国包邮吗'))
        self.assertFalse(looks_anaphoric(''))
        self.assertFalse(looks_anaphoric(None))
        self.assertFalse(looks_anaphoric('这个' + '很' * 60))  # 超长
        self.assertTrue(looks_anaphoric('那台怎么样'))


if __name__ == '__main__':
    unittest.main()
