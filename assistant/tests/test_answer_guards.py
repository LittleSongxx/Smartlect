import unittest

from smartlect.answer_guards import STATE_CLAIM_TOOLS, unsupported_state_claims


class StateClaimGuardTests(unittest.TestCase):
    def test_flags_fabricated_order_state_without_receipt(self):
        answer = '订单发货后不能修改地址。目前查询到您的订单列表为空，请提供订单号。'
        claims = unsupported_state_claims(answer, [])
        self.assertTrue(claims)
        self.assertIn('查询到您的订单', claims)
        self.assertIn('订单列表为空', claims)

    def test_flags_coupon_state_claim(self):
        claims = unsupported_state_claims('您账户下暂无可用优惠券。', [])
        self.assertTrue(claims)

    def test_passes_when_order_tool_receipt_exists(self):
        answer = '查询到您的订单列表为空。'
        for tool in STATE_CLAIM_TOOLS:
            self.assertEqual(unsupported_state_claims(answer, [tool]), [])

    def test_policy_wording_is_not_a_state_claim(self):
        # 权限/流程说明是合法政策内容，不得误伤
        legal = [
            '登录用户只能查询本人账户下的订单，提供他人订单号不能获取对方订单信息。',
            '订单在发货前均可取消，取消请求已受理与取消已完成是两个阶段。',
            '未登录访客可以咨询公开商品和店铺政策，不能查询任何订单。',
            '退款审核需要 1-2 个工作日，审核通过后 3-5 个工作日内原路退回。',
        ]
        for text in legal:
            self.assertEqual(unsupported_state_claims(text, []), [], text)


    def test_flags_point_balance_claim(self):
        claims = unsupported_state_claims('按抵扣规则，您有 10000 积分可抵 100 元。', [])
        self.assertTrue(any('积分' in c for c in claims))
        # 政策陈述不误伤
        self.assertEqual(unsupported_state_claims('积分抵扣部分不开票、不再积分。', []), [])
        self.assertEqual(unsupported_state_claims('使用积分抵扣的订单退货时按积分原路退回。', []), [])

    def test_empty_answer_passes(self):
        self.assertEqual(unsupported_state_claims('', None), [])
        self.assertEqual(unsupported_state_claims(None, []), [])


if __name__ == '__main__':
    unittest.main()
