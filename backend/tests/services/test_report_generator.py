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
from app.models.enums import BoundaryLevel, JobStatus, JobType, RiskFactor, SatelliteIndexType, UserRole
from app.models.evidence import EvidenceRecord, ValidationFinding, ValidationRun
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.observation_fetch import ObservationFetch
from app.models.risk import ConfigWeight, RiskFactorScore, RiskScore
from app.models.satellite import SatelliteObservation
from app.models.user import AppUser
from app.services.provenance import HARNESS_VERSION
from app.services.reporting.progress import STAGE_IDS
from app.services.reporting.report_generator import _read_cached_observations, generate_farm_report
from app.services.risk.engine import RiskEngine
from app.services.satellite.gee_provider import GeeProvider
from tests.fakes.fake_satellite_provider import FakeSatelliteDataProvider


class _DescribedFakeProvider(FakeSatelliteDataProvider, GeeProvider):
    """The fake's data and constructor (no credentials, no network), but an
    instance of GeeProvider — so provenance takes the described Earth Engine
    lineage path end to end, not the "lineage not described" fallback."""


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
        # Lineage references its result without a foreign key (the house
        # polymorphic pattern), so deleting the score would orphan it.
        # Findings cascade from their run at the database.
        score_ids = select(RiskScore.id).where(RiskScore.entity_id == farm.id)
        await cleanup.execute(delete(ValidationRun).where(ValidationRun.result_id.in_(score_ids)))
        await cleanup.execute(delete(EvidenceRecord).where(EvidenceRecord.result_id.in_(score_ids)))
        await cleanup.execute(delete(RiskFactorScore).where(RiskFactorScore.risk_score_id.in_(
            select(RiskScore.id).where(RiskScore.entity_id == farm.id)
        )))
        await cleanup.execute(delete(RiskScore).where(RiskScore.entity_id == farm.id))
        await cleanup.execute(delete(SatelliteObservation).where(SatelliteObservation.entity_id == farm.id))
        await cleanup.execute(delete(ObservationFetch).where(ObservationFetch.entity_id == farm.id))
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

        # M2B P9 — Evidence & Method provenance persisted alongside the
        # score itself, not derived later.
        assert risk_score.observation_window_start is not None
        assert risk_score.observation_window_end is not None
        assert risk_score.observation_window_start < risk_score.observation_window_end
        assert risk_score.weighted_average_score is not None
        assert 0.0 <= risk_score.weighted_average_score <= 100.0

        factors = (
            await db.execute(select(RiskFactorScore).where(RiskFactorScore.risk_score_id == risk_score.id))
        ).scalars().all()
        assert {f.factor for f in factors} == set(RiskFactor)

        observations = (
            await db.execute(select(SatelliteObservation).where(SatelliteObservation.entity_id == scenario["farm"].id))
        ).scalars().all()
        assert len(observations) > 0  # NDVI/MNDWI/NDMI/rainfall were fetched and cached


@pytest.mark.asyncio
async def test_source_scene_dates_persisted_for_optical_indices_not_rainfall(scenario):
    """M2B P9 Evidence tab: real Sentinel-2 acquisition dates must reach
    the database for NDVI/MNDWI/NDMI. Rainfall (CHIRPS) honestly has none
    — a daily gridded product has no discrete 'scene' to date, so this
    must stay empty rather than fabricate one."""
    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=FakeSatelliteDataProvider(),
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        observations = (
            await db.execute(select(SatelliteObservation).where(SatelliteObservation.entity_id == scenario["farm"].id))
        ).scalars().all()

        optical = [o for o in observations if o.index_type != SatelliteIndexType.RAINFALL]
        rainfall = [o for o in observations if o.index_type == SatelliteIndexType.RAINFALL]
        assert optical, "expected NDVI/MNDWI/NDMI rows"
        assert rainfall, "expected rainfall rows"

        for observation in optical:
            assert observation.source_dates, f"{observation.index_type} row missing scene dates"
            for scene_date in observation.source_dates:
                # Persisted as ISO strings (see _persist_observations);
                # every scene must fall within that observation's own month.
                assert observation.period_start.isoformat() <= scene_date < observation.period_end.isoformat()

        for observation in rainfall:
            assert observation.source_dates == []


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


