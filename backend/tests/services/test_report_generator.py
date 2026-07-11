"""Integration tests for the report generation pipeline, against a real
local PostGIS instance — FarmPolygon.geometry cannot be meaningfully
exercised against SQLite (GeoAlchemy2 has no non-PostGIS backend without
the SpatiaLite extension, which this project does not use). Uses
FakeSatelliteDataProvider throughout, so no real Earth Engine call is made.

Requires the M0 docker-compose PostGIS instance to be running locally
(DATABASE_URL from backend/.env). Skips cleanly if it isn't reachable,
rather than failing the whole suite in an environment without Docker.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import delete, select, text

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.models.admin import AdminBoundary
from app.models.enums import BoundaryLevel, JobStatus, JobType, RiskFactor, UserRole
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.risk import ConfigWeight, RiskFactorScore, RiskScore
from app.models.satellite import SatelliteObservation
from app.models.user import AppUser
from app.services.reporting.report_generator import generate_farm_report
from app.services.risk.engine import RiskEngine
from tests.fakes.fake_satellite_provider import FakeSatelliteDataProvider


async def _database_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def db_session():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def scenario(db_session):
    """One farm, one village, one user, one active config, one pending
    job — everything generate_farm_report() needs. Torn down afterward in
    FK-safe order, including whatever the pipeline itself wrote
    (satellite_observation / risk_score / risk_factor_score), which are
    not pre-created and so must be cleaned up by query, not by reference.
    """
    village = AdminBoundary(
        level=BoundaryLevel.VILLAGE,
        name=f"Test Village {uuid4().hex[:8]}",
        geometry=from_shape(
            Polygon([(76.0, 18.0), (76.05, 18.0), (76.05, 18.05), (76.0, 18.05), (76.0, 18.0)]), srid=4326
        ),
    )
    user = AppUser(
        email=f"test-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("test-password"),
        full_name="Test Officer",
        role=UserRole.CREDIT_OFFICER,
        is_active=True,
    )
    db_session.add_all([village, user])
    await db_session.flush()

    farm = FarmPolygon(
        village_id=village.id,
        geometry=from_shape(
            Polygon([(76.01, 18.01), (76.02, 18.01), (76.02, 18.02), (76.01, 18.02), (76.01, 18.01)]), srid=4326
        ),
        area_ha=1.0,
        drawn_by=user.id,
    )
    config = ConfigWeight(
        weights={f.value: 0.25 for f in RiskFactor},
        floor_thresholds={"threshold": 80.0},
        effective_from=datetime.now(timezone.utc),
        created_by=user.id,
    )
    db_session.add_all([farm, config])
    await db_session.flush()

    job = Job(type=JobType.FARM_REPORT, status=JobStatus.PENDING, created_by=user.id)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(farm)
    await db_session.refresh(job)
    await db_session.refresh(config)

    yield {"farm": farm, "user": user, "village": village, "config": config, "job": job}

    async with AsyncSessionLocal() as cleanup:
        await cleanup.execute(delete(RiskFactorScore).where(RiskFactorScore.risk_score_id.in_(
            select(RiskScore.id).where(RiskScore.entity_id == farm.id)
        )))
        await cleanup.execute(delete(RiskScore).where(RiskScore.entity_id == farm.id))
        await cleanup.execute(delete(SatelliteObservation).where(SatelliteObservation.entity_id == farm.id))
        await cleanup.execute(delete(Job).where(Job.id == job.id))
        await cleanup.execute(delete(FarmPolygon).where(FarmPolygon.id == farm.id))
        await cleanup.execute(delete(ConfigWeight).where(ConfigWeight.id == config.id))
        await cleanup.execute(delete(AppUser).where(AppUser.id == user.id))
        await cleanup.execute(delete(AdminBoundary).where(AdminBoundary.id == village.id))
        await cleanup.commit()


@pytest.mark.asyncio
async def test_pipeline_completes_job_and_persists_full_report(scenario):
    provider = FakeSatelliteDataProvider()

    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=provider,
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, scenario["job"].id)
        assert job.status == JobStatus.DONE
        assert job.entity_id is not None  # points at the resulting risk_score row

        risk_score = await db.get(RiskScore, job.entity_id)
        assert risk_score is not None
        assert risk_score.entity_id == scenario["farm"].id
        assert 0.0 <= risk_score.overall_score <= 100.0
        assert risk_score.model_version == RiskEngine.MODEL_VERSION

        factors = (
            await db.execute(select(RiskFactorScore).where(RiskFactorScore.risk_score_id == risk_score.id))
        ).scalars().all()
        assert {f.factor for f in factors} == set(RiskFactor)

        observations = (
            await db.execute(select(SatelliteObservation).where(SatelliteObservation.entity_id == scenario["farm"].id))
        ).scalars().all()
        assert len(observations) > 0  # NDVI/MNDWI/NDMI/rainfall were fetched and cached


@pytest.mark.asyncio
async def test_second_run_reuses_cached_observations_without_refetching(scenario):
    """Proves the caching contract: a second report for the same farm must
    not issue new fetch calls for data already cached from the first run."""
    provider = FakeSatelliteDataProvider()

    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=provider,
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        first_observation_count = len(
            (await db.execute(select(SatelliteObservation).where(SatelliteObservation.entity_id == scenario["farm"].id)))
            .scalars()
            .all()
        )

    # A second job against the same farm/window.
    async with AsyncSessionLocal() as db:
        job2 = Job(type=JobType.FARM_REPORT, status=JobStatus.PENDING, created_by=scenario["user"].id)
        db.add(job2)
        await db.commit()
        await db.refresh(job2)

    call_tracker = FakeSatelliteDataProvider()
    original_get_index = call_tracker.get_index_time_series
    call_counts = {"index_calls": 0}

    def _counting_get_index(*args, **kwargs):
        call_counts["index_calls"] += 1
        return original_get_index(*args, **kwargs)

    call_tracker.get_index_time_series = _counting_get_index

    await generate_farm_report(
        job_id=job2.id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=call_tracker,
        risk_engine=RiskEngine(),
    )

    assert call_counts["index_calls"] == 0  # fully served from cache, zero new fetches

    async with AsyncSessionLocal() as db:
        second_observation_count = len(
            (await db.execute(select(SatelliteObservation).where(SatelliteObservation.entity_id == scenario["farm"].id)))
            .scalars()
            .all()
        )
        job2_after = await db.get(Job, job2.id)
        assert job2_after.status == JobStatus.DONE
        await db.execute(delete(Job).where(Job.id == job2.id))
        await db.commit()

    assert second_observation_count == first_observation_count  # no duplicate rows written


@pytest.mark.asyncio
async def test_missing_farm_fails_job_with_generic_message_not_internal_detail(scenario):
    """A nonexistent farm_id must fail the job cleanly — status FAILED,
    generic client-safe message, no leaked internal exception text."""
    nonexistent_farm_id = uuid4()

    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=nonexistent_farm_id,
        lookback_years=3,
        satellite_provider=FakeSatelliteDataProvider(),
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, scenario["job"].id)
        assert job.status == JobStatus.FAILED
        assert job.error_message == "Report generation failed. Please retry; contact support if this persists."
        assert str(nonexistent_farm_id) not in job.error_message
        assert "Traceback" not in (job.error_message or "")


@pytest.mark.asyncio
async def test_missing_config_weight_raises_runtime_error():
    """No active ConfigWeight row (e.g. seed script never run) must raise
    a clear, specific error — the caller (generate_farm_report) is what
    translates that into a failed job, not a crashed worker process; that
    translation is already covered by test_missing_farm_fails_job_with_
    generic_message_not_internal_detail above.

    A pure mock, not a database of any kind: config_weight.weights uses
    Postgres-specific JSONB (unlike the generic Uuid type used elsewhere),
    so it can't be created against SQLite either — and standing up a real
    Postgres table just to test one function's control flow when it
    doesn't find a row is unnecessary. This also sidesteps a real
    fragility the previous version of this test had: it asserted "zero
    ConfigWeight rows anywhere in the database", which broke the moment a
    real ConfigWeight was legitimately seeded for actual use
    (scripts/seed_default_config_weight.py) — a global-state assumption
    that was never going to hold against a properly-seeded dev database.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.services.reporting.report_generator import _get_active_config_weight

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with pytest.raises(RuntimeError, match="No active risk-engine configuration"):
        await _get_active_config_weight(mock_db)
