"""Structured, truthful per-stage progress for report generation jobs
(M2B P8 — Product Design v2 §7.3 "Assessment Run", backend addition B2).

Every stage defined here corresponds to exactly one real, awaited
operation inside `report_generator.py`'s pipeline — nothing here is
decorative, and nothing here computes a percentage or an ETA, because
neither exists anywhere in this system. The frontend renders this JSONB
blob directly as a vertical timeline.

Deliberately more granular than the founder's illustrative 12-stage
example: NDVI, MNDWI, and NDMI are three independently cached-or-fetched
Earth Engine calls with potentially different cache outcomes each, so
they are three separate stages here rather than one merged "vegetation
indicators" step — collapsing them would hide honest information (see
DECISIONS.md for the full mapping and reasoning). Conversely, "calculating
factor scores" and "running the risk engine" collapse into the single
`scoring` stage here, because in the real code they are the identical
synchronous call (`RiskEngine.compute()`) — inventing two stages around
one call would be exactly the "fake stage" this phase forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job

StageStatus = Literal["pending", "running", "done", "failed"]


@dataclass(frozen=True)
class StageDefinition:
    id: str
    title: str


# Canonical, ordered stage list — one entry per real checkpoint in
# _run_pipeline. Order here is the order the pipeline actually executes
# in; the frontend trusts this order and never reorders stages itself.
STAGE_DEFINITIONS: list[StageDefinition] = [
    StageDefinition("preparing", "Preparing assessment"),
    StageDefinition("loading_geometry", "Loading farm geometry"),
    StageDefinition("vegetation_observations", "Retrieving vegetation observations (Sentinel-2 NDVI)"),
    StageDefinition("surface_water_observations", "Retrieving surface-water observations (Sentinel-2 MNDWI)"),
    StageDefinition("crop_moisture_observations", "Retrieving crop-moisture observations (Sentinel-2 NDMI)"),
    StageDefinition("rainfall_observations", "Retrieving rainfall observations (CHIRPS)"),
    StageDefinition("rainfall_climatology", "Retrieving 30-year rainfall normal"),
    StageDefinition("water_history", "Retrieving surface-water history (JRC)"),
    StageDefinition("scoring", "Calculating climate risk factors and composite score"),
    StageDefinition("saving", "Saving report"),
    StageDefinition("completed", "Completed"),
]

STAGE_IDS: list[str] = [stage.id for stage in STAGE_DEFINITIONS]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def initial_progress() -> dict:
    """The shape written the instant a job starts running: every stage
    present up front, all pending. The frontend renders the entire
    timeline from stage one, never only what has happened so far — a
    reconstruction-from-refresh requirement (Product Design v2 §7.3)
    that falls out naturally from always shipping the full stage list."""
    return {
        "stages": [
            {
                "id": stage.id,
                "title": stage.title,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "metadata": None,
            }
            for stage in STAGE_DEFINITIONS
        ]
    }


class ProgressTracker:
    """Bound to one job's `progress` column for the lifetime of a pipeline
    run. Mirrors the existing `_set_job_status` pattern in
    report_generator.py exactly (fetch via `db.get`, mutate a fresh dict,
    reassign, commit) — a nested dict mutated in place would NOT be
    detected as a change by SQLAlchemy's JSONB column tracking, so every
    write here reassigns `job.progress` to a brand new dict object.

    Each call is a small, targeted commit — cheap at pilot volume, and
    immediately visible to any other session polling `GET /jobs/{id}`
    (Postgres READ COMMITTED): an officer watching the Run page sees each
    stage transition as it actually happens, not buffered until the job
    ends.
    """

    def __init__(self, db: AsyncSession, job_id: UUID) -> None:
        self._db = db
        self._job_id = job_id

    async def initialize(self) -> None:
        job = await self._db.get(Job, self._job_id)
        if job is None:
            return
        job.progress = initial_progress()
        await self._db.commit()

    async def start(self, stage_id: str) -> None:
        await self._update_stage(stage_id, status="running", started_at=_now_iso())

    async def complete(self, stage_id: str, *, metadata: dict | None = None) -> None:
        await self._update_stage(stage_id, status="done", completed_at=_now_iso(), metadata=metadata)

    async def fail_current(self) -> None:
        """Marks whichever stage was in flight when the pipeline raised as
        failed. Every earlier stage's `done` status — and its timestamps
        and cache metadata — is left exactly as it was: completed work
        must never appear to regress just because a later stage failed
        (Product Design v2 Journey C)."""
        job = await self._db.get(Job, self._job_id)
        if job is None or job.progress is None:
            return
        stages = [dict(stage) for stage in job.progress["stages"]]
        for stage in stages:
            if stage["status"] == "running":
                stage["status"] = "failed"
                stage["completed_at"] = _now_iso()
        job.progress = {"stages": stages}
        await self._db.commit()

    async def _update_stage(
        self,
        stage_id: str,
        *,
        status: StageStatus,
        started_at: str | None = None,
        completed_at: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        job = await self._db.get(Job, self._job_id)
        if job is None:
            return
        progress = job.progress if job.progress is not None else initial_progress()
        stages = [dict(stage) for stage in progress["stages"]]
        for stage in stages:
            if stage["id"] == stage_id:
                stage["status"] = status
                if started_at is not None:
                    stage["started_at"] = started_at
                if completed_at is not None:
                    stage["completed_at"] = completed_at
                if metadata is not None:
                    stage["metadata"] = metadata
        job.progress = {"stages": stages}
        await self._db.commit()
