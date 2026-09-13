"""Tests for the Water Intelligence report orchestrator (ticket M5-001).

Split like tests/services/test_cgwb_persistence.py: pure/mock-session
tests for control-flow (provider/engine/persistence failure propagation,
and bundle assembly's realignment logic), which always run with no
database; and live-Postgres tests for actual end-to-end orchestration and
persistence correctness (successful run, empty-data run), which skip
cleanly without Docker/PostGIS.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import pytest_asyncio
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.models.catchment import Catchment
from app.models.enums import DelineationMethod, StorageChangeBand, StressBand, UserRole
from app.models.evidence import EvidenceRecord, ValidationFinding, ValidationRun
from app.models.user import AppUser
from app.models.water_balance import RechargeStressScore, WaterBalanceResult
from app.services.hydrology.engine import WaterBalanceEngine
from app.services.hydrology.gee_hydrology_provider import GEEHydrologyProvider
from app.services.hydrology.recharge_stress import RechargeStressEngine
from app.services.hydrology.water_report_generator import _index_observations_to_monthly_values, generate_water_report
from app.services.satellite._gee_common import monthly_periods
from app.services.satellite.gee_provider import GeeProvider
from app.services.satellite.provider import IndexObservation
from tests.fakes.fake_hydrology_provider import FakeHydrologyDataProvider
from tests.fakes.fake_satellite_provider import FakeSatelliteDataProvider


class _DescribedSatellite(FakeSatelliteDataProvider, GeeProvider):
    """Fake data and constructor, but an instance of GeeProvider, so the
    described Earth Engine lineage path runs without credentials."""


class _DescribedHydrology(FakeHydrologyDataProvider, GEEHydrologyProvider):
    """Same, for the hydrology provider."""


_VALID_SQUARE = [(76.0, 18.0), (76.01, 18.0), (76.01, 18.01), (76.0, 18.01), (76.0, 18.0)]


# =====================================================================
# Bundle assembly — pure, no DB, no session, no mocks.
# =====================================================================


def test_bundle_assembly_fills_missing_periods_with_none_and_preserves_order():
    """SatelliteDataProvider omits a month with no usable pass entirely
    (its own "missing is missing" convention) — the helper must
    reconstruct the full expected timeline against `periods`, in order,
    with a None for exactly the omitted month, never dropping or
    reordering a present one."""
    periods = monthly_periods(date(2023, 1, 1), date(2023, 4, 1))  # Jan, Feb, Mar 2023
    observations = [
        IndexObservation(period_start=date(2023, 1, 1), period_end=date(2023, 2, 1), value=10.0),
        IndexObservation(period_start=date(2023, 3, 1), period_end=date(2023, 4, 1), value=30.0),
        # February deliberately absent.
    ]

    result = _index_observations_to_monthly_values(observations, periods)

    assert [mv.period_start for mv in result] == [date(2023, 1, 1), date(2023, 2, 1), date(2023, 3, 1)]
    assert [mv.value for mv in result] == [10.0, None, 30.0]


def test_bundle_assembly_returns_all_none_for_wholly_empty_observations():
    periods = monthly_periods(date(2023, 1, 1), date(2023, 4, 1))
    result = _index_observations_to_monthly_values([], periods)
    assert [mv.value for mv in result] == [None, None, None]


# =====================================================================
# Provider / engine / persistence failure — mock session, no live DB.
# =====================================================================


def _fake_catchment(*, resolution_flags: list[str] | None = None) -> Catchment:
    """An in-memory, never-persisted Catchment — from_shape()/to_shape()
    are pure client-side WKB conversions with no DB round trip, so this
    is a real, decodable geometry without touching Postgres."""
    return Catchment(
        id=uuid4(),
        name="Fake Catchment",
        geometry=from_shape(Polygon(_VALID_SQUARE), srid=4326),
        area_ha=100.0,
        delineation_method=DelineationMethod.MANUAL,
        resolution_flags=resolution_flags or [],
        created_by=uuid4(),
    )


def _mock_session(catchment: Catchment) -> AsyncMock:
    """Mirrors test_cgwb_persistence.py's own _mock_session() shape:
    `.add` and `.add_all` overridden to plain (non-async) Mocks, since the
    real AsyncSession.add()/add_all() are synchronous even on an async
    session."""
    session = AsyncMock()
    session.add = Mock()
    session.add_all = Mock()
    session.get = AsyncMock(return_value=catchment)
    return session


@pytest.mark.asyncio
async def test_provider_failure_propagates_and_persists_nothing():
    """A provider raising (real Earth Engine outage, quota error, etc.)
    must propagate unmodified — this orchestrator never catches or
    masks it — and nothing must have reached db.add() beforehand."""
    session = _mock_session(_fake_catchment())

    class _RaisingSatelliteProvider(FakeSatelliteDataProvider):
        def get_rainfall_series(self, geometry_geojson, start, end):
            raise RuntimeError("Earth Engine request failed")

    with pytest.raises(RuntimeError, match="Earth Engine request failed"):
        await generate_water_report(
            session,
            catchment_id=uuid4(),
            hydrology_provider=FakeHydrologyDataProvider(),
            satellite_provider=_RaisingSatelliteProvider(),
            water_balance_engine=WaterBalanceEngine(),
            recharge_stress_engine=RechargeStressEngine(),
        )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_engine_failure_propagates_and_persists_nothing():
    """WaterBalanceEngine/RechargeStressEngine's own validation errors
    (or any other engine-raised exception) must propagate unmodified,
    with nothing persisted — bundle assembly succeeding does not mean
    the run is committed."""
    session = _mock_session(_fake_catchment())
    failing_engine = Mock(spec=WaterBalanceEngine)
    failing_engine.compute.side_effect = ValueError("malformed bundle")

    with pytest.raises(ValueError, match="malformed bundle"):
        await generate_water_report(
            session,
            catchment_id=uuid4(),
            hydrology_provider=FakeHydrologyDataProvider(),
            satellite_provider=FakeSatelliteDataProvider(),
            water_balance_engine=failing_engine,
            recharge_stress_engine=RechargeStressEngine(),
        )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_persistence_failure_rolls_back_and_propagates():
    """A database failure while persisting (connection lost, constraint
    violation surfaced as SQLAlchemyError, etc.) must roll back and
    re-raise — the same discipline cgwb_persistence.py's
    upsert_cgwb_observations already establishes for a genuine
    database-layer failure, reused here."""
    session = _mock_session(_fake_catchment())
    session.commit = AsyncMock(side_effect=SQLAlchemyError("connection lost"))

    # Lineage and validation rows join the same transaction (Phase B), so a
    # failed commit must roll them back with the results rather than leave
    # them behind. The rows are added before the commit that fails.
    with pytest.raises(SQLAlchemyError):
        await generate_water_report(
            session,
            catchment_id=uuid4(),
            hydrology_provider=FakeHydrologyDataProvider(),
            satellite_provider=FakeSatelliteDataProvider(),
            water_balance_engine=WaterBalanceEngine(),
            recharge_stress_engine=RechargeStressEngine(),
        )

    session.rollback.assert_awaited_once()
    # Lineage and findings were in the failed transaction, so the rollback
    # covers them too — none can outlive the results they describe.
    # add: the two results and the two validation runs (findings ride on
    # their run). add_all: the two evidence batches.
    assert session.add.call_count == 4
    assert session.add_all.call_count == 2


@pytest.mark.asyncio
async def test_unknown_catchment_raises_and_persists_nothing():
    session = _mock_session(catchment=None)  # db.get() returns None

    with pytest.raises(ValueError, match="not found"):
        await generate_water_report(
            session,
            catchment_id=uuid4(),
            hydrology_provider=FakeHydrologyDataProvider(),
            satellite_provider=FakeSatelliteDataProvider(),
            water_balance_engine=WaterBalanceEngine(),
            recharge_stress_engine=RechargeStressEngine(),
        )

    session.add.assert_not_called()


# =====================================================================
# Successful orchestration / empty data — live Postgres, real persistence.
# =====================================================================


async def _database_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def catchment_fixture():
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
            resolution_flags=["et_sub_pixel"],
            created_by=officer.id,
        )
        db.add(catchment)
        await db.commit()
        await db.refresh(officer)
        await db.refresh(catchment)

    yield catchment

    async with AsyncSessionLocal() as db:
        # Lineage references results without a foreign key; clear it first
        # or deleting the results orphans it. Findings cascade from runs.
        result_ids = select(WaterBalanceResult.id).where(WaterBalanceResult.catchment_id == catchment.id).union(
            select(RechargeStressScore.id).where(RechargeStressScore.catchment_id == catchment.id)
        )
        await db.execute(delete(ValidationRun).where(ValidationRun.result_id.in_(result_ids)))
        await db.execute(delete(EvidenceRecord).where(EvidenceRecord.result_id.in_(result_ids)))
        await db.execute(delete(RechargeStressScore).where(RechargeStressScore.catchment_id == catchment.id))
        await db.execute(delete(WaterBalanceResult).where(WaterBalanceResult.catchment_id == catchment.id))
        await db.execute(delete(Catchment).where(Catchment.id == catchment.id))
        await db.execute(delete(AppUser).where(AppUser.id == officer.id))
        await db.commit()


@pytest.mark.asyncio
async def test_successful_orchestration_persists_both_results_and_returns_metadata(catchment_fixture):
    catchment = catchment_fixture

    async with AsyncSessionLocal() as db:
        metadata = await generate_water_report(
            db,
            catchment_id=catchment.id,
            hydrology_provider=FakeHydrologyDataProvider(),
            satellite_provider=FakeSatelliteDataProvider(),
            water_balance_engine=WaterBalanceEngine(),
            recharge_stress_engine=RechargeStressEngine(),
        )

    assert metadata.catchment_id == catchment.id
    assert metadata.water_balance_result_id is not None
    assert metadata.recharge_stress_score_id is not None
    assert metadata.period_start < metadata.period_end

    async with AsyncSessionLocal() as db:
        water_balance_row = await db.get(WaterBalanceResult, metadata.water_balance_result_id)
        recharge_stress_row = await db.get(RechargeStressScore, metadata.recharge_stress_score_id)

    assert water_balance_row is not None
    assert water_balance_row.catchment_id == catchment.id
    # resolution_flags copied through from the catchment at compute time,
    # per WaterBalanceBundle's own documented contract.
    assert water_balance_row.resolution_flags == ["et_sub_pixel"]
    assert water_balance_row.data_completeness > 0.0

    assert recharge_stress_row is not None
    assert recharge_stress_row.catchment_id == catchment.id
    # Named, flagged architecture decisions (module docstring points 2-3):
    # no CGWB spatial join, no real ConfigWeight row exists for this
    # factor set — both left at their nullable defaults, not fabricated.
    assert recharge_stress_row.cgwb_category is None
    assert recharge_stress_row.cgwb_category_as_of is None
    assert recharge_stress_row.weights_version_id is None


@pytest.mark.asyncio
async def test_empty_provider_data_still_produces_a_neutral_persisted_result(catchment_fixture):
    """Every provider returning nothing (a brand-new catchment with no
    usable history yet) must not crash the orchestrator — both engines
    already define a deterministic neutral fallback for this case; the
    orchestrator's job is to persist it honestly, not paper over it."""
    catchment = catchment_fixture
    all_missing = set(range(100))  # covers every period in any lookback window used here

    async with AsyncSessionLocal() as db:
        metadata = await generate_water_report(
            db,
            catchment_id=catchment.id,
            hydrology_provider=FakeHydrologyDataProvider(et_value=None, surface_water_percent=None),
            satellite_provider=FakeSatelliteDataProvider(missing_months=all_missing),
            water_balance_engine=WaterBalanceEngine(),
            recharge_stress_engine=RechargeStressEngine(),
        )

    assert metadata.storage_change_band == StorageChangeBand.NORMAL
    assert metadata.stress_band == StressBand.MODERATE  # neutral score (50) per each engine's own fallback

    async with AsyncSessionLocal() as db:
        water_balance_row = await db.get(WaterBalanceResult, metadata.water_balance_result_id)

    assert water_balance_row.data_completeness == 0.0
    assert water_balance_row.rainfall_mm is None
    assert water_balance_row.et_mm is None
    assert water_balance_row.runoff_mm is None
    assert water_balance_row.storage_change_mm is None


