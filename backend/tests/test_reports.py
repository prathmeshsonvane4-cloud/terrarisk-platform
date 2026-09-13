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
from app.models.evidence import EvidenceRecord, ValidationRun
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
        # Full district -> taluka -> village hierarchy: get_report's M2A P5
        # farm-context enrichment joins two parent levels, so a parentless
        # village would fail — the fixture mirrors real loaded data.
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

    yield {
        "village": village,
        "taluka": taluka,
        "district": district,
        "officer": officer,
        "outsider": outsider,
        "config": config,
    }

    async with AsyncSessionLocal() as db:
        farm_ids = (
            await db.execute(select(FarmPolygon.id).where(FarmPolygon.village_id == village.id))
        ).scalars().all()
        if farm_ids:
            # Lineage references its score without a foreign key; clear it
            # before the score or it is orphaned. Findings cascade from runs.
            score_ids = select(RiskScore.id).where(RiskScore.entity_id.in_(farm_ids))
            await db.execute(delete(ValidationRun).where(ValidationRun.result_id.in_(score_ids)))
            await db.execute(delete(EvidenceRecord).where(EvidenceRecord.result_id.in_(score_ids)))
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
        await db.execute(delete(AdminBoundary).where(AdminBoundary.id.in_([village.id, taluka.id, district.id])))
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
    job_json = job_response.json()
    assert job_json["status"] == "done", (
        "background task did not complete synchronously within the ASGI test transport "
        f"(status was {job_json['status']!r})"
    )
    risk_score_id = job_json["entity_id"]

    # M2B P8 — the honest progress timeline survives the Pydantic
    # from_attributes round-trip through the real HTTP response, not just
    # the raw ORM dict the service layer writes.
    assert job_json["progress"] is not None
    stages = job_json["progress"]["stages"]
    assert stages[0]["id"] == "preparing"
    assert stages[-1]["id"] == "completed"
    assert all(stage["status"] == "done" for stage in stages)

    report_response = await api_client.get(
        f"/api/v1/reports/{risk_score_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()
    assert report["farm_id"] == farm_id
    assert 0.0 <= report["overall_score"] <= 100.0
    assert report["overall_band"] in ("low", "moderate", "high", "very_high")
    assert {f["factor"] for f in report["factors"]} == {f.value for f in RiskFactor}
    # Every factor ships its raw driver inputs (Blueprint §07 explainability).
    assert all(f["raw_inputs"] for f in report["factors"])

    # M2A P5 enrichment: farm context + cached observation series, all from
    # persisted data — the dashboard and PDF render from this one payload.
    assert report["farm"]["village_name"] == scenario["village"].name
    assert report["farm"]["taluka_name"] == scenario["taluka"].name
    assert report["farm"]["district_name"] == scenario["district"].name
    assert report["farm"]["officer_name"] == "Test Officer"
    assert report["farm"]["geometry"]["type"] == "Polygon"
    assert len(report["series"]["ndvi"]) > 0
    assert len(report["series"]["rainfall"]) > 0
    assert all(point["value"] is not None for point in report["series"]["ndvi"])

    # M2B P9 — Evidence & Method payload, through the real HTTP response.
    assert report["evidence"]["observation_window_start"] is not None
    assert report["evidence"]["observation_window_end"] is not None
    assert report["evidence"]["expected_months"] == len(report["series"]["ndvi"]) or (
        report["evidence"]["expected_months"] >= len(report["series"]["ndvi"])
    )  # expected >= usable always; equal only when nothing was skipped
    assert report["method"]["weights_version_id"] == str(scenario["config"].id)
    assert report["method"]["weights"] == {f.value: 0.25 for f in RiskFactor}
    assert report["method"]["floor_threshold"] == 80.0
    assert report["method"]["weighted_average_score"] is not None
    # Real Sentinel-2 scene dates reach the HTTP response for NDVI, honestly
    # absent for rainfall (CHIRPS has no per-scene concept).
    assert any(point["source_dates"] for point in report["series"]["ndvi"])
    assert all(point["source_dates"] == [] for point in report["series"]["rainfall"])


async def test_trigger_report_fails_fast_when_satellite_provider_construction_raises(
    api_client, scenario, monkeypatch
):
    """DEPLOY-1 finding, reproduced on a real server: constructing
    GeeProvider() (Earth Engine auth/init) happens in _run_report_job,
    *before* generate_farm_report()'s own try/except begins. A real
    deployment hit this exactly — a misconfigured/unreadable service
    account key raised inside GeeProvider.__init__(), and because nothing
    caught it there, the job stayed PENDING forever with no error_message
    instead of failing immediately like every other report failure mode.
    """

    class _RaisingProvider:
        def __init__(self) -> None:
            raise PermissionError("[Errno 13] Permission denied: '/run/secrets/gee-service-account.json'")

    monkeypatch.setattr("app.api.reports.GeeProvider", _RaisingProvider)

    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)

    trigger_response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    assert trigger_response.status_code == 202, trigger_response.text
    job_id = trigger_response.json()["job_id"]

    job_response = await api_client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert job_response.status_code == 200
    job_json = job_response.json()
    assert job_json["status"] == "failed", (
        "a satellite-provider construction failure must fail the job immediately, "
        f"not leave it stuck (status was {job_json['status']!r})"
    )
    # Same generic, safe message every other report failure uses — never the
    # raw PermissionError/credential-path text.
    assert job_json["error_message"] == "Report generation failed. Please retry; contact support if this persists."


