"""Owned preferences, bounded extractive context, and persistent local human handoff.

Token estimator adapted from frozen shop-ai-python app/memory/token_estimator.py,
commit 94d36aee925c75d286f48d2aee2eeea059a74dd9. Copyright (c) 2026 Audreator,
MIT; see licenses/shop-ai-python-LICENSE. Context storage and scope rules replaced.
"""
from datetime import timedelta
import json
import math
import re
import uuid

from smartlect.db import canonical
from smartlect.knowledge import KnowledgeStore, _merchant
from smartlect.shopping_mission import empty_mission, normalize_mission
from smartlect.state import SessionStore, StateError, _actor, _expiry, _integer, _json, _public, _text

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_ASCII_RE = re.compile(r"[A-Za-z0-9]")
_SYMBOL_RE = re.compile(r"[^\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaffA-Za-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")
PREFERENCE_KEYS = {"purpose", "budget_max_cents", "likes", "avoid", "categories"}


def estimate_text_tokens(text):
    """tiktoken cl100k_base. Not a billing source; provider usage remains authoritative."""
    if not text:
        return 0
    from smartlect.tokenizer import count_tokens
    return count_tokens(text)


def working_context(messages, *, turns=8, token_budget=6500, excerpt_budget=1400):
    """Keep complete chronological turns; summaries quote older user requests only.

    Compression here is extractive on purpose. Durable constraints are not carried by this
    summary: explicit and inferred preferences live in user_preference with the verbatim
    quote they came from, and transaction facts always come from Java. So a model-written
    abstract would restate what is already held in a checkable form while adding a way to
    drift from it. What extraction cannot do is hide loss, so every older request that does
    not fit is counted in `dropped` with its sequence range, letting the agent see that
    earlier turns exist and ask instead of assuming the history it sees is complete.
    """
    groups = []
    for message in messages:
        if message["role"] == "user":
            groups.append([])
        if groups:
            groups[-1].append(message)
    selected, used = [], 0
    for group in reversed(groups[-turns:]):
        cost = sum(estimate_text_tokens(row["content"]) + 4 for row in group)
        if used + cost > token_budget:
            break
        selected.insert(0, group)
        used += cost
    recent = [row for group in selected for row in group]
    first_sequence = recent[0]["sequence"] if recent else groups[-1][0]["sequence"] if groups else 0
    all_earlier = [row for row in messages if row["sequence"] < first_sequence and row["role"] == "user"]
    earlier = all_earlier[-32:]
    excerpts, summary_cost = [], 0
    for row in reversed(earlier):
        # Extractive historical requests cannot invent payment/refund completion.
        content = row["content"][:240]
        cost = estimate_text_tokens(content)
        if summary_cost + cost > excerpt_budget:
            break
        excerpts.insert(0, {"message_id": row["message_id"], "sequence": row["sequence"], "quote": content,
                            "truncated": len(content) < len(row["content"])})
        summary_cost += cost
    if not all_earlier:
        return recent, None
    quoted = {row["message_id"] for row in excerpts}
    dropped = [row for row in all_earlier if row["message_id"] not in quoted]
    # A summary is emitted whenever earlier requests exist, even when none of them fit. That
    # case is exactly when the agent most needs to know the history it sees is partial.
    summary = {"kind": "user_request_excerpts", "not_business_facts": True,
               "message_ids": [row["message_id"] for row in excerpts], "excerpts": excerpts,
               "from_sequence": excerpts[0]["sequence"] if excerpts else None,
               "to_sequence": excerpts[-1]["sequence"] if excerpts else None,
               "dropped": {"request_count": len(dropped),
                           "from_sequence": dropped[0]["sequence"] if dropped else None,
                           "to_sequence": dropped[-1]["sequence"] if dropped else None,
                           "reason": "excerpt_token_budget" if len(earlier) == len(all_earlier) else "older_than_retained_window"}}
    return recent, summary


def _preference(key, value):
    if key not in PREFERENCE_KEYS:
        raise StateError("invalid_preference_key", 422)
    if key == "budget_max_cents":
        _integer(value, "budget_max_cents", 0, 100000000)
    elif key == "purpose":
        _text(value, "purpose", 500)
    elif not isinstance(value, list) or len(value) > 20:
        raise StateError("invalid_preference_value", 422)
    else:
        for item in value:
            _text(item, "preference_value", 100)
    return canonical(value)