# =====================================================================
# Evidence provenance and validation (evidence-aware roadmap, Phase B)
# =====================================================================


@pytest.mark.asyncio
async def test_both_results_are_persisted_with_lineage_and_validation(catchment_fixture):
    catchment = catchment_fixture

    async with AsyncSessionLocal() as db:
        metadata = await generate_water_report(
            db,
            catchment_id=catchment.id,
            hydrology_provider=_DescribedHydrology(),
            satellite_provider=_DescribedSatellite(),
            water_balance_engine=WaterBalanceEngine(),
            recharge_stress_engine=RechargeStressEngine(),
        )

    async with AsyncSessionLocal() as db:
        evidence = (
            await db.execute(
                select(EvidenceRecord).where(
                    EvidenceRecord.result_id.in_([metadata.water_balance_result_id, metadata.recharge_stress_score_id])
                )
            )
        ).scalars().all()
        runs = (
            await db.execute(
                select(ValidationRun).where(
                    ValidationRun.result_id.in_([metadata.water_balance_result_id, metadata.recharge_stress_score_id])
                )
            )
        ).scalars().all()
        findings = (
            await db.execute(select(ValidationFinding).where(ValidationFinding.validation_run_id.in_([r.id for r in runs])))
        ).scalars().all()

    balance = {e.quantity: e for e in evidence if e.result_table == "water_balance_result"}
    stress = {e.quantity: e for e in evidence if e.result_table == "recharge_stress_score"}

    assert {"rainfall_monthly_mm", "rainfall_daily_mm", "et_monthly_mm", "curve_number", "closed_catchment_assumed"} <= set(balance)
    assert {"ndvi", "ndvi_baseline", "surface_water_percent", "surface_water_baseline", "rainfall_climatology_mm"} <= set(stress)
    assert balance["et_monthly_mm"].source == "MODIS/061/MOD16A2"
    assert balance["et_monthly_mm"].acquisition_dates is None  # not recorded, and stored as NULL, not []
    # The catchment's own sub-pixel flag reaches the lineage of its inputs.
    assert any("et_sub_pixel" in limitation for limitation in balance["et_monthly_mm"].known_limitations)

    assert {r.result_table for r in runs} == {"water_balance_result", "recharge_stress_score"}
    assert all(r.source == "pipeline" for r in runs)
    # The fake climatology is 80 mm x 12 months = 960 mm/yr.
    assert all(r.agro_climatic_zone == "sub_humid" for r in runs)
    # Findings persist, including INFO ones: a skipped check must stay
    # distinguishable from a passed one after it leaves memory.
    assert findings, "validation findings should be stored with their runs"


