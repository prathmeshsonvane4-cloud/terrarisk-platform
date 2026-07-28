"""Integration tests for GET /catchments/{id}/water-reports (ticket
M5-003), against real PostGIS and real JWT auth end to end — mirrors
tests/test_water_report_job_execution.py's own pattern: GEEHydrologyProvider/
GeeProvider are monkeypatched to deterministic fakes so triggering a real,
completed report never depends on live Earth Engine credentials or quota.
"""

from __future__ import annotations

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
    """Every test in this module runs any triggered background job
    against deterministic fakes, never real Earth Engine — mirrors
    test_water_report_job_execution.py's own fixture exactly."""
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
            resolution_flags=["et_sub_pixel"],
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
        await db.execute(
            delete(AppUser).where(AppUser.id.in_([officer.id, other_officer.id, credit_officer.id]))
        )
        await db.commit()


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "correct-password"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _trigger_and_complete(api_client: AsyncClient, token: str, catchment_id) -> dict:
    """Triggers a water report and returns the resulting Job JSON —
    the background task runs synchronously within the ASGI test
    transport, so by the time this returns the job has already reached
    a terminal status (same assumption test_water_report_job_execution.py
    already relies on)."""
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
async def test_get_latest_water_report_success(api_client, users_and_catchment):
    officer = users_and_catchment["officer"]
    catchment = users_and_catchment["catchment"]
    token = await _login(api_client, officer.email)
    completed_job = await _trigger_and_complete(api_client, token, catchment.id)

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["catchment_id"] == str(catchment.id)
    assert body["generated_at"] is not None

    assert set(body["water_balance"].keys()) == {
        "id",
        "period_start",
        "period_end",
        "rainfall_mm",
        "et_mm",
        "runoff_mm",
        "storage_change_mm",
        "storage_change_band",
        "data_completeness",
        "calibration_status",
        "closed_catchment_assumed",
        "resolution_flags",
        "model_version",
        "computed_at",
    }
    assert body["water_balance"]["resolution_flags"] == ["et_sub_pixel"]

    assert set(body["recharge_stress"].keys()) == {
        "id",
        "stress_score",
        "stress_band",
        "baseline_window",
        "rainfall_anomaly_ratio",
        "vci",
        "surface_water_trend",
        "cgwb_category",
        "cgwb_category_as_of",
        "raw_inputs",
        "computed_at",
    }

    assert body["job"]["id"] == completed_job["id"]
    assert body["job"]["status"] == "done"


@pytest.mark.asyncio
async def test_get_latest_water_report_returns_404_when_no_report_exists(api_client, users_and_catchment):
    officer = users_and_catchment["officer"]
    catchment = users_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_latest_water_report_rejects_unauthenticated_request(api_client, users_and_catchment):
    catchment = users_and_catchment["catchment"]
    response = await api_client.get(f"/api/v1/catchments/{catchment.id}/water-reports")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_latest_water_report_rejects_role_without_catchment_permission(api_client, users_and_catchment):
    """A bank Credit Officer is a real, authenticated user — but Water
    Intelligence is not their product; same 403 as the other catchment
    endpoints' own role gate."""
    catchment = users_and_catchment["catchment"]
    credit_officer = users_and_catchment["credit_officer"]
    token = await _login(api_client, credit_officer.email)

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_latest_water_report_returns_404_for_a_catchment_owned_by_someone_else(
    api_client, users_and_catchment
):
    """Same IDOR-safe discipline as get_catchment: a catchment outside
    the caller's own scope must 404, not succeed and not 403 — proven
    here even though a completed report exists, for the *owner*."""
    officer = users_and_catchment["officer"]
    other_officer = users_and_catchment["other_officer"]
    catchment = users_and_catchment["catchment"]
    owner_token = await _login(api_client, officer.email)
    await _trigger_and_complete(api_client, owner_token, catchment.id)

    other_token = await _login(api_client, other_officer.email)
    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_latest_water_report_returns_the_latest_of_multiple_completed_reports(
    api_client, users_and_catchment
):
    officer = users_and_catchment["officer"]
    catchment = users_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    first_job = await _trigger_and_complete(api_client, token, catchment.id)
    second_job = await _trigger_and_complete(api_client, token, catchment.id)
    assert first_job["id"] != second_job["id"]

    response = await api_client.get(
        f"/api/v1/catchments/{catchment.id}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["job"]["id"] == second_job["id"]
    assert body["job"]["id"] != first_job["id"]

    async with AsyncSessionLocal() as db:
        water_balance_rows = (
            await db.execute(
                select(WaterBalanceResult).where(WaterBalanceResult.catchment_id == catchment.id)
            )
        ).scalars().all()
    assert len(water_balance_rows) == 2, "both runs must have persisted their own result row"
    latest_by_computed_at = max(water_balance_rows, key=lambda row: row.computed_at)
    assert body["water_balance"]["id"] == str(latest_by_computed_at.id)
