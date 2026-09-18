"""pgvector HNSW for knowledge chunks. Not a MySQL JSON table scan.

When DSN is missing the caller must use lexical-only retrieval and record
vector_backend=unavailable. That is not advertised as ANN.
"""
from __future__ import annotations

import json

from smartlect.postgres import dsn_from_env

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS knowledge_embedding (
    chunk_pk TEXT PRIMARY KEY,
    execution_scope_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    chunk_id TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    index_version TEXT NOT NULL,
    acl TEXT NOT NULL,
    acl_actor_id TEXT,
    product_ids_json TEXT,
    corpus TEXT,
    valid_until TIMESTAMPTZ,
    embedding vector NOT NULL
);
"""


def _connect(dsn):
    import psycopg
    return psycopg.connect(dsn, autocommit=True)


def setup(env=None):
    dsn = dsn_from_env(env)
    if not dsn:
        return False
    with _connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute(SCHEMA_SQL)
        cursor.execute("SELECT embedding FROM knowledge_embedding LIMIT 0")
        # HNSW needs a known dimension; create on first upsert when we know it.
    return True


def _ensure_index(cursor, dimensions):
    cursor.execute(
        """SELECT indexname FROM pg_indexes
           WHERE tablename='knowledge_embedding' AND indexname='knowledge_embedding_hnsw'"""
    )
    if cursor.fetchone():
        return
    cursor.execute(
        f"CREATE INDEX knowledge_embedding_hnsw ON knowledge_embedding "
        f"USING hnsw (embedding vector_cosine_ops)"
    )


def upsert_vectors(rows, *, env=None):
    """rows: dicts with chunk_pk, embedding list, metadata."""
    dsn = dsn_from_env(env)
    if not dsn or not rows:
        return 0
    with _connect(dsn) as conn, conn.cursor() as cursor:
        dimensions = len(rows[0]["embedding"])
        try:
            _ensure_index(cursor, dimensions)
        except Exception:
            pass
        for row in rows:
            vector = row["embedding"]
            literal = "[" + ",".join(str(float(x)) for x in vector) + "]"
            cursor.execute(
                """INSERT INTO knowledge_embedding
                   (chunk_pk,execution_scope_id,doc_id,version,chunk_id,embedding_model,index_version,
                    acl,acl_actor_id,product_ids_json,corpus,valid_until,embedding)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                   ON CONFLICT (chunk_pk) DO UPDATE SET
                     embedding=EXCLUDED.embedding, embedding_model=EXCLUDED.embedding_model,
                     index_version=EXCLUDED.index_version, acl=EXCLUDED.acl,
                     valid_until=EXCLUDED.valid_until""",
                (row["chunk_pk"], row["execution_scope_id"], row["doc_id"], row["version"],
                 row["chunk_id"], row["embedding_model"], row["index_version"], row["acl"],
                 row.get("acl_actor_id"), row.get("product_ids_json"), row.get("corpus"),
                 row.get("valid_until"), literal),
            )
    return len(rows)


def ann_search(query_vector, *, scope, embedding_model, index_version, limit=50,
               actor_kind=None, actor_id=None, product_id=None, corpus=None, env=None):
    dsn = dsn_from_env(env)
    if not dsn:
        return None
    literal = "[" + ",".join(str(float(x)) for x in query_vector) + "]"
    clauses = ["execution_scope_id=%s", "embedding_model=%s", "index_version=%s",
               "(valid_until IS NULL OR valid_until > NOW())"]
    values = [scope, embedding_model, index_version]
    if actor_kind == "user":
        clauses.append("(acl='PUBLIC' OR acl='USER' OR (acl='ACTOR' AND acl_actor_id=%s))")
        values.append(actor_id)
    elif actor_kind == "merchant":
        clauses.append("(acl='PUBLIC' OR acl='MERCHANT')")
    else:
        clauses.append("acl='PUBLIC'")
    if product_id:
        clauses.append("(product_ids_json IS NULL OR product_ids_json='' OR product_ids_json LIKE %s)")
        values.append("%" + product_id + "%")
    if corpus:
        clauses.append("(corpus=%s OR corpus IS NULL)")
        values.append(corpus)
    sql = (
        "SELECT chunk_pk, doc_id, version, chunk_id, 1 - (embedding <=> %s::vector) AS score "
        "FROM knowledge_embedding WHERE " + " AND ".join(clauses) +
        " ORDER BY embedding <=> %s::vector LIMIT %s"
    )
    with _connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute(sql, (literal, *values, literal, limit))
        return [{"chunk_pk": row[0], "doc_id": row[1], "version": row[2],
                 "chunk_id": row[3], "score": float(row[4])} for row in cursor.fetchall()]
