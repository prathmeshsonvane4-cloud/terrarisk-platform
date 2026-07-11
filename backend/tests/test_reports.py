"""Integration tests for the report trigger/fetch endpoints, including one
genuine end-to-end test that drives the entire Service 1 workflow through
the real HTTP API: create farm -> trigger report -> poll job -> fetch
report JSON — the literal M1 Definition of Done.

The satellite provider is patched to FakeSatelliteDataProvider for the
background task (app.api.reports.GeeProvider is monkeypatched), so this
never depends on live Earth Engine credentials or quota — only
test_gee_provider.py's live tests do that.
"""

from __future__ import annotations

import asyncio
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
from app.models.admin import AdminBoundary
from app.models.enums import BoundaryLevel, JobStatus, JobType, RiskFactor, UserRole
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
    """Every test in this module runs the background report job against
    the deterministic fake, never real Earth Engine."""
    monkeypatch.setattr("app.api.reports.GeeProvider", FakeSatelliteDataProvider)


@pytest_asyncio.fixture
async def scenario():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    async with AsyncSessionLocal() as db:
        village = AdminBoundary(
            level=BoundaryLevel.VILLAGE,
            name=f"Test Village {uuid4().hex[:8]}",
            geometry=from_shape(
                Polygon([(76.0, 18.0), (76.5, 18.0), (76.5, 18.5), (76.0, 18.5), (76.0, 18.0)]), srid=4326
            ),
        )
        officer = AppUser(
            email=f"officer-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
        )
        outsider = AppUser(
            email=f"outsider-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Different Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
        )
        db.add_all([village, officer, outsider])
        await db.flush()

        config = ConfigWeight(
            weights={f.value: 0.25 for f in RiskFactor},
            floor_thresholds={"threshold": 80.0},
            effective_from=datetime.now(timezone.utc),
            created_by=officer.id,
        )
        db.add(config)
        await db.commit()
        await db.refresh(village)
        await db.refresh(officer)
        await db.refresh(outsider)
        await db.refresh(config)

    yield {"village": village, "officer": officer, "outsider": outsider, "config": config}

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
        # Matched by created_by, not entity_id: a completed job's entity_id
        # has already been overwritten to point at its resulting
        # risk_score (see app/api/reports.py), so it would no longer match
        # a farm_ids-based filter.
        await db.execute(delete(Job).where(Job.created_by.in_([officer.id, outsider.id])))
        await db.execute(delete(FarmPolygon).where(FarmPolygon.village_id == village.id))
        await db.execute(delete(ConfigWeight).where(ConfigWeight.id == config.id))
        await db.execute(delete(AppUser).where(AppUser.id.in_([officer.id, outsider.id])))
        await db.execute(delete(AdminBoundary).where(AdminBoundary.id == village.id))
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


@pytest.mark.asyncio
async def test_full_service_1_workflow_end_to_end(api_client, scenario):
    """The literal M1 Definition of Done: create farm -> trigger report ->
    poll job -> GET complete report JSON."""
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    trigger_response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    assert trigger_response.status_code == 202, trigger_response.text
    job_id = trigger_response.json()["job_id"]
    assert trigger_response.json()["status"] == "queued"

    job_response = await api_client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "done", (
        "background task did not complete synchronously within the ASGI test transport "
        f"(status was {job_response.json()['status']!r})"
    )
    risk_score_id = job_response.json()["entity_id"]

    report_response = await api_client.get(
        f"/api/v1/reports/{risk_score_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()
    assert report["farm_id"] == farm_id
    assert 0.0 <= report["overall_score"] <= 100.0
    assert report["overall_band"] in ("low", "moderate", "high", "very_high")
    assert {f["factor"] for f in report["factors"]} == {f.value for f in RiskFactor}


@pytest.mark.asyncio
async def test_trigger_report_rejects_unknown_farm(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    response = await api_client.post(
        f"/api/v1/farms/{uuid4()}/reports", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_trigger_report_rejects_duplicate_in_flight_request(api_client, scenario):
    """A second trigger while the first is still pending/running must be
    rejected as a conflict, not silently start a second job."""
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    async with AsyncSessionLocal() as db:
        stuck_job = Job(
            type=JobType.FARM_REPORT,
            status=JobStatus.RUNNING,
            entity_id=farm_id,
            created_by=scenario["officer"].id,
        )
        db.add(stuck_job)
        await db.commit()

    response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_trigger_report_concurrent_requests_do_not_race(api_client, scenario):
    """Two genuinely simultaneous triggers for the same farm (not one
    pre-seeded, sequential request like the test above) must still result
    in exactly one accepted job — proves the pg_advisory_xact_lock in
    trigger_report actually closes the TOCTOU race between the
    check-for-in-flight-job query and the job insert, found during the
    Staff Engineer review. Without the lock, both requests can pass the
    check before either commits."""
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    responses = await asyncio.gather(
        api_client.post(f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={}),
        api_client.post(f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={}),
    )
    status_codes = sorted(r.status_code for r in responses)
    assert status_codes == [202, 409], f"expected exactly one accepted and one rejected, got {status_codes}"


@pytest.mark.asyncio
async def test_trigger_report_rejects_invalid_lookback_years(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports",
        headers={"Authorization": f"Bearer {token}"},
        json={"lookback_years": 0},
    )
    assert response.status_code == 422

    response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports",
        headers={"Authorization": f"Bearer {token}"},
        json={"lookback_years": 999},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_report_returns_404_for_unknown_id(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    response = await api_client.get(f"/api/v1/reports/{uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_report_rejects_user_outside_owner_or_branch(api_client, scenario):
    officer_token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, officer_token, scenario["village"].id)

    trigger_response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {officer_token}"}, json={}
    )
    job_id = trigger_response.json()["job_id"]
    job_response = await api_client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {officer_token}"})
    risk_score_id = job_response.json()["entity_id"]

    outsider_token = await _login(api_client, scenario["outsider"].email)
    response = await api_client.get(
        f"/api/v1/reports/{risk_score_id}", headers={"Authorization": f"Bearer {outsider_token}"}
    )
    assert response.status_code == 404
