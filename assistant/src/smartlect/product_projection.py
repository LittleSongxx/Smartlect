"""Save/shelf → PRODUCT_AUTO projection. Product save must never wait on this path.

Only PRODUCT_AUTO documents are created or republished here. MANUAL store policy
is never touched. Price and stock never enter the projected body.
"""
import asyncio
import logging
import uuid

from smartlect.auth import ActorContext
from smartlect.knowledge_import import build_document, product_doc_id
from smartlect.state import SessionStore, StateError, _actor, _public, _text

log = logging.getLogger(__name__)

JOB_STATES = ("PENDING", "RUNNING", "DONE", "FAILED", "SKIPPED")
MAX_ATTEMPTS = 3
INTERNAL_ACTOR_ID = "product-projection"


def projection_actor(scope="store", actor_id=INTERNAL_ACTOR_ID):
    return ActorContext(subject_type="merchant", actor_id=actor_id, session_id="product-projection",
                        permissions=("admin:legacy", "shopping:read"), execution_scope_id=scope)


class ProjectionJobStore(SessionStore):
    def create(self, actor, product_id):
        _actor(actor)
        job_id = uuid.uuid4().hex
        row = {"job_id": job_id, "execution_scope_id": actor.execution_scope_id,
               "actor_id": actor.actor_id, "product_id": _text(product_id, "product_id", 64),
               "state": "PENDING", "attempt": 0, "checksum": None, "doc_id": None, "version": None,
               "index_job_id": None, "message": None, "error_type": None}
        with self._transaction() as cursor:
            cursor.execute("""INSERT INTO product_projection_job
                (job_id,execution_scope_id,actor_id,product_id,state,attempt,created_at,updated_at)
                VALUES (%s,%s,%s,%s,'PENDING',0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
                           (job_id, row["execution_scope_id"], row["actor_id"], row["product_id"]))
        return row

    def active_job(self, actor, product_id):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("""SELECT * FROM product_projection_job
                WHERE execution_scope_id=%s AND product_id=%s AND state IN ('PENDING','RUNNING')
                ORDER BY created_at DESC LIMIT 1""",
                           (actor.execution_scope_id, _text(product_id, "product_id", 64)))
            row = cursor.fetchone()
            return _public(row) if row else None

    def latest(self, actor, product_id):
        _actor(actor)
        with self._transaction() as cursor:
            cursor.execute("""SELECT * FROM product_projection_job
                WHERE execution_scope_id=%s AND product_id=%s
                ORDER BY created_at DESC LIMIT 1""",
                           (actor.execution_scope_id, _text(product_id, "product_id", 64)))
            row = cursor.fetchone()
            return _public(row) if row else None

    def claim(self, job_id):
        job_id = _text(job_id, "job_id", 32)
        with self._transaction() as cursor:
            # FAILED 也可被重新认领：退避后的自动重试与人工 /retry 都从这里进。
            cursor.execute("""UPDATE product_projection_job
                SET state='RUNNING',attempt=attempt+1,updated_at=UTC_TIMESTAMP(6)
                WHERE job_id=%s AND state IN ('PENDING','RUNNING','FAILED')""", (job_id,))
            if cursor.rowcount != 1:
                raise StateError("projection_job_not_resumable", 409)
            cursor.execute("SELECT * FROM product_projection_job WHERE job_id=%s", (job_id,))
            return _public(cursor.fetchone())

    def finish(self, job_id, state, *, checksum=None, doc_id=None, version=None,
               index_job_id=None, message=None, error_type=None):
        if state not in ("DONE", "FAILED", "SKIPPED"):
            raise StateError("invalid_projection_job_state", 422)
        with self._transaction() as cursor:
            cursor.execute("""UPDATE product_projection_job
                SET state=%s,checksum=%s,doc_id=%s,version=%s,index_job_id=%s,message=%s,error_type=%s,
                    updated_at=UTC_TIMESTAMP(6)
                WHERE job_id=%s AND state='RUNNING'""",
                           (state, checksum, doc_id, version, index_job_id, message, error_type,
                            _text(job_id, "job_id", 32)))
            if cursor.rowcount != 1:
                raise StateError("projection_job_not_running", 409)

    def stale_jobs(self):
        with self._transaction() as cursor:
            cursor.execute("""SELECT * FROM product_projection_job
                WHERE state IN ('PENDING','RUNNING') ORDER BY created_at LIMIT 50""")
            return [_public(row) for row in cursor.fetchall()]

    def retryable_failed_jobs(self, *, backoff_seconds=90):
        """FAILED 且未烧完尝试次数、且已过退避窗口的任务，供周期清扫自动重投。"""
        with self._transaction() as cursor:
            cursor.execute("""SELECT * FROM product_projection_job
                WHERE state='FAILED' AND attempt < %s
                  AND updated_at < UTC_TIMESTAMP(6) - INTERVAL %s SECOND
                ORDER BY updated_at LIMIT 20""", (MAX_ATTEMPTS, int(backoff_seconds)))
            return [_public(row) for row in cursor.fetchall()]

    def ops_summary(self):
        with self._transaction() as cursor:
            cursor.execute("""SELECT state, COUNT(*) AS count FROM product_projection_job
                GROUP BY state""")
            counts = {row["state"]: int(row["count"]) for row in cursor.fetchall()}
            cursor.execute("""SELECT job_id,product_id,attempt,error_type,message,updated_at
                FROM product_projection_job WHERE state='FAILED' ORDER BY updated_at DESC LIMIT 20""")
            failed = [_public(row) for row in cursor.fetchall()]
        return {"counts": counts, "failed": failed, "max_attempts": MAX_ATTEMPTS}


class ProductProjectionService:
    def __init__(self, connect, knowledge, commerce, indexing=None):
        self.jobs = ProjectionJobStore(connect)
        self._sweeper = None
        self.knowledge = knowledge
        self.commerce = commerce
        self.indexing = indexing
        self._tasks = {}
        self._gate = asyncio.Semaphore(2)
        self._loop = None

    def bind_loop(self, loop=None):
        self._loop = loop or asyncio.get_running_loop()
        return self._loop

    def enqueue(self, actor, product_id):
        product_id = _text(product_id, "product_id", 64)
        existing = self.jobs.active_job(actor, product_id)
        if existing:
            if existing["job_id"] not in self._tasks:
                self._spawn(existing["job_id"])
            log.info("product_projection_reuse product_id=%s job_id=%s state=%s",
                     product_id, existing["job_id"], existing["state"])
            return existing
        job = self.jobs.create(actor, product_id)
        self._spawn(job["job_id"])
        log.info("product_projection_enqueued product_id=%s job_id=%s scope=%s",
                 product_id, job["job_id"], actor.execution_scope_id)
        return job

    def _event_loop(self):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            self._loop = running
            return running
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("projection_loop_unavailable")
        return self._loop

    def _start_task(self, job_id):
        if job_id in self._tasks:
            return
        task = asyncio.create_task(self._run(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    def _spawn(self, job_id):
        loop = self._event_loop()
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._start_task(job_id)
            return
        loop.call_soon_threadsafe(self._start_task, job_id)

    async def _run(self, job_id):
        async with self._gate:
            try:
                await self._execute(job_id)
            except Exception as error:
                log.exception("product_projection_crashed job_id=%s", job_id)
                try:
                    await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                            message=f"projection_crashed: {type(error).__name__}",
                                            error_type=type(error).__name__)
                except StateError:
                    pass

    async def _execute(self, job_id):
        job = await asyncio.to_thread(self.jobs.claim, job_id)
        actor = projection_actor(job["execution_scope_id"], job["actor_id"])
        product_id = job["product_id"]
        try:
            details = await self.commerce.request(
                "product", "/internal/product/commerce/batchDetail", actor=actor,
                data={"productIds": [product_id]})
        except Exception as error:
            code = getattr(error, "code", None) or type(error).__name__
            if job.get("attempt", 1) < MAX_ATTEMPTS:
                await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                        message=f"commerce_retryable: {code}", error_type=code)
            else:
                await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                        message=f"commerce_unavailable: {code}", error_type=code)
            log.warning("product_projection_commerce_failed product_id=%s job_id=%s error=%s",
                        product_id, job_id, code)
            return
        detail = None
        if isinstance(details, list):
            detail = next((item for item in details if isinstance(item, dict)
                           and str(item.get("productId")) == product_id), None)
        document = build_document(detail)
        if document is None:
            await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                    message="nothing_citable", error_type="nothing_citable")
            log.info("product_projection_skipped_empty product_id=%s job_id=%s", product_id, job_id)
            return
        doc_id = document["doc_id"]
        versions = await asyncio.to_thread(self.knowledge.latest_product_auto, actor, doc_id)
        published = next((row for row in versions if row.get("status") == "PUBLISHED"), None)
        if published and published.get("checksum") == document["checksum"]:
            await asyncio.to_thread(self.jobs.finish, job_id, "SKIPPED",
                                    checksum=document["checksum"], doc_id=doc_id,
                                    version=published.get("version"),
                                    message="checksum_unchanged")
            log.info("product_projection_unchanged product_id=%s checksum=%s", product_id, document["checksum"])
            return
        try:
            await asyncio.to_thread(self.knowledge.discard_auto_drafts, actor, [doc_id])
            payload = {key: value for key, value in document.items() if key != "checksum"}
            created = await asyncio.to_thread(self.knowledge.create_draft, actor, payload)
            version = created["version"]
            checksum = created["checksum"]
            index_job_id = None
            if self.indexing is not None and self.indexing.embedding_enabled():
                try:
                    index_job = await self.indexing.submit(actor, doc_id, version)
                    index_job_id = index_job.get("job_id")
                    await asyncio.to_thread(
                        self.jobs.finish, job_id, "DONE", checksum=checksum, doc_id=doc_id,
                        version=version, index_job_id=index_job_id,
                        message="submitted_index")
                    log.info("product_projection_indexed product_id=%s doc_id=%s version=%s index_job=%s checksum=%s",
                             product_id, doc_id, version, index_job_id, checksum)
                    return
                except Exception as error:
                    log.warning("product_projection_index_submit_failed product_id=%s error=%s",
                                product_id, type(error).__name__)
            published_row = await asyncio.to_thread(self.knowledge.publish, actor, doc_id, version)
            await asyncio.to_thread(
                self.jobs.finish, job_id, "DONE", checksum=checksum, doc_id=doc_id,
                version=published_row.get("version", version), index_job_id=index_job_id,
                message="published_bm25")
            log.info("product_projection_published product_id=%s doc_id=%s version=%s checksum=%s",
                     product_id, doc_id, version, checksum)
        except Exception as error:
            code = getattr(error, "code", None) or type(error).__name__
            await asyncio.to_thread(self.jobs.finish, job_id, "FAILED",
                                    message=f"project_failed: {code}", error_type=code)
            log.warning("product_projection_failed product_id=%s job_id=%s error=%s",
                        product_id, job_id, code)

    def status(self, actor, product_id):
        product_id = _text(product_id, "product_id", 64)
        job = self.jobs.latest(actor, product_id)
        doc_id = product_doc_id(product_id)
        versions = self.knowledge.latest_product_auto(actor, doc_id)
        published = next((row for row in versions if row.get("status") == "PUBLISHED"), None)
        draft = next((row for row in versions if row.get("status") == "DRAFT"), None)
        index_job = None
        if job and job.get("index_job_id") and self.indexing is not None:
            try:
                index_job = self.indexing.jobs.get_job(actor, job["index_job_id"])
            except StateError:
                index_job = None
        ai_status = _compose_ai_status(job, published, draft, index_job)
        return {"product_id": product_id, "doc_id": doc_id, "ai_status": ai_status,
                "job": job, "index_job": index_job, "published": published, "draft": draft}

    def retry(self, actor, product_id):
        return self.enqueue(actor, product_id)

    async def import_catalog(self, actor, product_ids=None):
        """Merchant bulk enqueue. Same auto-publish path as save-hook projection."""
        if product_ids is None:
            ids = await self.commerce.request("product", "/internal/product/listOnSaleProductIds", actor=actor)
            if not isinstance(ids, list):
                from smartlect.commerce import CommerceError
                raise CommerceError("commerce_outcome_unknown")
            product_ids = [str(item) for item in ids if item]
        product_ids = list(dict.fromkeys(str(item) for item in product_ids))[:200]
        imported, failed = [], []
        for product_id in product_ids:
            try:
                self.enqueue(actor, product_id)
                imported.append(product_id)
            except Exception as error:
                failed.append({"product_id": product_id,
                               "error": getattr(error, "code", None) or type(error).__name__})
        await self.drain()
        return {"imported": imported, "skipped": [], "failed": failed,
                "published_pending_review": [], "requested": len(product_ids),
                "truncated": len(product_ids) == 200,
                "note": "已入投影队并自动发布商品知识；店规仍需人工发布。"}

    async def resume_stale(self):
        self.bind_loop()
        for job in await asyncio.to_thread(self.jobs.stale_jobs):
            self._spawn(job["job_id"])
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_failed())

    async def _sweep_failed(self):
        """FAILED 自动重试：90 秒退避，attempt 上限内每分钟扫一批。"""
        while True:
            await asyncio.sleep(60)
            try:
                for job in await asyncio.to_thread(self.jobs.retryable_failed_jobs):
                    log.info("product_projection_retry_scheduled job_id=%s product_id=%s attempt=%s",
                             job["job_id"], job["product_id"], job.get("attempt"))
                    self._spawn(job["job_id"])
            except Exception:
                log.exception("product_projection_sweep_failed")

    async def drain(self):
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    def shutdown(self):
        if self._sweeper is not None:
            self._sweeper.cancel()
        for task in self._tasks.values():
            task.cancel()


def _compose_ai_status(job, published, draft, index_job):
    index_state = (index_job or {}).get("state")
    job_state = (job or {}).get("state")
    if published and index_state in {None, "DONE"} and job_state in {None, "DONE", "SKIPPED"}:
        return "visible"
    if index_state == "FAILED" and not published:
        return "failed"
    if job_state == "FAILED" and not published:
        return "failed"
    if job_state in {"PENDING", "RUNNING"} or index_state in {"PENDING", "RUNNING"}:
        return "indexing"
    if published:
        return "visible"
    if draft:
        return "indexing"
    if job_state == "FAILED":
        return "failed"
    return "idle"
