"""Integration tests for _run_water_report_job's real pipeline wiring
(ticket M5-002), exercised through the actual HTTP trigger endpoint +
GET /jobs/{id} — mirrors test_reports.py's own pattern for testing
Service 1's identical _run_report_job wiring: GEEHydrologyProvider/
GeeProvider are monkeypatched to deterministic fakes so this never
depends on live Earth Engine credentials or quota.
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
_GENERIC_FAILURE_MESSAGE = "Water report generation failed. Please retry; contact support if this persists."


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
    """Every test in this module runs the background job against
    deterministic fakes, never real Earth Engine — mirrors
    test_reports.py's own patch_gee_provider fixture exactly, applied to
    both of _run_water_report_job's providers."""
    monkeypatch.setattr("app.api.catchments.GEEHydrologyProvider", FakeHydrologyDataProvider)
    monkeypatch.setattr("app.api.catchments.GeeProvider", FakeSatelliteDataProvider)


@pytest_asyncio.fixture
async def officer_and_catchment():
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
        db.add(officer)
        await db.flush()
        catchment = Catchment(
            name=f"Test Catchment {uuid4().hex[:8]}",
            geometry=from_shape(Polygon(_VALID_SQUARE), srid=4326),
            area_ha=100.0,
            delineation_method=DelineationMethod.MANUAL,
            resolution_flags=[],
            created_by=officer.id,
        )
        db.add(catchment)
        await db.commit()
        await db.refresh(officer)
        await db.refresh(catchment)

    yield {"officer": officer, "catchment": catchment}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(RechargeStressScore).where(RechargeStressScore.catchment_id == catchment.id))
        await db.execute(delete(WaterBalanceResult).where(WaterBalanceResult.catchment_id == catchment.id))
        await db.execute(delete(Job).where(Job.created_by == officer.id))
        await db.execute(delete(Catchment).where(Catchment.id == catchment.id))
        await db.execute(delete(AppUser).where(AppUser.id == officer.id))
        await db.commit()


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "correct-password"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _trigger(api_client: AsyncClient, token: str, catchment_id) -> dict:
    response = await api_client.post(
        f"/api/v1/catchments/{catchment_id}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 202, response.text
    return response.json()


async def _get_job(api_client: AsyncClient, token: str, job_id: str) -> dict:
    response = await api_client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_successful_job_reaches_done_and_persists_both_results(api_client, officer_and_catchment):
    officer = officer_and_catchment["officer"]
    catchment = officer_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    trigger_body = await _trigger(api_client, token, catchment.id)
    job_json = await _get_job(api_client, token, trigger_body["job_id"])

    assert job_json["status"] == "done", (
        "background task did not complete synchronously within the ASGI test transport "
        f"(status was {job_json['status']!r})"
    )
    # entity_id deliberately stays catchment_id, never overwritten — see
    # app/api/catchments.py's module docstring (two sibling result
    # artifacts, no single id to overwrite it with).
    assert job_json["entity_id"] == str(catchment.id)
    assert job_json["error_message"] is None

    async with AsyncSessionLocal() as db:
        water_balance_rows = (
            await db.execute(select(WaterBalanceResult).where(WaterBalanceResult.catchment_id == catchment.id))
        ).scalars().all()
        recharge_stress_rows = (
            await db.execute(select(RechargeStressScore).where(RechargeStressScore.catchment_id == catchment.id))
        ).scalars().all()
    assert len(water_balance_rows) == 1
    assert len(recharge_stress_rows) == 1


@pytest.mark.asyncio
async def test_job_reaches_done_status(api_client, officer_and_catchment):
    """Dedicated status-only assertion, distinct from the persistence
    assertions above — the ticket's own "Job DONE" scenario."""
    officer = officer_and_catchment["officer"]
    catchment = officer_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    trigger_body = await _trigger(api_client, token, catchment.id)
    job_json = await _get_job(api_client, token, trigger_body["job_id"])

    assert job_json["status"] == "done"


@pytest.mark.asyncio
async def test_provider_construction_failure_fails_the_job(api_client, officer_and_catchment, monkeypatch):
    """Mirrors test_reports.py's
    test_trigger_report_fails_fast_when_satellite_provider_construction_raises:
    a provider raising during construction (bad/unreadable credentials)
    must fail the job immediately with the generic message, not hang."""

    class _RaisingProvider:
        def __init__(self) -> None:
            raise PermissionError("[Errno 13] Permission denied: '/run/secrets/gee-hydrology-service-account.json'")

    monkeypatch.setattr("app.api.catchments.GEEHydrologyProvider", _RaisingProvider)

    officer = officer_and_catchment["officer"]
    catchment = officer_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    trigger_body = await _trigger(api_client, token, catchment.id)
    job_json = await _get_job(api_client, token, trigger_body["job_id"])

    assert job_json["status"] == "failed"
    assert job_json["error_message"] == _GENERIC_FAILURE_MESSAGE


@pytest.mark.asyncio
async def test_orchestrator_failure_fails_the_job(api_client, officer_and_catchment, monkeypatch):
    """generate_water_report() raising for any reason (engine validation
    error, persistence failure, unknown catchment) must fail the job the
    same way a provider-construction failure does — proven here by
    monkeypatching the orchestrator call site directly, independent of
    which internal cause triggered it (already covered by
    test_water_report_generator.py's own provider/engine/persistence
    failure tests)."""
    monkeypatch.setattr(
        "app.api.catchments.generate_water_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pipeline exploded")),
    )

    officer = officer_and_catchment["officer"]
    catchment = officer_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    trigger_body = await _trigger(api_client, token, catchment.id)
    job_json = await _get_job(api_client, token, trigger_body["job_id"])

    assert job_json["status"] == "failed"


