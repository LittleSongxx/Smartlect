"""Opt-in F1 checks against one dedicated disposable Smartlect MySQL container."""

import concurrent.futures
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import unittest
import uuid

from smartlect.state import SessionStore, StateError
from test_events import batch, outcome
import test_ledger_mysql as ledger_tests


@unittest.skipUnless(os.getenv("SMARTLECT_RUN_MYSQL_TESTS") == "1", "set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL")
class StateMySQLTests(unittest.TestCase):
    # Reuse the existing, ownership-checked disposable container setup without inheriting its tests.
    setUpClass = classmethod(ledger_tests.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(ledger_tests.LedgerMySQLTests.tearDownClass.__func__)

    def setUp(self):
        self.store = SessionStore(self.connect)
        self.actor = SimpleNamespace(subject_type="user", actor_id=uuid.uuid4().hex, execution_scope_id="test-scope")
        self.conversation = self.store.create_conversation(self.actor)["conversation_id"]

    def run_and_lease(self, message="message", parent=None):
        run = self.store.create_run(self.actor, self.conversation, message, "请查询订单", parent_run_id=parent)
        return run, self.store.claim_run(self.actor, run["agent_run_id"], owner="test-worker")

    def proposal(self, lease):
        return self.store.create_proposal(lease, action_type="order", parameters={"sku": "sku", "quantity": 1},
                                          expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                                          quote_id="java-quote", quote_total_cents=0)

    def test_concurrent_message_idempotency_and_actor_scope_isolation(self):
        def create(_):
            return self.store.create_run(self.actor, self.conversation, "same-message", "same text")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            runs = list(executor.map(create, range(2)))
        self.assertEqual(runs[0]["agent_run_id"], runs[1]["agent_run_id"])
        self.assertEqual(len(self.store.get_conversation(self.actor, self.conversation)["messages"]), 1)
        with self.assertRaisesRegex(StateError, "message_id_conflict"):
            self.store.create_run(self.actor, self.conversation, "same-message", "changed text")
        for actor in (SimpleNamespace(subject_type="user", actor_id="different", execution_scope_id="test-scope"),
                      SimpleNamespace(subject_type="user", actor_id=self.actor.actor_id, execution_scope_id="another-scope"),
                      SimpleNamespace(subject_type="merchant", actor_id=self.actor.actor_id, execution_scope_id="test-scope")):
            with self.assertRaises(StateError) as error:
                self.store.get_run(actor, runs[0]["agent_run_id"])
            self.assertEqual(error.exception.status, 404)

    def test_lease_reclaim_fences_old_worker_and_events_only_replay(self):
        run, lease = self.run_and_lease()
        with self.assertRaisesRegex(StateError, "conversation_busy"):
            self.store.claim_run(self.actor, run["agent_run_id"], owner="competitor")
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE conversation SET lease_until=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE conversation_id=%s", (self.conversation,))
            connection.commit()
        successor = self.store.claim_run(self.actor, run["agent_run_id"], owner="successor")
        self.assertGreater(successor["epoch"], lease["epoch"])
        with self.assertRaisesRegex(StateError, "lease_lost"):
            self.store.append_event(lease, "completed", {"bad": "stale worker"})
        first = self.store.append_event(successor, "message_delta", {"text": "saved"})
        self.store.append_message(successor, "saved", message_id="assistant-message")
        self.store.append_message(successor, "saved", message_id="assistant-message")
        self.store.append_event(successor, "completed", {"result": "saved"})
        self.store.finish_run(successor, state="COMPLETED", result={"text": "saved"})
        restarted = SessionStore(self.connect)
        self.assertEqual(restarted.get_run(self.actor, run["agent_run_id"])["state"], "COMPLETED")
        self.assertEqual([event["sequence"] for event in restarted.events(self.actor, run["agent_run_id"], first["sequence"])], [2])
        self.assertEqual(len(restarted.get_conversation(self.actor, self.conversation)["messages"]), 2)
        with self.assertRaisesRegex(StateError, "run_not_claimable"):
            restarted.claim_run(self.actor, run["agent_run_id"], owner="replay")

    def test_quote_confirmation_replay_and_uncertain_action_recovery_keep_key(self):
        run, lease = self.run_and_lease()
        proposal = self.proposal(lease)
        repeated = self.store.create_proposal(lease, action_type="order", parameters=proposal["parameters"],
                                              expires_at=datetime.now(timezone.utc) + timedelta(minutes=6), quote_id="new-quote-on-retry",
                                              quote_total_cents=proposal["quote_total_cents"])
        self.assertEqual(repeated["proposal_id"], proposal["proposal_id"])
        self.assertEqual(repeated["quote_id"], proposal["quote_id"])
        self.assertEqual(repeated["expires_at"], proposal["expires_at"])
        self.store.finish_run(lease, state="WAIT_USER", result={"proposal_id": proposal["proposal_id"]})
        confirmed = self.store.confirm_proposal(self.actor, proposal["proposal_id"], proposal["version"])
        self.assertEqual(confirmed["status"], "CONFIRMED")
        self.assertEqual(self.store.confirm_proposal(self.actor, proposal["proposal_id"], proposal["version"])["version"], confirmed["version"])
        with self.assertRaisesRegex(StateError, "proposal_version_conflict"):
            self.store.confirm_proposal(self.actor, proposal["proposal_id"], proposal["version"], approved=False)
        confirm_run, confirm_lease = self.run_and_lease("confirm", run["agent_run_id"])
        execution = self.store.begin_action(confirm_lease, proposal["proposal_id"])
        self.assertFalse(execution["recover_only"])
        self.assertEqual(execution["action_id"], proposal["action_id"])
        self.store.record_action_result(confirm_lease, proposal["proposal_id"], outcome="unknown", receipt={"error": "timeout"})
        self.store.finish_run(confirm_lease, state="WAIT_OUTCOME")
        recovery_run, recovery = self.run_and_lease("recover", confirm_run["agent_run_id"])
        recovered = SessionStore(self.connect).begin_action(recovery, proposal["proposal_id"])
        self.assertTrue(recovered["recover_only"])
        self.assertEqual(recovered["idempotency_key"], execution["idempotency_key"])
        pending = self.store.record_action_result(recovery, proposal["proposal_id"], outcome="business_pending", receipt={"refundStatus": "PROCESSING"})
        self.assertEqual(pending["status"], "EXECUTING")
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE agent_run SET deadline=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE agent_run_id=%s",
                           (recovery_run["agent_run_id"],))
            cursor.execute("UPDATE conversation SET lease_until=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE conversation_id=%s", (self.conversation,))
            connection.commit()
        with self.assertRaisesRegex(StateError, "run_deadline_exceeded"):
            self.store.claim_run(self.actor, recovery_run["agent_run_id"], owner="late-restart")
        _, recovery = self.run_and_lease("recover-again", recovery_run["agent_run_id"])
        self.assertEqual(self.store.begin_action(recovery, proposal["proposal_id"])["idempotency_key"], execution["idempotency_key"])
        completed = self.store.record_action_result(recovery, proposal["proposal_id"], outcome="business_completed", receipt={"refundStatus": "COMPLETED"})
        self.assertEqual(completed["status"], "SUCCEEDED")
        self.assertEqual(self.store.record_action_result(recovery, proposal["proposal_id"], outcome="business_completed", receipt={"refundStatus": "COMPLETED"})["version"], completed["version"])
        with self.assertRaisesRegex(StateError, "action_already_terminal"):
            self.store.record_action_result(recovery, proposal["proposal_id"], outcome="unknown", receipt={})
        self.assertEqual(self.store.confirm_proposal(self.actor, proposal["proposal_id"], proposal["version"])["status"], "SUCCEEDED")

    def test_expired_proposal_is_persisted_and_unconfirmed_action_is_rejected(self):
        _, lease = self.run_and_lease()
        proposal = self.proposal(lease)
        with self.assertRaisesRegex(StateError, "proposal_not_confirmed"):
            self.store.begin_action(lease, proposal["proposal_id"])
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE proposal SET expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE proposal_id=%s", (proposal["proposal_id"],))
            connection.commit()
        with self.assertRaisesRegex(StateError, "proposal_expired"):
            self.store.confirm_proposal(self.actor, proposal["proposal_id"], proposal["version"])
        self.assertEqual(self.store.get_proposal(self.actor, proposal["proposal_id"])["status"], "EXPIRED")

    def test_tool_receipts_are_bound_to_arguments_and_do_not_overwrite(self):
        _, lease = self.run_and_lease()
        self.store.start_tool_call(lease, "call", "get_order", {"id": "one"})
        with self.assertRaisesRegex(StateError, "tool_call_id_conflict"):
            self.store.start_tool_call(lease, "call", "get_order", {"id": "another"})
        done = self.store.finish_tool_call(lease, "call", outcome="business_completed", receipt={"id": "one"})
        self.assertEqual(self.store.finish_tool_call(lease, "call", outcome="business_completed", receipt={"id": "one"}), done)
        with self.assertRaisesRegex(StateError, "tool_call_already_terminal"):
            self.store.finish_tool_call(lease, "call", outcome="unknown", receipt={})

    def test_legacy_ledger_adoption_preserves_raw_facts_and_checksum_guard(self):
        pay, item = uuid.uuid4().hex, uuid.uuid4().hex
        event = outcome("PAYMENT", pay, item)
        self.ledger.ingest(batch(event))
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT raw_json,fingerprint FROM commerce_event WHERE event_id=%s", (event["eventId"],))
            original = cursor.fetchone()
            cursor.execute("DELETE FROM schema_migration")
            connection.commit()
        self.store.initialize()
        self.assertEqual(self.ledger.summary(pay)["paidCents"], 9000)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT raw_json,fingerprint FROM commerce_event WHERE event_id=%s", (event["eventId"],))
            self.assertEqual(cursor.fetchone(), original)
            cursor.execute("SELECT checksum FROM schema_migration WHERE name='0001_ledger.sql'")
            checksum = cursor.fetchone()["checksum"]
            cursor.execute("UPDATE schema_migration SET checksum=%s WHERE name='0001_ledger.sql'", ("0" * 64,))
            connection.commit()
        try:
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                self.store.initialize()
        finally:
            with self.connect() as connection, connection.cursor() as cursor:
                cursor.execute("UPDATE schema_migration SET checksum=%s WHERE name='0001_ledger.sql'", (checksum,))
                connection.commit()

    def test_trial_chat_budget_is_persisted_and_caps_without_consuming_overflow(self):
        actor_id = self.actor.actor_id
        self.assertEqual(self.store.increment_trial_chat(actor_id, daily_limit=2), 1)
        self.assertEqual(self.store.increment_trial_chat(actor_id, daily_limit=2), 2)
        with self.assertRaisesRegex(StateError, "trial_chat_limit"):
            self.store.increment_trial_chat(actor_id, daily_limit=2)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT turns FROM trial_chat_budget WHERE actor_id=%s AND budget_date=UTC_DATE()",
                           (actor_id,))
            self.assertEqual(cursor.fetchone()["turns"], 2)


if __name__ == "__main__":
    unittest.main()
