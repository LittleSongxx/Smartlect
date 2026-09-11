"""Pure trust-boundary checks; durable behavior is tested in test_state_mysql."""

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from smartlect.state import SessionStore, StateError, _expiry, _json, _public


class StateInputTests(unittest.TestCase):
    def test_utc_expiry_and_json_boundaries(self):
        expected = datetime(2026, 9, 9, 0)
        self.assertEqual(_expiry("2026-09-09T08:00:00+08:00"), expected)
        self.assertEqual(_expiry("2026-09-09T00:00:00Z"), expected)
        self.assertEqual(_expiry(expected.replace(tzinfo=timezone.utc)), expected)
        for value in ("2026-09-09T00:00:00", expected, None, "not-a-date"):
            with self.assertRaises(StateError):
                _expiry(value)
        for value in ([], {"amount": float("nan")}, {"value": "x" * 65537}, {"text": "\ud800"}):
            with self.assertRaises(StateError):
                _json(value)
        self.assertEqual(_json({"b": 2, "a": 1}), _json({"a": 1, "b": 2}))

    def test_invalid_confirmation_and_order_quote_never_reach_database(self):
        connect = Mock(side_effect=AssertionError("invalid request reached DB"))
        store = SessionStore(connect)
        for kind in ("visitor", "merchant"):
            with self.assertRaisesRegex(StateError, "user_required"):
                store.confirm_proposal(SimpleNamespace(subject_type=kind, actor_id="one"), "p", 1)
        actor = SimpleNamespace(subject_type="user", actor_id="one")
        for version in (True, 0, "1"):
            with self.assertRaises(StateError):
                store.confirm_proposal(actor, "p", version)
        with self.assertRaises(StateError):
            store.confirm_proposal(actor, "p", 1, approved="true")
        for quote_id, cents in ((None, 1), ("q", True), ("q", -1), ("q", 1.0)):
            with self.assertRaises(StateError):
                store.create_proposal({}, action_type="order", parameters={},
                                      expires_at="2026-09-10T00:00:00Z", quote_id=quote_id, quote_total_cents=cents)
        connect.assert_not_called()

    def test_public_records_hide_lease_capability_and_decode_json(self):
        record = _public({"lease_token": "secret", "lease_owner": "worker", "lease_epoch": 3,
                          "created_at": datetime(2026, 9, 9), "parameters_json": '{"amount":0}', "approved": 1})
        self.assertEqual(record, {"created_at": "2026-09-09T00:00:00Z", "parameters": {"amount": 0}, "approved": True})


if __name__ == "__main__":
    unittest.main()
