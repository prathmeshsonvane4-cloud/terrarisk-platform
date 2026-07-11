"""Report generation orchestrator (Blueprint §01 Service 1 workflow):

    farm -> cached/fetched satellite observations -> ObservationBundle
    -> RiskEngine -> persisted RiskScore/RiskFactorScore -> Job completion

Runs as a FastAPI BackgroundTask (Blueprint §10 CTO review: no message
queue needed at MVP volume). Owns its own database session — background
tasks execute after the triggering request's response has already been
sent, so the request-scoped session is no longer valid to reuse.

Transaction strategy: satellite observations are persisted incrementally,
one series at a time, as soon as each is fetched — a later failure should
not discard genuinely valid, already-fetched data (a retry would otherwise
re-spend Earth Engine quota re-fetching it). The final RiskScore and its
RiskFactorScore rows are written as a single atomic transaction — a score
without its factor breakdown would be a broken, half-written result.

Rainfall climatology is deliberately not cached in v1: it is the cheapest
of the Earth Engine calls (one request, server-side aggregated across the
climatology window), and it represents a "normal," not a dated
observation — forcing it into the period-shaped satellite_observation
table would need an awkward convention for a small saving.

Async note: SatelliteDataProvider's methods are synchronous by design —
they mirror the underlying Earth Engine Python SDK, which performs
blocking network I/O with no async variant. Every call to a provider
method here is wrapped in asyncio.to_thread() so that a slow real GEE
request runs on a worker thread rather than blocking this process's
single event loop — without that, one farm's report generation would
stall every other concurrent request the API is serving for however long
that GEE call takes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from uuid import UUID

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import AsyncSessionLocal
from app.models.enums import JobStatus, RiskEntityType, RiskFactor, SatelliteIndexType
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.risk import ConfigWeight, RiskFactorScore, RiskScore
from app.models.satellite import SatelliteObservation
from app.services.risk.engine import RiskEngine
from app.services.risk.models import MonthlyValue, ObservationBundle, RiskEngineConfig
from app.services.satellite.gee_provider import _monthly_periods
from app.services.satellite.provider import IndexObservation, SatelliteDataProvider, SatelliteIndex

logger = logging.getLogger(__name__)

_INDEX_TO_SATELLITE_INDEX_TYPE: dict[SatelliteIndex, SatelliteIndexType] = {
    SatelliteIndex.NDVI: SatelliteIndexType.NDVI,
    SatelliteIndex.MNDWI: SatelliteIndexType.MNDWI,
    SatelliteIndex.NDMI: SatelliteIndexType.NDMI,
}

_GENERIC_FAILURE_MESSAGE = "Report generation failed. Please retry; contact support if this persists."


async def generate_farm_report(
    *,
    job_id: UUID,
    farm_id: UUID,
    lookback_years: int,
    satellite_provider: SatelliteDataProvider,
    risk_engine: RiskEngine,
) -> None:
    """Background-task entry point. Guarantees the job always reaches a
    terminal status (DONE or FAILED) — never left RUNNING forever, per the
    background-job requirement that no job may get stuck."""
    async with AsyncSessionLocal() as db:
        try:
            await _set_job_status(db, job_id, JobStatus.RUNNING)
            risk_score_id = await _run_pipeline(db, farm_id, lookback_years, satellite_provider, risk_engine)
            await _set_job_status(db, job_id, JobStatus.DONE, result_entity_id=risk_score_id)
        except Exception:
            # Full detail goes to the server log only; the job row (and
            # therefore the API) only ever exposes a generic message.
            logger.exception("report_generation_failed", extra={"job_id": str(job_id), "farm_id": str(farm_id)})
            await _set_job_status(db, job_id, JobStatus.FAILED, error_message=_GENERIC_FAILURE_MESSAGE)


async def _run_pipeline(
    db: AsyncSession,
    farm_id: UUID,
    lookback_years: int,
    satellite_provider: SatelliteDataProvider,
    risk_engine: RiskEngine,
) -> UUID:
    farm = await db.get(FarmPolygon, farm_id)
    if farm is None:
        raise ValueError(f"Farm {farm_id} not found")

    geometry_geojson = mapping(to_shape(farm.geometry))
    end = datetime.now(timezone.utc).date().replace(day=1)
    start = date(end.year - lookback_years, end.month, 1)
    periods = _monthly_periods(start, end)

    ndvi = await _get_or_fetch_index_series(db, farm_id, SatelliteIndex.NDVI, geometry_geojson, start, end, satellite_provider)
    mndwi = await _get_or_fetch_index_series(db, farm_id, SatelliteIndex.MNDWI, geometry_geojson, start, end, satellite_provider)
    ndmi = await _get_or_fetch_index_series(db, farm_id, SatelliteIndex.NDMI, geometry_geojson, start, end, satellite_provider)
    rainfall = await _get_or_fetch_rainfall_series(db, farm_id, geometry_geojson, start, end, satellite_provider)
    rainfall_normal_by_month = await asyncio.to_thread(satellite_provider.get_rainfall_climatology, geometry_geojson)
    water_history = await asyncio.to_thread(satellite_provider.get_water_history, geometry_geojson)

    bundle = ObservationBundle(
        ndvi_monthly=_to_monthly_values(ndvi, periods),
        mndwi_monthly=_to_monthly_values(mndwi, periods),
        ndmi_monthly=_to_monthly_values(ndmi, periods),
        rainfall_monthly=_to_monthly_values(rainfall, periods),
        rainfall_normal_by_month=rainfall_normal_by_month,
        jrc_water_occurrence_percent=water_history.occurrence_percent,
    )

    config_row = await _get_active_config_weight(db)
    config = RiskEngineConfig(
        weights={RiskFactor(k): v for k, v in config_row.weights.items()},
        floor_threshold=float(config_row.floor_thresholds["threshold"]),
        model_version=RiskEngine.MODEL_VERSION,
        weights_version_id=str(config_row.id),
    )

    result = risk_engine.compute(bundle, config)
    return await _persist_risk_result(db, farm_id, config_row.id, result)


async def _persist_risk_result(db: AsyncSession, farm_id: UUID, weights_version_id: UUID, result) -> UUID:
    """Single atomic transaction: a RiskScore is never left without its
    RiskFactorScore rows."""
    risk_score = RiskScore(
        entity_type=RiskEntityType.FARM,
        entity_id=farm_id,
        overall_score=result.overall_score,
        overall_band=result.overall_band,
        confidence=result.confidence,
        model_version=result.model_version,
        weights_version_id=weights_version_id,
        computed_at=datetime.now(timezone.utc),
    )
    db.add(risk_score)
    await db.flush()  # assigns risk_score.id for the factor rows below

    for factor_result in result.factors:
        db.add(
            RiskFactorScore(
                risk_score_id=risk_score.id,
                factor=factor_result.factor,
                value=factor_result.score,
                band=factor_result.band,
                raw_inputs=factor_result.raw_inputs,
            )
        )

    await db.commit()
    return risk_score.id


async def _get_or_fetch_index_series(
    db: AsyncSession,
    farm_id: UUID,
    index: SatelliteIndex,
    geometry_geojson: dict,
    start: date,
    end: date,
    provider: SatelliteDataProvider,
) -> list[IndexObservation]:
    index_type = _INDEX_TO_SATELLITE_INDEX_TYPE[index]
    cached = await _read_cached_observations(db, farm_id, index_type, start, end)
    if cached:
        return cached

    fetched = await asyncio.to_thread(provider.get_index_time_series, geometry_geojson, index, start, end)
    await _persist_observations(db, farm_id, index_type, fetched)
    return fetched


async def _get_or_fetch_rainfall_series(
    db: AsyncSession, farm_id: UUID, geometry_geojson: dict, start: date, end: date, provider: SatelliteDataProvider
) -> list[IndexObservation]:
    cached = await _read_cached_observations(db, farm_id, SatelliteIndexType.RAINFALL, start, end)
    if cached:
        return cached

    fetched = await asyncio.to_thread(provider.get_rainfall_series, geometry_geojson, start, end)
    await _persist_observations(db, farm_id, SatelliteIndexType.RAINFALL, fetched)
    return fetched


async def _read_cached_observations(
    db: AsyncSession, farm_id: UUID, index_type: SatelliteIndexType, start: date, end: date
) -> list[IndexObservation]:
    stmt = (
        select(SatelliteObservation)
        .where(
            SatelliteObservation.entity_type == RiskEntityType.FARM,
            SatelliteObservation.entity_id == farm_id,
            SatelliteObservation.index_type == index_type,
            SatelliteObservation.period_start >= start,
            SatelliteObservation.period_start < end,
        )
        .order_by(SatelliteObservation.period_start)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [IndexObservation(period_start=r.period_start, period_end=r.period_end, value=r.value) for r in rows]


async def _persist_observations(
    db: AsyncSession, farm_id: UUID, index_type: SatelliteIndexType, observations: list[IndexObservation]
) -> None:
    """Commits immediately — this data is valid regardless of what happens
    later in the pipeline, and a retry should not need to re-fetch it."""
    for observation in observations:
        db.add(
            SatelliteObservation(
                entity_type=RiskEntityType.FARM,
                entity_id=farm_id,
                index_type=index_type,
                period_start=observation.period_start,
                period_end=observation.period_end,
                value=observation.value,
                source_dates=[d.isoformat() for d in observation.source_scene_dates],
            )
        )
    await db.commit()


async def _get_active_config_weight(db: AsyncSession) -> ConfigWeight:
    now = datetime.now(timezone.utc)
    stmt = (
        select(ConfigWeight)
        .where(ConfigWeight.effective_from <= now)
        .order_by(ConfigWeight.effective_from.desc())
        .limit(1)
    )
    config = (await db.execute(stmt)).scalar_one_or_none()
    if config is None:
        raise RuntimeError(
            "No active risk-engine configuration found — run scripts/seed_default_config_weight.py"
        )
    return config


def _to_monthly_values(observations: list[IndexObservation], periods: list[tuple[date, date]]) -> list[MonthlyValue]:
    """Reconstructs the full expected timeline, filling any period with no
    observation as None. This must stay a full-length series (not a sparse
    list of only present values) — RiskEngine's confidence calculation
    depends on knowing how many months were *expected*, not just how many
    were present."""
    by_period_start = {obs.period_start: obs.value for obs in observations}
    return [MonthlyValue(period_start=p_start, value=by_period_start.get(p_start)) for p_start, _ in periods]


async def _set_job_status(
    db: AsyncSession,
    job_id: UUID,
    status: JobStatus,
    *,
    result_entity_id: UUID | None = None,
    error_message: str | None = None,
) -> None:
    job = await db.get(Job, job_id)
    if job is None:
        logger.error("job_not_found_during_status_update", extra={"job_id": str(job_id)})
        return
    job.status = status
    if result_entity_id is not None:
        job.entity_id = result_entity_id
    if error_message is not None:
        job.error_message = error_message
    await db.commit()
