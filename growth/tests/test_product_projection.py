"""Projection idempotency: same checksum skips; MANUAL is never touched."""
import asyncio
import unittest
from unittest.mock import Mock

from smartlect.auth import ActorContext
from smartlect.knowledge_import import build_document
from smartlect.product_projection import ProductProjectionService, ProjectionJobStore

ACTOR = ActorContext(subject_type="merchant", actor_id="boss", session_id="s",
                     permissions=("admin:legacy", "shopping:read"), execution_scope_id="scope")


class MemoryProjectionJobs(ProjectionJobStore):
    def __init__(self):
        self.rows = {}

    def create(self, actor, product_id):
        job = {"job_id": "job-" + product_id, "execution_scope_id": actor.execution_scope_id,
               "actor_id": actor.actor_id, "product_id": product_id, "state": "PENDING",
               "attempt": 0, "checksum": None, "doc_id": None, "version": None,
               "index_job_id": None, "message": None, "error_type": None}
        self.rows[job["job_id"]] = job
        return dict(job)

    def active_job(self, actor, product_id):
        for job in self.rows.values():
            if job["product_id"] == product_id and job["state"] in {"PENDING", "RUNNING"}:
                return dict(job)
        return None

    def latest(self, actor, product_id):
        matches = [job for job in self.rows.values() if job["product_id"] == product_id]
        return dict(matches[-1]) if matches else None

    def claim(self, job_id):
        job = self.rows[job_id]
        job["state"] = "RUNNING"
        job["attempt"] += 1
        return dict(job)

    def finish(self, job_id, state, **fields):
        self.rows[job_id].update(fields, state=state)

    def stale_jobs(self):
        return [dict(job) for job in self.rows.values() if job["state"] in {"PENDING", "RUNNING"}]


class ProjectionIdempotencyTests(unittest.TestCase):
    def test_same_checksum_skips_and_does_not_touch_manual(self):
        detail = {"productId": "p1", "productName": "杯", "description": "不锈钢",
                  "propertyValues": [{"propertyName": "容量", "propertyValue": "500ml"}]}
        document = build_document(detail)
        knowledge = Mock()
        knowledge.latest_product_auto.return_value = [
            {"status": "PUBLISHED", "checksum": document["checksum"], "version": 2, "source_type": "PRODUCT_AUTO"}]
        knowledge.discard_auto_drafts = Mock()
        knowledge.create_draft = Mock()
        commerce = Mock()

        async def batch(*_args, **_kwargs):
            return [detail]

        commerce.request = batch
        service = ProductProjectionService(Mock(), knowledge, commerce)
        service.jobs = MemoryProjectionJobs()

        async def scenario():
            job = service.enqueue(ACTOR, "p1")
            await service.drain()
            return job

        asyncio.run(scenario())
        finished = service.jobs.rows["job-p1"]
        self.assertEqual(finished["state"], "SKIPPED")
        knowledge.create_draft.assert_not_called()
        knowledge.discard_auto_drafts.assert_not_called()

    def test_changed_checksum_creates_auto_draft_only(self):
        detail = {"productId": "p1", "productName": "杯", "description": "新描述"}
        knowledge = Mock()
        knowledge.latest_product_auto.return_value = [
            {"status": "PUBLISHED", "checksum": "old", "version": 1, "source_type": "PRODUCT_AUTO"}]
        knowledge.create_draft.return_value = {"version": 2, "checksum": "new"}
        knowledge.publish.return_value = {"version": 2}
        commerce = Mock()

        async def batch(*_args, **_kwargs):
            return [detail]

        commerce.request = batch
        service = ProductProjectionService(Mock(), knowledge, commerce)
        service.jobs = MemoryProjectionJobs()
        async def scenario():
            service.enqueue(ACTOR, "p1")
            await service.drain()

        asyncio.run(scenario())
        knowledge.discard_auto_drafts.assert_called_once()
        payload = knowledge.create_draft.call_args[0][1]
        self.assertEqual(payload["source_type"], "PRODUCT_AUTO")
        self.assertEqual(payload["product_ids"], ["p1"])
        self.assertNotIn("checksum", payload)
        knowledge.publish.assert_called_once()
        self.assertEqual(service.jobs.rows["job-p1"]["state"], "DONE")

    def test_enqueue_from_worker_thread_still_runs(self):
        detail = {"productId": "p1", "productName": "杯", "description": "不锈钢"}
        knowledge = Mock()
        knowledge.latest_product_auto.return_value = []
        knowledge.create_draft.return_value = {"version": 1, "checksum": "new"}
        knowledge.publish.return_value = {"version": 1}
        commerce = Mock()

        async def batch(*_args, **_kwargs):
            return [detail]

        commerce.request = batch
        service = ProductProjectionService(Mock(), knowledge, commerce)
        service.jobs = MemoryProjectionJobs()

        async def scenario():
            service.bind_loop()
            await asyncio.to_thread(service.enqueue, ACTOR, "p1")
            await asyncio.sleep(0)
            await service.drain()

        asyncio.run(scenario())
        self.assertEqual(service.jobs.rows["job-p1"]["state"], "DONE")
        knowledge.publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
