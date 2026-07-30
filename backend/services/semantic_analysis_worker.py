"""
Lightweight, persistent, MongoDB-backed background worker for semantic map
analysis (Section 10 of the spec).

Why a custom worker instead of Celery/Redis: QuickRoute does not already
use a task-queue system, and the spec explicitly says not to introduce
Redis/Celery unless the project already uses them — "keep it suitable for
a university-project deployment but persistent/auditable." The
`semantic_map_analyses` collection itself IS the queue: a job's `status`
field ("queued" -> "processing" -> "completed"/"failed"/...) is the whole
state machine, and every state transition happens through a single atomic
MongoDB findOneAndUpdate (see `_claim_next_job` below), so multiple worker
instances (e.g. multiple backend processes) can never both claim the same
job — no separate locking mechanism is needed.

This worker is deliberately NOT a bare, untracked `asyncio.create_task()`
fire-and-forget: the task object is kept on the worker instance so
`stop()` can cancel/await it cleanly during FastAPI shutdown (see
app.py's lifespan).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from beanie.odm.queries.update import UpdateResponse

from models.map_model import Map
from models.semantic_map_analysis_model import SemanticMapAnalysis
from services import semantic_analysis_service as svc

logger = logging.getLogger("semantic_analysis_worker")

DEFAULT_POLL_INTERVAL_SECONDS = 5


class SemanticAnalysisWorker:
    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self.poll_interval_seconds = poll_interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_loop(), name="semantic-analysis-worker"
        )
        logger.info(
            "Semantic analysis worker %s started (poll every %ss).",
            self.worker_id,
            self.poll_interval_seconds,
        )

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=15)
            except asyncio.TimeoutError:
                self._task.cancel()
            except Exception:  # noqa: BLE001
                logger.exception("Error while stopping semantic analysis worker.")
            self._task = None
        logger.info("Semantic analysis worker %s stopped.", self.worker_id)

    # -----------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            did_work = False
            try:
                await self._requeue_stale_jobs()
                claimed = await self._claim_next_job()
                if claimed is not None:
                    did_work = True
                    await self._process_job(claimed)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Semantic analysis worker loop error (continuing)."
                )

            if did_work:
                # Immediately look for more queued work instead of
                # sleeping a full interval between every single job.
                continue

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.poll_interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    # -----------------------------------------------------------------
    # Stale-job recovery (Section 10, rule 8-9)
    # -----------------------------------------------------------------

    async def _requeue_stale_jobs(self) -> None:
        processing_jobs = await SemanticMapAnalysis.find(
            {"status": "processing"}
        ).to_list()

        for job in processing_jobs:
            if svc.is_job_stale(job):
                logger.warning(
                    "Requeuing stale semantic analysis job %s (claimed by "
                    "%s, timed out).",
                    job.analysis_id,
                    job.worker_claim_id,
                )
                job.status = "queued"
                job.worker_claim_id = None
                job.processing_started_at = None
                job.updated_at = datetime.utcnow()
                await job.save()

    # -----------------------------------------------------------------
    # Atomic claim (Section 10, rule 3-4)
    # -----------------------------------------------------------------

    async def _claim_next_job(self) -> Optional[SemanticMapAnalysis]:
        # A single MongoDB findOneAndUpdate — atomic, so exactly one
        # worker process can ever claim a given "queued" document even
        # when several backend processes run this loop simultaneously.
        return await SemanticMapAnalysis.find_one({"status": "queued"}).update(
            {
                "$set": {
                    "status": "processing",
                    "worker_claim_id": self.worker_id,
                    "processing_started_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
            },
            response_type=UpdateResponse.NEW_DOCUMENT,
        )

    # -----------------------------------------------------------------
    # Job execution + retry policy (Section 10, rule 5-7)
    # -----------------------------------------------------------------

    async def _process_job(self, analysis: SemanticMapAnalysis) -> None:
        try:
            files = await svc.resolve_source_files_for_analysis(analysis)
        except Exception as error:  # noqa: BLE001
            await self._fail(analysis, "source_file_unavailable", str(error))
            return

        if not files:
            await self._fail(
                analysis,
                "source_file_unavailable",
                "No source file could be located on disk for this "
                "analysis (the Map's uploaded file may have been "
                "removed).",
            )
            return

        map_title = None
        if analysis.map_id:
            try:
                map_item = await Map.get(analysis.map_id)
                map_title = map_item.title if map_item else None
            except Exception:  # noqa: BLE001
                map_title = None

        await svc.run_queued_analysis(analysis, files=files, map_title=map_title)

        refreshed = await SemanticMapAnalysis.get(analysis.id)
        if refreshed is None:
            return

        if (
            refreshed.status == "failed"
            and svc.is_retryable_error(refreshed.error_code)
            and refreshed.attempt_count <= svc.get_max_retries()
        ):
            logger.info(
                "Retrying semantic analysis %s after transient error "
                "%s (attempt %s/%s).",
                refreshed.analysis_id,
                refreshed.error_code,
                refreshed.attempt_count,
                svc.get_max_retries(),
            )
            refreshed.status = "queued"
            refreshed.worker_claim_id = None
            refreshed.updated_at = datetime.utcnow()
            await refreshed.save()

    async def _fail(
        self, analysis: SemanticMapAnalysis, error_code: str, message: str
    ) -> None:
        analysis.status = "failed"
        analysis.error_code = error_code
        analysis.error_message = message
        analysis.updated_at = datetime.utcnow()
        await analysis.save()


# Single process-wide worker instance, started/stopped from app.py's
# lifespan. A second instance can be constructed directly in tests
# without touching this shared one.
worker = SemanticAnalysisWorker()
