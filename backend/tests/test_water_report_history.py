"""Integration tests for GET /catchments/{id}/water-reports/history, against
real PostGIS and real JWT auth end to end — same fixture/fake-provider
pattern as test_water_report_detail.py.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import Polygon
from sqlalchemy import delete, text

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.main import app
from app.models.catchment import Catchment
from app.models.enums import DelineationMethod, UserRole
from app.models.job import Job
from app.models.user import AppUser
from app.models.water_balance import RechargeStressScore, WaterBalanceResult
from tests.fakes.fake_hydrology_provider import FakeHydrologyDataProvider
from tests.fakes.fake_satellite_provider import FakeSatelliteDataProvider

_VALID_SQUARE = [(76.0, 18.0), (76.01, 18.0), (76.01, 18.01), (76.0, 18.01), (76.0, 18.0)]


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
def patch_real_providers(monkeypatch):
    monkeypatch.setattr("app.api.catchments.GEEHydrologyProvider", FakeHydrologyDataProvider)
    monkeypatch.setattr("app.api.catchments.GeeProvider", FakeSatelliteDataProvider)


@pytest_asyncio.fixture
async def users_and_catchment():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    async with AsyncSessionLocal() as db:
        officer = AppUser(
            email=f"officer-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Programme Officer",
            role=UserRole.PROGRAMME_OFFICER,
            is_active=True,
        )
        other_officer = AppUser(
            email=f"other-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Different Programme Officer",
            role=UserRole.PROGRAMME_OFFICER,
            is_active=True,
        )
        credit_officer = AppUser(
            email=f"credit-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Bank Credit Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
        )
        db.add_all([officer, other_officer, credit_officer])
        await db.flush()
        catchment = Catchment(
            name=f"Test Catchment {uuid4().hex[:8]}",
            geometry=from_shape(Polygon(_VALID_SQUARE), srid=4326),
            area_ha=100.0,
            delineation_method=DelineationMethod.MANUAL,
            created_by=officer.id,
        )
        db.add(catchment)
        await db.commit()
        await db.refresh(officer)
        await db.refresh(other_officer)
        await db.refresh(credit_officer)
        await db.refresh(catchment)

    yield {"officer": officer, "other_officer": other_officer, "credit_officer": credit_officer, "catchment": catchment}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(RechargeStressScore).where(RechargeStressScore.catchment_id == catchment.id))
        await db.execute(delete(WaterBalanceResult).where(WaterBalanceResult.catchment_id == catchment.id))
        await db.execute(delete(Job).where(Job.created_by.in_([officer.id, other_officer.id, credit_officer.id])))
        await db.execute(delete(Catchment).where(Catchment.id == catchment.id))
        await db.execute(delete(AppUser).where(AppUser.id.in_([officer.id, other_officer.id, credit_officer.id])))
        await db.commit()


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "correct-password"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _trigger_and_complete(api_client: AsyncClient, token: str, catchment_id) -> dict:
    trigger_response = await api_client.post(
        f"/api/v1/catchments/{catchment_id}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )
    assert trigger_response.status_code == 202, trigger_response.text
    job_id = trigger_response.json()["job_id"]

    job_response = await api_client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    job_json = job_response.json()
    assert job_json["status"] == "done", f"trigger did not complete successfully: {job_json}"
    return job_json


@pytest.mark.asyncio
async def test_history_rejects_unauthenticated_request(api_client, users_and_catchment):
    catchment = users_and_catchment["catchment"]
    response = await api_client.get(f"/api/v1/catchments/{catchment.id}/water-reports/history")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_history_rejects_role_without_catchment_permission(api_client, users_and_catchment):
    catchment = users_and_catchment["catchment"]
    credit_officer = users_and_catchment["credit_officer"]
    token = await _login(api_client, credit_officer.email)

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports/history", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_history_returns_404_for_a_catchment_owned_by_someone_else(api_client, users_and_catchment):
    officer = users_and_catchment["officer"]
    other_officer = users_and_catchment["other_officer"]
    catchment = users_and_catchment["catchment"]
    owner_token = await _login(api_client, officer.email)
    await _trigger_and_complete(api_client, owner_token, catchment.id)

    other_token = await _login(api_client, other_officer.email)
    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports/history", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_history_returns_empty_list_when_no_report_exists(api_client, users_and_catchment):
    """Unlike the single-latest endpoint, an empty history is a normal,
    real state (a brand-new catchment) — 200 with `[]`, not a 404."""
    officer = users_and_catchment["officer"]
    catchment = users_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports/history", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_history_returns_every_completed_run_newest_first(api_client, users_and_catchment):
    officer = users_and_catchment["officer"]
    catchment = users_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    first_job = await _trigger_and_complete(api_client, token, catchment.id)
    second_job = await _trigger_and_complete(api_client, token, catchment.id)
    third_job = await _trigger_and_complete(api_client, token, catchment.id)
    assert len({first_job["id"], second_job["id"], third_job["id"]}) == 3, "each trigger must be a distinct run"

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports/history", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body) == 3
    computed_ats = [item["generated_at"] for item in body]
    assert computed_ats == sorted(computed_ats, reverse=True), "must be ordered newest first"

    # Every item is a real, correctly-paired water_balance + recharge_stress
    # sibling — not two independently-truncated lists zipped by position.
    for item in body:
        assert item["water_balance"]["computed_at"] == item["generated_at"]
        assert item["recharge_stress"]["computed_at"] == item["generated_at"]
        assert "job" not in item


@pytest.mark.asyncio
async def test_history_respects_the_limit_parameter(api_client, users_and_catchment):
    officer = users_and_catchment["officer"]
    catchment = users_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    await _trigger_and_complete(api_client, token, catchment.id)
    await _trigger_and_complete(api_client, token, catchment.id)
    await _trigger_and_complete(api_client, token, catchment.id)

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports/history",
        params={"limit": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_history_rejects_a_limit_outside_the_allowed_range(api_client, users_and_catchment):
    officer = users_and_catchment["officer"]
    catchment = users_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports/history",
        params={"limit": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
