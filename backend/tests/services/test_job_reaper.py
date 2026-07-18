"""RC2 reliability fix — app/services/jobs/reaper.py recovers jobs orphaned
by a process kill/restart or a hung in-process call. Real Postgres, same
skip-if-unreachable convention as test_jobs.py/test_workspace.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, text, update

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.models.enums import JobStatus, JobType, UserRole
from app.models.job import Job
from app.models.user import AppUser
from app.services.jobs.reaper import _fail_stale_jobs, sweep_orphaned_on_startup


async def _database_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def job_owner():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    async with AsyncSessionLocal() as db:
        owner = AppUser(
            email=f"reaper-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Reaper Test Owner",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
            branch_id=None,
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        yield owner
        # Delete this owner's jobs first — job.created_by is a NOT NULL FK
        # to app_user, same cleanup-ordering convention as test_jobs.py.
        await db.execute(delete(Job).where(Job.created_by == owner.id))
        await db.execute(delete(AppUser).where(AppUser.id == owner.id))
        await db.commit()


async def _make_job(owner_id, status: JobStatus) -> Job:
    async with AsyncSessionLocal() as db:
        job = Job(type=JobType.FARM_REPORT, status=status, entity_id=uuid4(), created_by=owner_id)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def _reload(job_id) -> Job:
    async with AsyncSessionLocal() as db:
        return await db.get(Job, job_id)


@pytest.mark.asyncio
async def test_startup_sweep_fails_pending_and_running_jobs(job_owner):
    pending = await _make_job(job_owner.id, JobStatus.PENDING)
    running = await _make_job(job_owner.id, JobStatus.RUNNING)

    await sweep_orphaned_on_startup()

    reloaded_pending = await _reload(pending.id)
    reloaded_running = await _reload(running.id)
    assert reloaded_pending.status == JobStatus.FAILED
    assert reloaded_running.status == JobStatus.FAILED
    assert "restart" in reloaded_pending.error_message.lower()
    assert "restart" in reloaded_running.error_message.lower()


@pytest.mark.asyncio
async def test_startup_sweep_leaves_terminal_jobs_alone(job_owner):
    done = await _make_job(job_owner.id, JobStatus.DONE)
    failed = await _make_job(job_owner.id, JobStatus.FAILED)

    await sweep_orphaned_on_startup()

    reloaded_done = await _reload(done.id)
    reloaded_failed = await _reload(failed.id)
    assert reloaded_done.status == JobStatus.DONE
    assert reloaded_failed.status == JobStatus.FAILED
    assert reloaded_failed.error_message is None  # untouched, not overwritten


@pytest.mark.asyncio
async def test_periodic_style_sweep_leaves_recently_updated_running_jobs_alone(job_owner):
    """A job actively progressing (updated_at bumped moments ago) must
    never be killed just because a periodic sweep happens to run — this is
    the exact case the age check protects against."""
    running = await _make_job(job_owner.id, JobStatus.RUNNING)

    failed_count = await _fail_stale_jobs(
        statuses=[JobStatus.RUNNING], max_age=timedelta(minutes=20), message="should not apply"
    )

    reloaded = await _reload(running.id)
    assert reloaded.status == JobStatus.RUNNING
    assert failed_count == 0


@pytest.mark.asyncio
async def test_periodic_style_sweep_fails_genuinely_stuck_running_jobs(job_owner):
    """A job with no sign of life in over _MAX_JOB_AGE — the hung-process
    case a restart-only sweep can never catch — is failed."""
    stuck = await _make_job(job_owner.id, JobStatus.RUNNING)
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    async with AsyncSessionLocal() as db:
        await db.execute(update(Job).where(Job.id == stuck.id).values(updated_at=stale_time))
        await db.commit()

    failed_count = await _fail_stale_jobs(
        statuses=[JobStatus.RUNNING], max_age=timedelta(minutes=20), message="stuck job message"
    )

    reloaded = await _reload(stuck.id)
    assert reloaded.status == JobStatus.FAILED
    assert reloaded.error_message == "stuck job message"
    assert failed_count == 1
