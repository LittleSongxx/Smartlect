"""Real MySQL source/identity/ledger contracts; Java and ad fixtures are explicitly synthetic."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import os
import unittest
import uuid

from smartlect.attribution import AttributionStore, iso
from smartlect.auth import ActorContext
from smartlect.events import canonical
from smartlect.recommendation.store import StrategyStore
from smartlect.state import SessionStore, StateError
import test_ledger_mysql
from test_events import outcome, batch


@unittest.skipUnless(os.getenv('SMARTLECT_RUN_MYSQL_TESTS') == '1', 'set SMARTLECT_RUN_MYSQL_TESTS=1 for dedicated MySQL')
class AttributionMySQLTests(unittest.TestCase):
    setUpClass = classmethod(test_ledger_mysql.LedgerMySQLTests.setUpClass.__func__)
    tearDownClass = classmethod(test_ledger_mysql.LedgerMySQLTests.tearDownClass.__func__)

    def setUp(self):
        self.now = datetime(2026,9,9,12)
        self.user = ActorContext(subject_type='user', actor_id='u-'+uuid.uuid4().hex[:16], session_id='synthetic-session',
                                 permissions=('shopping:read','orders:read','orders:write'), visitor_id=uuid.uuid4().hex)
        self.store = AttributionStore(self.connect, secret='synthetic-context-test-secret-only-1234567890', clock=lambda:self.now)
        self.sessions = SessionStore(self.connect)
        self.strategies = StrategyStore(self.connect)
        self.pay, self.item = uuid.uuid4().hex, uuid.uuid4().hex

    def recommendation(self, actor=None):
        actor=actor or self.user
        assignment=self.strategies.assign(actor,subject_key=actor.recommendation_subject_key)
        return self.store.save_recommendation(actor, {**assignment, 'items': [{'productId':'B','propertyValueIdHash':'B-standard',
             'propertyValueIds':'v1','sku_key':'B:B-standard','stock':5,'price_cents':9000}], 'ranking_mode':'rules'})

    def test_registered_synthetic_visitor_is_scoped_without_becoming_a_user(self):
        visitor=ActorContext(subject_type='visitor',actor_id=uuid.uuid4().hex,session_id=uuid.uuid4().hex,
                             permissions=('shopping:read',))
        other=visitor.model_copy(update={'actor_id':uuid.uuid4().hex})
        scope='visitor-scope-'+uuid.uuid4().hex
        self.store.register_scope(scope,scenario_run_id=scope,branch_id='rag',users=[self.user.actor_id],
                                  products=['product-'+scope],visitors=[visitor.actor_id])
        scoped=self.store.resolve_actor(visitor)
        self.assertEqual(scoped.execution_scope_id,scope)
        self.assertEqual(scoped.subject_type,'visitor')
        self.assertEqual(scoped.permissions,('shopping:read',))
        self.assertEqual(self.store.resolve_actor(other).execution_scope_id,'store')
        self.assertEqual(self.store.resolve_actor(visitor.model_copy(update={'subject_type':'user'})).execution_scope_id,'store')
        conversation=self.sessions.create_conversation(scoped)
        with self.assertRaises(StateError):self.sessions.get_conversation(other,conversation['conversation_id'])
        mismatched=self.user.model_copy(update={'visitor_id':visitor.actor_id})
        with self.assertRaisesRegex(StateError,'visitor_scope_conflict'):
            self.store.bind_visitor(mismatched)
        owner=self.store.resolve_actor(mismatched)
        self.assertEqual(self.store.bind_visitor(owner)['conversation_ids'],[conversation['conversation_id']])
        self.assertEqual(self.sessions.get_conversation(owner,conversation['conversation_id'])['actor_id'],owner.actor_id)
        with self.assertRaises(StateError):self.sessions.get_conversation(scoped,conversation['conversation_id'])

    def context(self):
        key=uuid.uuid4().hex
        token=self.store.freeze_context(self.user,key)
        encoded=token.split('.')[0]
        proof=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        return key, proof

    def event(self, kind, proof=None, **changes):
        event=outcome(kind,self.pay,self.item,userId=self.user.actor_id,productId='B',skuKey='B-standard',orderId='order-'+self.item,**changes)
        if proof:
            event['payload']['attribution']={'contextStatus':'VERIFIED','contextId':proof['context_id'],
                'snapshotVersion':proof['snapshot_version'],'snapshotHash':proof['snapshot_hash'],
                'executionScopeId':proof['execution_scope_id'],'orderCreatedAt':iso(self.now+timedelta(seconds=1))}
        return event

    def ingest(self,*events):
        self.ledger.ingest(canonical({'schema_version':2,'events':events}).encode())

    def projected(self,event):
        with self.connect() as c,c.cursor() as cursor:
            cursor.execute('SELECT * FROM commerce_attribution WHERE event_id=%s',(event['eventId'],));return cursor.fetchone()

    def test_bound_browser_keeps_assignment_and_conversation_ownership_without_cross_user_claim(self):
        visitor=self.user.model_copy(update={'subject_type':'visitor','actor_id':self.user.visitor_id,'permissions':('shopping:read',)})
        visitor=self.store.resolve_actor(visitor)
        original=self.strategies.assign(visitor,subject_key=visitor.recommendation_subject_key)
        conv=self.sessions.create_conversation(visitor)['conversation_id']
        self.store.landing(visitor,'arrival')
        rec=self.recommendation(visitor)
        click=self.store.interact(visitor,rec['recommendation_id'],[1],clicked=True)['touches'][0]
        binding=self.store.bind_visitor(self.user)
        self.assertIn(conv,binding['conversation_ids'])
        user=self.store.resolve_actor(self.user)
        current=self.strategies.assign(user,subject_key=user.recommendation_subject_key)
        self.assertEqual((original['assignment_id'],original['group']),(current['assignment_id'],current['group']))
        self.assertEqual(self.sessions.get_conversation(user,conv)['actor_id'],user.actor_id)
        with self.assertRaises(StateError):self.sessions.get_conversation(visitor,conv)
        with self.assertRaises(StateError):self.store.bind_visitor(self.user.model_copy(update={'actor_id':'other-user'}))
        # The same recommendation callback after login returns the old touch, without a second click.
        self.assertEqual(self.store.interact(user,rec['recommendation_id'],[1],clicked=True)['touches'][0]['touch_id'],click['touch_id'])
        self.assertEqual(self.store.resolve_actor(user).recommendation_subject_key,visitor.recommendation_subject_key)

    def test_frozen_ad_a_rec_b_natural_revisit_delayed_payment_and_reversed_refund(self):
        self.store.landing(self.user,'initial')
        ad=self.store.record_ad_click(self.user,click_key=uuid.uuid4().hex,campaign_id='A',creative_id='A-copy',
                                    product_id='A',sku_key='A-standard',origin='f3_fixture')
        self.now+=timedelta(seconds=1)
        rec=self.recommendation();self.store.interact(self.user,rec['recommendation_id'],[1])
        click=self.store.interact(self.user,rec['recommendation_id'],[1],clicked=True)['touches'][0]
        self.now+=timedelta(seconds=1);self.store.landing(self.user,'natural-return')
        _,proof=self.context()
        payment=self.event('PAYMENT',proof,occurredAt=iso(self.now+timedelta(days=12)))
        refund=self.event('REFUND',proof,occurredAt=iso(self.now+timedelta(days=13)))
        self.ingest(refund);self.assertEqual(self.projected(refund)['calculation_status'],'PENDING')
        self.now+=timedelta(hours=1)
        self.store.record_ad_click(self.user,click_key=uuid.uuid4().hex,campaign_id='hijack',creative_id='later',
                                  product_id='B',sku_key='B-standard',origin='f3_fixture')
        self.ingest(payment,refund);self.ingest(payment)
        for event in (payment,refund):
            row=self.projected(event)
            self.assertEqual((row['category'],row['campaign_id'],row['traffic_channel']),('AD_ATTRIBUTED','A','NATURAL'))
            self.assertEqual(row['ad_click_id'],ad['touch_id'])
            self.assertEqual(row['recommendation_click_id'],click['touch_id'])
            self.assertEqual(row['calculation_status'],'FINAL')
        summary=self.ledger.summary(self.pay)
        self.assertEqual((summary['paidCents'],summary['refundedCents'],summary['netCents'],summary['paymentConversions']),(9000,9000,0,1))

    def test_missing_frozen_touch_can_arrive_late_but_new_touch_cannot_enter_snapshot(self):
        touch=self.store.landing(self.user,'natural')
        _,proof=self.context()
        with self.connect() as c,c.cursor() as cur:
            cur.execute('SELECT * FROM traffic_touch WHERE touch_id=%s',(touch['touch_id'],));saved=cur.fetchone()
            cur.execute('DELETE FROM traffic_touch WHERE touch_id=%s',(touch['touch_id'],));c.commit()
        payment=self.event('PAYMENT',proof);self.ingest(payment)
        self.assertEqual(self.projected(payment)['calculation_status'],'PENDING')
        self.now+=timedelta(seconds=2)
        self.store.record_ad_click(self.user,click_key=uuid.uuid4().hex,campaign_id='late',creative_id='late',product_id='B',sku_key='B-standard',origin='f3_fixture')
        with self.connect() as c,c.cursor() as cur:
            cur.execute('INSERT INTO traffic_touch ('+','.join(saved)+') VALUES ('+','.join(['%s']*len(saved))+')',tuple(saved.values()));c.commit()
        self.ledger.replay_pending();row=self.projected(payment)
        self.assertEqual((row['calculation_status'],row['category'],row['campaign_id']),('FINAL','NATURAL_VERIFIED',None))

    def test_context_owner_scope_hash_and_bad_metadata_cannot_claim_natural_or_erase_money(self):
        self.store.landing(self.user,'natural');_,proof=self.context()
        for field,value in [('user_id','other'),('execution_scope_id','other'),('snapshot_hash','c'*64)]:
            altered={**proof,field:value}
            event=self.event('PAYMENT',altered)
            if field=='user_id':event['userId']=value
            event['payload']['orderItemId']=uuid.uuid4().hex;event['payload']['payOrderId']=uuid.uuid4().hex
            self.ingest(event);self.assertEqual(self.projected(event)['category'],'UNKNOWN_CONTEXT')
        no_context=self.event('PAYMENT');no_context['payload']['orderItemId']=uuid.uuid4().hex
        self.ingest(no_context);self.assertEqual(self.projected(no_context)['category'],'UNKNOWN_CONTEXT')
        self.assertEqual(self.ledger.summary(self.pay)['paidCents'],9000)

    def test_concurrent_receipts_idempotency_scope_filter_and_legacy_raw_preservation(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            touches=list(pool.map(lambda _:self.store.landing(self.user,'once'),range(4)))
        self.assertEqual(len({t['touch_id'] for t in touches}),1)
        key=uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=4) as pool:
            tokens=list(pool.map(lambda _:self.store.freeze_context(self.user,key),range(4)))
        self.assertEqual(len(set(tokens)),1)
        scope='branch-'+uuid.uuid4().hex
        self.store.register_scope(scope,scenario_run_id='scenario',branch_id='branch',users=[self.user.actor_id],products=['B-'+scope])
        scoped=self.store.resolve_actor(self.user)
        self.assertEqual(scoped.execution_scope_id,scope)
        self.assertEqual(self.store.product_scope(scoped)['include'],['B-'+scope])
        self.assertIn('B-'+scope,self.store.product_scope(self.user.model_copy(update={'actor_id':'store-user'}))['exclude'])
        event=self.event('PAYMENT');self.ledger.ingest(batch(event))
        with self.connect() as c,c.cursor() as cur:
            cur.execute('SELECT raw_json,fingerprint FROM commerce_event WHERE event_id=%s',(event['eventId'],));before=cur.fetchone()
        self.ledger.replay_pending();self.assertEqual(self.projected(event)['category'],'LEGACY_UNKNOWN')
        with self.connect() as c,c.cursor() as cur:
            cur.execute('SELECT raw_json,fingerprint FROM commerce_event WHERE event_id=%s',(event['eventId'],));self.assertEqual(cur.fetchone(),before)

    def test_binding_only_claims_prior_visitor_facts_and_repeated_bind_explicitly_extends_cutoff(self):
        visitor=self.user.model_copy(update={'subject_type':'visitor','actor_id':self.user.visitor_id,'permissions':('shopping:read',)})
        self.store.landing(visitor,'before-login')
        self.store.bind_visitor(self.user)
        self.now+=timedelta(seconds=2)
        later=self.store.record_ad_click(visitor,click_key=uuid.uuid4().hex,campaign_id='after-logout',creative_id='copy',
                                         product_id='A',sku_key='sku',origin='f3_fixture')
        rec=self.recommendation(visitor)
        with self.assertRaises(StateError):self.store.interact(self.user,rec['recommendation_id'],[1],clicked=True)
        _,proof=self.context();event=self.event('PAYMENT',proof);self.ingest(event)
        self.assertEqual(self.projected(event)['category'],'NATURAL_VERIFIED')
        self.store.bind_visitor(self.user)
        _,proof=self.context();event=self.event('PAYMENT',proof)
        event['payload']['orderItemId']=uuid.uuid4().hex
        self.ingest(event)
        self.assertEqual(self.projected(event)['ad_click_id'],later['touch_id'])

    def test_touch_key_conflicts_and_changed_fact_cannot_reuse_frozen_fingerprint(self):
        key=uuid.uuid4().hex
        arguments=dict(click_key=key,campaign_id='A',creative_id='copy',product_id='A',sku_key='sku',origin='f3_fixture',metadata={'price_cents':7})
        ad=self.store.record_ad_click(self.user,**arguments)
        self.assertEqual(self.store.record_ad_click(self.user,**arguments)['touch_id'],ad['touch_id'])
        for actor,change in [(self.user,{'campaign_id':'different'}),(self.user,{'metadata':{'price_cents':8}}),
                              (self.user.model_copy(update={'actor_id':'different-user'}),{})]:
            with self.assertRaises(StateError):self.store.record_ad_click(actor,**{**arguments,**change})
        _,proof=self.context()
        with self.connect() as c,c.cursor() as cur:
            cur.execute('UPDATE traffic_touch SET campaign_id=%s WHERE touch_id=%s',('tampered',ad['touch_id']));c.commit()
        event=self.event('PAYMENT',proof);self.ingest(event)
        self.assertEqual(self.projected(event)['reason'],'frozen_reference_mismatch')
        self.assertEqual(self.ledger.summary(self.pay)['paidCents'],9000)

    def test_v2_view_scope_uses_registered_user_without_changing_source_fact(self):
        scope='view-'+uuid.uuid4().hex
        self.store.register_scope(scope,scenario_run_id='view-scenario',branch_id='branch',users=[self.user.actor_id],products=['B'])
        event=self.event('VIEW')
        event['payload']={'executionScopeId':'untrusted-producer-scope'}
        self.ingest(event)
        with self.connect() as c,c.cursor() as cur:
            cur.execute('SELECT e.raw_json,e.amount_cents,m.execution_scope_id,m.metadata_json FROM commerce_event e JOIN commerce_attribution_meta m USING(event_id) WHERE event_id=%s', (event['eventId'],))
            row=cur.fetchone()
        self.assertEqual(row['execution_scope_id'],scope)
        self.assertEqual(json.loads(row['metadata_json'])['producerDeclaredScope'],'untrusted-producer-scope')
        self.assertEqual(json.loads(row['raw_json']),event)
        self.assertIsNone(row['amount_cents'])


if __name__=='__main__':unittest.main()
