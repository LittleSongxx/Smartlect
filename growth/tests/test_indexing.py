"""Async index pipeline contracts: audit-before-HTTP, retry, fatal abort, resume skip, batch windows."""
import asyncio
import unittest
import uuid
from unittest.mock import MagicMock, Mock

import httpx

from smartlect.auth import ActorContext
from smartlect.config import Settings
from smartlect.indexing import IndexingJobStore, IndexingService
from smartlect.provider import Provider
from test_provider import CONFIG

ACTOR = ActorContext(subject_type="merchant", actor_id="boss", session_id="s",
                     permissions=("admin:legacy",), execution_scope_id="scope")


class MemoryJobs(IndexingJobStore):
    """In-memory job rows; SQL-level behaviour is covered by the MySQL-gated contract."""

    def __init__(self, connect):
        super().__init__(connect)  # IndexModelAudit writes through this connect
        self.rows = {}

    def create(self, actor, doc_id, version, total_chunks):
        job = {"job_id": uuid.uuid4().hex, "execution_scope_id": actor.execution_scope_id, "actor_id": actor.actor_id,
               "doc_id": doc_id, "version": version, "state": "PENDING", "total_chunks": total_chunks,
               "processed_chunks": 0, "failed_chunks": 0, "embedding_model": None, "index_version": None,
               "message": None, "error_type": None}
        self.rows[job["job_id"]] = job
        return dict(job)

    def claim(self, job_id):
        job = self.rows[job_id]
        assert job["state"] in ("PENDING", "RUNNING")
        job["state"] = "RUNNING"
        return dict(job)

    def progress(self, job_id, *, processed, failed):
        self.rows[job_id]["processed_chunks"], self.rows[job_id]["failed_chunks"] = processed, failed

    def finish(self, job_id, state, **fields):
        assert self.rows[job_id]["state"] == "RUNNING"
        self.rows[job_id].update(fields, state=state)

    def stale_jobs(self):
        return [dict(job) for job in self.rows.values() if job["state"] in ("PENDING", "RUNNING")]


def mock_connect():
    connection, cursor = MagicMock(), MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.rowcount = 1
    return Mock(return_value=connection), cursor


def build_service(handler, chunks):
    connect, cursor = mock_connect()
    knowledge = Mock()
    knowledge.draft_chunks_with_status.return_value = chunks
    knowledge.embedding_counts.return_value = {"total": len(chunks), "embedded": len(chunks)}
    provider = Provider(CONFIG, transport=httpx.MockTransport(handler))
    service = IndexingService(connect, knowledge, provider, settings=Settings(model_mode="live"), config=CONFIG)
    service.jobs = MemoryJobs(connect)
    return service, knowledge, cursor


def embedding_response(count):
    return httpx.Response(200, json={"model": "text-embedding-v4",
                                     "data": [{"index": i, "embedding": [0.1] * 64} for i in range(count)],
                                     "usage": {"prompt_tokens": 1, "total_tokens": 1}})


def run_to_completion(service, doc_id, version):
    """submit + drain inside one event loop: the spawned task must not outlive its loop."""
    async def scenario():
        job = await service.submit(ACTOR, doc_id, version)
        await service.drain()
        return job
    return asyncio.run(scenario())

def chunks_of(count, embedded=False):
    return [{"chunk_id": f"c{i:02}", "heading": "h", "content": f"政策文本{i}", "embedded": embedded} for i in range(count)]


class IndexingServiceTests(unittest.TestCase):
    def test_success_publishes_after_batches_and_audit_row_precedes_http(self):
        checks = []

        def handler(request):
            inserts = [c for c in cursor.execute.call_args_list if "INSERT INTO knowledge_index_attempt" in c.args[0]]
            checks.append(len(inserts))
            return embedding_response(3)

        service, knowledge, cursor = build_service(handler, chunks_of(3))
        job = run_to_completion(service, "doc", 1)
        self.assertEqual(checks, [1])  # one audit row already inserted before the only HTTP call
        row = service.jobs.rows[job["job_id"]]
        self.assertEqual((row["state"], row["processed_chunks"]), ("DONE", 3))
        self.assertEqual(row["embedding_model"], "text-embedding-v4")
        knowledge.embed_batch.assert_called_once()
        knowledge.publish.assert_called_once()

    def test_transient_503_retries_then_fatal_401_aborts_without_publish(self):
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(503, text="transient")
            if len(calls) == 2:
                return embedding_response(1)
            return httpx.Response(401, text="invalid key")

        service, knowledge, _ = build_service(handler, chunks_of(1))
        job = run_to_completion(service, "doc", 1)
        self.assertEqual(service.jobs.rows[job["job_id"]]["state"], "DONE")
        knowledge.publish.assert_called_once()

        service2, knowledge2, _ = build_service(handler, chunks_of(1))
        job2 = run_to_completion(service2, "doc", 2)
        row2 = service2.jobs.rows[job2["job_id"]]
        self.assertEqual(row2["state"], "FAILED")
        self.assertIn("已成功 0/1", row2["message"])
        knowledge2.publish.assert_not_called()

    def test_resume_skips_embedded_chunks_without_http(self):
        def handler(request):
            raise AssertionError("all chunks already embedded; no HTTP expected")

        service, knowledge, _ = build_service(handler, chunks_of(2, embedded=True))
        job = run_to_completion(service, "doc", 1)
        self.assertEqual(service.jobs.rows[job["job_id"]]["state"], "DONE")
        knowledge.publish.assert_called_once()

    def test_more_than_four_batches_rotate_audit_publication_ids(self):
        def handler(request):
            import json as json_module
            count = len(json_module.loads(request.content)["input"])
            return embedding_response(count)

        service, _, cursor = build_service(handler, chunks_of(45))  # 5 batches: 10+10+10+10+5
        job = run_to_completion(service, "doc", 1)
        inserts = [c for c in cursor.execute.call_args_list if "INSERT INTO knowledge_index_attempt" in c.args[0]]
        self.assertEqual(len(inserts), 5)
        batch_indexes = [c.args[1][6] for c in inserts]
        self.assertEqual(batch_indexes, [0, 1, 2, 3, 0])  # window rotates, index stays within 0-3
        publications = {c.args[1][1] for c in inserts}
        self.assertEqual(len(publications), 2)
        self.assertEqual(service.jobs.rows[job["job_id"]]["state"], "DONE")


if __name__ == "__main__":
    unittest.main()
