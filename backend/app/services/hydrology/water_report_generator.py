"""Water Intelligence report orchestrator (ticket M5-001):

    catchment -> HydrologyDataProvider/SatelliteDataProvider calls ->
    WaterBalanceBundle/RechargeStressBundle -> WaterBalanceEngine/
    RechargeStressEngine -> persisted WaterBalanceResult/
    RechargeStressScore -> WaterReportMetadata

This is the orchestrator `WaterBalanceBundle`'s and `RechargeStressBundle`'s
own docstrings (`app/services/hydrology/models.py`, `recharge_stress.py`)
both name as "a later ticket, M5" — the thing
`app/api/catchments.py::_run_water_report_job` (ticket M4-006) discovered
was missing and failed the job over rather than fabricate. This ticket
builds exactly that piece and nothing else: `Do NOT: Modify APIs` means
`_run_water_report_job` is not touched here — wiring this function into
the job-status/BackgroundTasks lifecycle is a separate, later ticket, the
same way `report_generator.py::generate_farm_report` (the entry point,
owns Job/ProgressTracker) is a distinct layer from `_run_pipeline` (the
pure pipeline body). `generate_water_report()` below is that inner-pipeline
layer only — no `job_id`, no `Job`/`JobStatus` writes, no progress
tracking. It raises on any failure; a future caller wraps it in exactly
the try/except-then-set-FAILED shape `generate_farm_report` already uses.

Orchestrate only (this ticket's own first responsibility): every provider
call goes through the existing `HydrologyDataProvider`/`SatelliteDataProvider`
ABCs, both engines are called via their existing `compute(bundle, config)`
contracts, unmodified. No Earth Engine, band-math, or scoring logic lives
in this file.

ARCHITECTURE DECISIONS, FLAGGED — read before extending this module:

1. **No `SatelliteObservation` caching layer.** `report_generator.py`
   caches each fetched series incrementally (`_get_or_fetch_index_series`/
   `_get_or_fetch_rainfall_series`), and `RiskEntityType.CATCHMENT`
   already exists specifically so this table could be reused the same way
   for catchments (its own docstring says so). This ticket does not build
   that layer: none of the six required test scenarios need it, "orchestrate
   only" is this ticket's literal first responsibility, and adding an
   untested caching path now would be scope creep beyond what was asked.
   Every call here always fetches fresh. Recommended as its own follow-up
   ticket, not solved speculatively here.
2. **No CGWB category context.** `RechargeStressScore.cgwb_category`/
   `cgwb_category_as_of` are left `None`. Populating them needs a spatial
   join from a catchment to its containing CGWB block
   (`cgwb_groundwater_observation` has "no foreign key to catchment,
   deliberately... that lookup happens at score-computation time" per its
   own docstring) — that join does not exist anywhere in this codebase
   yet. `cgwb_persistence.py` (named in this ticket's "reuse existing
   persistence") has nothing to reuse for this: its only function,
   `upsert_cgwb_observations`, is an ingestion write path, not a
   catchment-to-block lookup. Inventing that join now would be new
   business logic, not reuse — left as a named, honest gap, not a
   silent one.
3. **No real `weights_version_id` FK value.** `RechargeStressConfig`
   (the engine's own config type) takes a plain `str` for its own
   record-keeping; `RechargeStressScore.weights_version_id` (the ORM
   column) is a real, nullable FK to `config_weight.id`. No
   `ConfigWeight` row anywhere in this codebase carries
   `RechargeStressFactor`-keyed weights (every existing row is
   `RiskFactor`-keyed, for `RiskEngine`) — inventing one here would mean
   seeding/migration work outside "orchestrate only." A fixed, named
   equal-weighting (`_DEFAULT_RECHARGE_STRESS_WEIGHTS` below) is used —
   the same "named literature/MVP default, not locally calibrated"
   discipline `engine.py`'s own `_CURVE_NUMBER` already establishes — and
   the persisted `weights_version_id` column is left `None`, exactly as
   `RechargeStressScore`'s own docstring already anticipates ("this
   ticket only creates the schema — no engine populates this table yet").
4. **`SurfaceWaterMethod.COMBINED`** is used for
   `RechargeStressBundle.surface_water_monthly` — Blueprint v2 Part 4's
   named methodology ("SAR primary, MNDWI secondary confirmation"), which
   `GEEHydrologyProvider`'s own `COMBINED` branch already implements by
   returning the SAR series and logging an MNDWI agreement signal
   separately. Calling it here, rather than `.SAR` directly, is the one
   call that gets both the reported number and that QA signal for free.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catchment import Catchment
from app.models.enums import BaselineWindow, StorageChangeBand, StressBand
from app.models.water_balance import RechargeStressScore, WaterBalanceResult
from app.services.hydrology.engine import WaterBalanceEngine
from app.services.hydrology.models import WaterBalanceBundle, WaterBalanceConfig
from app.services.hydrology.provider import HydrologyDataProvider, SurfaceWaterMethod
from app.services.hydrology.recharge_stress import (
    RechargeStressBundle,
    RechargeStressConfig,
    RechargeStressEngine,
    RechargeStressFactor,
)
from app.services.risk.models import MonthlyValue
from app.services.risk.seasonal import BASELINE_YEARS
from app.services.satellite._gee_common import monthly_periods
from app.services.satellite.provider import IndexObservation, SatelliteDataProvider, SatelliteIndex

logger = logging.getLogger(__name__)

# See module docstring, point 3 — a named MVP default, not locally
# calibrated, mirroring engine.py's own _CURVE_NUMBER discipline. Equal
# thirds: no methodology document (Blueprint v2 D6) names a non-uniform
# weighting for these three factors, so none is invented here.
_DEFAULT_RECHARGE_STRESS_WEIGHTS: dict[RechargeStressFactor, float] = {
    RechargeStressFactor.RAINFALL_ANOMALY: 1.0 / 3,
    RechargeStressFactor.VEGETATION_CONDITION: 1.0 / 3,
    RechargeStressFactor.SURFACE_WATER_TREND: 1.0 / 3,
}
# A caller-facing label only (the engine's own record-keeping field) —
# never written to RechargeStressScore.weights_version_id, which is a
# real, nullable FK left None (see module docstring, point 3).
_DEFAULT_RECHARGE_STRESS_WEIGHTS_LABEL = "recharge-stress-equal-weights-v1"

_DEFAULT_LOOKBACK_YEARS = 3


@dataclass(frozen=True)
class WaterReportMetadata:
    """This orchestrator's only return shape — enough for a caller to
    locate both persisted rows and show a headline without a second
    query, mirroring `ReportTriggerResponse`'s "just enough to route/
    display" scope."""

    catchment_id: UUID
    water_balance_result_id: UUID
    recharge_stress_score_id: UUID
    period_start: date
    period_end: date
    computed_at: datetime
    storage_change_band: StorageChangeBand
    stress_band: StressBand