def preference_conflicts(key, value, existing):
    """跨键一致性检查（组件 10，纯函数）：新写入与现存偏好的 likes∩avoid 折叠交集。

    existing 为 _preferences 输出形态（[{preference_key, value, ...}]）。
    单键内的新值覆盖旧值不算冲突（那是 UPDATE 语义）；likes 与 avoid 出现
    同一词条才是用户立场自相矛盾——按「标冲突并要求澄清」处理，不静默覆盖。
    返回冲突描述列表（空列表 = 无冲突）。
    """
    def fold(text):
        return str(text).strip().casefold()

    if key not in {"likes", "avoid"} or not isinstance(value, list):
        return []
    other = "avoid" if key == "likes" else "likes"
    opposite = {fold(item) for row in existing or []
                if row.get("preference_key") == other for item in (row.get("value") or [])}
    if not opposite:
        return []
    overlap = sorted({fold(item) for item in value} & opposite)
    if not overlap:
        return []
    return [{"keys": sorted([key, other]), "terms": overlap}]


class MemoryStore(SessionStore):
    def finish_answer(self, lease, actor, result: dict, context: dict):
        """Commit one grounded final answer, its events and terminal run atomically."""
        result = json.loads(_json(result))
        context_json = _json(context)
        answer = _text(result.get("answer"), "answer", 16000)
        citations = result.get("citations", [])
        if not isinstance(citations, list) or len(citations) > 4:
            raise StateError("invalid_citations", 422)
        if result.get("answer_status") not in {"answered", "insufficient", "conflicting", "needs_human"}:
            raise StateError("invalid_answer_status", 422)
        with self._transaction() as cursor:
            conversation, run = self._locked(cursor, lease)
            if (conversation["subject_type"], conversation["actor_id"], conversation["execution_scope_id"]) != _actor(actor):
                raise StateError("conversation_not_found", 404)
            handoff = self._handoff(cursor, conversation["conversation_id"])
            supplied_ticket = result.get("ticket") or {}
            if handoff and not (isinstance(supplied_ticket, dict) and handoff["status"] == "OPEN"
                    and supplied_ticket.get("ticket_id") == handoff["ticket_id"]
                    and result["answer_status"] in {"insufficient", "conflicting", "needs_human"}
                    and not result.get("proposal")):
                raise StateError("human_control_active")
            if supplied_ticket and not handoff:
                raise StateError("handoff_state_changed")
            if handoff:
                result["ticket"] = handoff
            if citations:
                cursor.execute("SELECT revision FROM knowledge_catalog WHERE execution_scope_id=%s FOR SHARE",
                               (conversation["execution_scope_id"],))
                if not cursor.fetchone() or not KnowledgeStore._validate_citations(cursor, actor, citations):
                    raise StateError("citation_no_longer_visible")
            proposal = result.get("proposal")
            if proposal:
                if not isinstance(proposal, dict):
                    raise StateError("invalid_proposal", 422)
                cursor.execute("SELECT * FROM proposal WHERE proposal_id=%s AND conversation_id=%s FOR UPDATE",
                    (_text(proposal.get("proposal_id"), "proposal_id", 32), conversation["conversation_id"]))
                authoritative = cursor.fetchone()
                if not authoritative or authoritative["agent_run_id"] != run["agent_run_id"]:
                    raise StateError("proposal_not_found", 404)
                result["proposal"] = _public(authoritative)
            model_mode = result.get("model_mode", run["model_mode"])
            if model_mode not in {"mock", "live", "rule-fallback"}:
                raise StateError("invalid_model_mode", 422)
            message = self._message(cursor, conversation["conversation_id"], run["agent_run_id"],
                                    "answer:" + run["agent_run_id"], "assistant", answer)
            result["answer"] = message["content"]
            result_json = _json(result)
            final_event = "proposal_required" if proposal else "completed"
            # 成本反范式列（组件 12）：run 级 token/成本入列，管理端 GROUP BY 归因不再解 JSON。
            audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
            total_tokens = sum(int(((attempt.get("usage") or {}).get("total_tokens")) or 0)
                               for attempt in (context.get("model_attempts") or []))
            cursor.executemany("""INSERT INTO agent_run_event (agent_run_id,sequence,event_type,data_json,created_at)
                VALUES (%s,%s,%s,%s,UTC_TIMESTAMP(6))""", [
                # replace=True：权威全文收口——前端收到后重置增量游标为该全文，
                # 与此前流式预览的增量（session.on_token）保持幂等对账。
                (run["agent_run_id"], run["event_sequence"] + 1, "message_delta",
                 _json({"text": result["answer"], "replace": True})),
                (run["agent_run_id"], run["event_sequence"] + 2, final_event, result_json)])
            cursor.execute("""UPDATE agent_run SET context_json=%s,result_json=%s,model_mode=%s,state=%s,
                event_sequence=%s,cost_estimate_cny=%s,total_tokens=%s,version=version+1,updated_at=UTC_TIMESTAMP(6)
                WHERE agent_run_id=%s AND version=%s""", (context_json, result_json, model_mode,
                "WAIT_USER" if proposal else "COMPLETED", run["event_sequence"] + 2,
                audit.get("cost_estimate_cny"), total_tokens, run["agent_run_id"], run["version"]))
            if cursor.rowcount != 1:
                raise StateError("run_version_conflict")
            self._unlock(cursor, conversation["conversation_id"])
            cursor.execute("SELECT * FROM agent_run WHERE agent_run_id=%s", (run["agent_run_id"],))
            return _public(cursor.fetchone())

    @staticmethod
    def _memory(cursor, conversation_id):
        cursor.execute("INSERT IGNORE INTO conversation_memory (conversation_id,updated_at) VALUES (%s,UTC_TIMESTAMP(6))", (conversation_id,))
        cursor.execute("SELECT * FROM conversation_memory WHERE conversation_id=%s FOR UPDATE", (conversation_id,))
        return cursor.fetchone()

    @staticmethod
    def _preferences(cursor, actor):
        if _actor(actor)[0] != "user":
            return []
        cursor.execute("""SELECT preference_key,value_json,source,confidence,evidence_ids_json,observed_at,expires_at,version
            FROM user_preference WHERE subject_type=%s AND actor_id=%s AND execution_scope_id=%s AND deleted_at IS NULL
            AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP(6)) ORDER BY preference_key""", _actor(actor))
        return [{**_public(row), "confidence": float(row["confidence"])} for row in cursor.fetchall()]

    def preferences(self, actor):
        if _actor(actor)[0] != "user":
            raise StateError("login_required", 401)
        with self._transaction() as cursor:
            return self._preferences(cursor, actor)

    def set_preference(self, actor, key, value, *, source="explicit", evidence_ids=None,
                       conversation_id=None, confidence=1.0, expires_at=None, lease=None):
        owner = _actor(actor)
        if owner[0] != "user":
            raise StateError("login_required", 401)
        encoded = _preference(key, value)
        if (source not in {"explicit", "inferred"} or type(confidence) not in {float, int}
                or not math.isfinite(confidence) or not 0 < confidence <= 1):
            raise StateError("invalid_preference_source", 422)
        evidence_ids = [] if evidence_ids is None else evidence_ids
        if not isinstance(evidence_ids, list) or len(evidence_ids) > 32:
            raise StateError("invalid_evidence_ids", 422)
        for identifier in evidence_ids:
            _text(identifier, "evidence_id", 128)
        if source == "inferred" and (not evidence_ids or conversation_id is None):
            raise StateError("inference_requires_owned_evidence", 422)
        if evidence_ids and conversation_id is None:
            raise StateError("evidence_requires_conversation", 422)
        with self._transaction() as cursor:
            if lease is not None:
                leased_conversation, _ = self._locked(cursor, lease)
                if (leased_conversation["conversation_id"] != conversation_id or
                        (leased_conversation["subject_type"], leased_conversation["actor_id"],
                         leased_conversation["execution_scope_id"]) != owner):
                    raise StateError("conversation_not_found", 404)
            cursor.execute("SELECT UTC_TIMESTAMP(6) AS now")
            now = cursor.fetchone()["now"]
            expiry = _expiry(expires_at) if expires_at is not None else now + timedelta(days=30) if source == "inferred" else None
            if expiry is not None and (expiry <= now or source == "inferred" and expiry > now + timedelta(days=30)):
                raise StateError("invalid_preference_expiry", 422)
            if conversation_id is not None:
                self._conversation(cursor, actor, conversation_id, lock=True)
                memory = self._memory(cursor, conversation_id)
                for identifier in evidence_ids:
                    cursor.execute("""SELECT message_id FROM message WHERE conversation_id=%s AND message_id=%s
                        AND role='user' AND sequence>%s AND created_at>UTC_TIMESTAMP(6)-INTERVAL 30 DAY""",
                        (conversation_id, identifier, memory["forgotten_before_sequence"]))
                    if not cursor.fetchone():
                        raise StateError("evidence_not_found", 404)
            evidence = [{"conversation_id": conversation_id, "message_id": identifier} for identifier in evidence_ids]
            if not evidence:
                evidence = [{"user_edit_id": uuid.uuid4().hex, "actor_id": owner[1]}]
            cursor.execute("SELECT * FROM user_preference WHERE subject_type=%s AND actor_id=%s AND execution_scope_id=%s "
                           "AND preference_key=%s FOR UPDATE", (*owner, key))
            prior = cursor.fetchone()
            if source == "inferred" and prior and (prior["deleted_at"] is not None or
                    prior["source"] == "explicit" and (prior["expires_at"] is None or prior["expires_at"] > now)):
                raise StateError("explicit_preference_has_priority")
            existing = self._preferences(cursor, actor)
            # 跨键冲突（组件 10）：likes/avoid 同词条是立场自相矛盾，要求澄清而非静默覆盖；
            # 被拒写入把「挡住这次写入的既有偏好行」快照进台账（action=rejected_conflict），
            # 「为什么没存进去」可追溯。
            conflicts = preference_conflicts(key, value, existing)
            if conflicts:
                other_key = "avoid" if key == "likes" else "likes"
                cursor.execute("SELECT * FROM user_preference WHERE subject_type=%s AND actor_id=%s "
                               "AND execution_scope_id=%s AND preference_key=%s FOR UPDATE", (*owner, other_key))
                blocker = cursor.fetchone()
                if blocker is not None and blocker["deleted_at"] is None:
                    self._history(cursor, blocker, action="rejected_conflict", superseded_at=now, conflict=conflicts)
                    # 本事务到这里只有台账插入这一个待写变更（upsert 尚未发生），先提交
                    # 再抛错——拒绝路径的审计记录不能随事务回滚一起消失。
                    cursor.connection.commit()
                raise StateError("preference_conflict_needs_clarification", 409)
            # NOOP（组件 10）：同值同源同效期的重复写入不升 version、不重置过期，
            # 只留一条 noop 台账——重复点击/重复推断不应制造版本噪声。
            if (prior is not None and prior["deleted_at"] is None and prior["value_json"] == encoded
                    and prior["source"] == source and prior["expires_at"] == expiry):
                self._history(cursor, prior, action="noop", superseded_at=now)
                return next(row for row in existing if row["preference_key"] == key)
            # 双时态最小版（组件 10，对齐 Zep 的 invalidate-not-delete）：覆盖/复活前
            # 先把旧值快照进历史表，活表行保持唯一——「上周预算是多少」可回溯。
            if prior is not None and prior["deleted_at"] is None:
                self._history(cursor, prior, action="superseded", superseded_at=now)
            cursor.execute("""INSERT INTO user_preference (subject_type,actor_id,execution_scope_id,preference_key,
                value_json,source,confidence,evidence_ids_json,observed_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS incoming
                ON DUPLICATE KEY UPDATE value_json=incoming.value_json,source=incoming.source,confidence=incoming.confidence,
                evidence_ids_json=incoming.evidence_ids_json,observed_at=incoming.observed_at,expires_at=incoming.expires_at,
                deleted_at=NULL,version=user_preference.version+1""", (*owner, key, encoded, source, confidence, canonical(evidence), now, expiry))
            return next(row for row in self._preferences(cursor, actor) if row["preference_key"] == key)

    @staticmethod
    def _history(cursor, prior, *, action, superseded_at, conflict=None):
        """把被覆盖/删除/拒绝前的偏好行快照进 user_preference_history（双时态最小版）。

        活表（user_preference）保持单行热路径不变；历史行回答「当时这条偏好是什么、
        为什么被换掉/拒绝」。id 客户端生成（与 answer_feedback 同款 CHAR(32) 惯例）。
        """
        cursor.execute("""INSERT INTO user_preference_history (id,subject_type,actor_id,execution_scope_id,
            preference_key,value_json,source,confidence,evidence_ids_json,observed_at,expires_at,version,
            deleted_at,action,conflict_json,superseded_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (uuid.uuid4().hex, prior["subject_type"], prior["actor_id"], prior["execution_scope_id"],
             prior["preference_key"], prior["value_json"], prior["source"], prior["confidence"],
             prior["evidence_ids_json"], prior["observed_at"], prior["expires_at"], prior["version"],
             prior["deleted_at"], action, canonical(conflict) if conflict else None, superseded_at))

    def preference_history(self, actor, *, key=None, limit=100):
        """偏好变更台账（组件 10，只读、owner 范围）：superseded/deleted/noop/rejected_conflict。"""
        owner = _actor(actor)
        if owner[0] != "user":
            raise StateError("login_required", 401)
        limit = max(1, min(int(limit), 200))
        where = "subject_type=%s AND actor_id=%s AND execution_scope_id=%s"
        values = list(owner)
        if key is not None:
            where += " AND preference_key=%s"
            values.append(_text(key, "preference_key", 32))
        with self._transaction() as cursor:
            cursor.execute("""SELECT preference_key,value_json,source,confidence,evidence_ids_json,
                observed_at,expires_at,version,action,conflict_json,superseded_at FROM user_preference_history
                WHERE """ + where + " ORDER BY superseded_at DESC,id DESC LIMIT %s", (*values, limit))
            return [{**_public(row), "confidence": float(row["confidence"])} for row in cursor.fetchall()]

    # 历史证据回查（组件 9）只认事实类工具：流程类（load_skill）与结论文本类
    # （task_dispatch）回执不是可引用的历史观测。
    EVIDENCE_TOOLS = ("search_knowledge", "search_skus", "recommend_skus", "compare_skus",
                      "get_product_offer", "get_my_orders", "get_order_status",
                      "get_refund_status", "get_payment_status")

    def conversation_evidence(self, actor, conversation_id, *, call_id=None, term=None, limit=3):
        """按引用/关键词回查本会话历史工具回执（组件 9，只读、owner 范围）。

        tool_call.receipt_json 本就按调用完整存档（30 天保留），缺的只是模型侧的
        回查口。返回行是历史观察值——消费方必须带「当前值以实时工具为准」语义，
        本方法不裁剪 receipt 数据（观察投影层负责体积）。
        """
        limit = max(1, min(int(limit), 5))
        placeholders = ",".join(["%s"] * len(self.EVIDENCE_TOOLS))
        where = (f"r.conversation_id=%s AND t.tool_name IN ({placeholders}) "
                 "AND t.receipt_json IS NOT NULL")
        values = [conversation_id, *self.EVIDENCE_TOOLS]
        if call_id is not None:
            where += " AND t.call_id=%s"
            values.append(_text(call_id, "result_ref", 64))
        elif term is not None:
            where += " AND (t.arguments_json LIKE %s OR t.receipt_json LIKE %s)"
            needle = "%" + _text(term, "term", 64) + "%"
            values.extend([needle, needle])
        with self._transaction() as cursor:
            self._conversation(cursor, actor, conversation_id)
            cursor.execute("""SELECT t.call_id,t.tool_name,t.arguments_json,t.receipt_json,t.started_at,t.outcome
                FROM tool_call t JOIN agent_run r USING(agent_run_id)
                WHERE """ + where + " ORDER BY t.started_at DESC,t.call_id DESC LIMIT %s", (*values, limit))
            records = []
            for row in cursor.fetchall():
                receipt = json.loads(row["receipt_json"]) if row["receipt_json"] else {}
                # 只回放带事实载荷的回执：拒绝/失败回执只有 error_type，
                # 不是可引用的历史观测。
                if not isinstance(receipt, dict) or "data" not in receipt:
                    continue
                records.append({
                    "result_ref": row["call_id"], "tool_name": row["tool_name"],
                    "observed_at": receipt.get("observed_at"), "outcome": row["outcome"],
                    "data": receipt.get("data"),
                })
            return records

    @staticmethod
    def _fence(cursor, conversation_id):
        # Caller holds the conversation lock. Revoking this lease stops late local
        # writes; an already dispatched Java operation must still be reconciled.
        cursor.execute("""UPDATE agent_run SET state='CANCELLED',version=version+1,
            updated_at=UTC_TIMESTAMP(6) WHERE conversation_id=%s AND state='RUNNING'""", (conversation_id,))
        cursor.execute("""UPDATE conversation SET lease_run_id=NULL,lease_owner=NULL,lease_token=NULL,
            lease_until=NULL,lease_epoch=lease_epoch+1,version=version+1,updated_at=UTC_TIMESTAMP(6)
            WHERE conversation_id=%s""", (conversation_id,))

    @staticmethod
    def _forget(cursor, actor, conversation_id=None):
        where = "subject_type=%s AND actor_id=%s AND execution_scope_id=%s"
        values = _actor(actor)
        if conversation_id is not None:
            where += " AND conversation_id=%s"
            values = (*values, conversation_id)
        cursor.execute("SELECT conversation_id,message_sequence FROM conversation WHERE " + where + " ORDER BY conversation_id FOR UPDATE", values)
        conversations = list(cursor.fetchall())
        for conversation in conversations:
            MemoryStore._fence(cursor, conversation["conversation_id"])
            MemoryStore._memory(cursor, conversation["conversation_id"])
            cursor.execute("""UPDATE conversation_memory SET forgotten_before_sequence=%s,summary_json=NULL,
                mission_json=NULL,summary_sequence=0,version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE conversation_id=%s""",
                (conversation["message_sequence"], conversation["conversation_id"]))

    def delete_preference(self, actor, key):
        if _actor(actor)[0] != "user":
            raise StateError("login_required", 401)
        if key not in PREFERENCE_KEYS:
            raise StateError("invalid_preference_key", 422)
        with self._transaction() as cursor:
            self._forget(cursor, actor)
            cursor.execute("SELECT * FROM user_preference WHERE subject_type=%s AND actor_id=%s "
                           "AND execution_scope_id=%s AND preference_key=%s FOR UPDATE", (*_actor(actor), key))
            prior = cursor.fetchone()
            if prior is not None and prior["deleted_at"] is None:
                cursor.execute("SELECT UTC_TIMESTAMP(6) AS now")
                self._history(cursor, prior, action="deleted", superseded_at=cursor.fetchone()["now"])
            # Tombstones stop forgotten implicit evidence from recreating a deleted preference.
            cursor.execute("""INSERT INTO user_preference (subject_type,actor_id,execution_scope_id,preference_key,
                value_json,source,confidence,evidence_ids_json,observed_at,deleted_at)
                VALUES (%s,%s,%s,%s,'null','explicit',1,'[]',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE value_json='null',evidence_ids_json='[]',deleted_at=UTC_TIMESTAMP(6),version=version+1""",
                (*_actor(actor), key))
        return {"deleted": key, "summary_references_revoked": True}

    def clear(self, actor, conversation_id=None):
        with self._transaction() as cursor:
            if conversation_id is not None:
                self._conversation(cursor, actor, conversation_id)
            # Long-term preferences may have appeared in any conversation summary.
            self._forget(cursor, actor)
            owner = _actor(actor)
            cursor.execute("SELECT * FROM user_preference WHERE subject_type=%s AND actor_id=%s "
                           "AND execution_scope_id=%s AND deleted_at IS NULL FOR UPDATE", owner)
            rows = list(cursor.fetchall())
            if rows:
                cursor.execute("SELECT UTC_TIMESTAMP(6) AS now")
                now = cursor.fetchone()["now"]
                for prior in rows:
                    self._history(cursor, prior, action="deleted", superseded_at=now)
            cursor.execute("""UPDATE user_preference SET value_json='null',evidence_ids_json='[]',deleted_at=UTC_TIMESTAMP(6),
                version=version+1 WHERE subject_type=%s AND actor_id=%s AND execution_scope_id=%s""", owner)
        return {"cleared": True, "summary_references_revoked": True, "transaction_audit_preserved": True}

    @staticmethod
    def _mission_payload(memory):
        raw = None if memory is None else memory.get('mission_json')
        raw = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        return normalize_mission(raw) if raw else empty_mission()

    def mission(self, actor, conversation_id):
        with self._transaction() as cursor:
            self._conversation(cursor, actor, conversation_id)
            return self._mission_payload(self._memory(cursor, conversation_id))

    def put_mission(self, actor, conversation_id, mission, *, lease=None):
        normalized = normalize_mission(mission)
        with self._transaction() as cursor:
            if lease is not None:
                conversation, _ = self._locked(cursor, lease)
                if (conversation['conversation_id'] != conversation_id or
                        (conversation['subject_type'], conversation['actor_id'],
                         conversation['execution_scope_id']) != _actor(actor)):
                    raise StateError('conversation_not_found', 404)
            else:
                self._conversation(cursor, actor, conversation_id, lock=True)
            self._memory(cursor, conversation_id)
            cursor.execute("""UPDATE conversation_memory SET mission_json=%s,version=version+1,
                updated_at=UTC_TIMESTAMP(6) WHERE conversation_id=%s""",
                (canonical(normalized), conversation_id))
            return normalized

    @staticmethod
    def _handoff(cursor, conversation_id):
        cursor.execute("SELECT * FROM support_ticket WHERE conversation_id=%s AND status IN ('OPEN','TAKEN_OVER') "
                       "ORDER BY created_at DESC LIMIT 1", (conversation_id,))
        row = cursor.fetchone()
        return _public(row) if row else None

    def context(self, actor, conversation_id):
        with self._transaction() as cursor:
            conversation = self._conversation(cursor, actor, conversation_id, lock=True)
            memory = self._memory(cursor, conversation_id)
            cursor.execute("""SELECT * FROM message WHERE conversation_id=%s AND sequence>%s
                AND created_at>UTC_TIMESTAMP(6)-INTERVAL 30 DAY ORDER BY sequence DESC LIMIT 256""",
                (conversation_id, memory["forgotten_before_sequence"]))
            rows = [_public(row) for row in reversed(cursor.fetchall())]
            messages, summary = working_context(rows)
            stored_summary = memory["summary_json"]
            stored_summary = json.loads(stored_summary) if isinstance(stored_summary, (str, bytes)) else stored_summary
            if stored_summary:
                stored_summary = {key: value for key, value in stored_summary.items() if key != "version"}
            if memory["summary_sequence"] != conversation["message_sequence"] or stored_summary != summary:
                version = memory["version"] + 1
                if summary:
                    summary["version"] = version
                cursor.execute("""UPDATE conversation_memory SET summary_json=%s,summary_sequence=%s,version=%s,
                    updated_at=UTC_TIMESTAMP(6) WHERE conversation_id=%s""",
                    (canonical(summary) if summary else None, conversation["message_sequence"], version, conversation_id))
            else:
                version = memory["version"]
                if summary:
                    summary["version"] = version
            return {"messages": messages, "summary": summary, "preferences": self._preferences(cursor, actor),
                    "mission": self._mission_payload(memory),
                    "handoff": self._handoff(cursor, conversation_id), "memory_version": version,
                    "forgotten_before_sequence": memory["forgotten_before_sequence"]}

    def handoff_state(self, actor, conversation_id):
        with self._transaction() as cursor:
            self._conversation(cursor, actor, conversation_id)
            return self._handoff(cursor, conversation_id)

    def recover_handoff_run(self, actor, run_id):
        """Exact-request replay may recover an existing ticket, never restart automation."""
        with self._transaction() as cursor:
            run = self._owned_record(cursor, actor, run_id, 'run')
            self._conversation(cursor, actor, run['conversation_id'], lock=True)
            cursor.execute('SELECT * FROM agent_run WHERE agent_run_id=%s FOR UPDATE', (run_id,))
            run = cursor.fetchone()
            ticket = self._handoff(cursor, run['conversation_id'])
            if not ticket:
                return None
            if run['state'] in {'CREATED', 'RUNNING'}:
                self._fence(cursor, run['conversation_id'])
                result = {'answer_status': 'needs_human', 'ticket': ticket,
                          'handoff_origin': 'recovered_existing_ticket', 'model_mode': run['model_mode']}
                cursor.execute("UPDATE agent_run SET state='CANCELLED',result_json=%s,version=version+1,updated_at=UTC_TIMESTAMP(6) "
                               'WHERE agent_run_id=%s', (_json(result), run_id))
                cursor.execute('SELECT * FROM agent_run WHERE agent_run_id=%s', (run_id,))
                run = cursor.fetchone()
            return _public(run)

    def handoff(self, actor, conversation_id, reason, evidence=None, *, cancel_running=True, lease=None):
        if type(cancel_running) is not bool:
            raise StateError("invalid_cancel_running", 422)
        reason = _text(reason, "reason", 64)
        evidence = [] if evidence is None else evidence
        if not isinstance(evidence, list) or len(evidence) > 4:
            raise StateError("invalid_ticket_evidence", 422)
        # Keep references only, never persist model-supplied policy or credential dumps.
        references = []
        for item in evidence:
            if not isinstance(item, dict):
                raise StateError("invalid_ticket_evidence", 422)
            references.append({"doc_id": _text(item.get("doc_id"), "doc_id", 128),
                               "version": _integer(item.get("version"), "version", 1, 2147483647),
                               "chunk_id": _text(item.get("chunk_id"), "chunk_id", 32)})
        with self._transaction() as cursor:
            if lease is not None:
                conversation, _ = self._locked(cursor, lease)
                if cancel_running or conversation['conversation_id'] != conversation_id or (
                        conversation['subject_type'], conversation['actor_id'], conversation['execution_scope_id']) != _actor(actor):
                    raise StateError('invalid_handoff_lease', 409)
            self._conversation(cursor, actor, conversation_id, lock=True)
            if cancel_running:
                self._fence(cursor, conversation_id)
            prior = self._handoff(cursor, conversation_id)
            if prior:
                return prior
            ticket_id = uuid.uuid4().hex
            cursor.execute("""INSERT INTO support_ticket (ticket_id,conversation_id,status,reason,evidence_json,created_at,updated_at)
                VALUES (%s,%s,'OPEN',%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
                (ticket_id, conversation_id, reason, canonical(references)))
            return self._handoff(cursor, conversation_id)

    def list_tickets(self, actor):
        _merchant(actor, "admin:legacy")
        with self._transaction() as cursor:
            cursor.execute("""SELECT t.* FROM support_ticket t JOIN conversation c USING(conversation_id)
                WHERE c.execution_scope_id=%s ORDER BY t.created_at DESC LIMIT 100""", (_actor(actor)[2],))
            return [_public(row) for row in cursor.fetchall()]

    def get_ticket(self, actor, ticket_id, *, before_sequence=None):
        """Read persisted context through ticket ownership, never an impersonated user."""
        _merchant(actor, "admin:legacy")
        ticket_id = _text(ticket_id, "ticket_id", 32)
        if before_sequence is not None:
            _integer(before_sequence, "before_sequence", 1)
        with self._transaction() as cursor:
            cursor.execute("""SELECT c.conversation_id FROM conversation c JOIN support_ticket t USING(conversation_id)
                WHERE t.ticket_id=%s AND c.execution_scope_id=%s""", (ticket_id, _actor(actor)[2]))
            linked = cursor.fetchone()
            if not linked:
                raise StateError("ticket_not_found", 404)
            conversation_id = linked["conversation_id"]
            # Same lock order as takeover: keep assignment stable while reading this page.
            cursor.execute("SELECT * FROM conversation WHERE conversation_id=%s FOR SHARE", (conversation_id,))
            conversation = _public(cursor.fetchone())
            cursor.execute("SELECT * FROM support_ticket WHERE ticket_id=%s FOR SHARE", (ticket_id,))
            ticket = cursor.fetchone()
            if ticket["assigned_actor_id"] not in {None, actor.actor_id}:
                raise StateError("ticket_assigned_to_another", 403)
            cursor.execute("SELECT * FROM message WHERE conversation_id=%s AND sequence<%s ORDER BY sequence DESC LIMIT 101",
                           (conversation_id, before_sequence if before_sequence is not None else conversation["message_sequence"] + 1))
            page = list(cursor.fetchall())
            messages = [_public(row) for row in reversed(page[:100])]
            run_ids = sorted({row["agent_run_id"] for row in messages if row["agent_run_id"]})
            runs, proposals = [], []
            if run_ids:
                placeholders = ','.join(['%s'] * len(run_ids))
                cursor.execute("SELECT agent_run_id,state,model_mode,result_json,created_at FROM agent_run "
                               f"WHERE conversation_id=%s AND agent_run_id IN ({placeholders}) ORDER BY created_at,agent_run_id",
                               (conversation_id, *run_ids))
                for row in cursor.fetchall():
                    run = _public(row)
                    result = run["result"] or {}
                    # No tool arguments, hidden run context, credentials or stale proposal copy.
                    run["result"] = {key: result[key] for key in (
                        "answer_status", "citations", "error", "wait_reason", "decision", "checks") if key in result}
                    runs.append(run)
                cursor.execute(f"SELECT * FROM proposal WHERE conversation_id=%s AND agent_run_id IN ({placeholders}) ORDER BY created_at,proposal_id",
                               (conversation_id, *run_ids))
                proposals = [_public(row) for row in cursor.fetchall()]
            return {"ticket": _public(ticket), "conversation": conversation, "messages": messages,
                    "runs": runs, "proposals": proposals,
                    "next_before_sequence": messages[0]["sequence"] if len(page) > 100 else None}

    def manage_ticket(self, actor, ticket_id, *, action, version, reply=None):
        _merchant(actor, "admin:legacy")
        if action not in {"take_over", "reply", "close"}:
            raise StateError("invalid_ticket_action", 422)
        _integer(version, "version", 1)
        with self._transaction() as cursor:
            cursor.execute("""SELECT c.* FROM conversation c JOIN support_ticket t USING(conversation_id)
                WHERE t.ticket_id=%s AND c.execution_scope_id=%s""",
                (_text(ticket_id, "ticket_id", 32), _actor(actor)[2]))
            conversation = cursor.fetchone()
            if not conversation:
                raise StateError("ticket_not_found", 404)
            # Match handoff/forget lock order: conversation before run/ticket.
            cursor.execute("SELECT conversation_id FROM conversation WHERE conversation_id=%s FOR UPDATE",
                           (conversation["conversation_id"],))
            cursor.execute("SELECT * FROM support_ticket WHERE ticket_id=%s FOR UPDATE", (ticket_id,))
            ticket = cursor.fetchone()
            if ticket["version"] != version or ticket["status"] == "CLOSED":
                raise StateError("ticket_version_conflict")
            if ticket["assigned_actor_id"] not in {None, actor.actor_id}:
                raise StateError("ticket_assigned_to_another", 403)
            if action == "take_over":
                self._fence(cursor, ticket["conversation_id"])
            if action == "reply":
                if ticket["status"] != "TAKEN_OVER":
                    raise StateError("ticket_not_taken_over")
                reply = _text(reply, "reply", 4000)
                self._message(cursor, ticket["conversation_id"], None, "human-" + uuid.uuid4().hex, "assistant", reply)
            status = "CLOSED" if action == "close" else "TAKEN_OVER"
            cursor.execute("""UPDATE support_ticket SET status=%s,assigned_actor_id=%s,resolution=COALESCE(%s,resolution),
                version=version+1,updated_at=UTC_TIMESTAMP(6) WHERE ticket_id=%s""", (status, actor.actor_id, reply, ticket_id))
            cursor.execute("SELECT * FROM support_ticket WHERE ticket_id=%s", (ticket_id,))
            return _public(cursor.fetchone())
