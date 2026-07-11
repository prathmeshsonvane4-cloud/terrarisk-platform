"""Integration tests for the job polling endpoint — authorization scoping
(owner / same-branch) and the not-found-vs-forbidden information-leakage
guard are the parts worth real coverage; state-transition correctness
itself is covered by test_report_generator.py."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.main import app
from app.models.enums import JobStatus, JobType, UserRole
from app.models.job import Job
from app.models.user import AppUser


async def _database_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def api_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def job_scenario():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    async with AsyncSessionLocal() as db:
        branch_a_owner = AppUser(
            email=f"owner-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Job Owner",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
            branch_id=None,
        )
        same_branch_colleague = AppUser(
            email=f"colleague-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Same Branch Colleague",
            role=UserRole.BRANCH_MANAGER,
            is_active=True,
            branch_id=None,
        )
        stranger = AppUser(
            email=f"stranger-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Unrelated User",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
            branch_id=None,
        )
        db.add_all([branch_a_owner, same_branch_colleague, stranger])
        await db.flush()

        # Give owner and colleague the same real branch_id so the
        # same-branch authorization path is genuinely exercised.
        from app.models.admin import Branch

        branch = Branch(name=f"Test Branch {uuid4().hex[:8]}")
        db.add(branch)
        await db.flush()
        branch_a_owner.branch_id = branch.id
        same_branch_colleague.branch_id = branch.id

        job = Job(type=JobType.FARM_REPORT, status=JobStatus.PENDING, created_by=branch_a_owner.id)
        db.add(job)
        await db.commit()
        await db.refresh(branch_a_owner)
        await db.refresh(same_branch_colleague)
        await db.refresh(stranger)
        await db.refresh(job)

    yield {"owner": branch_a_owner, "colleague": same_branch_colleague, "stranger": stranger, "job": job}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Job).where(Job.id == job.id))
        await db.execute(delete(AppUser).where(AppUser.id.in_([branch_a_owner.id, same_branch_colleague.id, stranger.id])))
        await db.execute(delete(Branch).where(Branch.id == branch.id))
        await db.commit()


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "correct-password"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_owner_can_view_their_own_job(api_client, job_scenario):
    token = await _login(api_client, job_scenario["owner"].email)
    response = await api_client.get(f"/api/v1/jobs/{job_scenario['job'].id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_same_branch_colleague_can_view_the_job(api_client, job_scenario):
    token = await _login(api_client, job_scenario["colleague"].email)
    response = await api_client.get(f"/api/v1/jobs/{job_scenario['job'].id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unrelated_user_gets_404_not_403(api_client, job_scenario):
    """Authorization failure must look identical to the job not existing
    at all — never confirm to an unauthorized caller that a given job id
    is valid."""
    token = await _login(api_client, job_scenario["stranger"].email)
    response = await api_client.get(f"/api/v1/jobs/{job_scenario['job'].id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(api_client, job_scenario):
    response = await api_client.get(f"/api/v1/jobs/{job_scenario['job'].id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_truly_nonexistent_job_returns_404(api_client, job_scenario):
    token = await _login(api_client, job_scenario["owner"].email)
    response = await api_client.get(f"/api/v1/jobs/{uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_malformed_job_id_rejected_with_422(api_client, job_scenario):
    token = await _login(api_client, job_scenario["owner"].email)
    response = await api_client.get("/api/v1/jobs/not-a-uuid", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 422