async def generate_water_report(
    db: AsyncSession,
    *,
    catchment_id: UUID,
    hydrology_provider: HydrologyDataProvider,
    satellite_provider: SatelliteDataProvider,
    water_balance_engine: WaterBalanceEngine,
    recharge_stress_engine: RechargeStressEngine,
    lookback_years: int = _DEFAULT_LOOKBACK_YEARS,
) -> WaterReportMetadata:
    """Run one catchment's water-balance + recharge-stress pipeline and
    persist both results. Raises on any failure (unknown catchment,
    provider error, engine validation error, or a database failure while
    persisting) — never swallows an exception into a partial/fabricated
    result. A database failure specifically triggers a rollback before
    re-raising, so a half-written pair of results can never linger (see
    `_persist_results` below).
    """
    catchment = await db.get(Catchment, catchment_id)
    if catchment is None:
        raise ValueError(f"Catchment {catchment_id} not found")

    geometry_geojson = mapping(to_shape(catchment.geometry))
    end = datetime.now(timezone.utc).date().replace(day=1)
    start = date(end.year - lookback_years, end.month, 1)
    periods = monthly_periods(start, end)

    water_balance_bundle, recharge_stress_bundle = await _assemble_bundles(
        catchment, geometry_geojson, start, end, periods, hydrology_provider, satellite_provider
    )

    water_balance_result = water_balance_engine.compute(
        water_balance_bundle, WaterBalanceConfig(model_version=WaterBalanceEngine.MODEL_VERSION)
    )
    recharge_stress_result = recharge_stress_engine.compute(
        recharge_stress_bundle,
        RechargeStressConfig(
            weights=_DEFAULT_RECHARGE_STRESS_WEIGHTS, weights_version_id=_DEFAULT_RECHARGE_STRESS_WEIGHTS_LABEL
        ),
    )

    computed_at = datetime.now(timezone.utc)
    water_balance_row, recharge_stress_row = await _persist_results(
        db, catchment_id, start, end, computed_at, water_balance_result, recharge_stress_result
    )

    return WaterReportMetadata(
        catchment_id=catchment_id,
        water_balance_result_id=water_balance_row.id,
        recharge_stress_score_id=recharge_stress_row.id,
        period_start=start,
        period_end=end,
        computed_at=computed_at,
        storage_change_band=water_balance_result.storage_change_band,
        stress_band=recharge_stress_result.stress_band,
    )


