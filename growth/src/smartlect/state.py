"""Owned conversations and recoverable actions; this store never executes commerce."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import uuid

from smartlect.events import canonical, connect_from_env
from smartlect.migrate import migrate
from smartlect.privacy import redact_text


class StateError(RuntimeError):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


OUTCOMES = {"command_accepted", "business_pending", "business_completed", "rejected", "unknown"}
EVENT_TYPES = {"message_delta", "tool_started", "tool_result", "proposal_required",
               "operation_pending", "completed", "error"}
RUN_END_STATES = {"WAIT_USER", "WAIT_OUTCOME", "COMPLETED", "FAILED", "CANCELLED"}


def _text(value, name, limit=128):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise StateError("invalid_" + name, 422)
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise StateError("invalid_" + name, 422) from error
    return value


def _integer(value, name, minimum=0, maximum=9223372036854775807):
    if type(value) is not int or not minimum <= value <= maximum:
        raise StateError("invalid_" + name, 422)
    return value


def _actor(actor):
    def field(name, default=None):
        return actor.get(name, default) if isinstance(actor, dict) else getattr(actor, name, default)
    kind = field("subject_type")
    if kind not in {"user", "merchant", "visitor"}:
        raise StateError("invalid_actor", 403)
    return kind, _text(field("actor_id"), "actor_id", 64), _text(field("execution_scope_id", "store"), "scope", 128)


def _json(value):
    if not isinstance(value, dict):
        raise StateError("invalid_object", 422)
    try:
        result = canonical(value)
        json.loads(result, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        if len(result.encode("utf-8")) > 65536:
            raise ValueError("oversized")
        return result
    except (TypeError, ValueError, UnicodeError) as error:
        raise StateError("invalid_object", 422) from error


def _expiry(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone required")
        result = result.astimezone(timezone.utc).replace(tzinfo=None)
        if result.year < 1000:
            raise ValueError("outside MySQL datetime range")
        return result
    except (TypeError, ValueError, OverflowError) as error:
        raise StateError("invalid_expires_at", 422) from error


def _public(row):
    result = {}
    for name, value in row.items():
        if name.startswith("lease_") or name == "db_now":
            continue
        if name.endswith("_json"):
            name = name[:-5]
            value = json.loads(value) if isinstance(value, (str, bytes)) else value
        if isinstance(value, datetime):
            value = value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        result[name] = bool(value) if name == "approved" and value is not None else value
    return result


class SessionStore:
    def __init__(self, connect=connect_from_env):
        self.connect = connect

    def initialize(self):
        migrate(self.connect)

    @contextmanager
    def _transaction(self):
        with self.connect() as connection, connection.cursor() as cursor:
            try:
                yield cursor
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _conversation(cursor, actor, conversation_id, lock=False):
        owner = _actor(actor)
        cursor.execute("SELECT *,UTC_TIMESTAMP(6) AS db_now FROM conversation WHERE conversation_id=%s "
                       "AND subject_type=%s AND actor_id=%s AND execution_scope_id=%s" + (" FOR UPDATE" if lock else ""),
                       (_text(conversation_id, "conversation_id", 32), *owner))
        row = cursor.fetchone()
        if not row:
            raise StateError("conversation_not_found", 404)
        return row

    @classmethod
    def _owned_record(cls, cursor, actor, record_id, kind):
        # Table and key are selected only by the fixed internal callers below.
        table, key = {"run": ("agent_run", "agent_run_id"), "proposal": ("proposal", "proposal_id")}[kind]
        owner = _actor(actor)
        cursor.execute(f"SELECT owned.* FROM {table} AS owned JOIN conversation AS c "
                       f"ON c.conversation_id=owned.conversation_id WHERE owned.{key}=%s "
                       "AND c.subject_type=%s AND c.actor_id=%s AND c.execution_scope_id=%s",
                       (_text(record_id, key, 32), *owner))
        row = cursor.fetchone()
        if not row:
            raise StateError(kind + "_not_found", 404)
        return row

    @staticmethod
    def _locked(cursor, lease):
        if not isinstance(lease, dict):
            raise StateError("invalid_lease", 409)
        cursor.execute("""SELECT *,UTC_TIMESTAMP(6) AS db_now FROM conversation
            WHERE conversation_id=%s AND lease_run_id=%s AND lease_owner=%s AND lease_token=%s
            AND lease_epoch=%s AND lease_until>UTC_TIMESTAMP(6) FOR UPDATE""",
                       (_text(lease.get("conversation_id"), "conversation_id", 32),
                        _text(lease.get("agent_run_id"), "agent_run_id", 32),
                        _text(lease.get("owner"), "lease_owner"), _text(lease.get("token"), "lease_token", 32),
                        _integer(lease.get("epoch"), "lease_epoch", 1)))
        conversation = cursor.fetchone()
        if not conversation:
            raise StateError("lease_lost")
        cursor.execute("SELECT * FROM agent_run WHERE agent_run_id=%s AND conversation_id=%s FOR UPDATE",
                       (lease["agent_run_id"], lease["conversation_id"]))
        run = cursor.fetchone()
        if not run or run["state"] != "RUNNING":
            raise StateError("run_not_running")
        return conversation, run

    @staticmethod
    def _unlock(cursor, conversation_id):
        cursor.execute("""UPDATE conversation SET lease_run_id=NULL,lease_owner=NULL,lease_token=NULL,
            lease_until=NULL,version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE conversation_id=%s""",
                       (conversation_id,))

    @staticmethod
    def _message(cursor, conversation_id, run_id, message_id, role, text):
        text = redact_text(text)
        message_id, text = _text(message_id, "message_id"), _text(text, "text", 16000)
        fingerprint = sha256(canonical({"role": role, "text": text}).encode()).hexdigest()
        cursor.execute("SELECT * FROM message WHERE conversation_id=%s AND message_id=%s", (conversation_id, message_id))
        prior = cursor.fetchone()
        if prior:
            if prior["content_hash"] != fingerprint or prior["agent_run_id"] != run_id:
                raise StateError("message_id_conflict")
            return _public(prior)
        cursor.execute("UPDATE conversation SET message_sequence=message_sequence+1,version=version+1,"
                       "updated_at=UTC_TIMESTAMP(6) WHERE conversation_id=%s", (conversation_id,))
        cursor.execute("""INSERT INTO message (conversation_id,message_id,sequence,agent_run_id,role,content,content_hash,created_at)
            SELECT conversation_id,%s,message_sequence,%s,%s,%s,%s,UTC_TIMESTAMP(6)
            FROM conversation WHERE conversation_id=%s""", (message_id, run_id, role, text, fingerprint, conversation_id))
        cursor.execute("SELECT * FROM message WHERE conversation_id=%s AND message_id=%s", (conversation_id, message_id))
        return _public(cursor.fetchone())

    def create_conversation(self, actor, *, identity_key=None):
        owner = _actor(actor)
        conversation_id = sha256(canonical([*owner, identity_key]).encode()).hexdigest()[:32] if identity_key else uuid.uuid4().hex
        with self._transaction() as cursor:
            cursor.execute("""INSERT INTO conversation (conversation_id,subject_type,actor_id,execution_scope_id,created_at,updated_at)
                VALUES (%s,%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE conversation_id=conversation_id""", (conversation_id, *owner))
            return _public(self._conversation(cursor, actor, conversation_id))

    def get_conversation(self, actor, conversation_id):
        with self._transaction() as cursor:
            result = _public(self._conversation(cursor, actor, conversation_id))
            cursor.execute("SELECT * FROM message WHERE conversation_id=%s ORDER BY sequence DESC LIMIT 100", (conversation_id,))
            result["messages"] = [_public(row) for row in reversed(cursor.fetchall())]
            cursor.execute("SELECT * FROM agent_run WHERE conversation_id=%s ORDER BY created_at DESC LIMIT 30", (conversation_id,))
            result["runs"] = [{key: value for key, value in _public(row).items() if key in {
                "agent_run_id", "state", "result", "model_mode", "created_at"}} for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM proposal WHERE conversation_id=%s ORDER BY created_at DESC LIMIT 20", (conversation_id,))
            result["proposals"] = [_public(row) for row in cursor.fetchall()]
            return result

    def list_conversations(self, actor):
        kind, identifier, scope = _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("SELECT conversation_id,created_at,updated_at FROM conversation c "
                           "WHERE subject_type=%s AND actor_id=%s AND execution_scope_id=%s "
                           "AND NOT EXISTS(SELECT 1 FROM proposal p WHERE p.conversation_id=c.conversation_id AND p.action_type='payment') "
                           "ORDER BY updated_at DESC LIMIT 30", (kind, identifier, scope))
            return [_public(row) for row in cursor.fetchall()]

    def create_run(self, actor, conversation_id, message_id, text, *, parent_run_id=None, model_mode="mock"):
        _actor(actor)
        message_id, text = _text(message_id, "message_id"), _text(text, "text", 16000)
        if model_mode not in {"mock", "live", "rule-fallback"}:
            raise StateError("invalid_model_mode", 422)
        fingerprint = sha256(canonical({"text": text, "parent_run_id": parent_run_id, "model_mode": model_mode}).encode()).hexdigest()
        with self._transaction() as cursor:
            conversation = self._conversation(cursor, actor, conversation_id, lock=True)
            cursor.execute("SELECT * FROM agent_run WHERE conversation_id=%s AND message_id=%s", (conversation_id, message_id))
            prior = cursor.fetchone()
            if prior:
                if prior["request_hash"] != fingerprint:
                    raise StateError("message_id_conflict")
                return _public(prior)
            cursor.execute("SELECT ticket_id FROM support_ticket WHERE conversation_id=%s AND status IN ('OPEN','TAKEN_OVER') LIMIT 1",
                           (conversation_id,))
            if cursor.fetchone():
                raise StateError('human_control_active')
            if conversation['lease_until'] and conversation['lease_until'] > conversation['db_now']:
                raise StateError('conversation_busy')
            cursor.execute("SELECT agent_run_id FROM agent_run WHERE conversation_id=%s "
                           "AND state IN ('CREATED','RUNNING') LIMIT 1", (conversation_id,))
            if cursor.fetchone():
                raise StateError('conversation_busy')
            if conversation['lease_run_id']:
                cursor.execute("UPDATE agent_run SET state='FAILED',version=version+1,result_json=%s "
                               "WHERE agent_run_id=%s AND state='RUNNING'",
                               (canonical({'error': 'interrupted_run'}), conversation['lease_run_id']))
                self._unlock(cursor, conversation_id)
            if parent_run_id is not None:
                parent = self._owned_record(cursor, actor, parent_run_id, "run")
                if parent["conversation_id"] != conversation_id:
                    raise StateError("parent_run_not_found", 404)
            run_id = uuid.uuid4().hex
            cursor.execute("""INSERT INTO agent_run (agent_run_id,conversation_id,parent_run_id,message_id,request_hash,
                model_mode,context_json,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,'{}',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
                           (run_id, conversation_id, parent_run_id, message_id, fingerprint, model_mode))
            self._message(cursor, conversation_id, run_id, message_id, "user", text)
            return _public(self._owned_record(cursor, actor, run_id, "run"))

    def get_run(self, actor, run_id):
        with self._transaction() as cursor:
            run = self._owned_record(cursor, actor, run_id, 'run')
            conversation = self._conversation(cursor, actor, run['conversation_id'], lock=True)
            cursor.execute('SELECT * FROM agent_run WHERE agent_run_id=%s FOR UPDATE', (run_id,))
            run = cursor.fetchone()
            if run['state'] == 'RUNNING' and run['deadline'] and run['deadline'] <= conversation['db_now']:
                cursor.execute("UPDATE agent_run SET state='FAILED',version=version+1,result_json=%s WHERE agent_run_id=%s",
                               (canonical({'error': 'run_deadline_exceeded'}), run_id))
                if conversation['lease_run_id'] == run_id:
                    self._unlock(cursor, run['conversation_id'])
                cursor.execute('SELECT * FROM agent_run WHERE agent_run_id=%s', (run_id,))
                run = cursor.fetchone()
            return _public(run)

    def claim_run(self, actor, run_id, *, owner, ttl_seconds=30):
        owner = _text(owner, "lease_owner")
        ttl_seconds = _integer(ttl_seconds, "lease_ttl", 1, 90)
        with self._transaction() as cursor:
            run = self._owned_record(cursor, actor, run_id, "run")
            conversation = self._conversation(cursor, actor, run["conversation_id"], lock=True)
            cursor.execute("SELECT * FROM agent_run WHERE agent_run_id=%s FOR UPDATE", (run_id,))
            run = cursor.fetchone()
            if run["state"] not in {"CREATED", "RUNNING"}:
                raise StateError("run_not_claimable")
            if conversation["lease_until"] and conversation["lease_until"] > conversation["db_now"]:
                raise StateError("conversation_busy")
            if run["deadline"] and run["deadline"] <= conversation["db_now"]:
                raise StateError("run_deadline_exceeded")
            token, epoch = uuid.uuid4().hex, conversation["lease_epoch"] + 1
            cursor.execute("""UPDATE conversation SET lease_run_id=%s,lease_owner=%s,lease_token=%s,lease_epoch=%s,
                lease_until=TIMESTAMPADD(SECOND,%s,UTC_TIMESTAMP(6)),version=version+1,updated_at=UTC_TIMESTAMP(6)
                WHERE conversation_id=%s AND version=%s""",
                           (run_id, owner, token, epoch, ttl_seconds, conversation["conversation_id"], conversation["version"]))
            if cursor.rowcount != 1:
                raise StateError("conversation_version_conflict")
            cursor.execute("""UPDATE agent_run SET state='RUNNING',version=version+1,
                deadline=COALESCE(deadline,TIMESTAMPADD(SECOND,90,UTC_TIMESTAMP(6))),updated_at=UTC_TIMESTAMP(6)
                WHERE agent_run_id=%s""", (run_id,))
            cursor.execute("SELECT lease_until FROM conversation WHERE conversation_id=%s", (conversation["conversation_id"],))
            until = cursor.fetchone()["lease_until"].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            return {"conversation_id": conversation["conversation_id"], "agent_run_id": run_id,
                    "owner": owner, "token": token, "epoch": epoch, "lease_until": until}

    def renew_lease(self, lease, *, ttl_seconds=30):
        ttl_seconds = _integer(ttl_seconds, "lease_ttl", 1, 90)
        with self._transaction() as cursor:
            conversation, _ = self._locked(cursor, lease)
            cursor.execute("UPDATE conversation SET lease_until=TIMESTAMPADD(SECOND,%s,UTC_TIMESTAMP(6)),"
                           "version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE conversation_id=%s",
                           (ttl_seconds, conversation["conversation_id"]))
            cursor.execute("SELECT lease_until FROM conversation WHERE conversation_id=%s", (conversation["conversation_id"],))
            until = cursor.fetchone()["lease_until"].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            return {**lease, "lease_until": until}

    def increment_trial_chat(self, actor_id, *, daily_limit=30):
        actor_id = _text(actor_id, "actor_id", 64)
        daily_limit = _integer(daily_limit, "trial_chat_limit", 1, 1000)
        with self._transaction() as cursor:
            cursor.execute("""INSERT INTO trial_chat_budget (actor_id, budget_date, turns, updated_at)
                VALUES (%s, UTC_DATE(), 0, UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE actor_id=actor_id""", (actor_id,))
            cursor.execute("""UPDATE trial_chat_budget SET turns=turns+1, updated_at=UTC_TIMESTAMP(6)
                WHERE actor_id=%s AND budget_date=UTC_DATE() AND turns < %s""", (actor_id, daily_limit))
            if cursor.rowcount != 1:
                raise StateError("trial_chat_limit", 429)
            cursor.execute("SELECT turns FROM trial_chat_budget WHERE actor_id=%s AND budget_date=UTC_DATE()",
                           (actor_id,))
            return cursor.fetchone()["turns"]

    def release_run(self, lease):
        with self._transaction() as cursor:
            conversation, _ = self._locked(cursor, lease)
            self._unlock(cursor, conversation["conversation_id"])

    def finish_run(self, lease, *, state, result=None):
        if state not in RUN_END_STATES:
            raise StateError("invalid_run_state", 422)
        payload = _json(result) if result is not None else None
        with self._transaction() as cursor:
            conversation, run = self._locked(cursor, lease)
            cursor.execute("UPDATE agent_run SET state=%s,result_json=%s,version=version+1,updated_at=UTC_TIMESTAMP(6) "
                           "WHERE agent_run_id=%s AND version=%s", (state, payload, run["agent_run_id"], run["version"]))
            if cursor.rowcount != 1:
                raise StateError("run_version_conflict")
            self._unlock(cursor, conversation["conversation_id"])
            cursor.execute("SELECT * FROM agent_run WHERE agent_run_id=%s", (run["agent_run_id"],))
            return _public(cursor.fetchone())

    def save_context(self, lease, context):
        payload = _json(context)
        with self._transaction() as cursor:
            _, run = self._locked(cursor, lease)
            cursor.execute("UPDATE agent_run SET context_json=%s,version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE agent_run_id=%s",
                           (payload, run["agent_run_id"]))

    def append_message(self, lease, text, *, message_id, role="assistant"):
        if role not in {"assistant", "tool"}:
            raise StateError("invalid_message_role", 422)
        with self._transaction() as cursor:
            conversation, run = self._locked(cursor, lease)
            return self._message(cursor, conversation["conversation_id"], run["agent_run_id"], message_id, role, text)

    def append_event(self, lease, event_type, data):
        if event_type not in EVENT_TYPES:
            raise StateError("invalid_event_type", 422)
        payload = _json(data)
        with self._transaction() as cursor:
            conversation, run = self._locked(cursor, lease)
            sequence = run["event_sequence"] + 1
            cursor.execute("INSERT INTO agent_run_event (agent_run_id,sequence,event_type,data_json,created_at) "
                           "VALUES (%s,%s,%s,%s,UTC_TIMESTAMP(6))", (run["agent_run_id"], sequence, event_type, payload))
            cursor.execute("UPDATE agent_run SET event_sequence=%s,version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE agent_run_id=%s",
                           (sequence, run["agent_run_id"]))
            return {"agent_run_id": run["agent_run_id"], "conversation_id": conversation["conversation_id"],
                    "sequence": sequence, "event_type": event_type, "data": json.loads(payload)}

    def events(self, actor, run_id, after=0):
        after = _integer(after, "after")
        with self._transaction() as cursor:
            run = self._owned_record(cursor, actor, run_id, "run")
            cursor.execute("SELECT * FROM agent_run_event WHERE agent_run_id=%s AND sequence>%s ORDER BY sequence LIMIT 1000",
                           (run_id, after))
            return [{**_public(row), "conversation_id": run["conversation_id"]} for row in cursor.fetchall()]

    def create_proposal(self, lease, *, action_type, parameters, expires_at, quote_id=None, quote_total_cents=None):
        if action_type not in {"order", "cancel", "refund", "payment"}:
            raise StateError("invalid_action_type", 422)
        parameters_json, expires_at = _json(parameters), _expiry(expires_at)
        if action_type == "order":
            quote_id = _text(quote_id, "quote_id")
            quote_total_cents = _integer(quote_total_cents, "quote_total_cents")
        elif quote_id is not None or quote_total_cents is not None:
            raise StateError("unexpected_quote", 422)
        with self._transaction() as cursor:
            conversation, run = self._locked(cursor, lease)
            if conversation["subject_type"] != "user":
                raise StateError("user_required", 403)
            parameters_hash = sha256(parameters_json.encode()).hexdigest()
            cursor.execute("SELECT * FROM proposal WHERE agent_run_id=%s AND action_type=%s AND parameters_hash=%s",
                           (run["agent_run_id"], action_type, parameters_hash))
            prior = cursor.fetchone()
            if prior:
                return _public(prior)
            if expires_at <= conversation["db_now"]:
                raise StateError("proposal_expired", 410)
            binding = {"subject_type": conversation["subject_type"], "actor_id": conversation["actor_id"],
                       "execution_scope_id": conversation["execution_scope_id"], "conversation_id": conversation["conversation_id"],
                       "action_type": action_type, "parameters": json.loads(parameters_json), "quote_id": quote_id,
                       "quote_total_cents": quote_total_cents, "expires_at": expires_at.isoformat() + "Z"}
            fingerprint = sha256(canonical(binding).encode()).hexdigest()
            proposal_id, action_id = uuid.uuid4().hex, uuid.uuid4().hex
            cursor.execute("""INSERT INTO proposal (proposal_id,conversation_id,agent_run_id,action_type,parameters_json,
                parameters_hash,proposal_hash,quote_id,quote_total_cents,expires_at,action_id,idempotency_key,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
                           (proposal_id, conversation["conversation_id"], run["agent_run_id"], action_type, parameters_json,
                            parameters_hash, fingerprint, quote_id, quote_total_cents,
                            expires_at, action_id, "smartlect-" + action_id))
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s", (proposal_id,))
            return _public(cursor.fetchone())

    def get_proposal(self, actor, proposal_id):
        with self._transaction() as cursor:
            return _public(self._owned_record(cursor, actor, proposal_id, "proposal"))

    def confirm_proposal(self, actor, proposal_id, expected_version, *, approved=True):
        if _actor(actor)[0] != "user":
            raise StateError("user_required", 403)
        expected_version = _integer(expected_version, "proposal_version", 1)
        if type(approved) is not bool:
            raise StateError("invalid_approval", 422)
        expired = False
        with self._transaction() as cursor:
            proposal = self._owned_record(cursor, actor, proposal_id, "proposal")
            conversation = self._conversation(cursor, actor, proposal["conversation_id"], lock=True)
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s FOR UPDATE", (proposal_id,))
            proposal = cursor.fetchone()
            if proposal["decision_version"] == expected_version and bool(proposal["approved"]) == approved:
                return _public(proposal)
            if proposal["status"] != "PROPOSED" or proposal["version"] != expected_version:
                raise StateError("proposal_version_conflict")
            expired = proposal["expires_at"] <= conversation["db_now"]
            if expired:
                cursor.execute("UPDATE proposal SET status='EXPIRED',version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE proposal_id=%s",
                               (proposal_id,))
            else:
                cursor.execute("""UPDATE proposal SET status=%s,version=version+1,decision_version=%s,approved=%s,
                    confirmed_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6) WHERE proposal_id=%s AND version=%s""",
                               ("CONFIRMED" if approved else "REJECTED", expected_version, approved, proposal_id, expected_version))
                if cursor.rowcount != 1:
                    raise StateError("proposal_version_conflict")
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s", (proposal_id,))
            result = _public(cursor.fetchone())
        if expired:
            raise StateError("proposal_expired", 410)
        return result

    def begin_action(self, lease, proposal_id):
        expired = False
        with self._transaction() as cursor:
            conversation, _ = self._locked(cursor, lease)
            if conversation["subject_type"] != "user":
                raise StateError("user_required", 403)
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s AND conversation_id=%s FOR UPDATE",
                           (_text(proposal_id, "proposal_id", 32), conversation["conversation_id"]))
            proposal = cursor.fetchone()
            if not proposal:
                raise StateError("proposal_not_found", 404)
            if proposal["status"] in {"EXECUTING", "UNKNOWN", "SUCCEEDED", "FAILED"}:
                return {**_public(proposal), "recover_only": True}
            if proposal["status"] != "CONFIRMED":
                raise StateError("proposal_not_confirmed")
            expired = proposal["expires_at"] <= conversation["db_now"]
            cursor.execute("UPDATE proposal SET status=%s,version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE proposal_id=%s AND version=%s",
                           ("EXPIRED" if expired else "EXECUTING", proposal_id, proposal["version"]))
            if cursor.rowcount != 1:
                raise StateError("proposal_version_conflict")
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s", (proposal_id,))
            result = {**_public(cursor.fetchone()), "recover_only": False}
        if expired:
            raise StateError("proposal_expired", 410)
        return result

    def record_action_result(self, lease, proposal_id, *, outcome, receipt):
        if outcome not in OUTCOMES:
            raise StateError("invalid_outcome", 422)
        payload = _json(receipt)
        state = {"command_accepted": "EXECUTING", "business_pending": "EXECUTING", "business_completed": "SUCCEEDED",
                 "rejected": "FAILED", "unknown": "UNKNOWN"}[outcome]
        with self._transaction() as cursor:
            conversation, _ = self._locked(cursor, lease)
            if conversation["subject_type"] != "user":
                raise StateError("user_required", 403)
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s AND conversation_id=%s FOR UPDATE",
                           (_text(proposal_id, "proposal_id", 32), conversation["conversation_id"]))
            proposal = cursor.fetchone()
            if not proposal:
                raise StateError("proposal_not_found", 404)
            if proposal["status"] in {"SUCCEEDED", "FAILED"}:
                if proposal["status"] == state and proposal["outcome"] == outcome and canonical(json.loads(proposal["receipt_json"])) == payload:
                    return _public(proposal)
                raise StateError("action_already_terminal")
            if proposal["status"] not in {"EXECUTING", "UNKNOWN"}:
                raise StateError("action_not_started")
            cursor.execute("UPDATE proposal SET status=%s,outcome=%s,receipt_json=%s,version=version+1,updated_at=UTC_TIMESTAMP(6) "
                           "WHERE proposal_id=%s AND version=%s", (state, outcome, payload, proposal_id, proposal["version"]))
            if cursor.rowcount != 1:
                raise StateError("proposal_version_conflict")
            cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s", (proposal_id,))
            return _public(cursor.fetchone())

    def start_tool_call(self, lease, call_id, tool_name, arguments):
        call_id, tool_name = _text(call_id, "call_id"), _text(tool_name, "tool_name")
        payload = _json(arguments)
        fingerprint = sha256(payload.encode()).hexdigest()
        with self._transaction() as cursor:
            _, run = self._locked(cursor, lease)
            cursor.execute("SELECT * FROM tool_call WHERE agent_run_id=%s AND call_id=%s", (run["agent_run_id"], call_id))
            prior = cursor.fetchone()
            if prior:
                if prior["tool_name"] != tool_name or prior["arguments_hash"] != fingerprint:
                    raise StateError("tool_call_id_conflict")
                return _public(prior)
            cursor.execute("""INSERT INTO tool_call (agent_run_id,call_id,tool_name,arguments_hash,arguments_json,started_at)
                VALUES (%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))""", (run["agent_run_id"], call_id, tool_name, fingerprint, payload))
            cursor.execute("SELECT * FROM tool_call WHERE agent_run_id=%s AND call_id=%s", (run["agent_run_id"], call_id))
            return _public(cursor.fetchone())

    def finish_tool_call(self, lease, call_id, *, outcome, receipt):
        call_id = _text(call_id, "call_id")
        if outcome not in OUTCOMES:
            raise StateError("invalid_outcome", 422)
        payload = _json(receipt)
        with self._transaction() as cursor:
            _, run = self._locked(cursor, lease)
            cursor.execute("SELECT * FROM tool_call WHERE agent_run_id=%s AND call_id=%s FOR UPDATE", (run["agent_run_id"], call_id))
            prior = cursor.fetchone()
            if not prior:
                raise StateError("tool_call_not_found", 404)
            if prior["outcome"] != "started":
                if prior["outcome"] == outcome and canonical(json.loads(prior["receipt_json"])) == payload:
                    return _public(prior)
                raise StateError("tool_call_already_terminal")
            cursor.execute("UPDATE tool_call SET outcome=%s,receipt_json=%s,completed_at=UTC_TIMESTAMP(6) WHERE agent_run_id=%s AND call_id=%s",
                           (outcome, payload, run["agent_run_id"], call_id))
            cursor.execute("SELECT * FROM tool_call WHERE agent_run_id=%s AND call_id=%s", (run["agent_run_id"], call_id))
            return _public(cursor.fetchone())
