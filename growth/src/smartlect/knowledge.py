"""Versioned, prefiltered local RAG evidence; no commerce state or generated answers.

Adapted synonym normalization and RRF from frozen shop-ai-python, commit
94d36aee925c75d286f48d2aee2eeea059a74dd9, app/rag/query_expander.py and rrf.py.
Copyright (c) 2026 Audreator, MIT; see licenses/shop-ai-python-LICENSE.
Changes: fail-closed MySQL ACL/lifecycle, Chinese BM25, fixed RRF empty/duplicates.
"""
from collections import Counter
from hashlib import sha256
import json
import math
import re
import unicodedata
import uuid

from prometheus_client import Counter as PrometheusCounter

from smartlect.cache import TtlCache
from smartlect.events import canonical
from smartlect.state import SessionStore, StateError, _actor, _expiry, _integer, _json, _public, _text

KNOWLEDGE_CACHE_REQUESTS = PrometheusCounter("growth_knowledge_cache_requests_total",
                                             "Knowledge search cache outcomes", ["outcome"])

MAX_CHUNKS = 5000
LEXICAL_VERSION = "zh-bigram-bm25-v1"
RERANK_VERSION = "zh-coverage-proximity-v2"
COMPOSED_QUERY_LIMIT = 800
CONSTRAINT_WEIGHT = 0.45
FIRST_STAGE_DEPTH = 20
FUSED_DEPTH = 12
FINAL_DEPTH = 8
# Vocabulary variants only: colloquial or misspelled wording for the same word. Intent
# phrases do not belong here, because mapping an action request onto a document lookup
# only works for the phrasings someone thought to list.
SYNONYMS = (("退钱", "退款"), ("退回款项", "退款"), ("付钱", "支付"), ("付款", "支付"),
            ("快递", "物流"), ("包裹", "物流"), ("收货地", "地址"), ("优惠卷", "优惠券"),
            ("清空", "清理"))
STOP_TERMS = {"什么", "怎么", "如何", "可以", "能否", "是否", "请问", "一下", "我的", "这个", "那个", "哪些", "多少"}
INSTRUCTION_PATTERN = re.compile(r"忽略.{0,12}(?:指令|规则|提示)|(?:系统|开发者)提示词|泄露.{0,10}(?:密钥|token)|"
                                 r"ignore.{0,25}(?:instruction|previous)|system\s*prompt|api[_ -]?key", re.I)
VISIBLE_DOCUMENT = """d.execution_scope_id=%s AND d.status='PUBLISHED'
    AND d.valid_from<=UTC_TIMESTAMP(6) AND d.valid_until>UTC_TIMESTAMP(6)
    AND (d.acl='PUBLIC' OR (d.acl='USER' AND %s='user') OR (d.acl='MERCHANT' AND %s='merchant')
         OR (d.acl='ACTOR' AND %s='user' AND d.acl_actor_id=%s))"""
HIDDEN_DOCUMENT = """d.execution_scope_id=%s AND d.status='PUBLISHED'
    AND d.valid_from<=UTC_TIMESTAMP(6) AND d.valid_until>UTC_TIMESTAMP(6)
    AND NOT (d.acl='PUBLIC' OR (d.acl='USER' AND %s='user') OR (d.acl='MERCHANT' AND %s='merchant')
             OR (d.acl='ACTOR' AND %s='user' AND d.acl_actor_id=%s))"""


def _visibility(actor):
    kind, actor_id, scope = _actor(actor)
    return scope, kind, kind, kind, actor_id


def _merchant(actor, permission="admin:legacy"):
    if _actor(actor)[0] != "merchant" or permission not in getattr(actor, "permissions", ()):
        raise StateError("permission_denied", 403)


def _ids(value, name):
    if not isinstance(value, list) or len(value) > 64:
        raise StateError("invalid_" + name, 422)
    return sorted({_text(item, name, 128) for item in value})


def tokens(text):
    value = unicodedata.normalize("NFKC", text).casefold()
    for source, target in SYNONYMS:
        value = value.replace(source, target)
    result = []
    for part in re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", value):
        if re.fullmatch(r"[a-z0-9]+", part):
            result.append(part)
        elif len(part) == 1:
            continue  # Single Chinese characters create spurious policy evidence.
        else:
            result.extend(part[i:i + 2] for i in range(len(part) - 1) if part[i:i + 2] not in STOP_TERMS)
    return result


