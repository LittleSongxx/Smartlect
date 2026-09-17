"""Persistent fixed A/B groups and immutable ranking configurations; no outcome claims."""
from hashlib import sha256
import json
import math
import secrets

from smartlect.events import canonical
from smartlect.state import SessionStore, StateError, _actor, _integer, _json, _public, _text
from smartlect.recommendation.service import FEATURES, ROUTES

EXPERIMENT_ID = 'shopping-recommendation-v1'
DEFAULT_STRATEGIES = {
    'rules-v1': {'ranking': 'rule', 'weights': dict(content=3, category=3, copurchase=4, popularity=5,
        newness=1, preference=2, affordability=1),
        'quotas': dict(content=12, category=8, copurchase=10, popular=12, newest=8)},
    'content-v1': {'ranking': 'content', 'weights': dict(content=8, category=4, copurchase=3, popularity=1,
        newness=1, preference=5, affordability=1),
        'quotas': dict(content=16, category=12, copurchase=10, popular=6, newest=6)},
}


def strategy_config(value):
    if not isinstance(value, dict) or set(value) != {'ranking', 'weights', 'quotas'}:
        raise StateError('invalid_recommendation_strategy', 422)
    if value['ranking'] not in {'rule', 'content'}:
        raise StateError('invalid_recommendation_strategy', 422)
    weights, quotas = value['weights'], value['quotas']
    if (not isinstance(weights, dict) or set(weights) != set(FEATURES)
            or any(type(weight) not in {int, float} or not math.isfinite(weight) or not 0 <= weight <= 20 for weight in weights.values())
            or not sum(weights.values())):
        raise StateError('invalid_recommendation_weights', 422)
    if (not isinstance(quotas, dict) or set(quotas) != set(ROUTES)
            or any(type(quota) is not int or not 0 <= quota <= 20 for quota in quotas.values())
            or not 1 <= sum(quotas.values()) <= 50):
        raise StateError('invalid_recommendation_quotas', 422)
    return json.loads(_json(value))


def bucket_for(scope, experiment_id, subject_key, salt):
    return int(sha256(canonical([scope, experiment_id, subject_key, salt]).encode()).hexdigest()[:8], 16) % 100


