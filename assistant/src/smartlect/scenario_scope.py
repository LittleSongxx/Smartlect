"""评测场景 scope 管理（execution_scope / execution_resource / scope reset）。

2026-10 收敛重构：推荐/归因/触点线退役；本模块保留 demo 场景隔离所需的
scope 注册、退役守卫与 reset 水位——eval 与 Java demo scenario 依赖它们。
"""

import hashlib
import json
import uuid
from datetime import timedelta

from smartlect.db import canonical
from smartlect.state import SessionStore, StateError, _actor, _public


def utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _text(value, field, limit=64):
    if value is None or not str(value).strip() or len(str(value)) > limit:
        raise StateError('invalid_' + field, 422)
    return str(value).strip()


class ScenarioScopeStore(SessionStore):
    def __init__(self, connect, *, secret=None, clock=utc_now):
        super().__init__(connect)
        self.secret, self.clock = secret, clock

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

    def product_scope(self, actor):
        """Phase3a 退役 AttributionStore 后，导购检索的商品可见域仍需要 per-actor 解析。"""
        from smartlect.catalog_scope import product_scope
        return product_scope(self.connect, actor)

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

    @staticmethod
    def _scope(cursor, user_id):
        cursor.execute("SELECT execution_scope_id FROM execution_resource WHERE resource_type='user' AND resource_id=%s", (user_id,))
        row = cursor.fetchone()
        return row['execution_scope_id'] if row else 'store'

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
