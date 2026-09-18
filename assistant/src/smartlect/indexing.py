"""Async knowledge-indexing pipeline: publish-time embedding moved off the request path.

One job = one draft version's full embedding pass plus the publish step. Chunks are
embedded in batches of 10; each batch writes its IndexModelAudit row before the HTTP call
(crash-safe, same as the previous synchronous flow) and persists vectors through
KnowledgeStore.embed_batch, so a resumed job re-embeds only chunks that are still missing.
Jobs live in MySQL — a process restart re-enqueues PENDING/RUNNING work in lifespan —
because Growth runs single-instance and a queue broker would be unused infrastructure.

The worker actor is reconstructed from the job row with exactly the permissions the
pipeline needs (admin:legacy for the knowledge store, shopping:read for search), not the
submitting human's full identity.
"""
import asyncio
import uuid

from smartlect.auth import ActorContext
from smartlect.events import canonical
from smartlect.provider import IndexModelAudit, ProviderError
from smartlect.state import SessionStore, StateError, _actor, _integer, _public, _text

BATCH_SIZE = 10
AUDIT_BATCH_WINDOW = 4  # knowledge_index_attempt.batch_index is validated 0-3; rotate publication_id per window
JOB_STATES = ("PENDING", "RUNNING", "DONE", "FAILED")


