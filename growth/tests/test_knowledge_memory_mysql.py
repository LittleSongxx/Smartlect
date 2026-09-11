"""F2 database contracts; root runs these serially with the other MySQL suites."""
import concurrent.futures
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import unittest
import uuid

from smartlect.knowledge import KnowledgeStore
from smartlect.memory import MemoryStore
from smartlect.state import SessionStore, StateError
import test_ledger_mysql as ledger_tests


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS') == '1', 'set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL')
class KnowledgeMemoryMySQLTests(unittest.TestCase):
    setUpClass = classmethod(ledger_tests.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(ledger_tests.LedgerMySQLTests.tearDownClass.__func__)

    def setUp(self):
        self.scope = 'f2-' + uuid.uuid4().hex
        self.admin = self.actor('merchant', 'admin', ('admin:legacy',))
        self.user = self.actor('user', 'user', ('shopping:read',))
        self.other = self.actor('user', 'other', ('shopping:read',))
        self.visitor = self.actor('visitor', 'visitor', ('shopping:read',))
        self.knowledge, self.memory, self.state = KnowledgeStore(self.connect), MemoryStore(self.connect), SessionStore(self.connect)
        self.conversation = self.state.create_conversation(self.user)['conversation_id']

    def actor(self, kind, identifier, permissions=()):
        return SimpleNamespace(subject_type=kind, actor_id=identifier, execution_scope_id=self.scope, permissions=permissions)

    def draft(self, doc_id='refund', **overrides):
        now = datetime.now(timezone.utc)
        return self.knowledge.create_draft(self.admin, {'doc_id': doc_id, 'title': '退款申请', 'source_uri': 'fixture:' + doc_id,
            'body': '# 退款申请\n退款需要用户确认。', 'acl': 'PUBLIC', 'valid_from': now - timedelta(days=1),
            'valid_until': now + timedelta(days=30), **overrides})

    def message(self, number, content='用户请求'):
        run = self.state.create_run(self.user, self.conversation, 'u' + str(number), content)
        lease = self.state.claim_run(self.user, run['agent_run_id'], owner='test')
        self.state.append_message(lease, '正在处理，不能假称退款完成。', message_id='a' + str(number))
        self.state.finish_run(lease, state='COMPLETED')
        return run

    def test_lifecycle_acl_validity_scope_and_citation_revalidation(self):
        public = self.draft()
        self.assertEqual(self.knowledge.search(self.user, '退款')['answer_status'], 'insufficient')
        with self.assertRaisesRegex(StateError, 'document_not_found'):
            self.knowledge.read_published_document(self.user, 'refund', 1)
        self.knowledge.publish(self.admin, 'refund', public['version'])
        published = self.knowledge.read_published_document(self.visitor, 'refund', 1)
        self.assertEqual(published['body'], public['body'])
        self.assertEqual(set(published), {'doc_id', 'version', 'title', 'source_uri', 'body', 'checksum', 'language'})
        citations = self.knowledge.search(self.visitor, '退款')['citations']
        self.assertTrue(self.knowledge.validate_citations(self.visitor, citations))
        self.assertFalse(self.knowledge.validate_citations(self.visitor, [{**citations[0], 'content': '伪造的退款承诺'}]))
        for doc_id, acl, actor_id in [('registered', 'USER', None), ('private', 'ACTOR', 'user'), ('internal', 'MERCHANT', None)]:
            row = self.draft(doc_id, acl=acl, acl_actor_id=actor_id)
            self.knowledge.publish(self.admin, doc_id, row['version'])
        visible = lambda actor: {item['doc_id'] for item in self.knowledge.search(actor, '退款')['candidates']}
        self.assertEqual(visible(self.visitor), {'refund'})
        self.assertEqual(visible(self.other), {'refund', 'registered'})
        self.assertEqual(visible(self.user), {'refund', 'registered', 'private'})
        self.assertEqual(visible(self.admin), {'refund', 'internal'})
        for actor in (self.user, self.other, self.visitor, self.admin):
            for doc_id in ('refund', 'registered', 'private', 'internal'):
                if doc_id in visible(actor):
                    self.assertEqual(self.knowledge.read_published_document(actor, doc_id, 1)['doc_id'], doc_id)
                else:
                    with self.assertRaisesRegex(StateError, 'document_not_found'):
                        self.knowledge.read_published_document(actor, doc_id, 1)
        isolated = self.actor('user', 'user', ('shopping:read',))
        isolated.execution_scope_id += '-other'
        self.assertEqual(visible(isolated), set())
        # Same-topic hidden memos do not deny a covering visible policy.
        self.assertEqual(self.knowledge.search(self.visitor, '退款', utterance='退款需要确认吗')['acl_denied'], [])
        with self.assertRaisesRegex(StateError, 'document_not_found'):
            self.knowledge.read_published_document(isolated, 'refund', 1)
        newer = self.draft(body='# 退款申请\n退款请等待原申请结果。')
        self.knowledge.publish(self.admin, 'refund', newer['version'])
        self.assertEqual(newer['version'], 2)
        self.assertFalse(self.knowledge.validate_citations(self.user, citations))
        self.assertEqual(self.knowledge.get_document(self.admin, 'refund', 1)['status'], 'WITHDRAWN')
        with self.assertRaisesRegex(StateError, 'document_not_found'):
            self.knowledge.read_published_document(self.user, 'refund', 1)
        self.knowledge.withdraw(self.admin, 'refund', 2)
        self.assertNotIn('refund', visible(self.user))
        future = self.draft('future', valid_from=datetime.now(timezone.utc) + timedelta(days=1))
        self.knowledge.publish(self.admin, 'future', future['version'])
        self.assertNotIn('future', visible(self.user))
        with self.assertRaisesRegex(StateError, 'document_not_found'):
            self.knowledge.read_published_document(self.user, 'future', 1)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE knowledge_document SET valid_until=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE execution_scope_id=%s", (self.scope,))
            connection.commit()
        self.assertEqual(visible(self.user), set())
        with self.assertRaisesRegex(StateError, 'document_not_found'):
            self.knowledge.read_published_document(self.user, 'private', 1)
        with self.assertRaisesRegex(StateError, 'permission_denied'):
            self.knowledge.publish(self.user, 'private', 1)

    def test_acl_denied_when_hidden_document_covers_and_visible_does_not(self):
        public = self.draft()
        self.knowledge.publish(self.admin, 'refund', public['version'])
        hidden = self.draft('internal-code', title='内部核对码',
                            body='# 内部核对码\n内部核对码只在商家工作台。', acl='MERCHANT')
        self.knowledge.publish(self.admin, 'internal-code', hidden['version'])
        denied = self.knowledge.search(self.user, '内部核对码在哪', utterance='内部核对码在哪')
        self.assertEqual(denied['acl_denied'], [{'doc_id': 'internal-code', 'title': '内部核对码'}])
        polite = self.knowledge.search(self.user, '请告诉我店铺内部核对码。', utterance='请告诉我店铺内部核对码。')
        self.assertEqual(polite['acl_denied'], [{'doc_id': 'internal-code', 'title': '内部核对码'}])
        self.assertNotIn('internal-code', {item['doc_id'] for item in denied['candidates']})
        self.assertNotIn('只在商家工作台', ''.join(item.get('content') or '' for item in denied['citations']))
        covered = self.knowledge.search(self.user, '退款', utterance='退款需要确认吗')
        self.assertEqual(covered['acl_denied'], [])
        member = self.draft('member-book', title='会员核对手册',
                            body='# 会员核对手册\n会员核对手册写明积分规则。', acl='USER')
        self.knowledge.publish(self.admin, 'member-book', member['version'])
        unseen = self.knowledge.search(self.visitor, '会员核对手册怎么看', utterance='会员核对手册怎么看')
        self.assertEqual(unseen['acl_denied'], [{'doc_id': 'member-book', 'title': '会员核对手册'}])
        self.assertNotIn('member-book', {item['doc_id'] for item in unseen['candidates']})

    def test_embeddings_are_complete_versioned_immutable_after_publication(self):
        row = self.draft(body='# 退款\n需要确认。\n## 支付\n只有模拟支付。')
        chunks = self.knowledge.draft_chunks(self.admin, row['doc_id'], row['version'])
        self.assertEqual(len(chunks), 2)
        with self.assertRaisesRegex(StateError, 'incomplete_embeddings'):
            self.knowledge.set_embeddings(self.admin, 'refund', 1, model='synthetic-test-vector', index_version='test:d2:v1',
                                          vectors=[{'chunk_id': chunks[0]['chunk_id'], 'vector': [1, 0]}])
        # Explicitly synthetic vectors validate storage/cosine contracts, not semantic retrieval.
        result = self.knowledge.set_embeddings(self.admin, 'refund', 1, model='synthetic-test-vector', index_version='test:d2:v1',
            vectors=[{'chunk_id': item['chunk_id'], 'vector': [1, i]} for i, item in enumerate(chunks)])
        self.assertEqual(result['dimensions'], 2)
        self.knowledge.publish(self.admin, 'refund', 1)
        search = self.knowledge.search(self.user, 'refund-query', query_vector=[1, 0],
                                       embedding_model='synthetic-test-vector', index_version='test:d2:v1')
        self.assertEqual(search['retrieval']['dense_matches'], 2)
        with self.assertRaisesRegex(StateError, 'document_not_draft'):
            self.knowledge.set_embeddings(self.admin, 'refund', 1, model='other', index_version='other:d2:v1',
                vectors=[{'chunk_id': item['chunk_id'], 'vector': [1, i]} for i, item in enumerate(chunks)])

    def test_preferences_explicit_priority_evidence_expiry_deletion_and_isolation(self):
        self.message(1, '我喜欢轻便的商品')
        inferred = self.memory.set_preference(self.user, 'likes', ['轻便'], source='inferred',
            evidence_ids=['u1'], conversation_id=self.conversation, confidence=.6)
        observed = datetime.fromisoformat(inferred['observed_at'].replace('Z', '+00:00'))
        expires = datetime.fromisoformat(inferred['expires_at'].replace('Z', '+00:00'))
        self.assertEqual(expires - observed, timedelta(days=30))
        self.assertEqual(self.memory.preferences(self.other), [])
        explicit = self.memory.set_preference(self.user, 'likes', ['耐用'])
        self.assertEqual(explicit['source'], 'explicit')
        self.assertIn('user_edit_id', explicit['evidence_ids'][0])
        with self.assertRaisesRegex(StateError, 'priority'):
            self.memory.set_preference(self.user, 'likes', ['轻便'], source='inferred', evidence_ids=['u1'], conversation_id=self.conversation)
        with self.assertRaisesRegex(StateError, 'conversation_not_found'):
            self.memory.set_preference(self.other, 'likes', ['轻便'], source='inferred', evidence_ids=['u1'], conversation_id=self.conversation)
        self.memory.delete_preference(self.user, 'likes')
        self.assertEqual(self.memory.preferences(self.user), [])
        self.assertEqual(self.memory.context(self.user, self.conversation)['messages'], [])
        with self.assertRaisesRegex(StateError, 'evidence_not_found'):
            self.memory.set_preference(self.user, 'likes', ['轻便'], source='inferred', evidence_ids=['u1'], conversation_id=self.conversation)
        self.memory.set_preference(self.user, 'likes', ['新版明确偏好'])
        self.assertEqual(self.memory.preferences(self.user)[0]['value'], ['新版明确偏好'])
        written = self.memory.apply_behavior_inference(self.user, {'likes': ['零食'], 'purpose': '零食'},
                                                       product_ids=['snack-1'])
        self.assertNotIn('likes', written)
        self.assertEqual(self.memory.preferences(self.user)[0]['value'], ['新版明确偏好'])
        self.assertEqual(next(row['source'] for row in self.memory.preferences(self.user) if row['preference_key'] == 'likes'),
                         'explicit')
        self.assertIn('purpose', written)
        self.assertEqual(next(row['value'] for row in self.memory.preferences(self.user) if row['preference_key'] == 'purpose'),
                         '零食')

    def test_behavior_inference_writes_likes_when_user_has_no_explicit_preference(self):
        written = self.memory.apply_behavior_inference(self.user, {'likes': ['零食']}, product_ids=['snack-1'])
        self.assertEqual(written, ['likes'])
        row = self.memory.preferences(self.user)[0]
        self.assertEqual(row['preference_key'], 'likes')
        self.assertEqual(row['source'], 'inferred')
        self.assertEqual(row['value'], ['零食'])
        self.assertEqual(row['evidence_ids'][0]['origin'], 'behavior')

    def test_summary_survives_restart_and_clear_revokes_without_deleting_messages(self):
        for i in range(1, 11):
            self.message(i, '用途' + str(i))
        context = self.memory.context(self.user, self.conversation)
        self.assertEqual(len(context['messages']), 16)
        self.assertEqual(context['summary']['message_ids'], ['u1', 'u2'])
        restarted = MemoryStore(self.connect)
        self.assertEqual(restarted.context(self.user, self.conversation), context)
        with self.assertRaisesRegex(StateError, 'conversation_not_found'):
            restarted.context(self.other, self.conversation)
        self.memory.clear(self.user, self.conversation)
        cleared = restarted.context(self.user, self.conversation)
        self.assertEqual(cleared['messages'], [])
        self.assertIsNone(cleared['summary'])
        self.assertEqual(len(self.state.get_conversation(self.user, self.conversation)['messages']), 20)
        self.assertGreater(cleared['memory_version'], context['memory_version'])

    def test_handoff_deduplicates_persists_and_only_authorized_human_can_reply(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            tickets = list(executor.map(lambda _: self.memory.handoff(self.user, self.conversation, 'insufficient'), range(2)))
        self.assertEqual(tickets[0]['ticket_id'], tickets[1]['ticket_id'])
        restarted = MemoryStore(self.connect)
        self.assertEqual(restarted.handoff_state(self.user, self.conversation)['status'], 'OPEN')
        ticket = self.memory.manage_ticket(self.admin, tickets[0]['ticket_id'], action='take_over', version=1)
        with self.assertRaises(StateError):
            self.memory.manage_ticket(self.user, ticket['ticket_id'], action='reply', version=ticket['version'], reply='越权回复')
        alien_admin = self.actor('merchant', 'another-admin', ('admin:legacy',))
        with self.assertRaisesRegex(StateError, 'assigned_to_another'):
            self.memory.manage_ticket(alien_admin, ticket['ticket_id'], action='reply', version=ticket['version'], reply='未经接管')
        replied = self.memory.manage_ticket(self.admin, ticket['ticket_id'], action='reply', version=ticket['version'], reply='人工核实中，请等待。')
        self.assertEqual(self.state.get_conversation(self.user, self.conversation)['messages'][-1]['content'], '人工核实中，请等待。')
        closed = self.memory.manage_ticket(self.admin, ticket['ticket_id'], action='close', version=replied['version'])
        self.assertEqual(closed['status'], 'CLOSED')
        self.assertIsNone(restarted.handoff_state(self.user, self.conversation))

    def test_handoff_takeover_and_forgetting_fence_late_writes_preserving_proposals(self):
        for action in ('handoff', 'repeat_handoff', 'take_over', 'clear'):
            with self.subTest(action=action):
                self.conversation = self.state.create_conversation(self.user)['conversation_id']
                run = self.state.create_run(self.user, self.conversation, 'active', '请查询订单')
                run_id = run['agent_run_id']
                lease = self.state.claim_run(self.user, run_id, owner='late-model')
                proposal = self.state.create_proposal(lease, action_type='order', parameters={'sku': 'fixture'},
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                    quote_id='fixture-quote', quote_total_cents=0)
                self.state.start_tool_call(lease, 'inflight', 'get_order_status', {'orderId': 'fixture'})
                if action in {'repeat_handoff', 'take_over'}:
                    ticket = self.memory.handoff(self.user, self.conversation, 'insufficient', cancel_running=False)
                    self.assertEqual(self.state.get_run(self.user, run_id)['state'], 'RUNNING')
                if action == 'clear':
                    self.memory.clear(self.user, self.conversation)
                elif action == 'take_over':
                    self.memory.manage_ticket(self.admin, ticket['ticket_id'], action='take_over', version=ticket['version'])
                else:
                    result = self.memory.handoff(self.user, self.conversation, 'user_requested')
                    if action == 'repeat_handoff':
                        self.assertEqual(result['ticket_id'], ticket['ticket_id'])
                self.assertEqual(self.state.get_run(self.user, run_id)['state'], 'CANCELLED')
                self.assertEqual(self.state.get_proposal(self.user, proposal['proposal_id']), proposal)
                with self.assertRaisesRegex(StateError, 'lease_lost'):
                    self.state.append_message(lease, '不应发布的晚到回复', message_id='late')
                with self.assertRaisesRegex(StateError, 'lease_lost'):
                    self.state.finish_tool_call(lease, 'inflight', outcome='command_accepted', receipt={'late': True})
                with self.assertRaisesRegex(StateError, 'lease_lost'):
                    self.state.save_context(lease, {'stale': 'memory'})
                with self.assertRaisesRegex(StateError, 'lease_lost'):
                    self.memory.set_preference(self.user, 'likes', ['不应写入的推断'], source='inferred',
                        evidence_ids=['active'], conversation_id=self.conversation, lease=lease)
                self.assertEqual(self.memory.preferences(self.user), [])
                self.assertEqual(len(self.state.get_conversation(self.user, self.conversation)['messages']), 1)

    def test_ticket_detail_reads_real_history_citations_current_proposal_with_scope_and_assignment(self):
        self.draft()
        self.knowledge.publish(self.admin, 'refund', 1)
        citations = self.knowledge.search(self.user, '退款')['citations']
        run = self.state.create_run(self.user, self.conversation, 'question', '退款如何确认？')
        lease = self.state.claim_run(self.user, run['agent_run_id'], owner='support-detail-test')
        proposal = self.state.create_proposal(lease, action_type='refund', parameters={'orderId': 'owned-order', 'refundAmountCents': 500},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        self.memory.finish_answer(lease, self.user, {'answer': '请核对退款提案后由本人确认。', 'answer_status': 'answered',
            'citations': citations, 'proposal': proposal, 'model_mode': 'mock'}, {'private_context': 'must-not-be-exposed'})
        ticket = self.memory.handoff(self.user, self.conversation, 'user_requested')
        # Persist enough real messages to require another page, without starting more agents.
        with self.state._transaction() as cursor:
            for number in range(101):
                self.state._message(cursor, self.conversation, None, 'history-' + str(number), 'user', '后续补充 ' + str(number))
        latest = self.memory.get_ticket(self.admin, ticket['ticket_id'])
        self.assertEqual(len(latest['messages']), 100)
        earlier = self.memory.get_ticket(self.admin, ticket['ticket_id'], before_sequence=latest['next_before_sequence'])
        self.assertIsNone(earlier['next_before_sequence'])
        self.assertEqual([m['sequence'] for m in earlier['messages'] + latest['messages']], list(range(1, 104)))
        self.assertEqual(earlier['runs'][0]['result']['citations'], citations)
        self.assertEqual(earlier['proposals'], [self.state.get_proposal(self.user, proposal['proposal_id'])])
        self.assertNotIn('context', earlier['runs'][0])
        self.assertNotIn('proposal', earlier['runs'][0]['result'])
        self.assertEqual(earlier['conversation']['actor_id'], self.user.actor_id)
        self.assertFalse(any(key.startswith('lease_') for key in earlier['conversation']))
        self.assertEqual(self.memory.handoff_state(self.user, self.conversation)['status'], 'OPEN', 'Reading cannot take over')
        alien = self.actor('merchant', 'other-admin', ('admin:legacy',))
        self.memory.manage_ticket(self.admin, ticket['ticket_id'], action='take_over', version=ticket['version'])
        with self.assertRaisesRegex(StateError, 'ticket_assigned_to_another'):
            self.memory.get_ticket(alien, ticket['ticket_id'])
        wrong_scope = self.actor('merchant', 'admin', ('admin:legacy',))
        wrong_scope.execution_scope_id = 'other-scope'
        with self.assertRaisesRegex(StateError, 'ticket_not_found'):
            self.memory.get_ticket(wrong_scope, ticket['ticket_id'])
        with self.assertRaisesRegex(StateError, 'permission_denied'):
            self.memory.get_ticket(self.user, ticket['ticket_id'])
        taken = self.memory.get_ticket(self.admin, ticket['ticket_id'])['ticket']
        replied = self.memory.manage_ticket(self.admin, ticket['ticket_id'], action='reply', version=taken['version'], reply='人工已收到补充。')
        self.assertEqual(self.memory.get_ticket(self.admin, ticket['ticket_id'])['messages'][-1]['content'], '人工已收到补充。')
        self.memory.manage_ticket(self.admin, ticket['ticket_id'], action='close', version=replied['version'])
        self.assertEqual(MemoryStore(self.connect).get_ticket(self.admin, ticket['ticket_id'])['ticket']['status'], 'CLOSED')
        with self.assertRaisesRegex(StateError, 'ticket_assigned_to_another'):
            self.memory.get_ticket(alien, ticket['ticket_id'])

    def test_atomic_answer_rechecks_withdrawal_and_commits_refusal_events_together(self):
        self.draft()
        self.knowledge.publish(self.admin, 'refund', 1)
        citations = self.knowledge.search(self.user, '退款')['citations']
        run = self.state.create_run(self.user, self.conversation, 'policy-question', '如何退款？', model_mode='live')
        run_id = run['agent_run_id']
        lease = self.state.claim_run(self.user, run_id, owner='answer-test')
        self.assertTrue(self.knowledge.validate_citations(self.user, citations))
        self.knowledge.withdraw(self.admin, 'refund', 1)
        with self.assertRaisesRegex(StateError, 'citation_no_longer_visible'):
            self.memory.finish_answer(lease, self.user, {'answer': '不应发布的旧政策', 'answer_status': 'answered',
                'citations': citations, 'model_mode': 'live'}, {'model_calls': 2})
        self.assertEqual(self.state.get_run(self.user, run_id)['state'], 'RUNNING')
        self.assertEqual(self.state.get_run(self.user, run_id)['context'], {})
        self.assertEqual(self.state.events(self.user, run_id), [])
        self.assertEqual(len(self.state.get_conversation(self.user, self.conversation)['messages']), 1)
        ticket = self.memory.handoff(self.user, self.conversation, 'citation_withdrawn', cancel_running=False)
        saved = self.memory.finish_answer(lease, self.user, {'answer': '资料已撤回，请等待人工核实。',
            'answer_status': 'needs_human', 'citations': [], 'ticket': ticket, 'model_mode': 'rule-fallback'}, {'model_calls': 2})
        self.assertEqual((saved['state'], saved['model_mode']), ('COMPLETED', 'rule-fallback'))
        self.assertEqual(saved['context'], {'model_calls': 2})
        self.assertEqual(saved['event_sequence'], 2)
        events = self.state.events(self.user, run_id)
        self.assertEqual([event['event_type'] for event in events], ['message_delta', 'completed'])
        self.assertEqual(events[-1]['data'], saved['result'])
        self.assertEqual(len(self.state.get_conversation(self.user, self.conversation)['messages']), 2)
        with self.assertRaisesRegex(StateError, 'lease_lost'):
            self.memory.finish_answer(lease, self.user, saved['result'], {})

    def test_atomic_answer_respects_actor_human_fence_and_authoritative_proposal(self):
        run = self.state.create_run(self.user, self.conversation, 'proposal-question', '帮我准备订单')
        run_id = run['agent_run_id']
        lease = self.state.claim_run(self.user, run_id, owner='answer-test')
        proposal = self.state.create_proposal(lease, action_type='order', parameters={'sku': 'fixture'},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), quote_id='bound-quote', quote_total_cents=9000)
        result = {'answer': '请核对并确认。', 'answer_status': 'answered', 'citations': [],
                  'proposal': {**proposal, 'quote_total_cents': 1}}
        with self.assertRaisesRegex(StateError, 'conversation_not_found'):
            self.memory.finish_answer(lease, self.other, result, {})
        saved = self.memory.finish_answer(lease, self.user, result, {})
        self.assertEqual(saved['state'], 'WAIT_USER')
        self.assertEqual(saved['result']['proposal'], proposal)
        self.assertEqual(self.state.get_proposal(self.user, proposal['proposal_id']), proposal)
        self.assertEqual(self.state.events(self.user, run_id)[-1]['event_type'], 'proposal_required')

        other_conversation = self.state.create_conversation(self.user)['conversation_id']
        active = self.state.create_run(self.user, other_conversation, 'new-question', '请转人工')
        active_lease = self.state.claim_run(self.user, active['agent_run_id'], owner='answer-test')
        ticket = self.memory.handoff(self.user, other_conversation, 'user_requested')
        with self.assertRaisesRegex(StateError, 'lease_lost'):
            self.memory.finish_answer(active_lease, self.user, {'answer': '不应继续自动回复',
                'answer_status': 'needs_human', 'citations': [], 'ticket': ticket}, {})
        self.assertEqual(self.state.get_run(self.user, active['agent_run_id'])['state'], 'CANCELLED')
        self.assertEqual(self.state.events(self.user, active['agent_run_id']), [])


if __name__ == '__main__':
    unittest.main()
