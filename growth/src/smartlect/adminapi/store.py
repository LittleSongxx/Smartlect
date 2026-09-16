"""Read model for the admin run browser: scope-filtered agent_run audit without message bodies.

The browser is an ops surface for admin:legacy merchants. It reuses the same tables the
agents write (agent_run / tool_call / agent_run_event) but deliberately never selects from
`message`, so user conversation text stays out of this surface. Context fields are exposed
through a whitelist; anything dropped is named in context_hidden_keys so the omission is
visible instead of silent.
"""
from datetime import datetime

from smartlect.state import SessionStore, StateError, _actor, _public, _text

# Operational context keys an operator needs; anything else (mission text, utterance
# snippets, focus payloads) stays in the DB and is only named, not shown.
CONTEXT_KEYS = (
    "model_mode", "model_calls", "model_attempts", "model_errors",
    "prompt_version", "schema_version", "skill_versions", "budget", "wait_reason",
)
RESULT_KEYS = ("decision", "checks", "receipt", "error", "error_type", "answer_status", "citations")

AGENT_KINDS = ("shopping", "merchant", "mcp", "debug")


def _agent_kind(row):
    if row.get("is_merchant"):
        return "merchant"
    message_id = row.get("message_id") or ""
    if message_id.startswith("debug:"):
        return "debug"
    if message_id.startswith("mcp:"):
        return "mcp"
    return "shopping"


def _usage(context):
    attempts = (context or {}).get("model_attempts") or []
    totals = {"input_tokens": 0, "output_tokens": 0, "cost_estimate_cny": 0.0, "model_attempts": len(attempts)}
    for attempt in attempts:
        attempt = attempt or {}
        usage = attempt.get("usage") or {}
        totals["input_tokens"] += usage.get("input_tokens") or 0
        totals["output_tokens"] += usage.get("output_tokens") or 0
        totals["cost_estimate_cny"] += attempt.get("cost_estimate_cny") or 0.0
    return totals


class AdminRunStore(SessionStore):
    """Scope-scoped queries; all methods take the merchant actor and filter by execution_scope_id."""

    def list_runs(self, actor, agent=None, state=None, limit=50):
        _actor(actor)
        agent, state = agent or None, state or None
        if agent is not None and agent not in AGENT_KINDS:
            raise StateError("invalid_agent_filter", 422)
        limit = min(max(int(limit or 50), 10), 200)
        clauses = ["(c.execution_scope_id=%s OR m.execution_scope_id=%s)"]
        params = [actor.execution_scope_id, actor.execution_scope_id]
        if state:
            clauses.append("r.state=%s")
            params.append(_text(state, "state", 32))
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT r.*, c.subject_type AS conversation_subject, c.actor_id AS conversation_actor, "
                "(m.agent_run_id IS NOT NULL) AS is_merchant FROM agent_run r "
                "JOIN conversation c ON c.conversation_id=r.conversation_id "
                "LEFT JOIN merchant_run_context m ON m.agent_run_id=r.agent_run_id "
                "WHERE " + " AND ".join(clauses) + " ORDER BY r.created_at DESC LIMIT %s",
                (*params, limit),
            )
            rows = cursor.fetchall()
        result = [self._row(row) for row in rows]
        if agent is not None:
            result = [row for row in result if row["agent"] == agent]
        return {"items": result, "agent_kinds": list(AGENT_KINDS)}

    def run_detail(self, actor, run_id):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT r.*, c.subject_type AS conversation_subject, c.actor_id AS conversation_actor, "
                "(m.agent_run_id IS NOT NULL) AS is_merchant FROM agent_run r "
                "JOIN conversation c ON c.conversation_id=r.conversation_id "
                "LEFT JOIN merchant_run_context m ON m.agent_run_id=r.agent_run_id "
                "WHERE r.agent_run_id=%s AND (c.execution_scope_id=%s OR m.execution_scope_id=%s)",
                (_text(run_id, "agent_run_id", 32), actor.execution_scope_id, actor.execution_scope_id),
            )
            row = cursor.fetchone()
            if not row:
                raise StateError("run_not_found", 404)
            cursor.execute(
                "SELECT * FROM tool_call WHERE agent_run_id=%s ORDER BY started_at, call_id",
                (row["agent_run_id"],),
            )
            tool_calls = [_public(call) for call in cursor.fetchall()]
            cursor.execute(
                "SELECT sequence, event_type, data_json, created_at FROM agent_run_event "
                "WHERE agent_run_id=%s ORDER BY sequence",
                (row["agent_run_id"],),
            )
            events = [_public(event) for event in cursor.fetchall()]
        detail = self._row(row)
        detail["tool_calls"] = tool_calls
        detail["events"] = events
        context = row.get("context") or {}
        detail["model_attempts"] = context.get("model_attempts") or []
        return detail

    def _row(self, row):
        # _public decodes the *_json columns, renames them and normalizes datetimes.
        row = _public(row)
        # context_json starts as '{}' (create_run) and is scrubbed back to '{}' by the 30-day
        # purge, so "empty" cannot tell a fresh run from a scrubbed one; expose the fact and
        # let the UI phrase it. User message bodies are never selected by this surface.
        context = row.get("context") if isinstance(row.get("context"), dict) else {}
        context_empty = not context
        hidden = [] if context_empty else sorted(key for key in context if key not in CONTEXT_KEYS)
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        public = {key: value for key, value in row.items()
                  if key in {"agent_run_id", "conversation_id", "message_id", "state", "model_mode",
                             "created_at", "updated_at", "deadline", "conversation_subject", "conversation_actor"}}
        public["agent"] = _agent_kind(row)
        public["context_empty"] = context_empty
        public["usage"] = _usage(context)
        public["context"] = {} if context_empty else {key: context[key] for key in CONTEXT_KEYS if key in context}
        public["context_hidden_keys"] = hidden
        public["result"] = {key: result[key] for key in RESULT_KEYS if key in result}
        public["duration_ms"] = _duration_ms(row)
        return public


def _duration_ms(row):
    started, finished = row.get("created_at"), row.get("updated_at")
    if not started or not finished:
        return None
    started = datetime.fromisoformat(started.replace("Z", "+00:00"))
    finished = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    return int((finished - started).total_seconds() * 1000)