def split_document(body):
    """Heading chunks with exact Python-character offsets and one-based line locations."""
    body = _text(body, "body", 300000)
    chunks, start, heading = [], 0, ""
    boundaries = [match.start() for match in re.finditer(r"(?m)^#{1,6} +[^\n]+", body)]
    for end in sorted(set([*boundaries, len(body)])):
        if end <= start:
            continue
        section = body[start:end]
        first = re.match(r"#{1,6} +([^\n]+)", section)
        if first:
            heading = first.group(1)[:256]
        offset = start
        while offset < end:
            stop = min(offset + 1400, end)
            if stop < end:
                newline = body.rfind("\n", offset + 700, stop)
                if newline > offset:
                    stop = newline + 1
            content = body[offset:stop]
            if content.strip():
                chunks.append({"chunk_id": f"c{len(chunks) + 1:04d}", "heading": heading,
                               "content": content, "start_offset": offset, "end_offset": stop,
                               "start_line": body.count("\n", 0, offset) + 1,
                               "end_line": body.count("\n", 0, max(offset, stop - 1)) + 1})
            offset = stop
        start = end
    return chunks


def compose_search_query(utterance, model_query, *, limit=COMPOSED_QUERY_LIMIT):
    """Keep the user's words first; truncate the model rewrite when the pair is too long."""
    original = (utterance or "").strip()
    rewrite = (model_query or "").strip()
    if not original:
        return rewrite[:limit]
    if not rewrite or rewrite == original:
        return original[:limit]
    if len(original) >= limit:
        return original[:limit]
    room = limit - len(original) - 1
    if room <= 0:
        return original[:limit]
    return original + " " + rewrite[:room]


def constraint_terms(utterance, model_query):
    return set(tokens(utterance or "")) - set(tokens(model_query or ""))


def constraint_coverage(texts, extra_terms):
    if not extra_terms:
        return 1.0
    present = set(tokens(" ".join(texts)))
    return len(extra_terms & present) / len(extra_terms)


def citation_constraint_texts(items):
    return [((item.get('content') or '') + ' ' + (item.get('heading') or '') + ' ' + (item.get('title') or ''))
            for item in items or []]


def misses_utterance_constraints(items, utterance, model_query=''):
    extra = constraint_terms(utterance, model_query)
    if not extra:
        return False
    return constraint_coverage(citation_constraint_texts(items), extra) < 0.5


def hidden_document_covers(item, text):
    """True when the hidden passage covers the question, or the question names its title."""
    if not misses_utterance_constraints([item], text):
        return True
    title_terms = set(tokens((item.get('title') or '') + ' ' + (item.get('heading') or '')))
    return bool(title_terms) and constraint_coverage([text], title_terms) >= 0.5


def acl_denied_documents(visible_rows, hidden_rows, utterance, query=''):
    """Hidden published docs that cover the question, when visible leftovers do not.

    Titles only: the caller must not place hidden bodies in the model observation.
    """
    text = (utterance or query or '').strip()
    visible_items = [{'content': row.get('content') or '', 'heading': row.get('heading') or '',
                      'title': row.get('title') or ''} for row in visible_rows or []]
    if visible_rows and not misses_utterance_constraints(visible_items, text):
        return []
    grouped = {}
    for row in hidden_rows or []:
        doc_id = row.get('doc_id')
        if not doc_id:
            continue
        item = grouped.setdefault(doc_id, {'doc_id': doc_id, 'title': row.get('title') or '',
                                          'content': [], 'heading': [], 'acl': row.get('acl') or ''})
        if row.get('title'):
            item['title'] = row['title']
        item['content'].append(row.get('content') or '')
        item['heading'].append(row.get('heading') or '')
    hits = []
    for doc_id, item in grouped.items():
        packed = {'content': ' '.join(item['content']), 'heading': ' '.join(item['heading']),
                  'title': item['title']}
        if not hidden_document_covers(packed, text):
            continue
        hits.append({'doc_id': doc_id, 'title': item['title'], 'acl': item['acl']})
    return hits