@pytest.mark.asyncio
async def test_lineage_is_not_persisted_when_the_result_is_not(catchment_fixture):
    """The same transaction, both ways: a commit that fails must take the
    lineage with it, not leave evidence describing a result that does not
    exist."""
    catchment = catchment_fixture

    async with AsyncSessionLocal() as db:
        async def _fail(*args, **kwargs):
            raise SQLAlchemyError("simulated commit failure")

        db.commit = _fail
        with pytest.raises(SQLAlchemyError):
            await generate_water_report(
                db,
                catchment_id=catchment.id,
                hydrology_provider=_DescribedHydrology(),
                satellite_provider=_DescribedSatellite(),
                water_balance_engine=WaterBalanceEngine(),
                recharge_stress_engine=RechargeStressEngine(),
            )

    async with AsyncSessionLocal() as db:
        results = (
            await db.execute(select(WaterBalanceResult).where(WaterBalanceResult.catchment_id == catchment.id))
        ).scalars().all()
        orphans = (
            await db.execute(select(EvidenceRecord).where(EvidenceRecord.source == "MODIS/061/MOD16A2"))
        ).scalars().all()
        orphan_ids = {e.result_id for e in orphans}
        existing = set((await db.execute(select(WaterBalanceResult.id))).scalars().all())

    assert results == []
    assert orphan_ids <= existing, "evidence rows exist for a water balance that was never persisted"