# ---------------------------------------------------------------------------
# M2B P8 — honest progress. Every stage the pipeline reports must reflect
# what actually happened: full completion in order on a fresh run, cache
# labels on a re-run, and — on failure — the failing stage marked failed
# while every earlier stage's completed state is left untouched and every
# later stage stays truthfully unstarted.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_stages_all_complete_in_order_with_fetch_labels_on_fresh_run(scenario):
    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=FakeSatelliteDataProvider(),
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, scenario["job"].id)
        assert job.progress is not None
        stages = job.progress["stages"]

        # Every defined stage present, in the exact order the pipeline
        # actually executes them — the frontend trusts this order.
        assert [s["id"] for s in stages] == STAGE_IDS
        for stage in stages:
            assert stage["status"] == "done", f"{stage['id']} should be done, was {stage['status']}"
            assert stage["started_at"] is not None
            assert stage["completed_at"] is not None
            assert stage["started_at"] <= stage["completed_at"]

        by_id = {s["id"]: s for s in stages}
        for fetch_stage_id in (
            "vegetation_observations",
            "surface_water_observations",
            "crop_moisture_observations",
            "rainfall_observations",
        ):
            metadata = by_id[fetch_stage_id]["metadata"]
            assert metadata["source"] == "fetched"  # nothing cached yet — a genuine first fetch
            assert metadata["months"] == 36  # 3-year lookback


@pytest.mark.asyncio
async def test_progress_stages_show_cache_source_on_second_run(scenario):
    """The honest counterpart to test_second_run_reuses_cached_observations_
    without_refetching above: not just that no new fetch happened, but that
    the timeline SAYS so — 'restored from cache', not a suspiciously fast
    'fetched'."""
    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=FakeSatelliteDataProvider(),
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        job2 = Job(type=JobType.FARM_REPORT, status=JobStatus.PENDING, created_by=scenario["user"].id)
        db.add(job2)
        await db.commit()
        await db.refresh(job2)

    await generate_farm_report(
        job_id=job2.id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=FakeSatelliteDataProvider(),
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        job2_after = await db.get(Job, job2.id)
        by_id = {s["id"]: s for s in job2_after.progress["stages"]}
        for fetch_stage_id in (
            "vegetation_observations",
            "surface_water_observations",
            "crop_moisture_observations",
            "rainfall_observations",
        ):
            assert by_id[fetch_stage_id]["status"] == "done"
            assert by_id[fetch_stage_id]["metadata"]["source"] == "cache"

        await db.execute(delete(Job).where(Job.id == job2.id))
        await db.commit()


@pytest.mark.asyncio
async def test_progress_marks_the_failing_stage_and_leaves_later_stages_pending(scenario):
    """The missing-farm failure happens while loading_geometry is in
    flight (tracker.start() fires before the farm lookup) — the timeline
    must say exactly that, not just 'failed' with no location."""
    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=uuid4(),  # nonexistent — same failure mode as the test above
        lookback_years=3,
        satellite_provider=FakeSatelliteDataProvider(),
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, scenario["job"].id)
        by_id = {s["id"]: s for s in job.progress["stages"]}

        assert by_id["preparing"]["status"] == "done"
        assert by_id["loading_geometry"]["status"] == "failed"
        assert by_id["loading_geometry"]["completed_at"] is not None

        later_stages = STAGE_IDS[STAGE_IDS.index("loading_geometry") + 1 :]
        for stage_id in later_stages:
            stage = by_id[stage_id]
            assert stage["status"] == "pending", f"{stage_id} must stay pending, was {stage['status']}"
            assert stage["started_at"] is None
            assert stage["completed_at"] is None


