"""DB-backed runtime model selection: the admin console picks which whitelisted chat model
is active. API keys, endpoints and the embedding model stay in run/model.env — nothing
secret is stored here, and the Provider falls back to the env snapshot whenever the table
is empty or unreachable.
"""
import asyncio

from smartlect.provider import CHAT_MODEL_WHITELIST
from smartlect.state import SessionStore, StateError, _actor, _public, _text


class ModelConfigStore(SessionStore):
    def chat_config(self):
        with self._transaction() as cursor:
            cursor.execute("SELECT role,model_id,params_json,note,updated_by,updated_at "
                           "FROM model_runtime_config WHERE role='chat'")
            row = cursor.fetchone()
            return _public(row) if row else None

    def save_chat(self, actor, model_id, note=None):
        _actor(actor)
        model_id = _text(model_id, "model_id", 64)
        if model_id not in CHAT_MODEL_WHITELIST:
            raise StateError("model_id_not_authorized", 422)
        note = None if note is None else _text(note, "note", 256)
        with self._transaction() as cursor:
            cursor.execute("SELECT role FROM model_runtime_config WHERE role='chat' FOR UPDATE", ())
            cursor.execute("""INSERT INTO model_runtime_config (role,model_id,params_json,note,updated_by,updated_at)
                VALUES ('chat',%s,NULL,%s,%s,UTC_TIMESTAMP(6)) AS incoming
                ON DUPLICATE KEY UPDATE model_id=incoming.model_id,note=incoming.note,
                updated_by=incoming.updated_by,updated_at=UTC_TIMESTAMP(6)""", (model_id, note, actor.actor_id))
        return self.chat_config()

    def loader(self):
        """Async callable for Provider's runtime layer; returns {} on any DB problem."""
        def load():
            row = self.chat_config()
            return {"chat_model_id": row["model_id"]} if row else {}
        async def async_load():
            return await asyncio.to_thread(load)
        return async_load
