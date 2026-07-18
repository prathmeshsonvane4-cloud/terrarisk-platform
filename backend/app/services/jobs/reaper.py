"""Recovers jobs orphaned by a server crash/restart or a hung in-process
call (RC2 reliability audit — see docs/DECISIONS.md).

generate_farm_report()'s own try/except (report_generator.py) only
guarantees a terminal status for exceptions raised *within that process*.
It cannot catch the process being killed mid-job (a routine `docker compose
up -d --build` redeploy landing while a report is generating), which left
a job stuck in PENDING/RUNNING forever — with no reaper, `trigger_report`'s
own in-flight-job check (reports.py) then permanently refuses any future
report for that farm, with no operator unstick path short of a manual
database UPDATE.

Two sweeps, not one, because they catch different failure shapes:

- sweep_orphaned_on_startup(): runs once, before the app accepts traffic.
  Any job still PENDING/RUNNING when a new process starts was mid-flight
  when the *previous* process stopped — this process's startup can't be
  continuing it, so these fail immediately, unconditionally.
- periodic_stuck_job_sweep(): runs for the process's lifetime. Catches a
  job whose background task is still alive but hung (e.g. a network call
  that never times out) — the process never restarted, so the startup
  sweep never runs again to catch it. Anything RUNNING (or PENDING) longer
  than _MAX_JOB_AGE since its last observed write is failed. `Job.updated_at`
  is bumped by every ProgressTracker stage transition (progress.py), not
  just job creation, so this measures "time since last sign of life," not
  "time since the job started" — a legitimately long-but-still-progressing
  run is not killed just because its total runtime crosses the threshold.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database.base import AsyncSessionLocal
from app.models.enums import JobStatus
from app.models.job import Job

logger = logging.getLogger(__name__)

_ORPHANED_ON_STARTUP_MESSAGE = "Job was interrupted by a server restart. Please retry."
_STUCK_JOB_MESSAGE = "Job did not complete in the expected time and was marked failed. Please retry."

# Report generation typically takes 2-4 minutes (the assessment-run UI's own
# documented expectation, per frontend/src/features/report/use-job-status.ts's
# polling design) — 20 minutes is generous headroom over that, not a tuned
# real-world maximum.
_MAX_JOB_AGE = timedelta(minutes=20)
_SWEEP_INTERVAL_SECONDS = 5 * 60


async def _fail_stale_jobs(*, statuses: list[JobStatus], max_age: timedelta | None, message: str) -> int:
    async with AsyncSessionLocal() as db:
        jobs = (await db.execute(select(Job).where(Job.status.in_(statuses)))).scalars().all()
        cutoff = datetime.now(timezone.utc) - max_age if max_age is not None else None
        failed = 0
        for job in jobs:
            if cutoff is not None and job.updated_at is not None and job.updated_at > cutoff:
                continue  # within its normal running window — leave it alone
            job.status = JobStatus.FAILED
            job.error_message = message
            failed += 1
        if failed:
            await db.commit()
        return failed


async def sweep_orphaned_on_startup() -> None:
    try:
        failed = await _fail_stale_jobs(
            statuses=[JobStatus.PENDING, JobStatus.RUNNING], max_age=None, message=_ORPHANED_ON_STARTUP_MESSAGE
        )
        if failed:
            logger.warning("startup_job_sweep_failed_orphaned_jobs", extra={"count": failed})
    except Exception:
        # A DB hiccup at the exact moment this process starts (the same
        # class of race the M3 migration-retry entrypoint fix addresses)
        # must not prevent the API from starting and serving /health —
        # this sweep is a best-effort recovery, not a startup dependency.
        logger.exception("startup_job_sweep_failed")


async def periodic_stuck_job_sweep() -> None:
    """Runs until cancelled (app shutdown) — intended to be started once as
    a background asyncio task from main.py's lifespan."""
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
            failed = await _fail_stale_jobs(
                statuses=[JobStatus.PENDING, JobStatus.RUNNING], max_age=_MAX_JOB_AGE, message=_STUCK_JOB_MESSAGE
            )
            if failed:
                logger.warning("periodic_job_sweep_failed_stuck_jobs", extra={"count": failed})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic_job_sweep_error")