class IndexingJobStore(SessionStore):
    def create(self, actor, doc_id, version, total_chunks):
        _actor(actor)
        job_id = uuid.uuid4().hex
        row = {"job_id": job_id, "execution_scope_id": actor.execution_scope_id, "actor_id": actor.actor_id,
               "doc_id": _text(doc_id, "doc_id", 128), "version": _integer(version, "version", 1, 2147483647),
               "state": "PENDING", "total_chunks": _integer(total_chunks, "total_chunks", 1, 2147483647),
               "processed_chunks": 0, "failed_chunks": 0, "embedding_model": None, "index_version": None,
               "message": None, "error_type": None}
        # Return the built row instead of re-reading: connections are thread-local and a
        # REPEATABLE READ snapshot on another worker thread would miss this fresh INSERT.
        with self._transaction() as cursor:
            cursor.execute("""INSERT INTO knowledge_index_job (job_id,execution_scope_id,actor_id,doc_id,version,
                state,total_chunks,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,'PENDING',%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
                (job_id, row["execution_scope_id"], row["actor_id"], row["doc_id"], row["version"],
                 row["total_chunks"]))
        return row

    def claim(self, job_id):
        job_id = _text(job_id, "job_id", 32)
        with self._transaction() as cursor:
            cursor.execute("UPDATE knowledge_index_job SET state='RUNNING',updated_at=UTC_TIMESTAMP(6) "
                           "WHERE job_id=%s AND state IN ('PENDING','RUNNING')", (job_id,))
            if cursor.rowcount != 1:
                raise StateError("index_job_not_resumable", 409)
            cursor.execute("SELECT * FROM knowledge_index_job WHERE job_id=%s", (job_id,))
            return _public(cursor.fetchone())

    def progress(self, job_id, *, processed, failed):
        with self._transaction() as cursor:
            cursor.execute("UPDATE knowledge_index_job SET processed_chunks=%s,failed_chunks=%s,updated_at=UTC_TIMESTAMP(6) "
                           "WHERE job_id=%s", (_integer(processed, "processed", 0, 2147483647),
                                               _integer(failed, "failed", 0, 2147483647), _text(job_id, "job_id", 32)))

    def finish(self, job_id, state, *, message=None, error_type=None, embedding_model=None, index_version=None):
        if state not in ("DONE", "FAILED"):
            raise StateError("invalid_index_job_state", 422)
        # Optional fields stay NULL on failure paths; only validate what is actually set.
        message = None if message is None else _text(message, "message", 500)
        error_type = None if error_type is None else _text(error_type, "error_type", 64)
        embedding_model = None if embedding_model is None else _text(embedding_model, "embedding_model", 128)
        index_version = None if index_version is None else _text(index_version, "index_version", 128)
        with self._transaction() as cursor:
            cursor.execute("""UPDATE knowledge_index_job SET state=%s,message=%s,error_type=%s,
                embedding_model=%s,index_version=%s,updated_at=UTC_TIMESTAMP(6) WHERE job_id=%s AND state='RUNNING'""",
                (state, message, error_type, embedding_model, index_version, _text(job_id, "job_id", 32)))
            if cursor.rowcount != 1:
                raise StateError("index_job_not_running", 409)

    def list_jobs(self, actor, limit=20):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("SELECT * FROM knowledge_index_job WHERE execution_scope_id=%s "
                           "ORDER BY created_at DESC LIMIT %s", (actor.execution_scope_id, min(max(int(limit), 1), 100)))
            return [_public(row) for row in cursor.fetchall()]

    def get_job(self, actor, job_id):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("SELECT * FROM knowledge_index_job WHERE job_id=%s AND execution_scope_id=%s",
                           (_text(job_id, "job_id", 32), actor.execution_scope_id))
            row = cursor.fetchone()
            if not row:
                raise StateError("index_job_not_found", 404)
            return _public(row)

    def stale_jobs(self):
        with self._transaction() as cursor:
            cursor.execute("SELECT * FROM knowledge_index_job WHERE state IN ('PENDING','RUNNING') "
                           "ORDER BY created_at LIMIT 50")
            return [_public(row) for row in cursor.fetchall()]

    def failed_jobs(self, limit=20):
        with self._transaction() as cursor:
            cursor.execute("SELECT * FROM knowledge_index_job WHERE state='FAILED' "
                           "ORDER BY updated_at DESC LIMIT %s", (int(limit),))
            return [_public(row) for row in cursor.fetchall()]

    def counts_by_state(self):
        with self._transaction() as cursor:
            cursor.execute("SELECT state, COUNT(*) AS count FROM knowledge_index_job GROUP BY state")
            return {row["state"]: int(row["count"]) for row in cursor.fetchall()}


class IndexingService:
    def __init__(self, connect, knowledge, provider, *, settings, config):
        self.jobs = IndexingJobStore(connect)
        self.knowledge = knowledge
        self.provider = provider
        self.settings = settings
        self.config = config
        self._tasks = {}
        # Serialize embedding jobs: the provider semaphore is the cost gate for conversations,
        # bulk indexing must not multiply its pressure.
        self._gate = asyncio.Semaphore(1)

    def embedding_enabled(self):
        return self.settings.model_mode == "live" and bool(self.config.get("SMARTLECT_EMBEDDING_API_KEY"))

    def record_sync_publish(self, actor, doc_id, version):
        """BM25-only publish still leaves an ops-visible DONE job."""
        job = self.jobs.create(actor, doc_id, version, 1)
        self.jobs.claim(job["job_id"])
        self.jobs.progress(job["job_id"], processed=1, failed=0)
        self.jobs.finish(job["job_id"], "DONE", message="published_without_embedding",
                         index_version="bm25")
        return {**job, "state": "DONE", "processed_chunks": 1, "failed_chunks": 0,
                "message": "published_without_embedding", "index_version": "bm25"}

    async def submit(self, actor, doc_id, version):
        chunks = await asyncio.to_thread(self.knowledge.draft_chunks_with_status, actor, doc_id, version)
        job = await asyncio.to_thread(self.jobs.create, actor, doc_id, version, len(chunks))
        self._spawn(job["job_id"])
        return job

    def _spawn(self, job_id):
        task = asyncio.create_task(self._run(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    async def _run(self, job_id):
        async with self._gate:
            try:
                await self._execute(job_id)
            except Exception as error:
                try:
                    await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                            message=f"index_job_crashed: {type(error).__name__}",
                                            error_type=type(error).__name__)
                except StateError:
                    pass

    async def _execute(self, job_id):
        job = await asyncio.to_thread(self.jobs.claim, job_id)
        actor = ActorContext(subject_type="merchant", actor_id=job["actor_id"], session_id="knowledge-index",
                             permissions=("admin:legacy", "shopping:read"),
                             execution_scope_id=job["execution_scope_id"])
        try:
            chunks = await asyncio.to_thread(self.knowledge.draft_chunks_with_status, actor,
                                             job["doc_id"], job["version"])
        except StateError as error:
            await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                    message=f"草稿不可用：{error.code}", error_type=error.code)
            return
        todo = [chunk for chunk in chunks if not chunk["embedded"]]
        processed = len(chunks) - len(todo)
        model, index_version = None, None
        base_publication = uuid.uuid4().hex
        await asyncio.to_thread(self.jobs.progress, job_id, processed=processed, failed=0)
        for offset, start in enumerate(range(0, len(todo), BATCH_SIZE)):
            batch = todo[start:start + BATCH_SIZE]
            window, batch_index = divmod(offset, AUDIT_BATCH_WINDOW)
            publication_id = base_publication if window == 0 else uuid.uuid4().hex
            audit = IndexModelAudit(self.jobs.connect, actor, job["doc_id"], job["version"],
                                    publication_id, batch_index)
            try:
                embedded = await self.provider.embed(
                    [chunk["content"] for chunk in batch],
                    before_attempt=lambda: asyncio.to_thread(audit.start),
                    on_trace=lambda record: asyncio.to_thread(audit.finish, record),
                    prompt_version="knowledge-index-v1", schema_version="embedding-v1")
            except ProviderError as error:
                await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                        message=f"索引中断（{error.code}）：已成功 {processed}/{len(chunks)} 条切片；"
                                                "重试将从缺失切片续跑",
                                        error_type=error.code)
                return
            meta = embedded["metadata"]
            model, index_version = meta["model_id"], f"{meta['model_id']}:d{meta['dimensions']}:v1"
            await asyncio.to_thread(self.knowledge.embed_batch, actor, job["doc_id"], job["version"],
                                    model=model, index_version=index_version,
                                    vectors=[{"chunk_id": chunk["chunk_id"], "vector": vector}
                                             for chunk, vector in zip(batch, embedded["embeddings"], strict=True)])
            processed += len(batch)
            await asyncio.to_thread(self.jobs.progress, job_id, processed=processed, failed=0)
        counts = await asyncio.to_thread(self.knowledge.embedding_counts, actor, job["doc_id"], job["version"])
        if counts["embedded"] < counts["total"]:
            await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                    message=f"embedding_incomplete: {counts['embedded']}/{counts['total']}",
                                    error_type="embedding_incomplete")
            return
        await asyncio.to_thread(self.knowledge.publish, actor, job["doc_id"], job["version"])
        await asyncio.to_thread(self.jobs.finish, job_id, "DONE",
                                message=f"已发布：{counts['total']} 条切片完成索引",
                                embedding_model=model, index_version=index_version)

    async def resume_stale(self):
        for job in await asyncio.to_thread(self.jobs.stale_jobs):
            self._spawn(job["job_id"])

    def ops_summary(self):
        return {"counts": self.jobs.counts_by_state(), "failed": self.jobs.failed_jobs()}

    async def retry_failed(self, actor, job_id):
        """手动重试失败索引：同一 (doc_id, version) 重新提交一个全新任务。"""
        job = self.jobs.get_job(actor, job_id)
        if job.get("state") != "FAILED":
            raise StateError("index_job_not_failed", 409)
        return await self.submit(actor, job["doc_id"], job["version"])

    async def drain(self):
        """Wait for running jobs to settle; used by tests and graceful shutdown checks."""
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    def shutdown(self):
        for task in self._tasks.values():
            task.cancel()