@pytest.mark.asyncio
async def test_progress_preserves_earlier_completed_stages_when_a_later_stage_fails(scenario):
    """Journey C (Product Design v2 §6): 'An assessment fails at the
    rainfall stage... the Run page shows exactly which stage failed,
    keeps the completed stages visible.' Proven here against the actual
    persisted timeline, not just the narrative."""

    class FailsOnRainfall(FakeSatelliteDataProvider):
        def get_rainfall_series(self, geometry_geojson, start, end):
            raise RuntimeError("simulated Earth Engine quota exhaustion")

    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=FailsOnRainfall(),
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, scenario["job"].id)
        assert job.status == JobStatus.FAILED
        # Still the generic, client-safe message — the simulated
        # exception text must never reach the job row.
        assert "simulated Earth Engine quota exhaustion" not in (job.error_message or "")

        by_id = {s["id"]: s for s in job.progress["stages"]}

        for done_stage_id in (
            "preparing",
            "loading_geometry",
            "vegetation_observations",
            "surface_water_observations",
            "crop_moisture_observations",
        ):
            stage = by_id[done_stage_id]
            assert stage["status"] == "done", f"{done_stage_id} must remain done, was {stage['status']}"
            assert stage["completed_at"] is not None

        # The three fetch stages before rainfall genuinely fetched (this
        # farm has no prior observations cached) — real work, really done.
        for fetched_stage_id in (
            "vegetation_observations",
            "surface_water_observations",
            "crop_moisture_observations",
        ):
            assert by_id[fetched_stage_id]["metadata"]["source"] == "fetched"

        assert by_id["rainfall_observations"]["status"] == "failed"

        for pending_stage_id in ("rainfall_climatology", "water_history", "scoring", "saving", "completed"):
            stage = by_id[pending_stage_id]
            assert stage["status"] == "pending"
            assert stage["started_at"] is None


# =====================================================================
# Evidence provenance and validation (evidence-aware roadmap, Phase B)
# =====================================================================


async def _run_report(scenario, provider) -> RiskScore:
    await generate_farm_report(
        job_id=scenario["job"].id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=provider,
        risk_engine=RiskEngine(),
    )
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, scenario["job"].id)
        assert job.status == JobStatus.DONE, job.error_message
        return await db.get(RiskScore, job.entity_id)


@pytest.mark.asyncio
async def test_the_score_is_persisted_with_its_lineage(scenario):
    score = await _run_report(scenario, _DescribedFakeProvider())

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(EvidenceRecord).where(EvidenceRecord.result_id == score.id))).scalars().all()

    by_quantity = {row.quantity: row for row in rows}
    for quantity in (
        "ndvi", "mndwi", "ndmi", "ndvi_baseline", "rainfall_monthly_mm", "rainfall_climatology_mm",
        "jrc_occurrence_percent", "composite_min_weight_coverage", "confidence_level", "floor_threshold",
    ):
        assert quantity in by_quantity, f"no lineage recorded for {quantity}"

    assert all(row.result_table == "risk_score" for row in rows)
    assert all(row.validation_status == "unvalidated" for row in rows)
    assert by_quantity["jrc_occurrence_percent"].source == "JRC/GSW1_4/GlobalSurfaceWater"
    assert "unweighted" in by_quantity["jrc_occurrence_percent"].reducer
    assert by_quantity["ndvi"].acquisition_dates, "Sentinel-2 scene dates should reach the lineage"
    assert by_quantity["floor_threshold"].source == f"config_weight:{scenario['config'].id}"


@pytest.mark.asyncio
async def test_validation_findings_persist_with_their_run(scenario):
    """Regression test for a real defect found against a live database:
    findings were inserted before their run and rejected on the foreign
    key. The first Service 1 tests missed it because clean fake data
    produced no findings at all — so this one forces an ERROR."""
    score = await _run_report(scenario, FakeSatelliteDataProvider(jrc_occurrence_percent=150.0))

    async with AsyncSessionLocal() as db:
        runs = (await db.execute(select(ValidationRun).where(ValidationRun.result_id == score.id))).scalars().all()
        assert len(runs) == 1
        run = runs[0]
        findings = (
            await db.execute(select(ValidationFinding).where(ValidationFinding.validation_run_id == run.id))
        ).scalars().all()

    assert run.source == "pipeline"
    assert run.harness_version == HARNESS_VERSION
    assert run.failed is True
    assert run.error_count >= 1
    assert any(f.check_name == "series_within_hard_range" and f.severity == "error" for f in findings)


