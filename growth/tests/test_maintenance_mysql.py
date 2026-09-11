"""Serial opt-in retention check; proposal/commerce facts must survive text expiry."""
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import unittest
import uuid

from smartlect.maintenance import purge_expired
from smartlect.knowledge import KnowledgeStore
from smartlect.provider import IndexModelAudit
from smartlect.state import SessionStore
from test_events import batch, outcome
import test_ledger_mysql as ledger_tests


@unittest.skipUnless(os.getenv("SMARTLECT_RUN_MYSQL_TESTS") == "1", "set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL")
class MaintenanceMySQLTests(unittest.TestCase):
    setUpClass = classmethod(ledger_tests.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(ledger_tests.LedgerMySQLTests.tearDownClass.__func__)

    def test_expired_text_and_trace_are_removed_but_audit_recent_and_active_runs_survive(self):
        state = SessionStore(self.connect)
        actor = SimpleNamespace(subject_type="user", actor_id=uuid.uuid4().hex, execution_scope_id="retention-test")
        conversation_id = state.create_conversation(actor)["conversation_id"]
        run = state.create_run(actor, conversation_id, "old-user", "EXPIRED_USER_TEXT")
        run_id = run["agent_run_id"]
        lease = state.claim_run(actor, run_id, owner="retention-test")
        state.save_context(lease, {"model_prompt": "EXPIRED_CONTEXT"})
        state.append_message(lease, "EXPIRED_ANSWER", message_id="old-answer")
        state.start_tool_call(lease, "old-tool", "get_order_status", {"query": "EXPIRED_TOOL_ARGUMENT"})
        state.finish_tool_call(lease, "old-tool", outcome="command_accepted", receipt={"text": "EXPIRED_TOOL_REPLY"})
        state.append_event(lease, "completed", {"answer": "EXPIRED_EVENT_TEXT"})
        proposal = state.create_proposal(lease, action_type="order", parameters={"sku": "audit-sku", "quantity": 1},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), quote_id="audit-quote", quote_total_cents=9000)
        state.finish_run(lease, state="WAIT_USER", result={"answer": "EXPIRED_RESULT", "proposal_id": proposal["proposal_id"]})
        state.confirm_proposal(actor, proposal["proposal_id"], proposal["version"])
        confirmation = state.create_run(actor, conversation_id, "old-confirmation", "确认具体订单", parent_run_id=run_id)
        confirmation_id = confirmation["agent_run_id"]
        confirm_lease = state.claim_run(actor, confirmation_id, owner="retention-test")
        state.begin_action(confirm_lease, proposal["proposal_id"])
        state.record_action_result(confirm_lease, proposal["proposal_id"], outcome="business_completed",
                                   receipt={"orderId": "audit-order", "totalAmountCents": 9000})
        state.finish_run(confirm_lease, state="COMPLETED", result={"answer": "EXPIRED_CONFIRMATION_RESULT"})
        recent = state.create_run(actor, conversation_id, "recent-user", "RECENT_USER_TEXT")

        active_conversation = state.create_conversation(actor)["conversation_id"]
        active = state.create_run(actor, active_conversation, "active-user", "ACTIVE_LEASE_USER_TEXT")
        active_id = active["agent_run_id"]
        active_lease = state.claim_run(actor, active_id, owner="active-test", ttl_seconds=90)
        state.save_context(active_lease, {"text": "ACTIVE_LEASE_CONTEXT"})
        state.append_event(active_lease, "message_delta", {"text": "ACTIVE_LEASE_TRACE"})

        pay_id, item_id = uuid.uuid4().hex, uuid.uuid4().hex
        paid = outcome("PAYMENT", pay_id, item_id)
        self.ledger.ingest(batch(paid))
        admin = SimpleNamespace(subject_type="merchant", actor_id="index-admin", execution_scope_id="retention-test",
                                permissions=("admin:legacy",))
        knowledge = KnowledgeStore(self.connect)
        document = knowledge.create_draft(admin, {"doc_id": uuid.uuid4().hex, "title": "Synthetic indexing policy",
            "body": "# Synthetic policy\nNo real model called.", "source_uri": "fixture:index-audit", "acl": "PUBLIC",
            "valid_from": datetime.now(timezone.utc) - timedelta(days=1),
            "valid_until": datetime.now(timezone.utc) + timedelta(days=1)})
        audit = IndexModelAudit(self.connect, admin, document['doc_id'], 1, uuid.uuid4().hex, 0)
        old_attempts = []
        for status in ('failed', 'succeeded'):
            audit.start()
            old_attempts.append(audit.call_id)
            audit.finish({'status': status, 'provider': 'fake-contract-test', 'model_mode': 'mock',
                          'usage': {'input_tokens': 5, 'output_tokens': None}, 'body': 'DO_NOT_PERSIST_DOCUMENT'})
        interrupted = IndexModelAudit(self.connect, admin, document['doc_id'], 1, uuid.uuid4().hex, 1)
        interrupted.start()  # Simulate admission followed by process loss, not a successful call.
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT status,trace_json FROM knowledge_index_attempt WHERE call_id IN (%s,%s)", old_attempts)
            traces = cursor.fetchall()
            self.assertEqual({row['status'] for row in traces}, {'failed', 'succeeded'})
            self.assertNotIn('DO_NOT_PERSIST_DOCUMENT', str(traces))
            cursor.execute("UPDATE knowledge_index_attempt SET started_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY WHERE call_id IN (%s,%s)", old_attempts)
            cursor.execute("""UPDATE agent_run SET created_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY,
                updated_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY WHERE agent_run_id IN (%s,%s,%s)""", (run_id, confirmation_id, active_id))
            cursor.execute("UPDATE message SET created_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY WHERE agent_run_id IN (%s,%s,%s)",
                           (run_id, confirmation_id, active_id))
            cursor.execute("UPDATE agent_run_event SET created_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY WHERE agent_run_id IN (%s,%s)",
                           (run_id, active_id))
            cursor.execute("""UPDATE tool_call SET started_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY,
                completed_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY WHERE agent_run_id=%s""", (run_id,))
            cursor.execute("""INSERT INTO conversation_memory (conversation_id,summary_json,summary_sequence,updated_at)
                VALUES (%s,'{"message_ids":["old-user"],"excerpts":["EXPIRED_SUMMARY"]}',1,UTC_TIMESTAMP(6))""", (conversation_id,))
            cursor.execute("""INSERT INTO support_ticket (ticket_id,conversation_id,status,reason,evidence_json,resolution,created_at,updated_at)
                VALUES (%s,%s,'CLOSED','fixture','[]','EXPIRED_HUMAN_REPLY',UTC_TIMESTAMP(6)-INTERVAL 31 DAY,
                UTC_TIMESTAMP(6)-INTERVAL 31 DAY)""", (uuid.uuid4().hex, conversation_id))
            cursor.execute("UPDATE proposal SET created_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY,updated_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY WHERE proposal_id=%s", (proposal["proposal_id"],))
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s", (proposal["proposal_id"],))
            original_proposal = cursor.fetchone()
            cursor.execute("SELECT * FROM commerce_event WHERE event_id=%s", (paid["eventId"],))
            original_ledger = cursor.fetchone()
            connection.commit()

        counts = purge_expired(self.connect)
        self.assertEqual(counts["messages"], 3)
        self.assertEqual(counts["tool_calls"], 1)
        self.assertEqual(counts["run_events"], 1)
        self.assertEqual(counts["runs_scrubbed"], 2)
        self.assertEqual(counts["summaries_revoked"], 1)
        self.assertEqual(counts["ticket_replies"], 1)
        self.assertEqual(counts["index_model_attempts"], 2)
        self.assertEqual(state.get_run(actor, run_id)["context"], {})
        self.assertIsNone(state.get_run(actor, run_id)["result"])
        self.assertEqual(state.get_run(actor, confirmation_id)["parent_run_id"], run_id)
        self.assertEqual(state.get_run(actor, active_id)["context"], {"text": "ACTIVE_LEASE_CONTEXT"})
        self.assertEqual(len(state.events(actor, active_id)), 1)
        self.assertEqual([m["content"] for m in state.get_conversation(actor, conversation_id)["messages"]], ["RECENT_USER_TEXT"])
        self.assertEqual(state.get_run(actor, recent["agent_run_id"])["state"], "CREATED")
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT call_id,status FROM knowledge_index_attempt WHERE execution_scope_id=%s AND doc_id=%s",
                           (admin.execution_scope_id, document['doc_id']))
            self.assertEqual(cursor.fetchall(), [{'call_id': interrupted.call_id, 'status': 'started'}])
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s", (proposal["proposal_id"],))
            self.assertEqual(cursor.fetchone(), original_proposal)
            cursor.execute("SELECT * FROM commerce_event WHERE event_id=%s", (paid["eventId"],))
            self.assertEqual(cursor.fetchone(), original_ledger)
            cursor.execute("SELECT summary_json FROM conversation_memory WHERE conversation_id=%s", (conversation_id,))
            self.assertIsNone(cursor.fetchone()["summary_json"])
        repeated = purge_expired(self.connect)
        self.assertTrue(all(value == 0 for key, value in repeated.items() if key != "conversations_checked"))


if __name__ == "__main__":
    unittest.main()
