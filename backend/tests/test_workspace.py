"""Integration tests for the M2B P7 workspace list endpoints (Product
Design v2 §7): GET /farms, GET /farms/{id}/assessments, GET /jobs
(assessments index), GET /reports, and the 409-carries-job_id addition to
trigger_report.

Real HTTP through the ASGI transport, real PostGIS, real branch-scoping —
same conventions as test_reports.py. The satellite provider is patched to
the deterministic fake; only test_gee_provider.py's tests touch live Earth
Engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import Polygon
from sqlalchemy import delete, select, text

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.main import app
from app.models.admin import AdminBoundary, Branch
from app.models.enums import BoundaryLevel, JobStatus, JobType, RiskBand, RiskFactor, UserRole
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.risk import ConfigWeight, RiskFactorScore, RiskScore
from app.models.satellite import SatelliteObservation
from app.models.user import AppUser
from tests.fakes.fake_satellite_provider import FakeSatelliteDataProvider

_VALID_SQUARE = [[76.0, 18.0], [76.01, 18.0], [76.01, 18.01], [76.0, 18.01], [76.0, 18.0]]


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


@pytest_asyncio.fixture(autouse=True)
def patch_gee_provider(monkeypatch):
    monkeypatch.setattr("app.api.reports.GeeProvider", FakeSatelliteDataProvider)


@pytest_asyncio.fixture
async def scenario():
    """Two officers sharing a branch (colleague must see each other's
    work — branch-scoped visibility, Product Design v2 §5) plus one
    branchless outsider (must see neither)."""
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    async with AsyncSessionLocal() as db:
        district = AdminBoundary(
            level=BoundaryLevel.DISTRICT,
            name=f"Test District {uuid4().hex[:8]}",
            geometry=from_shape(
                Polygon([(75.5, 17.5), (77.0, 17.5), (77.0, 19.0), (75.5, 19.0), (75.5, 17.5)]), srid=4326
            ),
        )
        db.add(district)
        await db.flush()
        taluka = AdminBoundary(
            level=BoundaryLevel.TALUKA,
            name=f"Test Taluka {uuid4().hex[:8]}",
            parent_id=district.id,
            geometry=from_shape(
                Polygon([(75.8, 17.8), (76.8, 17.8), (76.8, 18.8), (75.8, 18.8), (75.8, 17.8)]), srid=4326
            ),
        )
        db.add(taluka)
        await db.flush()
        village = AdminBoundary(
            level=BoundaryLevel.VILLAGE,
            name=f"Test Village {uuid4().hex[:8]}",
            parent_id=taluka.id,
            geometry=from_shape(
                Polygon([(76.0, 18.0), (76.5, 18.0), (76.5, 18.5), (76.0, 18.5), (76.0, 18.0)]), srid=4326
            ),
        )
        branch = Branch(name=f"Test Branch {uuid4().hex[:8]}")
        db.add_all([village, branch])
        await db.flush()

        officer = AppUser(
            email=f"officer-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
            branch_id=branch.id,
        )
        colleague = AppUser(
            email=f"colleague-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Branch Colleague",
            role=UserRole.BRANCH_MANAGER,
            is_active=True,
            branch_id=branch.id,
        )
        outsider = AppUser(
            email=f"outsider-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Different Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
            branch_id=None,
        )
        db.add_all([officer, colleague, outsider])
        await db.flush()

        config = ConfigWeight(
            weights={f.value: 0.25 for f in RiskFactor},
            floor_thresholds={"threshold": 80.0},
            effective_from=datetime.now(timezone.utc),
            created_by=officer.id,
        )
        db.add(config)
        await db.commit()
        for obj in (village, taluka, district, branch, officer, colleague, outsider, config):
            await db.refresh(obj)

    yield {
        "village": village,
        "taluka": taluka,
        "district": district,
        "branch": branch,
        "officer": officer,
        "colleague": colleague,
        "outsider": outsider,
        "config": config,
    }

    async with AsyncSessionLocal() as db:
        farm_ids = (
            await db.execute(select(FarmPolygon.id).where(FarmPolygon.village_id == village.id))
        ).scalars().all()
        if farm_ids:
            await db.execute(
                delete(RiskFactorScore).where(
                    RiskFactorScore.risk_score_id.in_(select(RiskScore.id).where(RiskScore.entity_id.in_(farm_ids)))
                )
            )
            await db.execute(delete(RiskScore).where(RiskScore.entity_id.in_(farm_ids)))
            await db.execute(delete(SatelliteObservation).where(SatelliteObservation.entity_id.in_(farm_ids)))
        await db.execute(
            delete(Job).where(Job.created_by.in_([officer.id, colleague.id, outsider.id]))
        )
        await db.execute(delete(FarmPolygon).where(FarmPolygon.village_id == village.id))
        await db.execute(delete(ConfigWeight).where(ConfigWeight.id == config.id))
        await db.execute(delete(AppUser).where(AppUser.id.in_([officer.id, colleague.id, outsider.id])))
        await db.execute(delete(AdminBoundary).where(AdminBoundary.id.in_([village.id, taluka.id, district.id])))
        await db.execute(delete(Branch).where(Branch.id == branch.id))
        await db.commit()


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "correct-password"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _create_farm(client: AsyncClient, token: str, village_id) -> str:
    response = await client.post(
        "/api/v1/farms",
        headers={"Authorization": f"Bearer {token}"},
        json={"village_id": str(village_id), "geometry": {"type": "Polygon", "coordinates": [_VALID_SQUARE]}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_and_complete_report(client: AsyncClient, token: str, village_id) -> tuple[str, str]:
    """Full trigger flow; returns (farm_id, risk_score_id)."""
    farm_id = await _create_farm(client, token, village_id)
    trigger = await client.post(
        f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    assert trigger.status_code == 202, trigger.text
    job_id = trigger.json()["job_id"]
    job = await client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert job.json()["status"] == "done", job.text
    return farm_id, job.json()["entity_id"]


# ---------------------------------------------------------------------------
# GET /farms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_farms_shows_own_farm_with_no_assessment_yet(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    response = await api_client.get("/api/v1/farms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert any(item["id"] == farm_id for item in items)
    row = next(item for item in items if item["id"] == farm_id)
    assert row["village_name"] == scenario["village"].name
    assert row["taluka_name"] == scenario["taluka"].name
    assert row["district_name"] == scenario["district"].name
    assert row["officer_name"] == "Test Officer"
    assert row["latest_assessment"] is None
    assert row["active_job"] is None


@pytest.mark.asyncio
async def test_list_farms_includes_the_latest_completed_assessment(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id, risk_score_id = await _create_and_complete_report(api_client, token, scenario["village"].id)

    response = await api_client.get("/api/v1/farms", headers={"Authorization": f"Bearer {token}"})
    row = next(item for item in response.json()["items"] if item["id"] == farm_id)
    assert row["latest_assessment"]["risk_score_id"] == risk_score_id
    assert 0.0 <= row["latest_assessment"]["overall_score"] <= 100.0
    assert row["active_job"] is None


@pytest.mark.asyncio
async def test_list_farms_shows_an_in_flight_job(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    async with AsyncSessionLocal() as db:
        stuck_job = Job(
            type=JobType.FARM_REPORT, status=JobStatus.RUNNING, entity_id=farm_id, created_by=scenario["officer"].id
        )
        db.add(stuck_job)
        await db.commit()
        await db.refresh(stuck_job)

    response = await api_client.get("/api/v1/farms", headers={"Authorization": f"Bearer {token}"})
    row = next(item for item in response.json()["items"] if item["id"] == farm_id)
    assert row["active_job"]["job_id"] == str(stuck_job.id)
    assert row["active_job"]["status"] == "running"


@pytest.mark.asyncio
async def test_list_farms_is_branch_scoped(api_client, scenario):
    officer_token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, officer_token, scenario["village"].id)

    colleague_token = await _login(api_client, scenario["colleague"].email)
    colleague_response = await api_client.get(
        "/api/v1/farms", headers={"Authorization": f"Bearer {colleague_token}"}
    )
    assert any(item["id"] == farm_id for item in colleague_response.json()["items"]), (
        "same-branch colleague must see the officer's farm"
    )

    outsider_token = await _login(api_client, scenario["outsider"].email)
    outsider_response = await api_client.get(
        "/api/v1/farms", headers={"Authorization": f"Bearer {outsider_token}"}
    )
    assert not any(item["id"] == farm_id for item in outsider_response.json()["items"]), (
        "branchless outsider must not see the officer's farm"
    )


# ---------------------------------------------------------------------------
# GET /farms/{id}/assessments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_farm_assessment_history_orders_newest_first_and_shows_active_job(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id, first_score_id = await _create_and_complete_report(api_client, token, scenario["village"].id)

    # Simulate a re-assessment: a second, later RiskScore for the same farm.
    async with AsyncSessionLocal() as db:
        second_score = RiskScore(
            entity_type=(await db.get(RiskScore, first_score_id)).entity_type,
            entity_id=farm_id,
            overall_score=55.0,
            overall_band=RiskBand.HIGH,
            confidence=90.0,
            model_version="rule-engine-v1",
            weights_version_id=scenario["config"].id,
            computed_at=datetime.now(timezone.utc),
        )
        db.add(second_score)
        stuck_job = Job(
            type=JobType.FARM_REPORT, status=JobStatus.PENDING, entity_id=farm_id, created_by=scenario["officer"].id
        )
        db.add(stuck_job)
        await db.commit()
        await db.refresh(second_score)
        await db.refresh(stuck_job)

    response = await api_client.get(
        f"/api/v1/farms/{farm_id}/assessments", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["risk_score_id"] for item in body["items"]] == [str(second_score.id), first_score_id]
    assert body["active_job"]["job_id"] == str(stuck_job.id)


@pytest.mark.asyncio
async def test_farm_assessment_history_rejects_outsider(api_client, scenario):
    officer_token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, officer_token, scenario["village"].id)

    outsider_token = await _login(api_client, scenario["outsider"].email)
    response = await api_client.get(
        f"/api/v1/farms/{farm_id}/assessments", headers={"Authorization": f"Bearer {outsider_token}"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /jobs (assessments index)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_assessments_resolves_farm_context_for_a_completed_run(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id, risk_score_id = await _create_and_complete_report(api_client, token, scenario["village"].id)

    response = await api_client.get("/api/v1/jobs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["items"] if item["risk_score_id"] == risk_score_id)
    assert row["status"] == "done"
    assert row["farm_id"] == farm_id
    assert row["village_name"] == scenario["village"].name
    assert row["officer_name"] == "Test Officer"
    assert row["overall_band"] in ("low", "moderate", "high", "very_high")


@pytest.mark.asyncio
async def test_list_assessments_shows_pending_and_failed_runs_with_farm_context(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    async with AsyncSessionLocal() as db:
        pending_job = Job(
            type=JobType.FARM_REPORT, status=JobStatus.PENDING, entity_id=farm_id, created_by=scenario["officer"].id
        )
        failed_job = Job(
            type=JobType.FARM_REPORT,
            status=JobStatus.FAILED,
            entity_id=farm_id,
            created_by=scenario["officer"].id,
            error_message="Report generation failed. Please retry; contact support if this persists.",
        )
        db.add_all([pending_job, failed_job])
        await db.commit()
        await db.refresh(pending_job)
        await db.refresh(failed_job)

    response = await api_client.get("/api/v1/jobs", headers={"Authorization": f"Bearer {token}"})
    items_by_id = {item["job_id"]: item for item in response.json()["items"]}

    pending_row = items_by_id[str(pending_job.id)]
    assert pending_row["status"] == "pending"
    assert pending_row["farm_id"] == farm_id
    assert pending_row["village_name"] == scenario["village"].name
    assert pending_row["risk_score_id"] is None

    failed_row = items_by_id[str(failed_job.id)]
    assert failed_row["status"] == "failed"
    assert failed_row["error_message"] == failed_job.error_message


@pytest.mark.asyncio
async def test_list_assessments_is_branch_scoped(api_client, scenario):
    officer_token = await _login(api_client, scenario["officer"].email)
    farm_id, risk_score_id = await _create_and_complete_report(api_client, officer_token, scenario["village"].id)

    colleague_token = await _login(api_client, scenario["colleague"].email)
    colleague_items = (
        await api_client.get("/api/v1/jobs", headers={"Authorization": f"Bearer {colleague_token}"})
    ).json()["items"]
    assert any(item["risk_score_id"] == risk_score_id for item in colleague_items)

    outsider_token = await _login(api_client, scenario["outsider"].email)
    outsider_items = (
        await api_client.get("/api/v1/jobs", headers={"Authorization": f"Bearer {outsider_token}"})
    ).json()["items"]
    assert not any(item["risk_score_id"] == risk_score_id for item in outsider_items)


# ---------------------------------------------------------------------------
# GET /reports (issued-artifact index)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_reports_includes_the_issued_report(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id, risk_score_id = await _create_and_complete_report(api_client, token, scenario["village"].id)

    response = await api_client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["items"] if item["risk_score_id"] == risk_score_id)
    assert row["farm_id"] == farm_id
    assert row["village_name"] == scenario["village"].name
    assert row["taluka_name"] == scenario["taluka"].name
    assert row["district_name"] == scenario["district"].name
    assert row["officer_name"] == "Test Officer"


@pytest.mark.asyncio
async def test_list_reports_is_branch_scoped(api_client, scenario):
    officer_token = await _login(api_client, scenario["officer"].email)
    farm_id, risk_score_id = await _create_and_complete_report(api_client, officer_token, scenario["village"].id)

    colleague_token = await _login(api_client, scenario["colleague"].email)
    colleague_items = (
        await api_client.get("/api/v1/reports", headers={"Authorization": f"Bearer {colleague_token}"})
    ).json()["items"]
    assert any(item["risk_score_id"] == risk_score_id for item in colleague_items)

    outsider_token = await _login(api_client, scenario["outsider"].email)
    outsider_items = (
        await api_client.get("/api/v1/reports", headers={"Authorization": f"Bearer {outsider_token}"})
    ).json()["items"]
    assert not any(item["risk_score_id"] == risk_score_id for item in outsider_items)


# ---------------------------------------------------------------------------
# B5 — 409 on trigger_report carries the existing job_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_report_conflict_carries_the_in_flight_job_id(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    async with AsyncSessionLocal() as db:
        stuck_job = Job(
            type=JobType.FARM_REPORT, status=JobStatus.RUNNING, entity_id=farm_id, created_by=scenario["officer"].id
        )
        db.add(stuck_job)
        await db.commit()
        await db.refresh(stuck_job)

    response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["job_id"] == str(stuck_job.id)
    assert "already being generated" in body["error"]["message"]