@pytest.mark.asyncio
async def test_trigger_report_rejects_unknown_farm(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    response = await api_client.post(
        f"/api/v1/farms/{uuid4()}/reports", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_trigger_report_rejects_user_outside_owner_or_branch(api_client, scenario):
    """RC1 audit finding: trigger_report had no owner-or-branch check at
    all — any authenticated officer could trigger real, billed Earth
    Engine compute against any farm_id in the system, not just their own
    branch's, by learning/guessing a UUID. Same class of bug as the M1
    IDOR fix for get_farm (deps.py user_can_access_owned_resource), just
    never applied here. Mirrors test_get_farm_rejects_user_outside_owner_or_branch
    (test_farms.py) exactly: an unrelated user's farm_id must 404, not
    succeed and not 403 (indistinguishable from a farm that doesn't exist)."""
    owner_token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, owner_token, scenario["village"].id)

    outsider_token = await _login(api_client, scenario["outsider"].email)
    response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {outsider_token}"}, json={}
    )
    assert response.status_code == 404, response.text

    # And no job was actually created for the outsider's unauthorized attempt.
    async with AsyncSessionLocal() as db:
        jobs = (
            await db.execute(select(Job).where(Job.created_by == scenario["outsider"].id))
        ).scalars().all()
        assert jobs == []


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


# ---------------------------------------------------------------------------
# M2A P6 — PDF export endpoint. The map tile fetch is always stubbed out
# (no network in tests); the full tile path is covered by manual live
# verification, and the renderer itself by test_report_pdf.py.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
def pdf_environment(monkeypatch, tmp_path):
    """No live tile fetches, and a per-test cache directory so caching
    behavior is observable and tests never poison each other."""
    monkeypatch.setattr("app.api.reports.fetch_map_snapshot", lambda geometry: None)
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "report_pdf_cache_dir", str(tmp_path / "pdf_cache"))
    return tmp_path / "pdf_cache"