@pytest.mark.asyncio
async def test_a_cached_rerun_records_cache_retrieval_and_keeps_its_scene_dates(scenario):
    """Two defects in one path. Cached observations used to be rebuilt
    without their scene dates, so a re-assessment lost its acquisition
    lineage; and nothing recorded that the data was reused at all."""
    await _run_report(scenario, _DescribedFakeProvider())

    async with AsyncSessionLocal() as db:
        job2 = Job(type=JobType.FARM_REPORT, status=JobStatus.PENDING, created_by=scenario["user"].id)
        db.add(job2)
        await db.commit()
        await db.refresh(job2)
    await generate_farm_report(
        job_id=job2.id,
        farm_id=scenario["farm"].id,
        lookback_years=3,
        satellite_provider=_DescribedFakeProvider(),
        risk_engine=RiskEngine(),
    )

    async with AsyncSessionLocal() as db:
        job2_after = await db.get(Job, job2.id)
        second = await db.get(RiskScore, job2_after.entity_id)
        ndvi = (
            await db.execute(
                select(EvidenceRecord).where(EvidenceRecord.result_id == second.id, EvidenceRecord.quantity == "ndvi")
            )
        ).scalar_one()
        cached = await _read_cached_observations(
            db, scenario["farm"].id, SatelliteIndexType.NDVI, second.observation_window_start, second.observation_window_end
        )
        await db.execute(delete(Job).where(Job.id == job2.id))
        await db.commit()

    assert ndvi.retrieval == "cache"
    assert ndvi.acquisition_dates, "scene dates must survive the cache"
    assert all(obs.source_scene_dates for obs in cached)


