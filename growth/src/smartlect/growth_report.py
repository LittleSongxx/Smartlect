"""Growth report: deterministic data snapshot plus LLM narration.

The snapshot is assembled in code from authoritative sources — the attribution summary
(scope-filtered payments/refunds), the commerce event ledger counts, ads account state and
AI-domain activity counts. The model only receives those numbers and returns 3-5 plain
suggestions; it is told explicitly not to invent figures, and the snapshot stays valid even
when no live model is configured.
"""
import asyncio
import json

from smartlect.events import canonical
from smartlect.state import SessionStore, StateError, _actor, _public

REPORT_VERSION = "growth-report-v1"

SUGGESTION_SYSTEM = (
    "你是电商经营分析助手。只依据给出的数据快照输出 JSON："
    '{"suggestions": [字符串, 3至5条]}。'
    "每条建议指出依据的数据项与下一步动作；数据中没有的信息不要编造，不要发明数字。"
)


class GrowthReportStore(SessionStore):
    def save(self, actor, data, suggestions, model_label):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("""INSERT INTO growth_report_snapshot
                (execution_scope_id,data_json,suggestions,model_label,updated_by,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)) AS incoming
                ON DUPLICATE KEY UPDATE data_json=incoming.data_json,suggestions=incoming.suggestions,
                model_label=incoming.model_label,updated_by=incoming.updated_by,updated_at=UTC_TIMESTAMP(6)""",
                (actor.execution_scope_id, canonical(data), suggestions, model_label, actor.actor_id))
        return self.get(actor)

    def get(self, actor):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("SELECT * FROM growth_report_snapshot WHERE execution_scope_id=%s",
                (actor.execution_scope_id,))
            row = cursor.fetchone()
            return _public(row) if row else None

    def history(self, actor, limit=10):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("""SELECT execution_scope_id,data_json,suggestions,model_label,updated_by,
                created_at,updated_at FROM growth_report_snapshot WHERE execution_scope_id=%s
                ORDER BY updated_at DESC LIMIT %s""", (actor.execution_scope_id, min(max(int(limit), 1), 50)))
            return [_public(row) for row in cursor.fetchall()]


def build_snapshot(payment_totals, ai_activity):
    """Assemble the deterministic data view; every number here comes from a store, not the model.

    ``payment_totals`` is ``AttributionStore.totals()`` (one flat line per money figure), not
    ``summary()``: that one groups by category x calculation_status, so its paidCents /
    netCents live inside the group rows and are only additive within that single grouping.
    """
    return {
        "payments": {
            "paid_cents": payment_totals.get("paid_cents"),
            "refunded_cents": payment_totals.get("refunded_cents"),
            "net_cents": payment_totals.get("net_cents"),
            "conversions": payment_totals.get("payment_conversions"),
        },
        "ai_activity": ai_activity,
        "report_version": REPORT_VERSION,
    }


def _validated_suggestions(text):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise StateError("invalid_suggestions_json", 422) from None
    suggestions = data.get("suggestions") if isinstance(data, dict) else None
    if (not isinstance(suggestions, list) or not 3 <= len(suggestions) <= 5 or any(
            not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in suggestions)):
        raise StateError("invalid_suggestions", 422)
    return suggestions


async def generate(actor, attribution, store, provider, *, settings, ads=None):
    payment_totals = await asyncio.to_thread(attribution.totals, actor)
    ai_activity = await asyncio.to_thread(ai_activity_counts, store.connect, actor.execution_scope_id)
    snapshot = build_snapshot(payment_totals, ai_activity)
    if ads is not None:
        try:
            snapshot["ads"] = await asyncio.to_thread(ads.snapshot, actor).get("account")
        except Exception:
            snapshot["ads"] = None  # the report stays valid without the ads view

    suggestions, model_label, model_error = None, None, None
    if settings.model_mode == "live" and provider is not None:
        try:
            response = await provider.chat(
                [{"role": "system", "content": SUGGESTION_SYSTEM},
                 {"role": "user", "content": "数据快照：\n" + canonical(snapshot)}],
                response_format={"type": "json_object"}, max_tokens=900, max_attempts=1,
                prompt_version=REPORT_VERSION, schema_version="growth-suggestions-v1")
            suggestions = _validated_suggestions(response["message"]["content"])
            model_label = f"{provider.effective_chat_model()}@live"
        except StateError:
            raise
        except Exception as error:
            model_error = getattr(error, "code", type(error).__name__)
    else:
        model_error = "model_not_live"

    row = await asyncio.to_thread(GrowthReportStore(store.connect).save, actor, snapshot,
                                  canonical(suggestions) if suggestions else None, model_label)
    row["model_error"] = model_error
    return row


def ai_activity_counts(connect, scope):
    """Conversation / run / handoff / knowledge counts for the scope, read once per report."""
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS conversations FROM conversation WHERE execution_scope_id=%s", (scope,))
        conversations = cursor.fetchone()["conversations"]
        cursor.execute("""SELECT state,COUNT(*) AS count FROM agent_run r
            JOIN conversation c ON c.conversation_id=r.conversation_id
            WHERE c.execution_scope_id=%s GROUP BY r.state""", (scope,))
        run_states = {row["state"]: row["count"] for row in cursor.fetchall()}
        cursor.execute("""SELECT COUNT(*) AS tickets FROM support_ticket t
            JOIN conversation c ON c.conversation_id=t.conversation_id
            WHERE c.execution_scope_id=%s""", (scope,))
        tickets = cursor.fetchone()["tickets"]
        cursor.execute("SELECT COUNT(*) AS documents FROM knowledge_document WHERE execution_scope_id=%s "
                       "AND status='PUBLISHED'", (scope,))
        documents = cursor.fetchone()["documents"]
    return {"conversations": conversations, "run_states": run_states,
            "support_tickets": tickets, "published_documents": documents}