async def _generate_report(api_client, scenario) -> tuple[str, str]:
    """Full trigger flow; returns (officer token, risk_score_id)."""
    token = await _login(api_client, scenario["officer"].email)
    farm_id = await _create_farm(api_client, token, scenario["village"].id)
    trigger_response = await api_client.post(
        f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    job_id = trigger_response.json()["job_id"]
    job_response = await api_client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    return token, job_response.json()["entity_id"]


@pytest.mark.asyncio
async def test_report_pdf_download(api_client, scenario, pdf_environment):
    token, risk_score_id = await _generate_report(api_client, scenario)

    response = await api_client.get(
        f"/api/v1/reports/{risk_score_id}/pdf", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert scenario["village"].name.split()[0] in disposition  # village in the filename


@pytest.mark.asyncio
async def test_report_pdf_is_rendered_once_then_served_from_cache(
    api_client, scenario, pdf_environment, monkeypatch
):
    token, risk_score_id = await _generate_report(api_client, scenario)

    import app.api.reports as reports_module

    real_render = reports_module.render_report_pdf
    render_calls = 0

    def counting_render(report, map_png):
        nonlocal render_calls
        render_calls += 1
        return real_render(report, map_png)

    monkeypatch.setattr(reports_module, "render_report_pdf", counting_render)

    first = await api_client.get(
        f"/api/v1/reports/{risk_score_id}/pdf", headers={"Authorization": f"Bearer {token}"}
    )
    second = await api_client.get(
        f"/api/v1/reports/{risk_score_id}/pdf", headers={"Authorization": f"Bearer {token}"}
    )
    assert first.status_code == second.status_code == 200
    assert render_calls == 1, "second request must be served from the disk cache"
    assert first.content == second.content
    assert len(list(pdf_environment.iterdir())) == 1  # exactly the cache file, no leftover temps


@pytest.mark.asyncio
async def test_report_pdf_rejects_user_outside_owner_or_branch(api_client, scenario, pdf_environment):
    _, risk_score_id = await _generate_report(api_client, scenario)

    outsider_token = await _login(api_client, scenario["outsider"].email)
    response = await api_client.get(
        f"/api/v1/reports/{risk_score_id}/pdf", headers={"Authorization": f"Bearer {outsider_token}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_report_pdf_returns_404_for_unknown_id(api_client, scenario, pdf_environment):
    token = await _login(api_client, scenario["officer"].email)
    response = await api_client.get(
        f"/api/v1/reports/{uuid4()}/pdf", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


# =====================================================================
# GET /reports/{id}/lineage (evidence-aware roadmap, Phase B)
# =====================================================================


async def _completed_report(client: AsyncClient, token: str, village_id) -> str:
    farm_id = await _create_farm(client, token, village_id)
    trigger = await client.post(f"/api/v1/farms/{farm_id}/reports", headers={"Authorization": f"Bearer {token}"}, json={})
    assert trigger.status_code == 202, trigger.text
    job = (await client.get(f"/api/v1/jobs/{trigger.json()['job_id']}", headers={"Authorization": f"Bearer {token}"})).json()
    assert job["status"] == "done", job
    return job["entity_id"]


@pytest.mark.asyncio
async def test_report_lineage_returns_every_input_and_the_validation_run(api_client, scenario):
    token = await _login(api_client, scenario["officer"].email)
    risk_score_id = await _completed_report(api_client, token, scenario["village"].id)

    response = await api_client.get(f"/api/v1/reports/{risk_score_id}/lineage", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result_table"] == "risk_score"
    assert body["provenance_recorded"] is True
    assert body["provenance_note"] is None
    quantities = {item["quantity"] for item in body["evidence"]}
    assert {"ndvi", "rainfall_monthly_mm", "jrc_occurrence_percent", "floor_threshold"} <= quantities
    assert all(item["validation_status"] == "unvalidated" for item in body["evidence"])
    assert len(body["validation_runs"]) == 1
    assert body["validation_runs"][0]["source"] == "pipeline"


@pytest.mark.asyncio
async def test_report_lineage_is_not_visible_to_someone_who_cannot_see_the_report(api_client, scenario):
    """Same guard as the report itself: a 404, not a 403, so existence is
    not disclosed either."""
    token = await _login(api_client, scenario["officer"].email)
    risk_score_id = await _completed_report(api_client, token, scenario["village"].id)
    outsider_token = await _login(api_client, scenario["outsider"].email)

    response = await api_client.get(
        f"/api/v1/reports/{risk_score_id}/lineage", headers={"Authorization": f"Bearer {outsider_token}"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_report_from_before_lineage_says_provenance_was_not_recorded(api_client, scenario):
    """A score computed before Phase B has no evidence rows, and none are
    reconstructed. The endpoint must say that in words, not return an empty
    list that reads like a report which depended on nothing."""
    token = await _login(api_client, scenario["officer"].email)
    risk_score_id = await _completed_report(api_client, token, scenario["village"].id)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(EvidenceRecord).where(EvidenceRecord.result_id == risk_score_id))
        await db.execute(delete(ValidationRun).where(ValidationRun.result_id == risk_score_id))
        await db.commit()

    body = (
        await api_client.get(f"/api/v1/reports/{risk_score_id}/lineage", headers={"Authorization": f"Bearer {token}"})
    ).json()

    assert body["provenance_recorded"] is False
    assert "cannot be recovered" in body["provenance_note"]
    assert body["evidence"] == []