async def _assemble_bundles(
    catchment: Catchment,
    geometry_geojson: dict,
    start: date,
    end: date,
    periods: list[tuple[date, date]],
    hydrology_provider: HydrologyDataProvider,
    satellite_provider: SatelliteDataProvider,
) -> tuple[WaterBalanceBundle, RechargeStressBundle]:
    """Every provider call wrapped in `asyncio.to_thread()` — both
    provider ABCs are synchronous by design (they wrap the Earth Engine
    Python SDK, which has no async variant), the identical reasoning
    `report_generator.py`'s own module docstring already states, applied
    here unchanged rather than re-justified. Provider/network failures
    propagate unmodified; nothing here catches them (see this ticket's
    "Provider failure" test)."""
    rainfall_observations = await asyncio.to_thread(satellite_provider.get_rainfall_series, geometry_geojson, start, end)
    # Daily depths for the SCS-CN runoff term only; the P and dS terms
    # still use the monthly series above. Both read the same CHIRPS
    # product at the same scale — see WaterBalanceBundle.rainfall_daily
    # for why the runoff term cannot use the monthly totals.
    rainfall_daily = await asyncio.to_thread(
        satellite_provider.get_daily_rainfall_series, geometry_geojson, start, end
    )
    rainfall_normal_by_month = await asyncio.to_thread(satellite_provider.get_rainfall_climatology, geometry_geojson)
    ndvi_observations = await asyncio.to_thread(
        satellite_provider.get_index_time_series, geometry_geojson, SatelliteIndex.NDVI, start, end
    )
    et_monthly = await asyncio.to_thread(hydrology_provider.get_et_series, geometry_geojson, start, end)
    surface_water_monthly = await asyncio.to_thread(
        hydrology_provider.get_surface_water_extent_series,
        geometry_geojson,
        start,
        end,
        SurfaceWaterMethod.COMBINED,
    )

    # Multi-year climatological baselines for the two seasonal factors.
    # Fetched as their own longer window rather than by widening the
    # series above: the report's displayed period, its data-completeness
    # figure and the water balance all describe the 3-year window, and
    # stretching those to 8 years to serve a comparison would silently
    # change what the report claims to be about.
    baseline_start = start.replace(year=start.year - BASELINE_YEARS)
    ndvi_baseline_observations = await asyncio.to_thread(
        satellite_provider.get_index_time_series, geometry_geojson, SatelliteIndex.NDVI, baseline_start, end
    )
    surface_water_baseline = await asyncio.to_thread(
        hydrology_provider.get_surface_water_extent_series,
        geometry_geojson,
        baseline_start,
        end,
        SurfaceWaterMethod.COMBINED,
    )
    baseline_periods = monthly_periods(baseline_start, end)

    rainfall_monthly = _index_observations_to_monthly_values(rainfall_observations, periods)

    water_balance_bundle = WaterBalanceBundle(
        period_start=start,
        period_end=end,
        rainfall_monthly=rainfall_monthly,
        et_monthly=et_monthly,
        rainfall_daily=rainfall_daily,
        resolution_flags=list(catchment.resolution_flags),
    )
    recharge_stress_bundle = RechargeStressBundle(
        rainfall_monthly=rainfall_monthly,
        rainfall_normal_by_month=rainfall_normal_by_month,
        ndvi_monthly=_index_observations_to_monthly_values(ndvi_observations, periods),
        surface_water_monthly=surface_water_monthly,
        ndvi_baseline=_index_observations_to_monthly_values(ndvi_baseline_observations, baseline_periods),
        surface_water_baseline=surface_water_baseline,
        baseline_window=BaselineWindow.CLIMATOLOGY_30YR,
    )
    return water_balance_bundle, recharge_stress_bundle