class StrategyStore(SessionStore):
    @staticmethod
    def _put(cursor, scope, version, config, actor_id):
        encoded = canonical(strategy_config(config))
        checksum = sha256(encoded.encode()).hexdigest()
        cursor.execute("""INSERT INTO recommendation_strategy (execution_scope_id,strategy_version,config_json,
            config_checksum,created_by,created_at) VALUES (%s,%s,%s,%s,%s,UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE strategy_version=strategy_version""",
            (scope, _text(version, 'strategy_version', 128), encoded, checksum, actor_id))
        cursor.execute("SELECT * FROM recommendation_strategy WHERE execution_scope_id=%s AND strategy_version=%s", (scope, version))
        row = cursor.fetchone()
        if row['config_checksum'] != checksum:
            raise StateError('strategy_version_immutable')
        return _public(row)

    @staticmethod
    def _experiment(cursor, scope, experiment_id):
        # Defaults are inserted once; restart cannot rotate salt or overwrite policy.
        for version, config in DEFAULT_STRATEGIES.items():
            StrategyStore._put(cursor, scope, version, config, 'system')
        cursor.execute("""INSERT IGNORE INTO recommendation_experiment (execution_scope_id,experiment_id,salt,
            control_strategy_version,treatment_strategy_version,created_at,updated_at)
            VALUES (%s,%s,%s,'rules-v1','content-v1',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
            (scope, experiment_id, secrets.token_hex(32)))
        cursor.execute("SELECT * FROM recommendation_experiment WHERE execution_scope_id=%s AND experiment_id=%s FOR UPDATE",
                       (scope, experiment_id))
        return cursor.fetchone()

    def assign(self, actor, *, subject_key=None, experiment_id=EXPERIMENT_ID):
        kind, identifier, scope = _actor(actor)
        if 'shopping:read' not in getattr(actor, 'permissions', ()) and not (
                kind == 'merchant' and (
                    'admin:legacy' in getattr(actor, 'permissions', ())
                    or 'admin:trial' in getattr(actor, 'permissions', ()))):
            raise StateError('permission_denied', 403)
        subject_key = _text(subject_key if subject_key is not None else kind + ':' + identifier, 'subject_key', 128)
        experiment_id = _text(experiment_id, 'experiment_id', 128)
        with self._transaction() as cursor:
            experiment = self._experiment(cursor, scope, experiment_id)
            cursor.execute("SELECT * FROM recommendation_assignment WHERE execution_scope_id=%s AND experiment_id=%s AND subject_key=%s FOR UPDATE",
                           (scope, experiment_id, subject_key))
            prior = cursor.fetchone()
            bucket = prior['bucket'] if prior else bucket_for(scope, experiment_id, subject_key, experiment['salt'])
            group = prior['group_name'] if prior else 'control' if bucket < 50 else 'treatment'
            if group not in {'control', 'treatment'}:
                raise StateError('invalid_persisted_assignment', 503)
            version = experiment[group + '_strategy_version']
            assignment_id = prior['assignment_id'] if prior else sha256(canonical([scope, experiment_id, subject_key]).encode()).hexdigest()[:32]
            if prior:
                if prior['strategy_version'] != version:
                    # Preserve group/assignment; each recommendation receipt retains its
                    # own strategy version when a later approved policy is activated.
                    cursor.execute("UPDATE recommendation_assignment SET strategy_version=%s,updated_at=UTC_TIMESTAMP(6) WHERE assignment_id=%s",
                                   (version, assignment_id))
            else:
                cursor.execute("""INSERT INTO recommendation_assignment (assignment_id,execution_scope_id,experiment_id,
                    subject_key,group_name,bucket,strategy_version,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
                    (assignment_id, scope, experiment_id, subject_key, group, bucket, version))
            cursor.execute("SELECT config_json,config_checksum FROM recommendation_strategy WHERE execution_scope_id=%s AND strategy_version=%s", (scope, version))
            row = cursor.fetchone()
            config = strategy_config(json.loads(row['config_json']))
            if sha256(canonical(config).encode()).hexdigest() != row['config_checksum']:
                raise StateError('strategy_checksum_mismatch', 503)
            return {'assignment_id': assignment_id, 'experiment_id': experiment_id, 'group': group,
                    'bucket': bucket, 'strategy_version': version, 'experiment_revision': experiment['revision'], 'config': config}

    def put_strategy(self, actor, version, config):
        kind, identifier, scope = _actor(actor)
        if kind != 'merchant' or 'admin:legacy' not in actor.permissions:
            raise StateError('permission_denied', 403)
        with self._transaction() as cursor:
            return self._put(cursor, scope, version, config, identifier)

    def configure_experiment(self, actor, *, control_version, treatment_version, expected_revision, experiment_id=EXPERIMENT_ID):
        kind, _, scope = _actor(actor)
        if kind != 'merchant' or 'admin:legacy' not in actor.permissions:
            raise StateError('permission_denied', 403)
        experiment_id = _text(experiment_id, 'experiment_id', 128)
        control_version, treatment_version = _text(control_version, 'strategy_version', 128), _text(treatment_version, 'strategy_version', 128)
        _integer(expected_revision, 'expected_revision', 1)
        with self._transaction() as cursor:
            experiment = self._experiment(cursor, scope, experiment_id)
            if experiment['revision'] != expected_revision:
                raise StateError('experiment_revision_conflict')
            cursor.execute("SELECT strategy_version FROM recommendation_strategy WHERE execution_scope_id=%s AND strategy_version IN (%s,%s)",
                           (scope, control_version, treatment_version))
            if {row['strategy_version'] for row in cursor.fetchall()} != {control_version, treatment_version}:
                raise StateError('strategy_not_found', 404)
            cursor.execute("""UPDATE recommendation_experiment SET control_strategy_version=%s,treatment_strategy_version=%s,
                revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE execution_scope_id=%s AND experiment_id=%s""",
                (control_version, treatment_version, scope, experiment_id))
            return {'experiment_id': experiment_id, 'revision': expected_revision + 1,
                    'control_strategy_version': control_version, 'treatment_strategy_version': treatment_version}
