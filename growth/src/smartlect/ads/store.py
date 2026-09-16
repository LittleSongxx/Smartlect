"""Deterministic simulated CPC executor. Java remains the inventory authority.

ponytail: one scope row serializes ads writes; shard by budget account only if
measured throughput requires it. No network requests run while this lock is held.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import sha256
import json

from pymysql.err import IntegrityError

from smartlect.attribution import AttributionStore, iso, utc_now
from smartlect.events import canonical, connect_from_env
from smartlect.state import StateError, _actor, _expiry, _integer, _public, _text
from smartlect.recommendation.store import StrategyStore, DEFAULT_STRATEGIES, EXPERIMENT_ID, strategy_config

ACTION_TYPES = frozenset({'activate_campaign', 'activate_creative', 'resume_campaign', 'resume_creative',
                          'pause_campaign', 'pause_creative', 'set_budget', 'replace_creative',
                          'set_recommendation_policy'})
MAX_MONEY = 1_000_000_000_000


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise StateError('invalid_ads_fields', 422)
    return value


def _money(value, name='budget_cents', minimum=0):
    return _integer(value, name, minimum, MAX_MONEY)


def _merchant(actor):
    if _actor(actor)[0] != 'merchant' or 'admin:legacy' not in actor.permissions:
        raise StateError('merchant_permission_required', 403)


def policy_range(value):
    if value == {}:
        return value
    _fields(value,('rankings','groups','max_weight','max_quota'))
    for field,allowed in (('rankings',{'rule','content'}),('groups',{'control','treatment','all'})):
        if not isinstance(value[field],list) or not value[field] or any(type(v) is not str or v not in allowed for v in value[field]):
            raise StateError('invalid_policy_range',422)
    for field in ('max_weight','max_quota'):
        _integer(value[field],field,0,20)
    return value


class AdsStore(AttributionStore):
    def __init__(self, connect=connect_from_env, *, clock=utc_now):
        super().__init__(connect, clock=clock)

    @contextmanager
    def _transaction(self):
        try:
            with super()._transaction() as cursor:
                yield cursor
        except IntegrityError as error:
            # Global IDs can collide across independent scope locks; rollback has
            # already happened. Do not turn an idempotency conflict into HTTP 500.
            if error.args[0] == 1062:
                raise StateError('ads_identifier_conflict',409) from None
            raise

    @staticmethod
    def _lock(cursor, actor):
        cursor.execute('SELECT execution_scope_id FROM execution_scope WHERE execution_scope_id=%s FOR UPDATE',
                       (_actor(actor)[2],))
        if not cursor.fetchone():
            raise StateError('scope_not_found', 404)

    @staticmethod
    def _resource(cursor, actor, product_id):
        cursor.execute("SELECT execution_scope_id FROM execution_resource WHERE resource_type='product' AND resource_id=%s", (product_id,))
        row = cursor.fetchone()
        if (row['execution_scope_id'] if row else 'store') != actor.execution_scope_id:
            raise StateError('product_outside_scope', 403)

    @staticmethod
    def _row(cursor, actor, table, key, identifier, *, owner=False):
        cursor.execute(f'SELECT * FROM {table} WHERE {key}=%s', (identifier,))
        row = cursor.fetchone()
        if not row or row['execution_scope_id'] != actor.execution_scope_id:
            raise StateError(key + '_not_found', 404)
        if owner and row['owner_id'] != actor.actor_id:
            raise StateError('ads_owner_mismatch', 403)
        return row

    @staticmethod
    def _insert(cursor, table, row):
        cursor.execute('INSERT INTO ' + table + ' (' + ','.join(row) + ') VALUES (' + ','.join(['%s'] * len(row)) + ')', tuple(row.values()))

    def create_campaign(self, actor, data):
        _merchant(actor)
        _fields(data, ('campaign_id', 'name', 'product_id', 'sku_key', 'budget_cents', 'cpc_cents'))
        for field, limit in (('campaign_id',64), ('name',200), ('product_id',64), ('sku_key',128)):
            _text(data[field], field, limit)
        _money(data['budget_cents']); _money(data['cpc_cents'], 'cpc_cents', 1)
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            cursor.execute('SELECT * FROM ads_campaign WHERE campaign_id=%s', (data['campaign_id'],))
            prior = cursor.fetchone()
            if prior:
                return self._draft_replay(actor, prior, data)
            self._resource(cursor, actor, data['product_id'])
            cursor.execute('SELECT budget_cap_cents FROM ads_account WHERE execution_scope_id=%s',(actor.execution_scope_id,))
            account = cursor.fetchone()
            if account:
                cursor.execute('SELECT COALESCE(SUM(budget_cents),0) AS total FROM ads_campaign WHERE execution_scope_id=%s',(actor.execution_scope_id,))
                if cursor.fetchone()['total'] + data['budget_cents'] > account['budget_cap_cents']:
                    raise StateError('aggregate_budget_exceeds_grant',409)
            self._insert(cursor, 'ads_campaign', {**data, 'execution_scope_id':actor.execution_scope_id,
                         'owner_id':actor.actor_id, 'initial_json':canonical(data), 'created_at':self.clock()})
            return _public(self._row(cursor, actor, 'ads_campaign', 'campaign_id', data['campaign_id']))

    @staticmethod
    def _draft_replay(actor, prior, data):
        if (prior['execution_scope_id'] != actor.execution_scope_id or prior['owner_id'] != actor.actor_id or
                canonical(json.loads(prior['initial_json'])) != canonical(data)):
            raise StateError('draft_idempotency_conflict', 409)
        return _public(prior)

    def create_creative(self, actor, data):
        _merchant(actor)
        _fields(data, ('creative_id','campaign_id','copy_text'))
        for field, limit in (('creative_id',64), ('campaign_id',64), ('copy_text',1000)):
            _text(data[field], field, limit)
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            cursor.execute('SELECT * FROM ads_creative WHERE creative_id=%s', (data['creative_id'],))
            prior = cursor.fetchone()
            if prior:
                return self._draft_replay(actor, prior, data)
            self._row(cursor, actor, 'ads_campaign', 'campaign_id', data['campaign_id'], owner=True)
            self._insert(cursor, 'ads_creative', {**data, 'execution_scope_id':actor.execution_scope_id,
                         'owner_id':actor.actor_id, 'initial_json':canonical(data), 'created_at':self.clock()})
            return _public(self._row(cursor, actor, 'ads_creative', 'creative_id', data['creative_id']))

    def approve_grant(self, actor, data):
        _merchant(actor)
        _fields(data, ('grant_id','initial_plan_id','initial_plan_version','envelope','expected_campaign_versions','expected_creative_versions'), ('replaces_grant_id','merchant_plan_id'))
        _text(data['grant_id'],'grant_id',64); _text(data['initial_plan_id'],'initial_plan_id')
        _integer(data['initial_plan_version'],'initial_plan_version',1)
        envelope = data['envelope']
        _fields(envelope, ('objective','product_scope','allowed_action_types','budget_cap_cents','max_budget_change_cents','valid_until'), ('recommendation_policy_range',))
        _text(envelope['objective'],'objective',1000)
        if not isinstance(envelope['product_scope'],list) or not 1 <= len(envelope['product_scope']) <= 100:
            raise StateError('invalid_product_scope',422)
        for product in envelope['product_scope']:
            _text(product,'product_id',64)
        types = envelope['allowed_action_types']
        if not isinstance(types,list) or not types or any(type(t) is not str or t not in ACTION_TYPES for t in types):
            raise StateError('invalid_allowed_action_types',422)
        cap = _money(envelope['budget_cap_cents']); _money(envelope['max_budget_change_cents'],'max_budget_change_cents')
        policy_range(envelope.get('recommendation_policy_range',{}))
        until = _expiry(envelope['valid_until'])
        for field in ('expected_campaign_versions','expected_creative_versions'):
            if not isinstance(data[field],dict) or len(data[field]) > 100:
                raise StateError('invalid_expected_resource_versions',422)
            for identifier,version in data[field].items():
                _text(identifier,'resource_id',64); _integer(version,'resource_version',1)
        with self._transaction() as cursor:
            self._lock(cursor, actor)
            cursor.execute('SELECT * FROM ads_grant WHERE grant_id=%s',(data['grant_id'],))
            prior = cursor.fetchone()
            if prior:
                if prior['execution_scope_id'] != actor.execution_scope_id or prior['approval_actor'] != actor.actor_id or canonical(json.loads(prior['initial_json'])) != canonical(data):
                    raise StateError('grant_idempotency_conflict',409)
                return _public(prior)
            if until <= self.clock():
                raise StateError('grant_expired',410)
            for product in envelope['product_scope']:
                self._resource(cursor, actor, product)
            cursor.execute('SELECT * FROM ads_account WHERE execution_scope_id=%s',(actor.execution_scope_id,))
            account = cursor.fetchone()
            if account:
                if data.get('replaces_grant_id') != account['grant_id']:
                    raise StateError('explicit_grant_replacement_required',409)
                old = self._row(cursor,actor,'ads_grant','grant_id',account['grant_id'])
                if old['approval_actor'] != actor.actor_id:
                    raise StateError('grant_owner_mismatch',403)
                if cap < account['spent_cents']:
                    raise StateError('budget_below_spent',409)
            elif data.get('replaces_grant_id'):
                raise StateError('replacement_grant_not_found',404)
            cursor.execute('SELECT COALESCE(SUM(budget_cents),0) AS total FROM ads_campaign WHERE execution_scope_id=%s',(actor.execution_scope_id,))
            if cursor.fetchone()['total'] > cap:
                raise StateError('aggregate_budget_exceeds_grant',409)
            cursor.execute('SELECT * FROM ads_campaign WHERE execution_scope_id=%s AND owner_id=%s', (actor.execution_scope_id,actor.actor_id))
            planned_campaigns = [_public(row) for row in cursor.fetchall() if row['product_id'] in envelope['product_scope']]
            if {r['campaign_id']:r['version'] for r in planned_campaigns} != data['expected_campaign_versions']:
                raise StateError('approval_resource_version_conflict',409)
            ids = {row['campaign_id'] for row in planned_campaigns}
            cursor.execute('SELECT * FROM ads_creative WHERE execution_scope_id=%s AND owner_id=%s', (actor.execution_scope_id,actor.actor_id))
            planned_creatives = [_public(row) for row in cursor.fetchall() if row['campaign_id'] in ids]
            if {r['creative_id']:r['version'] for r in planned_creatives} != data['expected_creative_versions']:
                raise StateError('approval_resource_version_conflict',409)
            plan_snapshot = {'plan_id':data['initial_plan_id'],'version':data['initial_plan_version'],
                'actor_id':actor.actor_id,'execution_scope_id':actor.execution_scope_id,'objective':envelope['objective'],
                'product_scope':envelope['product_scope'],'period':'scope_lifetime','campaigns':planned_campaigns,
                'creatives':planned_creatives,'planned_budget_cents':sum(c['budget_cents'] for c in planned_campaigns)}
            if data.get('merchant_plan_id'):
                cursor.execute('SELECT * FROM merchant_plan WHERE plan_id=%s AND execution_scope_id=%s AND actor_id=%s',
                               (data['merchant_plan_id'],actor.execution_scope_id,actor.actor_id))
                merchant_plan = cursor.fetchone()
                if (not merchant_plan or merchant_plan['plan_id'] != data['initial_plan_id'] or
                        merchant_plan['version'] != data['initial_plan_version'] or merchant_plan['status'] not in {'VALIDATED','WAIT_APPROVAL'} or
                        merchant_plan['grant_id'] or merchant_plan['lease_token'] or json.loads(merchant_plan['action_receipts_json'])):
                    raise StateError('merchant_plan_approval_conflict',409)
                cursor.execute("SELECT action_id FROM growth_action WHERE execution_scope_id=%s AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.plan_id'))=%s LIMIT 1",
                               (actor.execution_scope_id,merchant_plan['plan_id']))
                if cursor.fetchone(): raise StateError('merchant_plan_approval_conflict',409)
                spec = json.loads(merchant_plan['spec_json'])
                if spec['objective'] != envelope['objective'] or not set(spec['product_scope']) <= set(envelope['product_scope']):
                    raise StateError('merchant_plan_envelope_mismatch',409)
                # Approval may account for its own protection pause, never an earlier independent edit.
                from smartlect.merchant.store import plan_batches
                versions={('campaign',r['campaign_id']):r['version'] for r in planned_campaigns}
                versions.update({('creative',r['creative_id']):r['version'] for r in planned_creatives})
                for batch in plan_batches({'spec':spec}):
                    for action in batch:
                        kind=action['action_type']
                        if kind=='set_recommendation_policy':
                            key=('recommendation','current')
                            versions.setdefault(key,self._recommendation_state(cursor,actor)['revision'])
                        else:
                            resource='creative' if kind.endswith('_creative') else 'campaign'
                            key=(resource,action[resource+'_id'])
                        if versions.get(key)!=action['expected_version']:
                            raise StateError('merchant_plan_resource_version_conflict',409)
                        versions[key]+=1
                plan_snapshot['merchant_plan_spec'] = spec
                if account:
                    # _pause_all below commits exactly these transitions under the same scope lock.
                    plan_snapshot['approval_resource_transitions']=[
                        {'kind':kind,'resource_id':r[kind+'_id'],'reason':'grant_replaced',
                         'before':{'version':r['version'],'status':r['status']},
                         'after':{'version':r['version']+1,'status':'PAUSED'}}
                        for kind,resources in (('campaign',planned_campaigns),('creative',planned_creatives))
                        for r in resources if r['status'] in {'ACTIVE','EXHAUSTED'}]
            self._insert(cursor,'ads_grant',{'grant_id':data['grant_id'],'execution_scope_id':actor.execution_scope_id,
                'approval_actor':actor.actor_id,'initial_plan_id':data['initial_plan_id'],'initial_plan_version':data['initial_plan_version'],
                'envelope_json':canonical(envelope),'envelope_hash':sha256(canonical(envelope).encode()).hexdigest(),
                'initial_json':canonical(data),'plan_snapshot_json':canonical(plan_snapshot),
                'plan_snapshot_hash':sha256(canonical(plan_snapshot).encode()).hexdigest(),'replaces_grant_id':data.get('replaces_grant_id'),'valid_until':until,'approval_time':self.clock()})
            if account:
                cursor.execute('UPDATE ads_grant SET revoked_at=COALESCE(revoked_at,%s),version=version+1 WHERE grant_id=%s',(self.clock(),account['grant_id']))
                cursor.execute('UPDATE ads_account SET grant_id=%s,budget_cap_cents=%s,version=version+1 WHERE execution_scope_id=%s',(data['grant_id'],cap,actor.execution_scope_id))
                self._pause_all(cursor,actor,'grant_replaced')
            else:
                self._insert(cursor,'ads_account',{'execution_scope_id':actor.execution_scope_id,'account_id':actor.execution_scope_id,
                    'budget_cap_cents':cap,'grant_id':data['grant_id'],'created_at':self.clock()})
            return _public(self._row(cursor,actor,'ads_grant','grant_id',data['grant_id']))

    @staticmethod
    def _pause_all(cursor, actor, reason):
        for table in ('ads_campaign','ads_creative'):
            cursor.execute(f"UPDATE {table} SET status='PAUSED',pause_reason=%s,version=version+1 WHERE execution_scope_id=%s AND status IN ('ACTIVE','EXHAUSTED')",(reason,actor.execution_scope_id))

    def _grant(self, cursor, actor, grant_id=None, *, owner=False):
        cursor.execute('SELECT * FROM ads_account WHERE execution_scope_id=%s',(actor.execution_scope_id,))
        account = cursor.fetchone()
        if not account or grant_id is not None and account['grant_id'] != grant_id:
            raise StateError('active_grant_required',403)
        grant = self._row(cursor,actor,'ads_grant','grant_id',account['grant_id'])
        if owner and grant['approval_actor'] != actor.actor_id:
            raise StateError('grant_owner_mismatch',403)
        if grant['revoked_at'] or self.clock() >= grant['valid_until']:
            raise StateError('grant_revoked_or_expired',403)
        return account, grant, json.loads(grant['envelope_json'])

    @staticmethod
    def _within_fresh_window(now, instant):
        # WSL/host sync can step the wall clock back a few hundred ms. A stamp
        # slightly ahead of now is skew, not a stale or future observation.
        return instant is not None and abs((now - instant).total_seconds()) <= 1

    @staticmethod
    def _reusable_fresh(row, now):
        # Freshness follows the last accepted Java read. Reusing generation must
        # not pin later exposures to the first query_started_at of that cohort.
        if row is None:
            return False
        completed = row.get('query_completed_at')
        elapsed = row.get('elapsed_ms')
        observed = row.get('observed_generation')
        pause = row.get('pause_generation') or 0
        stock = row.get('stock')
        return (observed is not None and observed > pause
                and stock is not None and stock > 0
                and AdsStore._within_fresh_window(now, completed)
                and elapsed is not None and elapsed <= 1000)

    def begin_observation(self, actor, product_id, sku_key):
        _text(product_id,'product_id',64); _text(sku_key,'sku_key',128)
        with self._transaction() as cursor:
            self._lock(cursor,actor); self._resource(cursor,actor,product_id)
            started = self.clock()
            cursor.execute('SELECT * FROM ads_inventory WHERE execution_scope_id=%s AND product_id=%s AND sku_key=%s',
                           (actor.execution_scope_id, product_id, sku_key))
            row = cursor.fetchone()
            latest = (row or {}).get('query_started_latest_at') or (row or {}).get('query_started_at')
            in_flight = bool(row) and (row.get('generation') or 0) > (row.get('observed_generation') or 0)
            if in_flight and AdsStore._within_fresh_window(started, latest):
                return {'product_id': product_id, 'sku_key': sku_key,
                        'generation': row['generation'], 'query_started_at': iso(latest)}
            if self._reusable_fresh(row, started) and not in_flight:
                return {'product_id': product_id, 'sku_key': sku_key,
                        'generation': row['observed_generation'],
                        'query_started_at': iso(row['query_started_at'])}
            cursor.execute('INSERT INTO ads_inventory (execution_scope_id,product_id,sku_key,generation,'
                           'query_started_latest_at) VALUES (%s,%s,%s,1,%s) AS incoming '
                           'ON DUPLICATE KEY UPDATE generation=ads_inventory.generation+1,'
                           'query_started_latest_at=incoming.query_started_latest_at',
                           (actor.execution_scope_id, product_id, sku_key, started))
            cursor.execute('SELECT generation FROM ads_inventory WHERE execution_scope_id=%s AND product_id=%s AND sku_key=%s',(actor.execution_scope_id,product_id,sku_key))
            return {'product_id':product_id,'sku_key':sku_key,'generation':cursor.fetchone()['generation'],'query_started_at':iso(started)}

    def finish_observation(self, actor, ticket, stock, query_completed_at, elapsed_ms):
        # This commits before action validation, including when that action is rejected.
        if stock is not None:
            _integer(stock,'stock',0)
        started = _expiry(ticket['query_started_at'])
        completed = _expiry(query_completed_at) if isinstance(query_completed_at,str) or query_completed_at.tzinfo else query_completed_at
        if not isinstance(elapsed_ms,(int,float)) or isinstance(elapsed_ms,bool) or not 0 <= elapsed_ms < 1e12:
            raise StateError('invalid_observation_elapsed',422)
        with self._transaction() as cursor:
            self._lock(cursor,actor)
            cursor.execute('SELECT * FROM ads_inventory WHERE execution_scope_id=%s AND product_id=%s AND sku_key=%s',(actor.execution_scope_id,ticket['product_id'],ticket['sku_key']))
            row = cursor.fetchone()
            generation = _integer(ticket['generation'],'generation',1)
            if not row or generation > row['generation']:
                raise StateError('observation_not_started',409)
            pause = row['pause_generation']
            if stock == 0:
                pause = row['generation']
                cursor.execute('UPDATE ads_inventory SET pause_generation=%s WHERE execution_scope_id=%s AND product_id=%s AND sku_key=%s',(pause,actor.execution_scope_id,ticket['product_id'],ticket['sku_key']))
                cursor.execute("UPDATE ads_creative cr JOIN ads_campaign ca ON ca.campaign_id=cr.campaign_id SET cr.status='PAUSED',cr.pause_reason='stockout',cr.version=cr.version+1 WHERE ca.execution_scope_id=%s AND ca.product_id=%s AND ca.sku_key=%s AND cr.status IN ('ACTIVE','EXHAUSTED')",(actor.execution_scope_id,ticket['product_id'],ticket['sku_key']))
                cursor.execute("UPDATE ads_campaign SET status='PAUSED',pause_reason='stockout',version=version+1 WHERE execution_scope_id=%s AND product_id=%s AND sku_key=%s AND status IN ('ACTIVE','EXHAUSTED')",(actor.execution_scope_id,ticket['product_id'],ticket['sku_key']))
            accepted = stock == 0 or generation > pause and generation >= row['observed_generation']
            if accepted:
                cursor.execute('UPDATE ads_inventory SET observed_generation=%s,stock=%s,query_started_at=%s,query_completed_at=%s,elapsed_ms=%s WHERE execution_scope_id=%s AND product_id=%s AND sku_key=%s',
                               (generation,stock,started,completed,elapsed_ms,actor.execution_scope_id,ticket['product_id'],ticket['sku_key']))
            return {**ticket,'stock':stock,'query_completed_at':iso(completed),'elapsed_ms':elapsed_ms,'pause_generation':pause,'accepted':accepted}

    def _fresh(self, cursor, actor, campaign, observations):
        obs = next((o for o in observations if o['product_id'] == campaign['product_id'] and o['sku_key'] == campaign['sku_key']),None)
        cursor.execute('SELECT * FROM ads_inventory WHERE execution_scope_id=%s AND product_id=%s AND sku_key=%s',(actor.execution_scope_id,campaign['product_id'],campaign['sku_key']))
        row = cursor.fetchone()
        if (not obs or not row or obs['generation'] != row['observed_generation']
                or not self._reusable_fresh(row, self.clock())):
            raise StateError('fresh_positive_stock_required',409)
        return _public(row)

    def snapshot(self, actor):
        _merchant(actor)
        with self._transaction() as cursor:
            result = {'model_mode':'deterministic','ad_mode':'simulated_cpc'}
            for key,table in (('campaigns','ads_campaign'),('creatives','ads_creative'),('grants','ads_grant'),('actions','growth_action'),('observations','ads_inventory')):
                cursor.execute(f'SELECT * FROM {table} WHERE execution_scope_id=%s',(actor.execution_scope_id,))
                result[key] = [_public(r) for r in cursor.fetchall()]
            cursor.execute('SELECT * FROM ads_account WHERE execution_scope_id=%s',(actor.execution_scope_id,))
            account = cursor.fetchone()
            result['account'] = _public(account) if account else None
            result['recommendation'] = self._recommendation_state(cursor,actor)
            cursor.execute('SELECT COUNT(*) AS impressions FROM ad_interaction WHERE execution_scope_id=%s',(actor.execution_scope_id,))
            result.update(cursor.fetchone())
            cursor.execute('SELECT COUNT(*) AS clicks,COALESCE(SUM(amount_cents),0) AS spend_cents FROM ad_spend WHERE execution_scope_id=%s',(actor.execution_scope_id,))
            result.update({k:int(v) for k,v in cursor.fetchone().items()})
            return result

    def get_action(self, actor, action_id):
        _merchant(actor)
        with self._transaction() as cursor:
            row = self._row(cursor,actor,'growth_action','action_id',action_id)
            if row['actor_id'] != actor.actor_id:
                raise StateError('action_owner_mismatch',403)
            return _public(row)

    def _action_replay(self, cursor, actor, data):
        cursor.execute('SELECT * FROM growth_action WHERE action_id=%s OR idempotency_key=%s',(data['action_id'],data['idempotency_key']))
        rows = cursor.fetchall()
        if not rows:
            return None
        prior = rows[0]
        if len(rows) != 1 or prior['actor_id'] != actor.actor_id or prior['execution_scope_id'] != actor.execution_scope_id or prior['fingerprint'] != sha256(canonical(data).encode()).hexdigest():
            raise StateError('action_idempotency_conflict',409)
        return json.loads(prior['result_json'])

    @staticmethod
    def _action_result(result):
        if result and result['status'] == 'REJECTED':
            raise StateError(result['reason_code'],result.get('http_status',409))
        return result

    def action_replay(self, actor, data):
        _merchant(actor)
        with self._transaction() as cursor:
            return self._action_result(self._action_replay(cursor,actor,data))

    def _save_action(self, cursor, actor, data, result):
        self._insert(cursor,'growth_action',{'action_id':data['action_id'],'idempotency_key':data['idempotency_key'],
            'execution_scope_id':actor.execution_scope_id,'actor_id':actor.actor_id,
            'fingerprint':sha256(canonical(data).encode()).hexdigest(),'request_json':canonical(data),
            'result_json':canonical(result),'created_at':self.clock()})
        return self._action_replay(cursor,actor,data)

    def action_targets(self, actor, data):
        _merchant(actor)
        with self._transaction() as cursor:
            targets = {}
            for action in data['actions']:
                if action['action_type'].startswith(('activate_','resume_')):
                    ca = self._row(cursor,actor,'ads_campaign','campaign_id',action['campaign_id'],owner=True)
                    targets[(ca['product_id'],ca['sku_key'])] = {'product_id':ca['product_id'],'sku_key':ca['sku_key']}
            return list(targets.values())

    def execute_action(self, actor, data, observations):
        _merchant(actor)
        _fields(data,('action_id','idempotency_key','grant_id','plan_id','plan_version','reason_code','evidence_ids','actions'),('agent_run_id','round_id'))
        for field,limit in (('action_id',64),('idempotency_key',128),('grant_id',64),('plan_id',128),('reason_code',128)):
            _text(data[field],field,limit)
        _integer(data['plan_version'],'plan_version',1)
        for field in ('agent_run_id','round_id'):
            if field in data: _text(data[field],field)
        if not isinstance(data['evidence_ids'],list) or len(data['evidence_ids']) > 100:
            raise StateError('invalid_evidence_ids',422)
        for identifier in data['evidence_ids']:
            _text(identifier,'evidence_id')
        if not isinstance(data['actions'],list) or not 1 <= len(data['actions']) <= 8:
            raise StateError('invalid_actions',422)
        with self._transaction() as cursor:
            self._lock(cursor,actor)
            replay = self._action_replay(cursor,actor,data)
            if replay:
                return self._action_result(replay)
            try:
                account,grant,envelope = self._grant(cursor,actor,data['grant_id'],owner=True)
                changes = self._prepare_actions(cursor,actor,data,observations,account,envelope)
                result = {'action_id':data['action_id'],'status':'APPLIED','grant_id':grant['grant_id'],
                          'envelope_hash':grant['envelope_hash'],'reason_code':data['reason_code'],
                          'evidence_ids':data['evidence_ids'],'changes':changes,'completed_at':iso(self.clock())}
            except StateError as error:
                result = {'action_id':data['action_id'],'status':'REJECTED','reason_code':error.code,'http_status':error.status,'changes':[],'completed_at':iso(self.clock())}
            if result['status'] == 'APPLIED':
                for change in changes:
                    if change['kind'] == 'recommendation':
                        after = change['after']
                        StrategyStore._put(cursor,actor.execution_scope_id,after['strategy_version'],after['config'],actor.actor_id)
                        groups = ('control','treatment') if after['group']=='all' else (after['group'],)
                        fields = ','.join(group+'_strategy_version=%s' for group in groups)
                        cursor.execute(f'UPDATE recommendation_experiment SET {fields},revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE execution_scope_id=%s AND experiment_id=%s',
                                       (*[after['strategy_version'] for _ in groups],actor.execution_scope_id,EXPERIMENT_ID))
                        continue
                    table = 'ads_creative' if change['kind'] == 'creative' else 'ads_campaign'
                    key = change['kind'] + '_id'
                    after = change['after']
                    fields = ['status','version','pause_reason','last_action_id'] + (['copy_text'] if change['kind'] == 'creative' else ['budget_cents'])
                    cursor.execute('UPDATE ' + table + ' SET ' + ','.join(f'{f}=%s' for f in fields) + f' WHERE {key}=%s',tuple(after[f] for f in fields) + (after[key],))
            result = self._save_action(cursor,actor,data,result)
        return self._action_result(result)

    def _prepare_actions(self, cursor, actor, data, observations, account, envelope):
        campaigns,creatives,changes = {},{},[]
        seen = set()
        for action in data['actions']:
            if not isinstance(action,dict):
                raise StateError('invalid_ads_action',422)
            kind = action.get('action_type')
            if not isinstance(kind,str):
                raise StateError('invalid_ads_action',422)
            if kind == 'set_recommendation_policy':
                _fields(action,('action_type','expected_version','policy'))
                if kind not in envelope['allowed_action_types']:
                    raise StateError('action_outside_grant',403)
                if ('recommendation',EXPERIMENT_ID) in seen:
                    raise StateError('duplicate_action_target',422)
                seen.add(('recommendation',EXPERIMENT_ID))
                change = self._prepare_policy(cursor,actor,action,envelope)
                changes.append(change)
                continue
            extras = (['creative_id'] if kind.endswith('_creative') else []) + (['budget_cents'] if kind == 'set_budget' else []) + (['copy_text'] if kind == 'replace_creative' else [])
            _fields(action,('action_type','campaign_id','expected_version',*extras))
            if kind not in envelope['allowed_action_types']:
                raise StateError('action_outside_grant',403)
            campaign_id = _text(action['campaign_id'],'campaign_id',64)
            ca = campaigns.setdefault(campaign_id,self._row(cursor,actor,'ads_campaign','campaign_id',campaign_id,owner=True))
            if ca['product_id'] not in envelope['product_scope']:
                raise StateError('product_outside_grant',403)
            self._resource(cursor,actor,ca['product_id'])
            creative_action = kind.endswith('_creative')
            cr = None
            if creative_action:
                crid = _text(action.get('creative_id'),'creative_id',64)
                cr = creatives.setdefault(crid,self._row(cursor,actor,'ads_creative','creative_id',crid,owner=True))
                if cr['campaign_id'] != campaign_id:
                    raise StateError('creative_campaign_mismatch',409)
            target = cr if cr is not None else ca
            key = ('creative',cr['creative_id']) if cr is not None else ('campaign',campaign_id)
            if key in seen:
                raise StateError('duplicate_action_target',422)
            seen.add(key)
            if _integer(action['expected_version'],'expected_version',1) != target['version']:
                raise StateError('ads_version_conflict',409)
            before = _public(dict(target))
            if kind.startswith(('activate_','resume_')):
                expected_states = {'DRAFT'} if kind.startswith('activate_') else {'PAUSED','EXHAUSTED'}
                if target['status'] not in expected_states:
                    raise StateError('invalid_ads_transition',409)
                self._fresh(cursor,actor,ca,observations)
                if ca['budget_cents'] - ca['spent_cents'] < ca['cpc_cents'] or account['budget_cap_cents'] - account['spent_cents'] < ca['cpc_cents']:
                    raise StateError('ads_budget_exhausted',409)
                if cr is not None and ca['status'] != 'ACTIVE':
                    raise StateError('campaign_not_active',409)
                target.update(status='ACTIVE',pause_reason=None)
            elif kind.startswith('pause_'):
                if target['status'] == 'DRAFT':
                    raise StateError('draft_cannot_pause',409)
                target.update(status='PAUSED',pause_reason=data['reason_code'])
            elif kind == 'set_budget':
                value = _money(action.get('budget_cents'))
                if value < ca['spent_cents']:
                    raise StateError('budget_below_spent',409)
                if abs(value-ca['budget_cents']) > envelope['max_budget_change_cents']:
                    raise StateError('budget_change_outside_grant',403)
                ca['budget_cents'] = value
                if ca['status']=='ACTIVE' and value-ca['spent_cents']<ca['cpc_cents']:
                    ca.update(status='EXHAUSTED',pause_reason='budget_exhausted')
            elif kind == 'replace_creative':
                target['copy_text'] = _text(action.get('copy_text'),'copy_text',1000)
            else:
                raise StateError('unsupported_ads_action',422)
            target.update(version=target['version']+1,last_action_id=data['action_id'])
            changes.append({'kind':key[0],'action_type':kind,'before':before,'after':_public(dict(target))})
        cursor.execute('SELECT campaign_id,budget_cents FROM ads_campaign WHERE execution_scope_id=%s',(actor.execution_scope_id,))
        total = sum(campaigns.get(r['campaign_id'],r)['budget_cents'] for r in cursor.fetchall())
        if total > account['budget_cap_cents'] and any(a['action_type'] in {'set_budget','activate_campaign','activate_creative','resume_campaign','resume_creative'} for a in data['actions']):
            raise StateError('aggregate_budget_exceeds_grant',409)
        return changes

    @staticmethod
    def _recommendation_state(cursor, actor):
        cursor.execute('SELECT * FROM recommendation_experiment WHERE execution_scope_id=%s AND experiment_id=%s',(actor.execution_scope_id,EXPERIMENT_ID))
        row = cursor.fetchone()
        result = _public(row) if row else {'experiment_id':EXPERIMENT_ID,'revision':1,'control_strategy_version':'rules-v1','treatment_strategy_version':'content-v1'}
        result.pop('salt',None)
        cursor.execute('SELECT strategy_version,config_json FROM recommendation_strategy WHERE execution_scope_id=%s',(actor.execution_scope_id,))
        result['strategies'] = [_public(r) for r in cursor.fetchall()] or [{'strategy_version':k,'config':v} for k,v in DEFAULT_STRATEGIES.items()]
        return result

    def _prepare_policy(self, cursor, actor, action, envelope):
        if actor.execution_scope_id=='store':
            raise StateError('policy_requires_registered_scope',403)
        policy = _fields(action['policy'],('strategy_version','config','group'))
        limits = policy_range(envelope.get('recommendation_policy_range',{}))
        if not limits or policy['group'] not in limits['groups']:
            raise StateError('policy_outside_grant',403)
        config = strategy_config(policy['config'])
        if (config['ranking'] not in limits['rankings'] or
                any(type(v) is not int or v > limits['max_weight'] for v in config['weights'].values()) or
                any(v > limits['max_quota'] for v in config['quotas'].values())):
            raise StateError('policy_outside_grant',403)
        version = _text(policy['strategy_version'],'strategy_version')
        # The policy controls all recommendations in this scope, so its grant
        # must cover every registered product (store-wide grant checked by service).
        cursor.execute("SELECT resource_id FROM execution_resource WHERE execution_scope_id=%s AND resource_type='product'",(actor.execution_scope_id,))
        if not {r['resource_id'] for r in cursor.fetchall()} <= set(envelope['product_scope']):
            raise StateError('policy_product_scope_outside_grant',403)
        before = self._recommendation_state(cursor,actor)
        if _integer(action['expected_version'],'expected_version',1) != before['revision']:
            raise StateError('experiment_revision_conflict',409)
        cursor.execute('SELECT config_checksum FROM recommendation_strategy WHERE execution_scope_id=%s AND strategy_version=%s',(actor.execution_scope_id,version))
        existing = cursor.fetchone()
        if existing and existing['config_checksum'] != sha256(canonical(config).encode()).hexdigest():
            raise StateError('strategy_version_immutable',409)
        StrategyStore._experiment(cursor,actor.execution_scope_id,EXPERIMENT_ID)
        return {'kind':'recommendation','action_type':'set_recommendation_policy','before':before,
                'after':{'strategy_version':version,'config':config,'group':policy['group'],'revision':before['revision']+1}}

    def revoke_grant(self, actor, grant_id, data):
        _merchant(actor)
        _fields(data,('action_id','idempotency_key','expected_version','reason_code'))
        for field,limit in (('action_id',64),('idempotency_key',128),('reason_code',128)):
            _text(data[field],field,limit)
        request = {**data,'grant_id':_text(grant_id,'grant_id',64),'action_type':'revoke_grant'}
        with self._transaction() as cursor:
            self._lock(cursor,actor)
            replay = self._action_replay(cursor,actor,request)
            if replay:
                return self._action_result(replay)
            grant = self._row(cursor,actor,'ads_grant','grant_id',grant_id)
            cursor.execute('SELECT grant_id FROM ads_account WHERE execution_scope_id=%s',(actor.execution_scope_id,))
            current = cursor.fetchone()
            if not current or current['grant_id'] != grant_id:
                raise StateError('only_current_grant_can_be_revoked',409)
            if grant['approval_actor'] != actor.actor_id:
                raise StateError('grant_owner_mismatch',403)
            if _integer(data['expected_version'],'expected_version',1) != grant['version']:
                raise StateError('ads_version_conflict',409)
            cursor.execute('UPDATE ads_grant SET revoked_at=%s,version=version+1 WHERE grant_id=%s',(self.clock(),grant_id))
            self._pause_all(cursor,actor,'grant_revoked')
            result = {'action_id':data['action_id'],'status':'APPLIED','reason_code':data['reason_code'],
                      'before':_public(grant),'after':_public(self._row(cursor,actor,'ads_grant','grant_id',grant_id))}
            return self._save_action(cursor,actor,request,result)

    @staticmethod
    def _interaction_owner(actor, row):
        if (row['execution_scope_id'],row['subject_type'],row['actor_id']) != (actor.execution_scope_id,actor.subject_type,actor.actor_id):
            raise StateError('ad_interaction_owner_mismatch',403)

    def _exposure(self, cursor, actor, exposure_id):
        row = self._row(cursor,actor,'ad_interaction','exposure_id',exposure_id)
        self._interaction_owner(actor,row)
        return json.loads(row['result_json'])

    def delivery_candidates(self, actor):
        """Read a bounded public candidate list without creating impressions or charges."""
        if _actor(actor)[0] not in {'user', 'visitor'}:
            raise StateError('shopping_actor_required', 403)
        with self._transaction() as cursor:
            try:
                account, _, envelope = self._grant(cursor, actor)
            except StateError as error:
                if error.code in {'active_grant_required', 'grant_revoked_or_expired'}:
                    return []
                raise
            products = envelope['product_scope']
            if not products:
                return []
            marks = ','.join(['%s'] * len(products))
            kind, viewer, _ = _actor(actor)
            # ponytail: rank at most 100 eligible creatives locally; add indexed retrieval only at measured scale.
            # viewer_impressions/viewer_clicks are this viewer's own recorded history with the
            # creative, used only for ordering. Reading them creates no impression and no charge.
            cursor.execute("""SELECT ca.campaign_id,ca.product_id,ca.sku_key,ca.version AS campaign_version,
                cr.creative_id,cr.version AS creative_version,cr.copy_text,
                ca.budget_cents,ca.spent_cents,ca.cpc_cents,
                (SELECT COUNT(*) FROM ad_interaction i WHERE i.execution_scope_id=ca.execution_scope_id
                    AND i.creative_id=cr.creative_id AND i.subject_type=%s AND i.actor_id=%s) AS viewer_impressions,
                (SELECT COUNT(*) FROM ad_spend s WHERE s.execution_scope_id=ca.execution_scope_id
                    AND s.creative_id=cr.creative_id AND s.subject_type=%s AND s.actor_id=%s) AS viewer_clicks
                FROM ads_campaign ca JOIN ads_creative cr ON cr.campaign_id=ca.campaign_id
                WHERE ca.execution_scope_id=%s AND cr.execution_scope_id=%s AND ca.status='ACTIVE' AND cr.status='ACTIVE'
                AND ca.product_id IN (""" + marks + """) AND ca.budget_cents-ca.spent_cents>=ca.cpc_cents
                AND ca.cpc_cents<=%s ORDER BY ca.created_at,ca.campaign_id,cr.creative_id LIMIT 100""",
                (kind, viewer, kind, viewer, actor.execution_scope_id, actor.execution_scope_id, *products,
                 account['budget_cap_cents'] - account['spent_cents']))
            return list(cursor.fetchall())

    @staticmethod
    def _exposure_input(data):
        _fields(data, ('exposure_id', 'creative_id'), ('expected_campaign_version', 'expected_creative_version'))
        for key in ('exposure_id', 'creative_id'):
            _text(data[key], key, 64)
        for key in ('expected_campaign_version', 'expected_creative_version'):
            if key in data:
                _integer(data[key], key, 1)

    @staticmethod
    def _displayed_versions(data, campaign_version, creative_version):
        if (data.get('expected_campaign_version', campaign_version) != campaign_version
                or data.get('expected_creative_version', creative_version) != creative_version):
            raise StateError('ad_exposure_version_changed', 409)

    def exposure_target(self, actor, data):
        self._exposure_input(data)
        with self._transaction() as cursor:
            cr = self._row(cursor,actor,'ads_creative','creative_id',data['creative_id'])
            ca = self._row(cursor,actor,'ads_campaign','campaign_id',cr['campaign_id'])
            return {'product_id':ca['product_id'],'sku_key':ca['sku_key']}

    def click_target(self, actor, data):
        _fields(data,('click_id','exposure_id'))
        for key in data: _text(data[key],key,64)
        with self._transaction() as cursor:
            receipt = self._exposure(cursor,actor,data['exposure_id'])
            return {'product_id':receipt['product_id'],'sku_key':receipt['sku_key']}

    def _click_replay(self, cursor, actor, data):
        cursor.execute('SELECT * FROM ad_spend WHERE click_id=%s',(data['click_id'],))
        row = cursor.fetchone()
        if row:
            self._interaction_owner(actor,row)
            if row['exposure_id'] != data['exposure_id']:
                raise StateError('click_idempotency_conflict',409)
            return json.loads(row['result_json'])
        return None

    def click_replay(self, actor, data):
        _fields(data,('click_id','exposure_id'))
        for key in data: _text(data[key],key,64)
        with self._transaction() as cursor:
            return self._click_replay(cursor,actor,data)

    def record_inventory_rejection(self, actor, operation, request, observation):
        if observation.get('stock')!=0 or not observation.get('accepted'):
            return
        key=sha256(canonical([*_actor(actor),operation,request]).encode()).hexdigest()
        with self._transaction() as cursor:
            self._lock(cursor,actor)
            cursor.execute('INSERT IGNORE INTO growth_diagnostic_fact VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                (key,actor.execution_scope_id,actor.subject_type,actor.actor_id,'AD_INVENTORY_REJECTED','observed_stockout',
                 canonical({'operation':operation,'request':request,'observation':observation}),self.clock()))

    def _eligible(self, cursor, actor, creative_id, observation):
        if actor.subject_type not in {'user','visitor'}:
            raise StateError('shopping_actor_required',403)
        cr = self._row(cursor,actor,'ads_creative','creative_id',creative_id)
        ca = self._row(cursor,actor,'ads_campaign','campaign_id',cr['campaign_id'])
        self._resource(cursor,actor,ca['product_id'])
        account,grant,envelope = self._grant(cursor,actor)
        if ca['product_id'] not in envelope['product_scope']:
            raise StateError('product_outside_grant',403)
        if ca['status'] != 'ACTIVE' or cr['status'] != 'ACTIVE':
            raise StateError('ads_not_active',409)
        stock = self._fresh(cursor,actor,ca,[observation])
        if ca['budget_cents'] - ca['spent_cents'] < ca['cpc_cents'] or account['budget_cap_cents'] - account['spent_cents'] < ca['cpc_cents']:
            raise StateError('ads_budget_exhausted',409)
        return ca,cr,account,grant,stock

    def expose(self, actor, data, observation):
        self._exposure_input(data)
        with self._transaction() as cursor:
            self._lock(cursor,actor)
            cursor.execute('SELECT * FROM ad_interaction WHERE exposure_id=%s',(data['exposure_id'],))
            prior = cursor.fetchone()
            if prior:
                self._interaction_owner(actor,prior)
                if prior['creative_id'] != data['creative_id']:
                    raise StateError('exposure_idempotency_conflict',409)
                saved = json.loads(prior['result_json'])
                self._displayed_versions(data, saved['campaign_version'], saved['creative_version'])
                return saved
            ca,cr,account,grant,stock = self._eligible(cursor,actor,data['creative_id'],observation)
            self._displayed_versions(data, ca['version'], cr['version'])
            result = {**data,'execution_scope_id':actor.execution_scope_id,'campaign_id':ca['campaign_id'],
                'campaign_version':ca['version'],'creative_version':cr['version'],'copy_text':cr['copy_text'],
                'product_id':ca['product_id'],'sku_key':ca['sku_key'],'grant_id':grant['grant_id'],
                'envelope_hash':grant['envelope_hash'],'account_id':account['account_id'],'cpc_cents':ca['cpc_cents'],
                'amount_cents':0,'traffic_channel':'AD_SIMULATED','ad_label':'模拟推广','created_at':iso(self.clock()),
                'last_action_id':cr['last_action_id'] or ca['last_action_id'],
                'campaign_last_action_id':ca['last_action_id'],'creative_last_action_id':cr['last_action_id'],'inventory_observation':stock}
            self._insert(cursor,'ad_interaction',{'exposure_id':data['exposure_id'],'creative_id':data['creative_id'],
                'execution_scope_id':actor.execution_scope_id,'subject_type':actor.subject_type,'actor_id':actor.actor_id,
                'result_json':canonical(result),'created_at':self.clock()})
            # MySQL JSON may normalize a double's final digit. First responses
            # must use the same persisted representation as every replay.
            return self._exposure(cursor,actor,data['exposure_id'])

    def click(self, actor, data, observation):
        _fields(data,('click_id','exposure_id'))
        for key in data: _text(data[key],key,64)
        with self._transaction() as cursor:
            self._lock(cursor,actor)
            replay = self._click_replay(cursor,actor,data)
            if replay:
                return replay
            exposure = self._exposure(cursor,actor,data['exposure_id'])
            cursor.execute('SELECT click_id FROM ad_spend WHERE exposure_id=%s',(data['exposure_id'],))
            if cursor.fetchone():
                raise StateError('exposure_already_clicked',409)
            ca,cr,account,grant,stock = self._eligible(cursor,actor,exposure['creative_id'],observation)
            if exposure['campaign_version'] != ca['version'] or exposure['creative_version'] != cr['version'] or exposure['grant_id'] != grant['grant_id']:
                raise StateError('ad_exposure_version_changed',409)
            if self.clock() - _expiry(exposure['created_at']) > timedelta(hours=1):
                raise StateError('ad_exposure_expired',410)
            fee = ca['cpc_cents']
            metadata = {'click_id':data['click_id'],'exposure_id':data['exposure_id'],'amount_cents':fee,
                        'grant_id':grant['grant_id'],'envelope_hash':grant['envelope_hash'],
                        'campaign_version':ca['version'],'creative_version':cr['version'],'last_action_id':exposure['last_action_id'],
                        'campaign_last_action_id':exposure['campaign_last_action_id'],
                        'creative_last_action_id':exposure['creative_last_action_id']}
            touch = self._touch(cursor,actor,'AD_CLICK','ads-cpc:'+data['click_id'],traffic_channel='AD_SIMULATED',
                origin='ads_executor',campaign_id=ca['campaign_id'],creative_id=cr['creative_id'],
                product_id=ca['product_id'],sku_key=ca['sku_key'],metadata=metadata)
            result = {**data,**metadata,'touch_id':touch['touch_id'],'traffic_touch_id':touch['touch_id'],
                      'campaign_id':ca['campaign_id'],'creative_id':cr['creative_id'],'account_id':account['account_id'],
                      'execution_scope_id':actor.execution_scope_id,'occurred_at':touch['occurred_at'],
                      'inventory_observation':stock,'status':'CHARGED','ad_mode':'simulated_cpc'}
            self._insert(cursor,'ad_spend',{'click_id':data['click_id'],'exposure_id':data['exposure_id'],
                'execution_scope_id':actor.execution_scope_id,'subject_type':actor.subject_type,'actor_id':actor.actor_id,
                'account_id':account['account_id'],'grant_id':grant['grant_id'],'campaign_id':ca['campaign_id'],
                'creative_id':cr['creative_id'],'amount_cents':fee,'touch_id':touch['touch_id'],'result_json':canonical(result),'occurred_at':self.clock()})
            cursor.execute('UPDATE ads_campaign SET spent_cents=spent_cents+%s WHERE campaign_id=%s',(fee,ca['campaign_id']))
            cursor.execute('UPDATE ads_account SET spent_cents=spent_cents+%s,version=version+1 WHERE execution_scope_id=%s',(fee,actor.execution_scope_id))
            cursor.execute("UPDATE ads_campaign SET status='EXHAUSTED',pause_reason='budget_exhausted',version=version+1 WHERE execution_scope_id=%s AND status='ACTIVE' AND (budget_cents-spent_cents < cpc_cents OR cpc_cents > %s)",(actor.execution_scope_id,account['budget_cap_cents']-account['spent_cents']-fee))
            return self._click_replay(cursor,actor,data)
