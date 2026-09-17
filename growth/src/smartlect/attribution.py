"""Trusted touchpoints and immutable order context; monetary facts stay in the ledger."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import uuid

import os

from smartlect.algo_version import content_hash
from smartlect.events import canonical
from smartlect.state import SessionStore, StateError, _actor, _expiry, _integer, _public, _text

AD_CLICK_WINDOW_DAYS = max(1, int(os.environ.get('SMARTLECT_AD_CLICK_WINDOW_DAYS') or 7))
REC_CLICK_WINDOW_HOURS = max(1, int(os.environ.get('SMARTLECT_REC_CLICK_WINDOW_HOURS') or 24))
RULE_VERSION = content_hash({
    'ad_window_days': AD_CLICK_WINDOW_DAYS,
    'rec_window_hours': REC_CLICK_WINDOW_HOURS,
    'ad_requires_product_or_sku': True,
})


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value):
    return value.isoformat() + 'Z'


def touch_fingerprint(row):
    keys = ('touch_id', 'idempotency_key', 'execution_scope_id', 'subject_type', 'actor_id', 'session_id',
            'conversation_id', 'kind', 'traffic_channel', 'campaign_id', 'creative_id', 'product_id', 'sku_key',
            'recommendation_id', 'position', 'assignment_id', 'strategy_version', 'occurred_at', 'origin')
    value = {key: iso(row[key]) if isinstance(row.get(key), datetime) else row.get(key) for key in keys}
    metadata = row.get('metadata_json', '{}')
    value['metadata'] = json.loads(metadata) if isinstance(metadata, str) else metadata
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def context_token(row, secret):
    if not secret or len(secret) < 32:
        return None  # Optional attribution cannot borrow business authentication keys.
    payload = {'v': 1, 'context_id': row['context_id'], 'snapshot_version': row['snapshot_version'],
               'snapshot_hash': row['snapshot_hash'], 'user_id': row['user_id'],
               'execution_scope_id': row['execution_scope_id'],
               'issued_at': int(row['captured_at'].replace(tzinfo=timezone.utc).timestamp()),
               'expires_at': int(row['expires_at'].replace(tzinfo=timezone.utc).timestamp())}
    encoded = base64.urlsafe_b64encode(canonical(payload).encode()).decode().rstrip('=')
    signature = hmac.new(secret.encode(), ('smartlect-attribution-v1:' + encoded).encode(), hashlib.sha256).hexdigest()
    return encoded + '.' + signature


class AttributionStore(SessionStore):
    def __init__(self, connect, *, secret=None, clock=utc_now):
        super().__init__(connect)
        self.secret, self.clock = secret, clock

    @staticmethod
    def _scope(cursor, user_id):
        cursor.execute("SELECT execution_scope_id FROM execution_resource WHERE resource_type='user' AND resource_id=%s", (user_id,))
        row = cursor.fetchone()
        return row['execution_scope_id'] if row else 'store'

    def resolve_actor(self, actor):
        """Only the trusted cookie bridge supplies visitor_id; request bodies never do."""
        with self._transaction() as cursor:
            scope = actor.execution_scope_id
            if actor.subject_type == 'user' and scope == 'store':
                scope = self._scope(cursor, actor.actor_id)
            elif actor.subject_type == 'visitor' and scope == 'store':
                cursor.execute("SELECT execution_scope_id FROM execution_resource WHERE resource_type='visitor' AND resource_id=%s", (actor.actor_id,))
                registered = cursor.fetchone()
                if registered: scope = registered['execution_scope_id']
            key = actor.subject_type + ':' + actor.actor_id
            if actor.subject_type == 'user' and actor.visitor_id:
                cursor.execute('SELECT * FROM visitor_binding WHERE visitor_id=%s', (actor.visitor_id,))
                binding = cursor.fetchone()
                if binding and binding['user_id'] == actor.actor_id and binding['execution_scope_id'] == scope:
                    key = 'visitor:' + actor.visitor_id
            return actor.model_copy(update={'execution_scope_id': scope, 'recommendation_subject_key': key})

    def bind_visitor(self, actor):
        kind, user, scope = _actor(actor)
        if kind != 'user' or not actor.visitor_id:
            raise StateError('verified_user_and_visitor_required', 403)
        visitor = actor.visitor_id
        with self._transaction() as cursor:
            cursor.execute("SELECT execution_scope_id FROM execution_resource WHERE resource_type='visitor' AND resource_id=%s", (visitor,))
            registered = cursor.fetchone()
            if registered and registered['execution_scope_id'] != scope:
                raise StateError('visitor_scope_conflict', 409)
            # A unique visitor claim cannot be transferred by logging into another account.
            cursor.execute("INSERT INTO visitor_binding (visitor_id,user_id,execution_scope_id,bound_at) VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE visitor_id=visitor_id",
                           (visitor, user, scope, self.clock()))
            cursor.execute('SELECT * FROM visitor_binding WHERE visitor_id=%s FOR UPDATE', (visitor,))
            row = cursor.fetchone()
            if row['user_id'] != user or row['execution_scope_id'] != scope:
                raise StateError('visitor_already_bound_to_another_account', 409)
            cursor.execute('UPDATE visitor_binding SET bound_at=%s WHERE visitor_id=%s', (self.clock(), visitor))
            cursor.execute("SELECT conversation_id FROM conversation WHERE subject_type='visitor' AND actor_id=%s AND execution_scope_id=%s ORDER BY conversation_id FOR UPDATE", (visitor, scope))
            conversations = [r['conversation_id'] for r in cursor.fetchall()]
            for identifier in conversations:
                # Same conversation ID, but the former visitor can no longer read it.
                from smartlect.memory import MemoryStore
                MemoryStore._fence(cursor, identifier)
                cursor.execute("UPDATE conversation SET subject_type='user',actor_id=%s,version=version+1 WHERE conversation_id=%s", (user, identifier))
            # Keep both previously assigned groups if a known account binds another browser.
            keys = [kind + ':' + identifier for kind, identifier in self._subjects(cursor, actor)]
            cursor.execute('SELECT experiment_id,group_name FROM recommendation_assignment WHERE execution_scope_id=%s AND subject_key IN (' +
                           ','.join(['%s'] * len(keys)) + ')', (scope, *keys))
            groups = {}
            for assignment in cursor.fetchall():
                groups.setdefault(assignment['experiment_id'], set()).add(assignment['group_name'])
            conflict = any(len(values) > 1 for values in groups.values())
            cursor.execute('UPDATE visitor_binding SET assignment_conflict=%s WHERE visitor_id=%s', (conflict, visitor))
            return {'bound': True, 'conversation_ids': conversations, 'assignment_conflict': conflict}

    def product_scope(self, actor):
        with self._transaction() as cursor:
            cursor.execute("SELECT resource_id,execution_scope_id FROM execution_resource WHERE resource_type='product'")
            rows = cursor.fetchall()
        scope = actor.execution_scope_id
        if scope == 'store':
            from smartlect.catalog_gate import is_isolated_product_id
            # 9100/9300 eval SKUs are excluded by prefix in catalog_gate.in_scope.
            # Only keep the remaining non-store IDs so the exclude list stays ≤5000.
            excluded = list(dict.fromkeys(
                r['resource_id'] for r in rows
                if r['execution_scope_id'] != 'store' and not is_isolated_product_id(r['resource_id'])))
            if len(excluded) > 5000:
                excluded = excluded[:5000]
            return {'include': None, 'exclude': excluded}
        # A bounded include already fences a scoped actor; enumerating every other
        # scope's products would grow with each demo scenario and trip the scope cap.
        return {'include': [r['resource_id'] for r in rows if r['execution_scope_id'] == scope],
                'exclude': []}

    def register_scope(self, scope, *, scenario_run_id, branch_id, users, products, visitors=()):
        """Local scenario setup only; there is no public resource registration endpoint."""
        scope = _text(scope, 'execution_scope_id')
        if scope == 'store' or not users or not products:
            raise StateError('scenario_resources_required', 422)
        with self._transaction() as cursor:
            cursor.execute('INSERT INTO execution_scope VALUES (%s,%s,%s,%s)',
                           (scope, _text(scenario_run_id, 'scenario_run_id'), _text(branch_id, 'branch_id', 64), self.clock()))
            for kind, resources in (('user', users), ('product', products), ('visitor', visitors)):
                for identifier in set(resources):
                    cursor.execute('INSERT INTO execution_resource VALUES (%s,%s,%s)', (kind, _text(identifier, 'resource_id', 64), scope))

    def assert_scope_writable(self, actor):
        """History and event ingestion retain the original resource mapping after retirement."""
        _, _, scope = _actor(actor)
        if scope == 'store': return
        with self._transaction() as cursor:
            cursor.execute('SELECT r.state FROM execution_scope s JOIN execution_scope_reset r USING(scenario_run_id) WHERE s.execution_scope_id=%s', (scope,))
            guard = cursor.fetchone()
            if guard:
                raise StateError('execution_scope_' + guard['state'].lower(), 410 if guard['state']=='RETIRED' else 409)

    def scope_reset_status(self, run_id):
        with self._transaction() as cursor:
            cursor.execute('SELECT * FROM execution_scope_reset WHERE scenario_run_id=%s', (_text(run_id,'scenario_run_id',64),))
            row=cursor.fetchone()
            return _public(row) if row else None

    @staticmethod
    def _reset_manifests(run_id, manifests):
        _text(run_id,'scenario_run_id',64)
        if run_id=='store' or not isinstance(manifests,list) or not 1 <= len(manifests) <= 32:
            raise StateError('reset_owned_scenario_required',422)
        scopes={}
        for manifest in manifests:
            scope=_text(manifest.get('executionScopeId'),'execution_scope_id')
            if scope=='store' or scope in scopes or manifest.get('scenarioRunId')!=run_id:
                raise StateError('reset_manifest_conflict',409)
            branch=_text(manifest.get('branchId'),'branch_id',64)
            users=[_text(u.get('userId'),'user_id',64) for u in manifest.get('users',[])]
            products=[_text(p,'product_id',64) for p in manifest.get('products',[])]
            if not users or not products or len(set(users))!=len(users) or len(set(products))!=len(products):
                raise StateError('reset_manifest_conflict',409)
            scopes[scope]=(branch,set(users),set(products))
        if len({v[0] for v in scopes.values()})!=len(scopes): raise StateError('reset_manifest_conflict',409)
        return scopes

    def _reset_owned(self, cursor, run_id, manifests):
        expected=self._reset_manifests(run_id,manifests)
        cursor.execute('SELECT * FROM execution_scope WHERE scenario_run_id=%s ORDER BY execution_scope_id FOR UPDATE',(run_id,))
        rows=cursor.fetchall()
        if {r['execution_scope_id']:r['branch_id'] for r in rows}!={k:v[0] for k,v in expected.items()}:
            raise StateError('reset_scope_ownership_conflict',409)
        marks=','.join(['%s']*len(expected))
        cursor.execute('SELECT * FROM execution_resource WHERE execution_scope_id IN ('+marks+') ORDER BY execution_scope_id,resource_type,resource_id FOR UPDATE',tuple(sorted(expected)))
        resources=list(cursor.fetchall())
        for scope,(_,users,products) in expected.items():
            actual=[r for r in resources if r['execution_scope_id']==scope]
            if ({r['resource_id'] for r in actual if r['resource_type']=='user'}!=users or
                    {r['resource_id'] for r in actual if r['resource_type']=='product'}!=products or
                    any(r['resource_type'] not in {'user','product','visitor'} for r in actual)):
                raise StateError('reset_resource_ownership_conflict',409)
        return sorted(expected)

    @staticmethod
    def _reset_busy(cursor, scopes):
        marks=','.join(['%s']*len(scopes)); busy={}
        cursor.execute("SELECT r.agent_run_id,r.state FROM agent_run r JOIN conversation c USING(conversation_id) WHERE c.execution_scope_id IN ("+marks+") AND r.state IN ('CREATED','RUNNING')",tuple(scopes))
        busy['runs']=list(cursor.fetchall())
        cursor.execute("SELECT p.proposal_id,p.status FROM proposal p JOIN conversation c USING(conversation_id) WHERE c.execution_scope_id IN ("+marks+") AND p.status IN ('CONFIRMED','EXECUTING','UNKNOWN')",tuple(scopes))
        busy['proposals']=list(cursor.fetchall())
        cursor.execute("SELECT plan_id,status FROM merchant_plan WHERE execution_scope_id IN ("+marks+") AND status='EXECUTING'",tuple(scopes))
        busy['plans']=list(cursor.fetchall())
        return busy

    @staticmethod
    def _reset_events(cursor, event_ids):
        identifiers=sorted(set(event_ids))
        for identifier in identifiers: _text(identifier,'event_id',128)
        if not identifiers: return
        cursor.execute("SELECT e.event_id,e.status,e.event_type,a.calculation_status FROM commerce_event e LEFT JOIN commerce_attribution a USING(event_id) WHERE e.event_id IN ("+
                       ','.join(['%s']*len(identifiers))+')',tuple(identifiers))
        rows=cursor.fetchall()
        if (len(rows)!=len(identifiers) or any(r['status']!='APPLIED' or
                r['event_type'] in {'PAYMENT','REFUND'} and r['calculation_status']!='FINAL' for r in rows)):
            raise StateError('reset_ledger_watermark_pending',409)

    def inspect_scope_reset(self, run_id, manifests, event_ids=()):
        with self._transaction() as cursor:
            scopes=self._reset_owned(cursor,run_id,manifests)
            self._reset_events(cursor,event_ids)
            busy=self._reset_busy(cursor,scopes)
            return {'scope_ids':scopes,'busy':busy,'ready':not any(busy.values())}

    def begin_scope_reset(self, run_id, request_id, manifests, event_ids=()):
        _text(request_id,'reset_request_id',64)
        encoded=canonical(sorted(manifests,key=lambda m:m['executionScopeId']))
        fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
        with self._transaction() as cursor:
            scopes=self._reset_owned(cursor,run_id,manifests)
            cursor.execute('SELECT * FROM execution_scope_reset WHERE scenario_run_id=%s FOR UPDATE',(run_id,))
            prior=cursor.fetchone()
            if prior:
                if prior['reset_request_id']!=request_id or prior['manifest_hash']!=fingerprint: raise StateError('scope_reset_conflict',409)
                return _public(prior)
            if any(self._reset_busy(cursor,scopes).values()): raise StateError('scope_reset_busy',409)
            self._reset_events(cursor,event_ids)
            cursor.execute('SELECT scenario_run_id FROM execution_scope_reset WHERE reset_request_id=%s',(request_id,))
            if cursor.fetchone(): raise StateError('scope_reset_conflict',409)
            cursor.execute("INSERT INTO execution_scope_reset (scenario_run_id,reset_request_id,state,manifest_hash,manifests_json,event_ids_json,created_at,updated_at) VALUES (%s,%s,'QUIESCING',%s,%s,%s,%s,%s)",
                           (run_id,request_id,fingerprint,encoded,canonical(sorted(set(event_ids))),self.clock(),self.clock()))
            cursor.execute('SELECT * FROM execution_scope_reset WHERE scenario_run_id=%s',(run_id,))
            return _public(cursor.fetchone())

    @staticmethod
    def _reset_guard(cursor, run_id, request_id):
        cursor.execute('SELECT * FROM execution_scope_reset WHERE scenario_run_id=%s FOR UPDATE',(run_id,))
        guard=cursor.fetchone()
        if not guard or guard['reset_request_id']!=request_id: raise StateError('scope_reset_conflict',409)
        return guard

    def mark_scope_reset_call(self, run_id, request_id, watermark_hash, event_ids=()):
        if not isinstance(watermark_hash,str) or not re.fullmatch('[0-9a-f]{64}',watermark_hash): raise StateError('invalid_reset_watermark',422)
        with self._transaction() as cursor:
            guard=self._reset_guard(cursor,run_id,request_id)
            if guard['state']=='RETIRED': return _public(guard)
            if guard['java_call_started']:
                if guard['expected_watermark_hash']!=watermark_hash: raise StateError('scope_reset_conflict',409)
                return _public(guard)
            scopes=self._reset_owned(cursor,run_id,json.loads(guard['manifests_json']))
            if any(self._reset_busy(cursor,scopes).values()): raise StateError('scope_reset_busy',409)
            self._reset_events(cursor,event_ids)
            cursor.execute('UPDATE execution_scope_reset SET java_call_started=TRUE,expected_watermark_hash=%s,event_ids_json=%s,updated_at=%s WHERE scenario_run_id=%s',
                           (watermark_hash,canonical(sorted(set(event_ids))),self.clock(),run_id))
            cursor.execute('SELECT * FROM execution_scope_reset WHERE scenario_run_id=%s',(run_id,))
            return _public(cursor.fetchone())

    def abort_scope_reset(self, run_id, request_id):
        with self._transaction() as cursor:
            guard=self._reset_guard(cursor,run_id,request_id)
            if guard['java_call_started'] or guard['state']!='QUIESCING': raise StateError('scope_reset_outcome_requires_recovery',409)
            cursor.execute('DELETE FROM execution_scope_reset WHERE scenario_run_id=%s AND reset_request_id=%s',(run_id,request_id))

    def finish_scope_reset(self, run_id, request_id, result):
        encoded=canonical(result)
        with self._transaction() as cursor:
            guard=self._reset_guard(cursor,run_id,request_id)
            if guard['state']=='RETIRED':
                if canonical(json.loads(guard['result_json']))!=encoded: raise StateError('scope_reset_result_conflict',409)
                return _public(guard)
            original=json.loads(guard['manifests_json'])
            scopes=self._reset_owned(cursor,run_id,original)
            if (not guard['java_call_started'] or result.get('resetRequestId')!=request_id or result.get('retiredRunId')!=run_id or
                    sorted(result.get('retiredScopeIds',[]))!=scopes or result.get('watermarkHash')!=guard['expected_watermark_hash'] or
                    result.get('mode')!='retire_and_replace' or result.get('replacementRunId') in {None,run_id,'store'}):
                raise StateError('scope_reset_result_conflict',409)
            replacements=result.get('replacementManifests',[])
            fresh=self._reset_manifests(result['replacementRunId'],replacements)
            previous={m['branchId']:m for m in original}
            if set(previous)!={v[0] for v in fresh.values()}: raise StateError('scope_reset_result_conflict',409)
            old_users={u['userId'] for m in original for u in m['users']}; old_products={p for m in original for p in m['products']}
            for manifest in replacements:
                old=previous[manifest['branchId']]
                scope=manifest['executionScopeId']; branch,users,products=fresh[scope]
                if (scope in scopes or users & old_users or products & old_products or len(users)!=len(old['users']) or
                        len(products)!=len(old['products']) or manifest.get('initialStock')!=old.get('initialStock') or
                        len(manifest.get('skus',[]))!=len(old.get('skus',[]))):
                    raise StateError('scope_reset_result_conflict',409)
                cursor.execute('SELECT * FROM execution_scope WHERE execution_scope_id=%s FOR UPDATE',(scope,))
                existing=cursor.fetchone()
                if existing and (existing['scenario_run_id']!=result['replacementRunId'] or existing['branch_id']!=branch):
                    raise StateError('reset_scope_ownership_conflict',409)
                if not existing:
                    cursor.execute('INSERT INTO execution_scope VALUES (%s,%s,%s,%s)',(scope,result['replacementRunId'],branch,self.clock()))
                    for kind,identifiers in (('user',users),('product',products)):
                        for identifier in sorted(identifiers): cursor.execute('INSERT INTO execution_resource VALUES (%s,%s,%s)',(kind,identifier,scope))
                cursor.execute('SELECT actor_id,label FROM merchant_scope_access WHERE execution_scope_id=%s',(old['executionScopeId'],))
                for access in cursor.fetchall():
                    cursor.execute('INSERT INTO merchant_scope_access VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE label=label',
                                   (access['actor_id'],scope,(access['label']+' · reset')[:200]))
            self._reset_owned(cursor,result['replacementRunId'],replacements)
            cursor.execute("UPDATE execution_scope_reset SET state='RETIRED',result_json=%s,updated_at=%s WHERE scenario_run_id=%s",(encoded,self.clock(),run_id))
            cursor.execute('SELECT * FROM execution_scope_reset WHERE scenario_run_id=%s',(run_id,))
            return _public(cursor.fetchone())

    @staticmethod
    def _subjects(cursor, actor):
        kind, identifier, scope = _actor(actor)
        subjects = {(kind, identifier): None}
        if kind == 'user':
            cursor.execute('SELECT visitor_id,bound_at FROM visitor_binding WHERE user_id=%s AND execution_scope_id=%s', (identifier, scope))
            subjects.update({('visitor', row['visitor_id']): row['bound_at'] for row in cursor.fetchall()})
        return subjects

    @staticmethod
    def _owned(subjects, kind, identifier, occurred_at):
        key = (kind, identifier)
        return key in subjects and (subjects[key] is None or occurred_at <= subjects[key])

    def _same_touch(self, cursor, actor, prior, kind, fields):
        stable = ('conversation_id', 'traffic_channel', 'campaign_id', 'creative_id', 'product_id', 'sku_key',
                  'recommendation_id', 'position', 'assignment_id', 'strategy_version')
        if (prior['execution_scope_id'] != actor.execution_scope_id or prior['kind'] != kind or
                not self._owned(self._subjects(cursor, actor), prior['subject_type'], prior['actor_id'], prior['occurred_at']) or
                any(prior.get(key) != fields.get(key) for key in stable) or
                prior['origin'] != fields.get('origin', 'user_interface') or
                canonical(json.loads(prior['metadata_json'])) != canonical(fields.get('metadata', {})) or
                prior['fingerprint'] != touch_fingerprint(prior)):
            raise StateError('touch_idempotency_conflict', 409)
        return _public(prior)

    def _touch(self, cursor, actor, kind, key, **fields):
        expected_fields = dict(fields)
        owner_kind, owner, scope = _actor(actor)
        if owner_kind not in {'user', 'visitor'}:
            raise StateError('shopping_actor_required', 403)
        dedup = hashlib.sha256(key.encode()).hexdigest()
        cursor.execute('SELECT * FROM traffic_touch WHERE idempotency_key=%s', (dedup,))
        prior = cursor.fetchone()
        if prior:
            return self._same_touch(cursor, actor, prior, kind, fields)
        record = {'touch_id': uuid.uuid4().hex, 'idempotency_key': dedup, 'execution_scope_id': scope,
                  'subject_type': owner_kind, 'actor_id': owner, 'session_id': actor.session_id,
                  'kind': kind, 'occurred_at': self.clock(), 'origin': fields.pop('origin', 'user_interface'),
                  'metadata_json': canonical(fields.pop('metadata', {})), **fields}
        record['fingerprint'] = touch_fingerprint(record)
        names = list(record)
        cursor.execute('INSERT INTO traffic_touch (' + ','.join(names) + ') VALUES (' + ','.join(['%s'] * len(names)) + ') ON DUPLICATE KEY UPDATE touch_id=touch_id',
                       tuple(record[k] for k in names))
        cursor.execute('SELECT * FROM traffic_touch WHERE idempotency_key=%s FOR UPDATE', (dedup,))
        return self._same_touch(cursor, actor, cursor.fetchone(), kind, expected_fields)

    def landing(self, actor, entry_id):
        entry_id = _text(entry_id, 'entry_id', 64)
        with self._transaction() as cursor:
            return self._touch(cursor, actor, 'NATURAL_VISIT', 'landing:' + ':'.join(_actor(actor)) + ':' + entry_id,
                               traffic_channel='NATURAL')

    def record_ad_click(self, actor, *, click_key, campaign_id, creative_id, product_id, sku_key, origin, metadata=None):
        """Called by the authorized CPC executor, or explicit F3 synthetic fixtures; never a model/public tool."""
        if origin not in {'ads_executor', 'f3_fixture'}:
            raise StateError('unverified_ad_click', 403)
        fields = {key: _text(value, key, 64 if key != 'sku_key' else 128) for key, value in {
            'campaign_id': campaign_id, 'creative_id': creative_id, 'product_id': product_id, 'sku_key': sku_key}.items()}
        with self._transaction() as cursor:
            return self._touch(cursor, actor, 'AD_CLICK', 'ad:' + _text(click_key, 'click_key'),
                               **fields, traffic_channel='AD_SIMULATED', origin=origin, metadata=metadata or {})

    def save_recommendation(self, actor, result, conversation_id=None):
        kind, identifier, scope = _actor(actor)
        now, recommendation_id = self.clock(), uuid.uuid4().hex
        result = json.loads(canonical(result))
        result['recommendation_id'] = recommendation_id
        result['items'] = [{**item, 'recommendation_id': recommendation_id, 'position': index + 1}
                           for index, item in enumerate(result['items'])]
        with self._transaction() as cursor:
            if conversation_id:
                self._conversation(cursor, actor, conversation_id)
            cursor.execute('INSERT INTO recommendation_receipt VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                           (recommendation_id, scope, kind, identifier, actor.session_id, conversation_id,
                            result['assignment_id'], str(result['strategy_version']), canonical(result), now, now + timedelta(hours=24)))
        return result

    def interact(self, actor, recommendation_id, positions, *, clicked=False):
        recommendation_id = _text(recommendation_id, 'recommendation_id', 32)
        if not isinstance(positions, list) or not 1 <= len(positions) <= 8:
            raise StateError('invalid_positions', 422)
        with self._transaction() as cursor:
            # One receipt lock makes duplicate visibility/click callbacks idempotent.
            cursor.execute('SELECT * FROM recommendation_receipt WHERE recommendation_id=%s FOR UPDATE', (recommendation_id,))
            receipt = cursor.fetchone()
            if (not receipt or receipt['execution_scope_id'] != actor.execution_scope_id or
                    not self._owned(self._subjects(cursor, actor), receipt['subject_type'], receipt['actor_id'], receipt['created_at'])):
                raise StateError('recommendation_not_found', 404)
            if receipt['expires_at'] <= self.clock():
                raise StateError('recommendation_expired', 410)
            items = {item['position']: item for item in json.loads(receipt['result_json'])['items']}
            result = []
            for position in sorted(set(_integer(p, 'position', 1, 8) for p in positions)):
                if position not in items:
                    raise StateError('recommendation_item_not_found', 404)
                item = items[position]
                kind = 'REC_CLICK' if clicked else 'REC_IMPRESSION'
                result.append(self._touch(cursor, actor, kind, f'rec:{recommendation_id}:{position}:{kind}',
                    recommendation_id=recommendation_id, position=position, product_id=item['productId'],
                    sku_key=item['propertyValueIdHash'], assignment_id=receipt['assignment_id'],
                    strategy_version=receipt['strategy_version'], conversation_id=receipt['conversation_id']))
            return {'touches': result}

    def freeze_context(self, actor, context_key):
        if actor.subject_type != 'user':
            raise StateError('user_required', 403)
        context_key = _text(context_key, 'context_key')
        with self._transaction() as cursor:
            cursor.execute('SELECT * FROM attribution_context WHERE context_key=%s', (context_key,))
            prior = cursor.fetchone()
            if prior:
                if (prior['user_id'], prior['execution_scope_id']) != (actor.actor_id, actor.execution_scope_id):
                    raise StateError('context_owner_conflict', 403)
                return context_token(prior, self.secret)
            now = self.clock()
            subjects = self._subjects(cursor, actor)
            cursor.execute('SELECT * FROM traffic_touch WHERE execution_scope_id=%s AND occurred_at BETWEEN %s AND %s ORDER BY occurred_at,touch_id',
                           (actor.execution_scope_id, now - timedelta(days=7), now))
            touches = [t for t in cursor.fetchall() if self._owned(subjects, t['subject_type'], t['actor_id'], t['occurred_at'])]
            if len(touches) > 1000:
                raise StateError('context_touch_limit', 422)
            snapshot = {'subjects': list(subjects), 'visitor_bound_at': {key[1]: iso(value) for key, value in subjects.items() if value is not None},
                        'references': [{'touch_id': t['touch_id'], 'fingerprint': t['fingerprint']} for t in touches]}
            encoded = canonical(snapshot)
            row = {'context_id': uuid.uuid4().hex, 'context_key': context_key, 'execution_scope_id': actor.execution_scope_id,
                   'user_id': actor.actor_id, 'snapshot_version': 1, 'snapshot_hash': hashlib.sha256(encoded.encode()).hexdigest(),
                   'snapshot_json': encoded, 'captured_at': now, 'expires_at': now + timedelta(seconds=300)}
            cursor.execute('INSERT INTO attribution_context VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE context_id=context_id', tuple(row.values()))
            cursor.execute('SELECT * FROM attribution_context WHERE context_key=%s FOR UPDATE', (context_key,))
            row = cursor.fetchone()
            if (row['user_id'], row['execution_scope_id']) != (actor.actor_id, actor.execution_scope_id):
                raise StateError('context_owner_conflict', 403)
            return context_token(row, self.secret)

    def validate_batch(self, user_id, items):
        from smartlect.auth import ActorContext
        actor = self.resolve_actor(ActorContext(subject_type='user', actor_id=user_id,
            session_id='trusted-java-validator', permissions=('shopping:read',)))
        result = []
        with self._transaction() as cursor:
            subjects = self._subjects(cursor, actor)
            for item in items:
                if not item.get('skuKey'):
                    continue  # Old product-only carriers cannot prove a clicked SKU.
                cursor.execute("""SELECT t.* FROM traffic_touch t WHERE recommendation_id=%s AND position=%s
                    AND product_id=%s AND sku_key=%s AND kind='REC_CLICK' AND execution_scope_id=%s
                    AND occurred_at BETWEEN %s AND %s ORDER BY occurred_at DESC,touch_id DESC""",
                    (item['requestId'], item['position'], item['productId'], item['skuKey'], actor.execution_scope_id,
                     self.clock() - timedelta(hours=24), self.clock()))
                touch = next((row for row in cursor.fetchall() if self._owned(subjects, row['subject_type'], row['actor_id'], row['occurred_at'])
                              and row['fingerprint'] == touch_fingerprint(row)), None)
                if touch:
                    result.append({**item, 'source': 'recommendation_click', 'occurredAt': iso(touch['occurred_at'])})
        return result

    def summary(self, actor, pay_order_id=None):
        actor.require_any('admin:legacy', 'admin:trial')
        where, params = "e.status='APPLIED' AND p.execution_scope_id=%s", [actor.execution_scope_id]
        if pay_order_id is not None:
            where += ' AND e.pay_order_id=%s'
            params.append(_text(pay_order_id, 'pay_order_id', 64))
        with self._transaction() as cursor:
            cursor.execute("""SELECT p.category,p.calculation_status,
                SUM(CASE WHEN e.event_type='PAYMENT' THEN e.amount_cents ELSE 0 END) AS paidCents,
                SUM(CASE WHEN e.event_type='REFUND' THEN e.amount_cents ELSE 0 END) AS refundedCents,
                COUNT(DISTINCT CASE WHEN e.event_type='PAYMENT' THEN e.pay_order_id END) AS paymentConversions
                FROM commerce_event e JOIN commerce_attribution p USING(event_id) WHERE """ + where + ' GROUP BY p.category,p.calculation_status', params)
            groups = [{**r, 'paidCents': int(r['paidCents']), 'refundedCents': int(r['refundedCents']),
                       'netCents': int(r['paidCents'])-int(r['refundedCents'])} for r in cursor.fetchall()]
            cursor.execute("""SELECT e.event_id,e.event_type,e.pay_order_id,e.order_item_id,e.amount_cents,p.*
                FROM commerce_event e JOIN commerce_attribution p USING(event_id) WHERE """ + where + ' ORDER BY e.received_at,e.event_id LIMIT 1001', params)
            rows = list(cursor.fetchall())
        return {'execution_scope_id': actor.execution_scope_id, 'currency': 'CNY', 'rule_version': RULE_VERSION,
                'categories': groups, 'events': [_public(r) for r in rows[:1000]], 'events_truncated': len(rows)>1000,
                'dimensions_are_not_additive': True}

    def totals(self, actor):
        """Flat scope totals under the same filter as summary(), without the dimensions.

        summary() groups by category x calculation_status, so its numbers are only additive
        across the groups of that one grouping; consumers that need a single line per money
        figure (the growth report) read this instead of re-deriving it from the groups.
        """
        actor.require_any('admin:legacy', 'admin:trial')
        with self._transaction() as cursor:
            cursor.execute("""SELECT
                COALESCE(SUM(CASE WHEN e.event_type='PAYMENT' THEN e.amount_cents ELSE 0 END),0) AS paid,
                COALESCE(SUM(CASE WHEN e.event_type='REFUND' THEN e.amount_cents ELSE 0 END),0) AS refunded,
                COUNT(DISTINCT CASE WHEN e.event_type='PAYMENT' THEN e.pay_order_id END) AS conversions
                FROM commerce_event e JOIN commerce_attribution p USING(event_id)
                WHERE e.status='APPLIED' AND p.execution_scope_id=%s""", (actor.execution_scope_id,))
            row = cursor.fetchone()
        paid, refunded = int(row['paid']), int(row['refunded'])
        return {'paid_cents': paid, 'refunded_cents': refunded, 'net_cents': paid - refunded,
                'payment_conversions': int(row['conversions'])}


def event_metadata(event):
    """Bad optional source metadata must not erase otherwise valid payment money."""
    value = event.get('payload', {}).get('attribution')
    if not isinstance(value, dict):
        return {'contextStatus': 'UNKNOWN_CONTEXT', 'reason': 'missing_context'}
    try:
        order_time = iso(_expiry(value['orderCreatedAt']))
        if value.get('contextStatus') != 'VERIFIED':
            return {'contextStatus': 'UNKNOWN_CONTEXT', 'orderCreatedAt': order_time, 'reason': 'unverified_context'}
        if not re.fullmatch('[0-9a-f]{32}', value.get('contextId', '')) or not re.fullmatch('[0-9a-f]{64}', value.get('snapshotHash', '')):
            raise ValueError('invalid context identity')
        return {'contextStatus': 'VERIFIED', 'contextId': value['contextId'],
                'snapshotVersion': _integer(value['snapshotVersion'], 'snapshot_version', 1, 2147483647),
                'snapshotHash': value['snapshotHash'], 'executionScopeId': _text(value['executionScopeId'], 'scope'),
                'orderCreatedAt': order_time}
    except (KeyError, TypeError, ValueError, StateError):
        return {'contextStatus': 'UNKNOWN_CONTEXT', 'reason': 'invalid_optional_context'}


def _ad_matches_order(touch, product_id, sku_key):
    return touch.get('product_id') == product_id or (
        sku_key and touch.get('sku_key') == sku_key)


def select_attribution(touches, order_time, product_id, sku_key):
    """Only already-frozen references enter here; inclusive business-time windows.

    Ad last-click must match the ordered product or SKU. Recommendation clicks stay
    SKU-matched inside the shorter window. Both windows are configuration, not
    hardcoded version names.
    """
    ordered = sorted(touches, key=lambda t: (t['occurred_at'], t['touch_id']))
    ad_start = order_time - timedelta(days=AD_CLICK_WINDOW_DAYS)
    rec_start = order_time - timedelta(hours=REC_CLICK_WINDOW_HOURS)
    recent = [t for t in ordered if ad_start <= t['occurred_at'] <= order_time]
    visits = [t for t in recent if t['kind'] in {'NATURAL_VISIT', 'AD_CLICK'}]
    ads = [t for t in recent if t['kind'] == 'AD_CLICK' and _ad_matches_order(t, product_id, sku_key)]
    matched = [t for t in recent if rec_start <= t['occurred_at']
               and t['product_id'] == product_id and t['sku_key'] == sku_key]
    clicks = [t for t in matched if t['kind'] == 'REC_CLICK']
    impressions = [t for t in matched if t['kind'] == 'REC_IMPRESSION']
    ad, rec = (ads[-1] if ads else {}), (clicks[-1] if clicks else {})
    return {'category': 'AD_ATTRIBUTED' if ad else 'NATURAL_VERIFIED' if visits else 'UNKNOWN_CONTEXT',
            'traffic_channel': visits[-1]['traffic_channel'] if visits else None,
            'ad_click_id': ad.get('touch_id'), 'campaign_id': ad.get('campaign_id'), 'creative_id': ad.get('creative_id'),
            'recommendation_click_id': rec.get('touch_id'), 'recommendation_id': rec.get('recommendation_id'),
            'recommendation_assist_id': impressions[-1]['touch_id'] if impressions else None,
            'assignment_id': rec.get('assignment_id'), 'strategy_version': rec.get('strategy_version')}


def project_pending(cursor):
    # ponytail: demo-scale pending scan; shard by payment if sustained ingest grows beyond this single ledger lock.
    cursor.execute("""SELECT e.*,m.metadata_json FROM commerce_event e
        LEFT JOIN commerce_attribution p USING(event_id) LEFT JOIN commerce_attribution_meta m USING(event_id)
        WHERE e.event_type IN ('PAYMENT','REFUND') AND (p.event_id IS NULL OR p.calculation_status='PENDING')
        ORDER BY e.event_type='PAYMENT' DESC,e.received_at,e.event_id""")
    for fact in cursor.fetchall():
        now = utc_now()
        row = {'event_id': fact['event_id'], 'execution_scope_id': AttributionStore._scope(cursor, fact['user_id']),
               'category': 'UNKNOWN_CONTEXT', 'calculation_status': 'FINAL', 'reason': 'missing_context',
               'rule_version': RULE_VERSION, 'as_of': now, 'context_id': None, 'order_created_at': None,
               'traffic_channel': None, 'ad_click_id': None, 'campaign_id': None, 'creative_id': None,
               'recommendation_click_id': None, 'recommendation_id': None, 'recommendation_assist_id': None,
               'assignment_id': None, 'strategy_version': None}
        if fact['status'] != 'APPLIED':
            row.update(calculation_status='PENDING' if fact['status'] == 'PENDING' else 'FINAL', reason='financial_' + fact['status'].lower())
        elif fact['event_type'] == 'REFUND':
            cursor.execute("""SELECT p.* FROM commerce_event e JOIN commerce_attribution p USING(event_id)
                WHERE e.order_item_id=%s AND e.event_type='PAYMENT' AND e.status='APPLIED'""", (fact['order_item_id'],))
            original = cursor.fetchone()
            if original:
                row.update({k: v for k, v in original.items() if k not in {'event_id', 'as_of', 'reason'}})
                row['reason'] = 'refund_inherits_payment'
            else:
                row.update(calculation_status='PENDING', reason='awaiting_payment_projection')
        elif fact['schema_version'] == 1:
            row.update(category='LEGACY_UNKNOWN', reason='legacy_schema_v1')
        else:
            meta = json.loads(fact['metadata_json']) if fact['metadata_json'] else {}
            if meta.get('orderCreatedAt'):
                row['order_created_at'] = _expiry(meta['orderCreatedAt'])
            if meta.get('contextStatus') == 'VERIFIED':
                row['context_id'] = meta['contextId']
                cursor.execute('SELECT * FROM attribution_context WHERE context_id=%s', (meta['contextId'],))
                context = cursor.fetchone()
                if not context:
                    row.update(calculation_status='PENDING', reason='awaiting_frozen_context')
                elif (context['user_id'] != fact['user_id'] or context['execution_scope_id'] != meta['executionScopeId'] or
                      context['snapshot_hash'] != meta['snapshotHash'] or context['snapshot_version'] != meta['snapshotVersion'] or
                      not context['captured_at'] <= row['order_created_at'] <= context['expires_at']):
                    row['reason'] = 'context_binding_mismatch'
                else:
                    snapshot = json.loads(context['snapshot_json'])
                    if hashlib.sha256(canonical(snapshot).encode()).hexdigest() != context['snapshot_hash']:
                        row['reason'] = 'context_snapshot_changed'
                    else:
                        touches, pending, invalid = [], False, False
                        for ref in snapshot['references']:
                            cursor.execute('SELECT * FROM traffic_touch WHERE touch_id=%s', (ref['touch_id'],))
                            touch = cursor.fetchone()
                            if not touch:
                                pending = True
                            elif (touch['fingerprint'] != ref['fingerprint'] or touch_fingerprint(touch) != ref['fingerprint'] or touch['execution_scope_id'] != context['execution_scope_id'] or
                                  [touch['subject_type'], touch['actor_id']] not in snapshot['subjects']):
                                invalid = True
                            else:
                                touches.append(touch)
                        row['execution_scope_id'] = context['execution_scope_id']
                        if invalid:
                            row['reason'] = 'frozen_reference_mismatch'
                        elif pending:
                            row.update(calculation_status='PENDING', reason='awaiting_frozen_touch')
                        else:
                            row.update(select_attribution(touches, row['order_created_at'], fact['product_id'], fact['sku_key']))
                            row['reason'] = 'frozen_context_resolved'
            else:
                row['reason'] = meta.get('reason', 'missing_context')
        names = list(row)
        cursor.execute('INSERT INTO commerce_attribution (' + ','.join(names) + ') VALUES (' + ','.join(['%s'] * len(names)) +
                       ') AS incoming ON DUPLICATE KEY UPDATE ' + ','.join(k + '=incoming.' + k for k in names if k != 'event_id'),
                       tuple(row[k] for k in names))
