"""Thirty-day text/trace retention without deleting commerce or action audit records."""
from smartlect.db import connect_from_env


def purge_expired(connect=connect_from_env):
    counts = dict(messages=0, tool_calls=0, run_events=0, runs_scrubbed=0,
                  summaries_revoked=0, ticket_replies=0, conversations_checked=0, index_model_attempts=0,
                  preference_history=0)
    cutoff, after = None, ""
    while True:
        with connect() as connection, connection.cursor() as cursor:
            try:
                if cutoff is None:
                    cursor.execute("SELECT UTC_TIMESTAMP(6)-INTERVAL 30 DAY AS cutoff")
                    cutoff = cursor.fetchone()["cutoff"]
                cursor.execute("DELETE FROM knowledge_index_attempt WHERE started_at<%s LIMIT 1000", (cutoff,))
                removed_attempts = cursor.rowcount
                counts['index_model_attempts'] += removed_attempts
                # 偏好历史（组件 10）与 message/trace 同口径的 30 天保留：个人数据
                # 最小化优先于无限期审计回溯；过期后双时态回答以活表与墓碑为准。
                cursor.execute("DELETE FROM user_preference_history WHERE superseded_at<%s LIMIT 1000", (cutoff,))
                removed_history = cursor.rowcount
                counts['preference_history'] += removed_history
                # Lock the same parent as SessionStore before touching its children.
                # Busy conversations are retried on the next maintenance invocation.
                cursor.execute("""SELECT conversation_id FROM conversation WHERE conversation_id>%s
                    AND (lease_until IS NULL OR lease_until<=UTC_TIMESTAMP(6))
                    ORDER BY conversation_id LIMIT 100 FOR UPDATE SKIP LOCKED""", (after,))
                conversations = list(cursor.fetchall())
                if not conversations:
                    connection.commit()
                    if removed_attempts == 1000 or removed_history == 1000:
                        continue
                    return counts
                for row in conversations:
                    conversation_id = row["conversation_id"]
                    cursor.execute("DELETE FROM message WHERE conversation_id=%s AND created_at<%s",
                                   (conversation_id, cutoff))
                    removed_messages = cursor.rowcount
                    counts["messages"] += removed_messages
                    cursor.execute("""DELETE t FROM tool_call t JOIN agent_run r USING(agent_run_id)
                        WHERE r.conversation_id=%s AND COALESCE(t.completed_at,t.started_at)<%s""",
                                   (conversation_id, cutoff))
                    counts["tool_calls"] += cursor.rowcount
                    cursor.execute("""DELETE e FROM agent_run_event e JOIN agent_run r USING(agent_run_id)
                        WHERE r.conversation_id=%s AND e.created_at<%s""", (conversation_id, cutoff))
                    counts["run_events"] += cursor.rowcount
                    cursor.execute("""UPDATE agent_run SET context_json='{}',result_json=NULL,version=version+1
                        WHERE conversation_id=%s AND updated_at<%s
                        AND (JSON_LENGTH(context_json)>0 OR result_json IS NOT NULL)""", (conversation_id, cutoff))
                    counts["runs_scrubbed"] += cursor.rowcount
                    cursor.execute("""UPDATE conversation_memory SET summary_json=NULL,summary_sequence=0,
                        version=version+1,updated_at=UTC_TIMESTAMP(6)
                        WHERE conversation_id=%s AND summary_json IS NOT NULL AND (updated_at<%s OR %s>0)""",
                                   (conversation_id, cutoff, removed_messages))
                    counts["summaries_revoked"] += cursor.rowcount
                    cursor.execute("""UPDATE support_ticket SET resolution=NULL,version=version+1
                        WHERE conversation_id=%s AND updated_at<%s AND resolution IS NOT NULL""", (conversation_id, cutoff))
                    counts["ticket_replies"] += cursor.rowcount
                    counts["conversations_checked"] += 1
                after = conversations[-1]["conversation_id"]
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
