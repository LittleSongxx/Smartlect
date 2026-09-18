"""Admin execution-scope selection; the surviving slice of the retired merchant line.

Scope registration backs the demo scenario harness; scope selection lets the admin
workspace operate on a registered scope instead of the live store.
"""
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

from smartlect.state import SessionStore, StateError, _text


class ScopeSelectRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    execution_scope_id: str = Field(min_length=1, max_length=128)


class AdminScopeStore(SessionStore):
    def grant_scope_access(self, actor_id, scope, label):
        """Local scenario registration only; never a model or public API capability."""
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO merchant_scope_access VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE label=label",
                (
                    _text(actor_id, "actor_id", 64),
                    _text(scope, "scope"),
                    _text(label, "label", 200),
                ),
            )

    def scopes(self, actor):
        self._require_admin_actor(actor, write=False)
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT execution_scope_id,label FROM merchant_scope_access WHERE actor_id=%s ORDER BY execution_scope_id",
                (actor.actor_id,),
            )
            return {
                "items": [
                    {"execution_scope_id": "store", "label": "默认店铺"},
                    *list(cursor.fetchall()),
                ]
            }

    def selected_actor(self, actor):
        if actor.subject_type != "merchant":
            return actor
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT s.execution_scope_id FROM merchant_scope_selection s JOIN merchant_scope_access a ON a.actor_id=s.actor_id AND a.execution_scope_id=s.execution_scope_id WHERE s.session_hash=%s AND s.actor_id=%s",
                (sha256(actor.session_id.encode()).hexdigest(), actor.actor_id),
            )
            row = cursor.fetchone()
            return actor.model_copy(
                update={
                    "execution_scope_id": row["execution_scope_id"] if row else "store"
                }
            )

    def select_scope(self, actor, scope):
        self._require_admin_actor(actor)
        _text(scope, "scope")
        if scope not in {r["execution_scope_id"] for r in self.scopes(actor)["items"]}:
            raise StateError("scope_not_authorized", 403)
        with self._transaction() as cursor:
            key = sha256(actor.session_id.encode()).hexdigest()
            if scope == "store":
                cursor.execute(
                    "DELETE FROM merchant_scope_selection WHERE session_hash=%s AND actor_id=%s",
                    (key, actor.actor_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO merchant_scope_selection VALUES (%s,%s,%s) AS incoming "
                    "ON DUPLICATE KEY UPDATE execution_scope_id=incoming.execution_scope_id",
                    (key, actor.actor_id, scope),
                )
        return actor.model_copy(update={"execution_scope_id": scope})

    @staticmethod
    def _require_admin_actor(actor, write=True):
        if actor.subject_type != 'merchant':
            raise StateError('merchant_permission_required', 403)
        perms = getattr(actor, 'permissions', ())
        if write:
            if 'admin:legacy' not in perms:
                raise StateError('merchant_permission_required', 403)
        elif not {'admin:legacy', 'admin:trial'} & set(perms):
            raise StateError('merchant_permission_required', 403)