@pytest.mark.asyncio
async def test_job_reaches_failed_status_on_orchestrator_failure(api_client, officer_and_catchment, monkeypatch):
    """Dedicated status-only assertion — the ticket's own "Job FAILED"
    scenario, independent of the error-message assertion below."""
    monkeypatch.setattr(
        "app.api.catchments.generate_water_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pipeline exploded")),
    )

    officer = officer_and_catchment["officer"]
    catchment = officer_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    trigger_body = await _trigger(api_client, token, catchment.id)
    job_json = await _get_job(api_client, token, trigger_body["job_id"])

    assert job_json["status"] == "failed"


@pytest.mark.asyncio
async def test_error_message_persisted_is_generic_never_the_raw_exception(
    api_client, officer_and_catchment, monkeypatch
):
    """The ticket's own "Error message persisted" scenario: a failure's
    real detail (which might include credential paths or internal
    exception text) must never reach Job.error_message — only the fixed,
    generic, non-internal message every other failure path in this
    codebase already uses."""
    monkeypatch.setattr(
        "app.api.catchments.generate_water_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("leaked internal detail: db=postgres://user:secret@host/db")
        ),
    )

    officer = officer_and_catchment["officer"]
    catchment = officer_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    trigger_body = await _trigger(api_client, token, catchment.id)
    job_json = await _get_job(api_client, token, trigger_body["job_id"])

    assert job_json["error_message"] == _GENERIC_FAILURE_MESSAGE
    assert "secret" not in job_json["error_message"]
    assert "postgres://" not in job_json["error_message"]


@pytest.mark.asyncio
async def test_failed_job_persists_no_water_report_results(api_client, officer_and_catchment, monkeypatch):
    """A failed run must leave no partial WaterBalanceResult/
    RechargeStressScore rows behind — nothing was ever added to the
    session before the orchestrator raised."""
    monkeypatch.setattr(
        "app.api.catchments.generate_water_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pipeline exploded")),
    )

    officer = officer_and_catchment["officer"]
    catchment = officer_and_catchment["catchment"]
    token = await _login(api_client, officer.email)

    await _trigger(api_client, token, catchment.id)

    async with AsyncSessionLocal() as db:
        water_balance_rows = (
            await db.execute(select(WaterBalanceResult).where(WaterBalanceResult.catchment_id == catchment.id))
        ).scalars().all()
        recharge_stress_rows = (
            await db.execute(select(RechargeStressScore).where(RechargeStressScore.catchment_id == catchment.id))
        ).scalars().all()
    assert water_balance_rows == []
    assert recharge_stress_rows == []