def covering_span(sequence, terms):
    """Distinct query terms present, and the shortest token window that holds them all."""
    positions = [(index, token) for index, token in enumerate(sequence) if token in terms]
    distinct = {token for _, token in positions}
    if len(distinct) < 2:
        return len(distinct), None
    window, best, left = Counter(), None, 0
    for index, token in positions:
        window[token] += 1
        while len(window) == len(distinct):
            best = min(best or index + 1, index - positions[left][0] + 1)
            dropped = positions[left][1]
            window[dropped] -= 1
            if not window[dropped]:
                del window[dropped]
            left += 1
    return len(distinct), best


def rerank(candidates, terms, constraint_terms=None):
    """Second stage over the fused candidates, scoring coverage and term proximity.

    The first stage already used term frequency and length, so repeating that here would
    only reorder by the same signal. This stage asks a different question: how many of the
    distinct query terms the chunk covers, and how tightly they sit together. A chunk that
    repeats one term many times therefore loses to one that discusses the whole question.

    Terms that appear only in the user's utterance (not the model rewrite) are extra
    constraints: a chunk that covers them outranks a theme-only passage. The first-stage
    BM25 formula is unchanged so a miss can still be attributed to recall or ranking.

    Keeping the stages separate is what makes a retrieval failure attributable. Compare the
    recorded first-stage order with the final order to tell a recall miss, where the chunk
    never entered the candidate set, from a ranking miss, where it entered and lost.
    """
    extra = set(constraint_terms or ())
    scored = []
    for key, row in candidates:
        sequence = tokens(row["heading"] + " " + row["content"])
        distinct, span = covering_span(sequence, terms)
        coverage = distinct / len(terms) if terms else 0.0
        density = 1.0 if span is None else distinct / span
        score = coverage * (.7 + .3 * density)
        if extra:
            score += CONSTRAINT_WEIGHT * (len(extra & set(sequence)) / len(extra))
        scored.append((key, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def rrf_merge(keyword_ids, vector_ids, limit=FUSED_DEPTH):
    if limit <= 0:
        return []
    scores = {}
    for ranked in (keyword_ids, vector_ids):
        seen = set()
        for identifier in ranked:
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            scores[identifier] = scores.get(identifier, 0.0) + 1.0 / (60 + len(seen))
    return [key for key, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _vector(value, dimensions=None):
    if (not isinstance(value, list) or not 1 <= len(value) <= 4096
            or dimensions is not None and len(value) != dimensions
            or any(type(number) not in {int, float} or not math.isfinite(number) for number in value)):
        raise StateError("invalid_embedding_vector", 422)
    norm = math.hypot(*value)
    if not math.isfinite(norm) or norm == 0:
        raise StateError("invalid_embedding_vector", 422)
    return [number / norm for number in value]


def rank_chunks(rows, query, *, query_vector=None, embedding_model=None, index_version=None,
                utterance=None, model_query=None):
    """Only accepts the already ACL/lifecycle-filtered rows from KnowledgeStore.search."""
    if len(rows) > MAX_CHUNKS:
        raise StateError("knowledge_capacity_exceeded", 503)
    terms = set(tokens(query))
    model_terms = set(tokens(model_query)) if model_query is not None else terms
    utterance_terms = set(tokens(utterance)) if utterance is not None else set()
    rerank_terms = model_terms | utterance_terms if (utterance is not None or model_query is not None) else terms
    extra_terms = constraint_terms(utterance, model_query) if utterance is not None else set()
    counters = [Counter(tokens(row["heading"] + " " + row["content"])) for row in rows]
    frequency = Counter(term for counter in counters for term in counter)
    average = sum(sum(counter.values()) for counter in counters) / max(len(rows), 1)
    lexical = []
    by_key = {}
    for row, counter in zip(rows, counters):
        key = (row["doc_id"], row["version"], row["chunk_id"])
        by_key[key] = row
        length, score = sum(counter.values()), 0.0
        matched = terms & counter.keys()
        for term in matched:
            tf = counter[term]
            idf = math.log(1 + (len(rows) - frequency[term] + .5) / (frequency[term] + .5))
            score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / max(average, 1)))
        if matched:
            # A single overlap in a long question is weak evidence, but discarding it also
            # drops the chunk that one rare term matched, and that chunk never reaches the
            # rerank stage to be judged. Downweight instead and let fusion decide.
            if len(terms) > 4 and len(matched) < 2:
                score *= .3
            lexical.append((key, score))
    lexical.sort(key=lambda item: (-item[1], item[0]))
    dense = []
    if query_vector is not None:
        vector = _vector(query_vector)
        _text(embedding_model, "embedding_model", 128)
        _text(index_version, "index_version", 128)
        for key, row in by_key.items():
            if (row.get("embedding_model"), row.get("embedding_dimensions"), row.get("index_version")) != (
                    embedding_model, len(vector), index_version):
                continue
            stored = row.get("vector_json")
            stored = json.loads(stored) if isinstance(stored, (str, bytes)) else stored
            normalized = _vector(stored, len(vector))
            score = sum(a * b for a, b in zip(vector, normalized))
            if score >= .45:
                dense.append((key, score))
        dense.sort(key=lambda item: (-item[1], item[0]))
    fused = rrf_merge([key for key, _ in lexical[:FIRST_STAGE_DEPTH]], [key for key, _ in dense[:FIRST_STAGE_DEPTH]])
    reranked = rerank([(key, by_key[key]) for key in fused], rerank_terms, extra_terms)
    keys = [key for key, _ in reranked[:FINAL_DEPTH]]
    retrieval = {"mode": "hybrid" if query_vector is not None else "lexical",
            "lexical_version": LEXICAL_VERSION, "embedding_model": embedding_model if query_vector is not None else None,
            "index_version": index_version if query_vector is not None else None,
            "dimensions": len(query_vector) if query_vector is not None else None,
            "eligible_chunks": len(rows), "lexical_matches": len(lexical), "dense_matches": len(dense),
            "dense_verified": query_vector is not None and bool(dense),
            "rerank_version": RERANK_VERSION, "first_stage_depth": FIRST_STAGE_DEPTH,
            "fused_candidates": len(fused), "final_depth": FINAL_DEPTH,
            # Recorded so a wrong answer can be attributed to recall or to ranking.
            "fused_ranking": [list(key) for key in fused],
            "rerank_scores": [{"chunk": list(key), "score": round(score, 6)} for key, score in reranked]}
    if model_query is not None:
        retrieval["submitted_query"] = query
        retrieval["model_query"] = model_query
    return [by_key[key] for key in keys], retrieval


def evidence_result(rows, retrieval):
    # All retrieved text is data. A lexical warning cannot decide intent or authorize tools,
    # but it does decide admissibility: a passage carrying instructions that try to override
    # the rules is flagged per chunk, so the caller can keep it out of the citable set while
    # still knowing the document exists and what it is about.
    warned = sum(bool(INSTRUCTION_PATTERN.search(row['content'])) for row in rows)
    citations = [{**{name: row[name] for name in ("doc_id", "version", "chunk_id", "title", "source_uri", "checksum",
                 "heading", "content", "start_offset", "end_offset", "start_line", "end_line")},
                 "carries_untrusted_instructions": bool(INSTRUCTION_PATTERN.search(row['content']))}
                 for row in rows[:4]]
    facts, conflicts = {}, set()
    for row in rows:
        values = row.get("facts_json", {})
        values = json.loads(values) if isinstance(values, (str, bytes)) else values
        for key, value in values.items():
            if key in facts and facts[key] != value:
                conflicts.add(key)
            facts[key] = value
    status = "conflicting" if conflicts else "answered" if citations else "insufficient"
    return {"answer_status": status, "citations": citations, "retrieval": retrieval,
            "conflict_keys": sorted(conflicts), "untrusted_instructions_detected": bool(warned),
            "source_trust": "untrusted_data",
            "requires_human": False,  # Retrieval cannot decide whether the task needs a human.
            "candidates": [{"doc_id": row["doc_id"], "version": row["version"], "chunk_id": row["chunk_id"]} for row in rows],
            "evidence_only": True}


class KnowledgeStore(SessionStore):
    def __init__(self, connect):
        super().__init__(connect)
        self._search_cache = TtlCache(256, 300)

    @staticmethod
    def _catalog(cursor, scope):
        cursor.execute("INSERT IGNORE INTO knowledge_catalog (execution_scope_id) VALUES (%s)", (scope,))
        cursor.execute("SELECT revision FROM knowledge_catalog WHERE execution_scope_id=%s FOR UPDATE", (scope,))
        return cursor.fetchone()["revision"]

    @staticmethod
    def _document(cursor, scope, doc_id, version):
        cursor.execute("SELECT * FROM knowledge_document WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                       (scope, _text(doc_id, "doc_id", 128), _integer(version, "version", 1, 2147483647)))
        row = cursor.fetchone()
        if not row:
            raise StateError("document_not_found", 404)
        return row

    def create_draft(self, actor, payload):
        _merchant(actor)
        if not isinstance(payload, dict) or set(payload) - {"doc_id", "title", "source_uri", "body", "language", "acl",
                "acl_actor_id", "product_ids", "category_ids", "facts", "valid_from", "valid_until"}:
            raise StateError("invalid_document", 422)
        scope = _actor(actor)[2]
        doc_id = _text(payload.get("doc_id", uuid.uuid4().hex), "doc_id", 128)
        title = _text(payload.get("title"), "title", 256)
        source_uri = _text(payload.get("source_uri"), "source_uri", 512)
        body = _text(payload.get("body"), "body", 300000)
        language = payload.get("language", "zh-CN")
        if language not in {"zh-CN", "en", "mixed"}:
            raise StateError("invalid_language", 422)
        acl = payload.get("acl")
        if acl not in {"PUBLIC", "USER", "MERCHANT", "ACTOR"}:
            raise StateError("invalid_acl", 422)
        acl_actor = _text(payload.get("acl_actor_id"), "acl_actor_id", 64) if acl == "ACTOR" else None
        if acl != "ACTOR" and payload.get("acl_actor_id") is not None:
            raise StateError("invalid_acl_actor_id", 422)
        start, end = _expiry(payload.get("valid_from")), _expiry(payload.get("valid_until"))
        if start >= end:
            raise StateError("invalid_validity_interval", 422)
        products = canonical(_ids(payload.get("product_ids", []), "product_ids"))
        categories = canonical(_ids(payload.get("category_ids", []), "category_ids"))
        facts = _json(payload.get("facts", {}))
        parsed_facts = json.loads(facts)
        if len(parsed_facts) > 32 or any(not isinstance(k, str) or len(k) > 128 or
                not isinstance(v, str) or not v or len(v) > 256 or v not in body for k, v in parsed_facts.items()):
            raise StateError("facts_require_verbatim_evidence", 422)
        chunks = split_document(body)
        with self._transaction() as cursor:
            self._catalog(cursor, scope)
            cursor.execute("SELECT COALESCE(MAX(version),0)+1 AS version FROM knowledge_document WHERE execution_scope_id=%s AND doc_id=%s", (scope, doc_id))
            version = cursor.fetchone()["version"]
            prefix = sha256(canonical({"scope": scope, "doc_id": doc_id, "version": version}).encode()).hexdigest()[:16]
            chunks = [{**chunk, "chunk_id": prefix + "-" + chunk["chunk_id"]} for chunk in chunks]
            cursor.execute("""INSERT INTO knowledge_document (execution_scope_id,doc_id,version,title,source_uri,checksum,
                body,language,acl,acl_actor_id,product_ids_json,category_ids_json,facts_json,valid_from,valid_until,status,
                created_by,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT',%s,UTC_TIMESTAMP(6))""",
                (scope, doc_id, version, title, source_uri, sha256(body.encode()).hexdigest(), body, language, acl, acl_actor,
                 products, categories, facts, start, end, actor.actor_id))
            cursor.executemany("""INSERT INTO knowledge_chunk (execution_scope_id,doc_id,version,chunk_id,heading,content,
                start_offset,end_offset,start_line,end_line) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(scope, doc_id, version, *[chunk[key] for key in ("chunk_id", "heading", "content", "start_offset", "end_offset", "start_line", "end_line")]) for chunk in chunks])
            return _public(self._document(cursor, scope, doc_id, version))

    def publish(self, actor, doc_id, version):
        _merchant(actor)
        scope = _actor(actor)[2]
        with self._transaction() as cursor:
            self._catalog(cursor, scope)
            row = self._document(cursor, scope, doc_id, version)
            if row["status"] == "PUBLISHED":
                return _public(row)
            if row["status"] != "DRAFT":
                raise StateError("document_not_draft")
            cursor.execute("SELECT UTC_TIMESTAMP(6) AS now")
            if row["valid_until"] <= cursor.fetchone()["now"]:
                raise StateError("document_expired")
            cursor.execute("""SELECT COUNT(*) AS count FROM knowledge_chunk c JOIN knowledge_document d
                USING(execution_scope_id,doc_id,version) WHERE d.execution_scope_id=%s AND
                ((d.status='PUBLISHED' AND d.doc_id<>%s) OR (d.doc_id=%s AND d.version=%s))""", (scope, doc_id, doc_id, version))
            if cursor.fetchone()["count"] > MAX_CHUNKS:
                raise StateError("knowledge_capacity_exceeded", 422)
            cursor.execute("UPDATE knowledge_document SET status='WITHDRAWN',withdrawn_at=UTC_TIMESTAMP(6) "
                           "WHERE execution_scope_id=%s AND doc_id=%s AND status='PUBLISHED'", (scope, doc_id))
            cursor.execute("UPDATE knowledge_document SET status='PUBLISHED',published_at=UTC_TIMESTAMP(6) "
                           "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s", (scope, doc_id, version))
            cursor.execute("UPDATE knowledge_catalog SET revision=revision+1 WHERE execution_scope_id=%s", (scope,))
            return _public(self._document(cursor, scope, doc_id, version))

    def withdraw(self, actor, doc_id, version):
        _merchant(actor)
        scope = _actor(actor)[2]
        with self._transaction() as cursor:
            self._catalog(cursor, scope)
            self._document(cursor, scope, doc_id, version)
            cursor.execute("UPDATE knowledge_document SET status='WITHDRAWN',withdrawn_at=UTC_TIMESTAMP(6) "
                           "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s AND status<>'WITHDRAWN'", (scope, doc_id, version))
            if cursor.rowcount:
                cursor.execute("UPDATE knowledge_catalog SET revision=revision+1 WHERE execution_scope_id=%s", (scope,))
            return _public(self._document(cursor, scope, doc_id, version))

    def list_documents(self, actor):
        _merchant(actor)
        with self._transaction() as cursor:
            cursor.execute("SELECT doc_id,version,title,status,acl,valid_from,valid_until,checksum,published_at "
                           "FROM knowledge_document WHERE execution_scope_id=%s ORDER BY doc_id,version DESC LIMIT 1000", (_actor(actor)[2],))
            return [_public(row) for row in cursor.fetchall()]

    def get_document(self, actor, doc_id, version):
        _merchant(actor)
        with self._transaction() as cursor:
            return _public(self._document(cursor, _actor(actor)[2], doc_id, version))

    def read_published_document(self, actor, doc_id, version):
        kind, _, _ = _actor(actor)
        if "shopping:read" not in getattr(actor, "permissions", ()) and kind != "merchant":
            raise StateError("permission_denied", 403)
        doc_id, version = _text(doc_id, "doc_id", 128), _integer(version, "version", 1, 2147483647)
        with self._transaction() as cursor:
            cursor.execute("SELECT d.doc_id,d.version,d.title,d.source_uri,d.body,d.checksum,d.language "
                           "FROM knowledge_document d WHERE " + VISIBLE_DOCUMENT + " AND d.doc_id=%s AND d.version=%s",
                           (*_visibility(actor), doc_id, version))
            row = cursor.fetchone()
            if not row:
                raise StateError("document_not_found", 404)
            return _public(row)

    def draft_chunks(self, actor, doc_id, version):
        _merchant(actor)
        with self._transaction() as cursor:
            self._document(cursor, _actor(actor)[2], doc_id, version)
            cursor.execute("SELECT chunk_id,heading,content FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s ORDER BY chunk_id", (_actor(actor)[2], doc_id, version))
            return list(cursor.fetchall())

    def set_embeddings(self, actor, doc_id, version, *, model, index_version, vectors):
        _merchant(actor)
        model, index_version = _text(model, "embedding_model", 128), _text(index_version, "index_version", 128)
        if not isinstance(vectors, list) or not vectors or len(vectors) > MAX_CHUNKS:
            raise StateError("invalid_embeddings", 422)
        mapped, dimensions = {}, None
        for item in vectors:
            if not isinstance(item, dict) or set(item) != {"chunk_id", "vector"}:
                raise StateError("invalid_embeddings", 422)
            key = _text(item["chunk_id"], "chunk_id", 32)
            vector = _vector(item["vector"], dimensions)
            if key in mapped:
                raise StateError("duplicate_embedding_chunk", 422)
            mapped[key], dimensions = vector, len(vector)
        scope = _actor(actor)[2]
        with self._transaction() as cursor:
            self._catalog(cursor, scope)
            row = self._document(cursor, scope, doc_id, version)
            if row["status"] != "DRAFT":
                raise StateError("document_not_draft")
            cursor.execute("SELECT chunk_id FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s", (scope, doc_id, version))
            if {row["chunk_id"] for row in cursor.fetchall()} != mapped.keys():
                raise StateError("incomplete_embeddings", 422)
            cursor.executemany("UPDATE knowledge_chunk SET embedding_model=%s,embedding_dimensions=%s,index_version=%s,vector_json=%s "
                "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s AND chunk_id=%s",
                [(model, dimensions, index_version, canonical(vector), scope, doc_id, version, key) for key, vector in mapped.items()])
        return {"model": model, "index_version": index_version, "dimensions": dimensions, "chunks": len(mapped)}

    def draft_chunks_with_status(self, actor, doc_id, version):
        """draft_chunks plus an embedded flag, so an index job can resume and skip done chunks."""
        _merchant(actor)
        with self._transaction() as cursor:
            self._document(cursor, _actor(actor)[2], doc_id, version)
            cursor.execute("SELECT chunk_id,heading,content,(vector_json IS NOT NULL) AS embedded FROM knowledge_chunk "
                "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s ORDER BY chunk_id",
                (_actor(actor)[2], doc_id, version))
            return [dict(row) for row in cursor.fetchall()]

    def embed_batch(self, actor, doc_id, version, *, model, index_version, vectors):
        """Batch-wise vector write for the async index pipeline: same validation as
        set_embeddings but without the all-chunks-at-once completeness check, so a job can
        persist progress batch by batch and a resumed job only re-embeds missing chunks."""
        _merchant(actor)
        model, index_version = _text(model, "embedding_model", 128), _text(index_version, "index_version", 128)
        if not isinstance(vectors, list) or not vectors:
            raise StateError("invalid_embeddings", 422)
        mapped, dimensions = {}, None
        for item in vectors:
            if not isinstance(item, dict) or set(item) != {"chunk_id", "vector"}:
                raise StateError("invalid_embeddings", 422)
            key = _text(item["chunk_id"], "chunk_id", 32)
            vector = _vector(item["vector"], dimensions)
            if key in mapped:
                raise StateError("duplicate_embedding_chunk", 422)
            mapped[key], dimensions = vector, len(vector)
        scope = _actor(actor)[2]
        with self._transaction() as cursor:
            row = self._document(cursor, scope, doc_id, version)
            if row["status"] != "DRAFT":
                raise StateError("document_not_draft")
            cursor.execute("SELECT chunk_id FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                           (scope, doc_id, version))
            known = {item["chunk_id"] for item in cursor.fetchall()}
            if not set(mapped) <= known:
                raise StateError("unknown_embedding_chunk", 422)
            cursor.executemany("UPDATE knowledge_chunk SET embedding_model=%s,embedding_dimensions=%s,index_version=%s,vector_json=%s "
                "WHERE execution_scope_id=%s AND doc_id=%s AND version=%s AND chunk_id=%s",
                [(model, dimensions, index_version, canonical(vector), scope, doc_id, version, key)
                 for key, vector in mapped.items()])
        return {"chunks": len(mapped), "model": model, "index_version": index_version}

    def embedding_counts(self, actor, doc_id, version):
        _merchant(actor)
        with self._transaction() as cursor:
            self._document(cursor, _actor(actor)[2], doc_id, version)
            cursor.execute("SELECT COUNT(*) AS total,COALESCE(SUM(vector_json IS NOT NULL),0) AS embedded "
                "FROM knowledge_chunk WHERE execution_scope_id=%s AND doc_id=%s AND version=%s",
                (_actor(actor)[2], doc_id, version))
            row = cursor.fetchone()
            return {"total": row["total"], "embedded": row["embedded"]}

    def search(self, actor, query, *, query_vector=None, embedding_model=None, index_version=None,
               product_id=None, category_id=None, utterance=None, model_query=None):
        kind, actor_id, scope = _actor(actor)
        query = _text(query, "query", 1000)
        if "shopping:read" not in getattr(actor, "permissions", ()) and kind != "merchant":
            raise StateError("permission_denied", 403)
        filters, values = [], []
        for field, value in (("product_ids_json", product_id), ("category_ids_json", category_id)):
            if value is not None:
                filters.append(f"AND (JSON_LENGTH(d.{field})=0 OR JSON_CONTAINS(d.{field},%s))")
                values.append(canonical(_text(value, field, 128)))
        # Identical authorized searches repeat within a turn and across sessions. The exact
        # scan pair below is the measured hot path, so reuse its result for 5 minutes; a
        # publish bumps catalog revision (key part), while expiry/ACL shifts can lag by the TTL.
        with self._transaction() as cursor:
            cursor.execute("SELECT revision FROM knowledge_catalog WHERE execution_scope_id=%s", (scope,))
            catalog = cursor.fetchone()
        revision = catalog["revision"] if catalog else 0
        vector_key = (sha256(canonical(query_vector).encode()).hexdigest()
                      if isinstance(query_vector, list) else None)
        cache_key = (scope, kind, actor_id, query, vector_key, embedding_model, index_version,
                     product_id, category_id, utterance, model_query, revision)
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            KNOWLEDGE_CACHE_REQUESTS.labels("hit").inc()
            return json.loads(cached)
        KNOWLEDGE_CACHE_REQUESTS.labels("miss").inc()
        with self._transaction() as cursor:
            # ponytail: derive <=5000 authorized chunks per request; move to a versioned
            # numeric index only when this bounded exact scan is a measured bottleneck.
            cursor.execute("""SELECT c.*,d.title,d.source_uri,d.checksum,d.facts_json FROM knowledge_document d
                JOIN knowledge_chunk c USING(execution_scope_id,doc_id,version)
                WHERE """ + VISIBLE_DOCUMENT + " " + " ".join(filters) +
                " ORDER BY d.doc_id,d.version,c.chunk_id LIMIT 5001", (*_visibility(actor), *values))
            rows = list(cursor.fetchall())
            cursor.execute("""SELECT c.content,c.heading,d.doc_id,d.title,d.acl FROM knowledge_document d
                JOIN knowledge_chunk c USING(execution_scope_id,doc_id,version)
                WHERE """ + HIDDEN_DOCUMENT + " " + " ".join(filters) +
                " ORDER BY d.doc_id,d.version,c.chunk_id LIMIT 5001", (*_visibility(actor), *values))
            hidden_rows = list(cursor.fetchall())
            cursor.execute("SELECT revision FROM knowledge_catalog WHERE execution_scope_id=%s", (scope,))
            catalog = cursor.fetchone()
        ranked, metadata = rank_chunks(rows, query, query_vector=query_vector, embedding_model=embedding_model,
                                       index_version=index_version, utterance=utterance, model_query=model_query)
        metadata["catalog_revision"] = catalog["revision"] if catalog else 0
        denied = acl_denied_documents(rows, hidden_rows, utterance, query)
        metadata["acl_denied"] = denied
        result = evidence_result(ranked, metadata)
        result["acl_denied"] = denied
        self._search_cache.put(cache_key, canonical(result))
        return result

    def validate_citations(self, actor, citations):
        """Recheck fresh publication, ACL and expiry immediately before answering.

        Historical answers retain their recorded version; this gate is for new answers.
        """
        _actor(actor)
        if not isinstance(citations, list) or not 1 <= len(citations) <= 4:
            return False
        with self._transaction() as cursor:
            return self._validate_citations(cursor, actor, citations)

    @staticmethod
    def _validate_citations(cursor, actor, citations):
        if not isinstance(citations, list) or not 1 <= len(citations) <= 4:
            return False
        for citation in citations:
            if not isinstance(citation, dict):
                return False
            try:
                doc_id = _text(citation.get("doc_id"), "doc_id", 128)
                version = _integer(citation.get("version"), "version", 1, 2147483647)
                chunk_id = _text(citation.get("chunk_id"), "chunk_id", 32)
            except StateError:
                return False
            # Current locking read: a prior query in the caller's REPEATABLE READ
            # transaction must not resurrect a document withdrawn before this check.
            cursor.execute("""SELECT c.content,c.start_offset,c.end_offset,c.start_line,c.end_line,d.checksum
                FROM knowledge_document d JOIN knowledge_chunk c USING(execution_scope_id,doc_id,version)
                WHERE """ + VISIBLE_DOCUMENT + " AND d.doc_id=%s AND d.version=%s AND c.chunk_id=%s FOR SHARE",
                (*_visibility(actor), doc_id, version, chunk_id))
            row = cursor.fetchone()
            if (not row or any(name in citation and citation[name] != value for name, value in row.items())
                    or "text" in citation and citation["text"] != row["content"]):
                return False
        return True
