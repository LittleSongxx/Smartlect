"""Payment proposal execution: mock completes locally, live returns the alipay form."""
import unittest
from types import SimpleNamespace

from smartlect.app import execute_proposal
from smartlect.commerce import CommerceRejected

PROPOSAL = {
    "action_type": "payment",
    "parameters": {"payOrderId": "po-1", "expected_amount_cents": 9000},
    "idempotency_key": "smartlect-act-1",
}


class FakeCommerce:
    def __init__(self, mode, status_sequence, pay_form=None):
        self.config = {"SMARTLECT_PAYMENT_MODE": mode}
        self.calls = []
        self._status_sequence = list(status_sequence)
        self._pay_form = pay_form

    async def request(self, service, path, *, actor=None, data=None, key=None):
        self.calls.append({"service": service, "path": path, "data": data, "key": key})
        if path.endswith("/actionStatus"):
            return self._status_sequence.pop(0)
        if path == "/internal/pay/mock/complete":
            return {"commandStatus": "business_completed"}
        if path == "/internal/pay/channel/getPayUrl":
            return {"payInfo": self._pay_form, "payOrderId": "po-1"}
        raise AssertionError(path)


ACTOR = SimpleNamespace(subject_type="user", actor_id="u1")


class PaymentChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_mode_completes_via_internal_channel_and_rechecks(self):
        commerce = FakeCommerce("mock", [
            {"amountCents": 9000, "paymentStatus": "PENDING"},
            {"amountCents": 9000, "paymentStatus": "PAID", "orderSynchronized": True},
        ])
        result = await execute_proposal(dict(PROPOSAL), ACTOR, commerce)
        self.assertEqual(result["paymentStatus"], "PAID")
        self.assertEqual(commerce.calls[1]["path"], "/internal/pay/mock/complete")
        self.assertEqual(commerce.calls[1]["key"], "smartlect-act-1")
        self.assertFalse(any(call["path"].endswith("getPayUrl") for call in commerce.calls))

    async def test_live_mode_pending_returns_alipay_form_without_completing(self):
        commerce = FakeCommerce("live", [
            {"amountCents": 9000, "paymentStatus": "PENDING"},
        ], pay_form="<form name='punchout_form'>alipay</form>")
        result = await execute_proposal(dict(PROPOSAL), ACTOR, commerce)
        self.assertEqual(result["paymentMode"], "live")
        self.assertEqual(result["payChannel"], "alipay_pc")
        self.assertIn("punchout_form", result["payInfo"])
        pay_call = commerce.calls[1]
        self.assertEqual(pay_call["service"], "pay")
        self.assertEqual(pay_call["data"]["payChannel"], "alipay_pc")
        self.assertEqual(pay_call["data"]["amount"], "90.00")
        # 绝不触碰模拟完成通道
        self.assertFalse(any("mock/complete" in call["path"] for call in commerce.calls))

    async def test_live_mode_already_paid_returns_status_only(self):
        commerce = FakeCommerce("live", [
            {"amountCents": 9000, "paymentStatus": "PAID", "orderSynchronized": True},
        ])
        result = await execute_proposal(dict(PROPOSAL), ACTOR, commerce)
        self.assertEqual(result["paymentStatus"], "PAID")
        self.assertNotIn("payInfo", result)
        self.assertEqual(len(commerce.calls), 1)

    async def test_amount_mismatch_requires_reconfirmation_in_both_modes(self):
        for mode in ("mock", "live"):
            commerce = FakeCommerce(mode, [{"amountCents": 100, "paymentStatus": "PENDING"}])
            with self.assertRaises(CommerceRejected) as ctx:
                await execute_proposal(dict(PROPOSAL), ACTOR, commerce)
            self.assertEqual(ctx.exception.reason, "RECONFIRM_REQUIRED")
            self.assertEqual(len(commerce.calls), 1)

    async def test_unknown_mode_is_rejected(self):
        commerce = FakeCommerce("sandbox", [{"amountCents": 9000, "paymentStatus": "PENDING"}])
        with self.assertRaises(CommerceRejected) as ctx:
            await execute_proposal(dict(PROPOSAL), ACTOR, commerce)
        self.assertEqual((ctx.exception.code, ctx.exception.reason), (403, "payment_mode_unsupported"))


if __name__ == '__main__':
    unittest.main()
