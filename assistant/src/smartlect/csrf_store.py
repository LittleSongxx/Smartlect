"""One-time CSRF nonce table. A used jti cannot be replayed."""
from __future__ import annotations


_memory = set()


def consume(connect, jti, *, actor_id, session_id):
    """Insert jti. Return True if this is the first use, False if already consumed."""
    if not jti:
        return False
    if connect is None:
        return _consume_memory(jti, actor_id, session_id)
    try:
        connection = connect()
    except Exception:
        return False
    if connection is None:
        # Tests and create_app may attach a no-op connect. That is "no table", not "table down".
        return _consume_memory(jti, actor_id, session_id)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT IGNORE INTO csrf_nonce (jti, actor_id, session_id, consumed_at)
                       VALUES (%s,%s,%s,UTC_TIMESTAMP(6))""",
                    (jti, actor_id, session_id),
                )
                first = cursor.rowcount == 1
            connection.commit()
        return first
    except Exception:
        # Fail closed. A memory fallback would replay a jti the table already consumed.
        return False


def _consume_memory(jti, actor_id, session_id):
    key = (jti, actor_id, session_id)
    if key in _memory:
        return False
    _memory.add(key)
    return True