@pytest.mark.asyncio
async def test_the_database_rejects_a_validation_level_that_does_not_exist(scenario):
    """The CHECK constraints are the database's half of the honesty rule:
    there is no 'plausibility_checked' level, and an ORM bypass cannot
    write one."""
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        db.add(
            EvidenceRecord(
                result_table="risk_score",
                result_id=uuid4(),
                kind="observation",
                quantity="ndvi",
                source="test",
                units="dimensionless",
                validation_status="plausibility_checked",
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


# =====================================================================
# Phase C — cache coverage, model confidence, decision sufficiency
# =====================================================================


class _RecordingProvider(_DescribedFakeProvider):
    """Records every index fetch as (index, start, end)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.index_calls: list[tuple] = []

    def get_index_time_series(self, geometry_geojson, index, start, end):
        self.index_calls.append((index, start, end))
        return super().get_index_time_series(geometry_geojson, index, start, end)


@pytest.mark.asyncio
async def test_a_first_report_fetches_the_full_seasonal_baseline(scenario):
    """Regression test for the defect that made three of the four factors in
    the production assessment uncomputable. The report window was fetched
    and cached first; the eight-year baseline request then found those rows,
    called the cache a hit, and never fetched the earlier years."""
    provider = _RecordingProvider()
    score = await _run_report(scenario, provider)

    ndvi_starts = sorted(start for index, start, _end in provider.index_calls if index.value == "ndvi")
    assert len(ndvi_starts) == 2, "the baseline must be fetched, not assumed from the report-window cache"
    assert ndvi_starts[0].year <= ndvi_starts[1].year - 8

    async with AsyncSessionLocal() as db:
        vegetation = (
            await db.execute(
                select(RiskFactorScore).where(
                    RiskFactorScore.risk_score_id == score.id, RiskFactorScore.factor == RiskFactor.VEGETATION_STABILITY
                )
            )
        ).scalar_one()
    assert vegetation.computed
    assert vegetation.raw_inputs["baseline_samples"] >= 5


@pytest.mark.asyncio
async def test_a_legacy_cache_without_a_coverage_record_is_refetched_without_duplicating_rows(scenario):
    """Production has cached rows written before coverage was recorded. They
    must not be trusted as complete, and refetching must not duplicate them."""
    first = _DescribedFakeProvider()
    await _run_report(scenario, first)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(ObservationFetch).where(ObservationFetch.entity_id == scenario["farm"].id))
        await db.commit()
        before = (
            await db.execute(select(SatelliteObservation).where(SatelliteObservation.entity_id == scenario["farm"].id))
        ).scalars().all()

    async with AsyncSessionLocal() as db:
        job2 = Job(type=JobType.FARM_REPORT, status=JobStatus.PENDING, created_by=scenario["user"].id)
        db.add(job2)
        await db.commit()
        await db.refresh(job2)
    refetch = _RecordingProvider()
    await generate_farm_report(
        job_id=job2.id, farm_id=scenario["farm"].id, lookback_years=3, satellite_provider=refetch, risk_engine=RiskEngine()
    )

    async with AsyncSessionLocal() as db:
        after = (
            await db.execute(select(SatelliteObservation).where(SatelliteObservation.entity_id == scenario["farm"].id))
        ).scalars().all()
        await db.execute(delete(Job).where(Job.id == job2.id))
        await db.commit()

    assert refetch.index_calls, "a cache with no coverage record must be refetched"
    keys = [(o.index_type, o.period_start) for o in after]
    assert len(keys) == len(set(keys)), "refetching duplicated cached rows"
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_the_score_is_persisted_with_model_confidence_and_sufficiency_as_separate_fields(scenario):
    score = await _run_report(scenario, _DescribedFakeProvider())

    async with AsyncSessionLocal() as db:
        stored = await db.get(RiskScore, score.id)
        factors = (await db.execute(select(RiskFactorScore).where(RiskFactorScore.risk_score_id == score.id))).scalars().all()

    assert stored.model_version == "rule-engine-v2"
    assert stored.decision_policy_id is not None
    mc, ds = stored.model_confidence, stored.decision_sufficiency
    assert set(mc) >= {"factors_computed", "overall_estimable", "overall_interval", "interval_coverage", "statement"}
    assert ds["policy_version"] == "sufficiency-v1" and ds["calibration_status"] == "uncalibrated"
    assert {t["tier"] for t in ds["tiers"]} == {"low", "medium", "high"}
    # No input is validated, so high stakes cannot be sufficient.
    high = next(t for t in ds["tiers"] if t["tier"] == "high")
    assert not high["sufficient"]
    assert any(i["code"] == "no_validated_evidence" for i in high["inadequacies"])
    # Factor detail: computed flags, intervals where defined, sub-signals kept.
    by_factor = {f.factor: f for f in factors}
    assert by_factor[RiskFactor.VEGETATION_STABILITY].interval_low is not None
    assert "sub_signals" in by_factor[RiskFactor.WATER_AVAILABILITY].raw_inputs


@pytest.mark.asyncio
async def test_a_farm_with_no_measurable_factors_stores_no_overall_score(scenario):
    """End to end, through the real database: the nullable columns and the
    computed-has-value constraint accept an honest absence."""
    empty = _DescribedFakeProvider(missing_months=set(range(200)))
    score = await _run_report(scenario, empty)

    async with AsyncSessionLocal() as db:
        stored = await db.get(RiskScore, score.id)
        factors = (await db.execute(select(RiskFactorScore).where(RiskFactorScore.risk_score_id == score.id))).scalars().all()

    assert stored.overall_score is None and stored.overall_band is None
    uncomputed = [f for f in factors if not f.computed]
    assert uncomputed and all(f.value is None and f.band is None for f in uncomputed)
    assert not any(t["sufficient"] for t in stored.decision_sufficiency["tiers"])