def _index_observations_to_monthly_values(
    observations: list[IndexObservation], periods: list[tuple[date, date]]
) -> list[MonthlyValue]:
    """Reconstructs the full expected timeline against `periods`, filling
    any period `SatelliteDataProvider` omitted (its own documented
    "missing is missing" convention — a month is left out, not returned
    as a false zero) as `MonthlyValue(value=None)`. Identical shape and
    reasoning to `report_generator.py::_to_monthly_values` — copied, not
    reimplemented differently, because `HydrologyDataProvider`'s own
    methods already return pre-aligned, full-length `MonthlyValue` lists
    (its contract promises one entry per period, `None` for a missing
    one) and need no equivalent reconciliation step here.
    """
    by_period_start = {obs.period_start: obs.value for obs in observations}
    return [MonthlyValue(period_start=p_start, value=by_period_start.get(p_start)) for p_start, _ in periods]


async def _persist_results(
    db: AsyncSession,
    catchment_id: UUID,
    start: date,
    end: date,
    computed_at: datetime,
    water_balance_result,
    recharge_stress_result,
) -> tuple[WaterBalanceResult, RechargeStressScore]:
    """Both rows in one transaction — a water-balance result and its
    sibling recharge-stress score for the same run are never left
    half-written, the same "a result is never left without its
    companion row" discipline `report_generator.py::_persist_risk_result`
    already applies to RiskScore/RiskFactorScore. On any SQLAlchemy
    failure, rolls back and re-raises rather than leaving a half-added
    session — the exact rollback-and-reraise shape
    `cgwb_persistence.py::upsert_cgwb_observations` already establishes
    for a genuine database-layer failure, reused here (this ticket's
    "reuse existing persistence" applied to error handling, not just the
    happy path)."""
    water_balance_row = WaterBalanceResult(
        catchment_id=catchment_id,
        period_start=start,
        period_end=end,
        rainfall_mm=water_balance_result.rainfall_mm,
        et_mm=water_balance_result.et_mm,
        runoff_mm=water_balance_result.runoff_mm,
        storage_change_mm=water_balance_result.storage_change_mm,
        storage_change_band=water_balance_result.storage_change_band,
        data_completeness=water_balance_result.data_completeness,
        calibration_status=water_balance_result.calibration_status,
        closed_catchment_assumed=water_balance_result.closed_catchment_assumed,
        resolution_flags=water_balance_result.resolution_flags,
        model_version=water_balance_result.model_version,
        computed_at=computed_at,
    )
    recharge_stress_row = RechargeStressScore(
        catchment_id=catchment_id,
        computed_at=computed_at,
        stress_score=recharge_stress_result.stress_score,
        stress_band=recharge_stress_result.stress_band,
        baseline_window=recharge_stress_result.baseline_window,
        rainfall_anomaly_ratio=recharge_stress_result.rainfall_anomaly_ratio,
        vci=recharge_stress_result.vci,
        surface_water_trend=recharge_stress_result.surface_water_trend,
        # cgwb_category/cgwb_category_as_of/weights_version_id all left at
        # their nullable defaults (None) — see module docstring, points 2-3.
        raw_inputs=recharge_stress_result.raw_inputs,
    )

    try:
        db.add(water_balance_row)
        db.add(recharge_stress_row)
        await db.flush()
        await db.commit()
    except SQLAlchemyError:
        logger.error(
            "water_report_persist_failed",
            extra={"catchment_id": str(catchment_id)},
        )
        await db.rollback()
        raise

    return water_balance_row, recharge_stress_row
