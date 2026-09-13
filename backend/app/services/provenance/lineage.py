"""Evidence lineage for every result — pure, zero I/O.

Turns "what the pipeline did" into `EvidenceItem`s: one per remote-sensing
series a result consumed, and one per method parameter it assumed. The
orchestrators persist them (`persistence.py`) in the same transaction as
the result, so a result can never exist without its lineage.

WHY THE DESCRIPTIONS IMPORT THE PROVIDERS' OWN CONSTANTS
--------------------------------------------------------
The scale, threshold, Curve Number and collection id recorded here are
imported from the modules that actually use them, never restated. A
lineage record that says "reduced at 500 m" while the provider reduces at
1000 m is worse than no record, because it is believed. If a provider
changes a value, the lineage changes with it.

WHY LINEAGE IS KEYED ON THE PROVIDER'S TYPE
-------------------------------------------
How a number was produced — scale, reducer, masking, compositing — is a
property of the provider implementation, not of the abstract interface.
The descriptions below are only true of the Earth Engine providers. Any
other provider gets a record that says its lineage is not described,
rather than borrowing the Earth Engine description and being wrong.

WHAT IS NOT RECORDED, AND SAYS SO
---------------------------------
`HydrologyDataProvider` returns bare `MonthlyValue`s, so the MODIS
composite dates and Sentinel-1 pass dates behind ET and surface water are
not available here. Those records carry `acquisition_dates=None` — "not
recorded" — plus a limitation saying so, never an empty list (which would
mean "there were none").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.enums import EvidenceKind, EvidenceValidation
from app.services.hydrology import engine as water_balance_engine
from app.services.hydrology import gee_hydrology_provider as hydro
from app.services.hydrology import recharge_stress
from app.services.risk import engine as risk_engine
from app.services.risk.models import MonthlyValue
from app.services.risk.seasonal import BASELINE_YEARS, MIN_BASELINE_SAMPLES
from app.services.satellite import _gee_common
from app.services.satellite import gee_provider as gee
from app.services.satellite.provider import IndexObservation, SatelliteIndex
from app.services.validation.ingestion import DELIVERED_SERIES
from app.services.validation.products import spec_for

__all__ = [
    "EvidenceItem",
    "recharge_stress_evidence",
    "risk_score_evidence",
    "water_balance_evidence",
]

_UNDESCRIBED = "Lineage for this provider is not described; how these values were produced is not traceable."


@dataclass(frozen=True)
class EvidenceItem:
    """One input to one result. Maps field-for-field onto
    `app.models.evidence.EvidenceRecord`, minus the result keys."""

    kind: EvidenceKind
    quantity: str
    source: str
    units: str
    product_version: str | None = None
    band: str | None = None
    value: float | None = None
    native_resolution_m: float | None = None
    requested_scale_m: float | None = None
    resampled: bool | None = None
    reducer: str | None = None
    temporal_aggregation: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    observations_expected: int | None = None
    observations_used: int | None = None
    # None = not recorded; [] = recorded, none. Never conflate.
    acquisition_dates: list[str] | None = None
    retrieval: str | None = None
    known_limitations: list[str] = field(default_factory=list)
    validation_status: EvidenceValidation = EvidenceValidation.UNVALIDATED
    spec_verified_on: date | None = None


# ---------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------
def _observation(
    *,
    quantity: str,
    collection_id: str,
    band: str,
    requested_scale_m: float,
    reducer: str,
    temporal_aggregation: str,
    period_start: date,
    period_end: date,
    observations_expected: int,
    observations_used: int,
    acquisition_dates: list[str] | None,
    retrieval: str | None,
    extra_limitations: list[str] | None = None,
) -> EvidenceItem:
    spec = spec_for(collection_id)
    limitations: list[str] = []
    if spec is None:
        limitations.append(f"{collection_id} is not in the product registry; its specification is unaudited.")
    else:
        if spec.geographic_limitations:
            limitations.append(spec.geographic_limitations)
        limitations.extend(f"Open defect: {defect}" for defect in spec.known_defects)
    if acquisition_dates is None:
        limitations.append(
            "Acquisition dates are not recorded for this series: the provider interface does not return them."
        )
    limitations.extend(extra_limitations or [])

    native = spec.native_resolution_m if spec else None
    expectation = DELIVERED_SERIES.get(quantity)
    return EvidenceItem(
        kind=EvidenceKind.OBSERVATION,
        quantity=quantity,
        source=collection_id,
        product_version=spec.product_version if spec else None,
        band=band,
        units=expectation.units if expectation else "unrecorded",
        native_resolution_m=native,
        requested_scale_m=float(requested_scale_m),
        resampled=None if native is None else abs(native - requested_scale_m) > 0.5,
        reducer=reducer,
        temporal_aggregation=temporal_aggregation,
        period_start=period_start,
        period_end=period_end,
        observations_expected=observations_expected,
        observations_used=min(observations_used, observations_expected),
        acquisition_dates=acquisition_dates,
        retrieval=retrieval,
        known_limitations=limitations,
        spec_verified_on=spec.verified_on if spec else None,
    )


def _undescribed(quantity: str, provider: object, period_start: date | None, period_end: date | None) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.OBSERVATION,
        quantity=quantity,
        source=f"{type(provider).__name__} (lineage not described)",
        units=DELIVERED_SERIES[quantity].units if quantity in DELIVERED_SERIES else "unrecorded",
        period_start=period_start,
        period_end=period_end,
        known_limitations=[_UNDESCRIBED],
    )


def _parameter(
    quantity: str, source: str, units: str, value: float | None, limitations: list[str]
) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.PARAMETER,
        quantity=quantity,
        source=source,
        units=units,
        value=value,
        known_limitations=limitations,
    )


def _used(series: list[MonthlyValue]) -> int:
    return sum(1 for m in series if m.value is not None)


def _scene_dates(observations: list[IndexObservation]) -> list[str]:
    """Every Sentinel-2 acquisition date that fed any month, sorted and
    de-duplicated. An empty list here means scenes were looked for and
    none were recorded — a recorded fact, unlike None."""
    return sorted({d.isoformat() for obs in observations for d in obs.source_scene_dates})


def _index_evidence(
    quantity: str,
    index: SatelliteIndex,
    observations: list[IndexObservation],
    monthly: list[MonthlyValue],
    period_start: date,
    period_end: date,
    retrieval: str | None,
    satellite_provider: object,
    purpose: str,
) -> EvidenceItem:
    if not isinstance(satellite_provider, gee.GeeProvider):
        return _undescribed(quantity, satellite_provider, period_start, period_end)
    numerator, denominator = gee._INDEX_BANDS[index]
    extra = []
    if "B11" in (numerator, denominator):
        extra.append("Uses B11 (SWIR1), natively 20 m: effective resolution is 20 m despite reduction at 10 m.")
    if retrieval == "cache":
        extra.append(
            "Reused from a previous retrieval rather than fetched for this result; values are as of that retrieval."
        )
    return _observation(
        quantity=quantity,
        collection_id=_gee_common.SENTINEL2_COLLECTION,
        band=f"({numerator} - {denominator}) / ({numerator} + {denominator})",
        requested_scale_m=gee._INDEX_SCALE_METERS,
        reducer="mean over polygon of the monthly composite",
        temporal_aggregation=(
            f"{purpose}. Per scene: pixels masked where s2cloudless probability >= "
            f"{_gee_common.CLOUD_PROBABILITY_THRESHOLD}; per calendar month: mean of the masked scenes."
        ),
        period_start=period_start,
        period_end=period_end,
        observations_expected=len(monthly),
        observations_used=_used(monthly),
        acquisition_dates=_scene_dates(observations),
        retrieval=retrieval,
        extra_limitations=extra,
    )


def _rainfall_monthly_evidence(
    monthly: list[MonthlyValue], start: date, end: date, retrieval: str | None, satellite_provider: object
) -> EvidenceItem:
    if not isinstance(satellite_provider, gee.GeeProvider):
        return _undescribed("rainfall_monthly_mm", satellite_provider, start, end)
    extra = [
        "The most recent month is provisional: CHIRPS revises recent data after first publication, "
        "and a figure can rise substantially between releases."
    ]
    if retrieval == "cache":
        extra.append(
            "Reused from a previous retrieval. A cached provisional month is not refreshed when CHIRPS "
            "revises it, so this value may be stale."
        )
    return _observation(
        quantity="rainfall_monthly_mm",
        collection_id=gee._CHIRPS_COLLECTION,
        band="precipitation",
        requested_scale_m=gee._CHIRPS_SCALE_METERS,
        reducer="mean over polygon of the monthly total",
        temporal_aggregation="Sum of daily images per calendar month; no negative-value filter on this path.",
        period_start=start,
        period_end=end,
        observations_expected=len(monthly),
        observations_used=_used(monthly),
        # Daily product: every day in each month is an input, so a date
        # list would carry no information beyond the period itself.
        acquisition_dates=None,
        retrieval=retrieval,
        extra_limitations=extra,
    )


def _climatology_evidence(normals: dict[int, float], satellite_provider: object, computed_in_year: int) -> EvidenceItem:
    """The 30-year monthly normal. The window is derived the way
    `GeeProvider.get_rainfall_climatology` derives it: the last complete
    calendar year, back 30 years."""
    end_year = computed_in_year - 1
    start_year = end_year - gee._CLIMATOLOGY_WINDOW_YEARS + 1
    start, end = date(start_year, 1, 1), date(end_year, 12, 31)
    if not isinstance(satellite_provider, gee.GeeProvider):
        return _undescribed("rainfall_monthly_mm", satellite_provider, start, end)
    item = _observation(
        quantity="rainfall_monthly_mm",
        collection_id=gee._CHIRPS_COLLECTION,
        band="precipitation",
        requested_scale_m=gee._CHIRPS_SCALE_METERS,
        reducer="mean over polygon of each year's monthly total",
        temporal_aggregation=(
            f"Climatological normal: for each calendar month, the mean of that month's total across "
            f"{gee._CLIMATOLOGY_WINDOW_YEARS} years ({start_year}-{end_year})."
        ),
        period_start=start,
        period_end=end,
        observations_expected=12,
        observations_used=len(normals),
        acquisition_dates=None,
        retrieval="fetched",
    )
    # Distinct quantity name, same units, so the report can tell the
    # normal apart from the observed series.
    return EvidenceItem(**{**item.__dict__, "quantity": "rainfall_climatology_mm"})


# ---------------------------------------------------------------------
# Water Intelligence
# ---------------------------------------------------------------------
def water_balance_evidence(
    *,
    rainfall_monthly: list[MonthlyValue],
    rainfall_daily: list[MonthlyValue],
    et_monthly: list[MonthlyValue],
    start: date,
    end: date,
    resolution_flags: list[str],
    satellite_provider: object,
    hydrology_provider: object,
) -> list[EvidenceItem]:
    """Lineage for one `WaterBalanceResult`: P, daily P (runoff), ET, and
    every parameter the P - ET - Q = dS method assumes."""
    location_limits = [f"Catchment flagged {flag}." for flag in resolution_flags]
    items: list[EvidenceItem] = []

    rainfall = _rainfall_monthly_evidence(rainfall_monthly, start, end, "fetched", satellite_provider)
    items.append(EvidenceItem(**{**rainfall.__dict__, "known_limitations": [*rainfall.known_limitations, *location_limits]}))

    if isinstance(satellite_provider, gee.GeeProvider):
        items.append(
            _observation(
                quantity="rainfall_daily_mm",
                collection_id=gee._CHIRPS_COLLECTION,
                band="precipitation",
                requested_scale_m=gee._CHIRPS_SCALE_METERS,
                reducer="mean over polygon of each daily image",
                temporal_aggregation=(
                    "One value per published day; negative values dropped as no-data. Used only for the "
                    "runoff term, one SCS-CN storm event per rainy day."
                ),
                period_start=start,
                period_end=end,
                observations_expected=(end - start).days,
                observations_used=len(rainfall_daily),
                acquisition_dates=None,
                retrieval="fetched",
                extra_limitations=location_limits,
            )
        )
    else:
        items.append(_undescribed("rainfall_daily_mm", satellite_provider, start, end))

    if isinstance(hydrology_provider, hydro.GEEHydrologyProvider):
        items.append(
            _observation(
                quantity="et_monthly_mm",
                collection_id=hydro._MODIS_ET_COLLECTION,
                band=hydro._ET_BAND,
                requested_scale_m=hydro._ET_SCALE_METERS,
                reducer="mean over polygon of the monthly composite",
                temporal_aggregation=(
                    f"Per 8-day composite: stored value <= {hydro._ET_VALID_MAX} kept, scaled by "
                    f"{hydro._ET_SCALE_FACTOR}. Per calendar month: mean of the composites starting in that "
                    f"month, multiplied by (days in month / {hydro._ET_COMPOSITE_DAYS:g}) to convert mm per "
                    "8-day window into a monthly total."
                ),
                period_start=start,
                period_end=end,
                observations_expected=len(et_monthly),
                observations_used=_used(et_monthly),
                acquisition_dates=None,
                retrieval="fetched",
                extra_limitations=[
                    "A composite that straddles a month boundary is attributed wholly to the month it starts in.",
                    *location_limits,
                ],
            )
        )
    else:
        items.append(_undescribed("et_monthly_mm", hydrology_provider, start, end))

    engine_source = "app/services/hydrology/engine.py"
    cn = water_balance_engine._CURVE_NUMBER
    items.extend(
        [
            _parameter(
                "curve_number",
                engine_source,
                "dimensionless",
                cn,
                [
                    f"NRCS TR-55 table value (row crops, good condition, Hydrologic Soil Group D), fixed at {cn:g} "
                    "for every catchment. Not calibrated against observed runoff anywhere.",
                    "No antecedent moisture adjustment: late-monsoon runoff is underestimated.",
                ],
            ),
            _parameter(
                "initial_abstraction_ratio",
                engine_source,
                "dimensionless",
                water_balance_engine._INITIAL_ABSTRACTION_RATIO,
                ["Standard SCS value. Much Indian rainfall-runoff literature fits ~0.05 better, which would raise runoff."],
            ),
            _parameter(
                "storage_change_band_thresholds_mm",
                engine_source,
                "mm",
                None,
                [
                    "Fixed bounds "
                    + ", ".join(f"{b.value} <= {v:g}" for v, b in water_balance_engine._STORAGE_CHANGE_BAND_THRESHOLDS)
                    + " — not climatology-relative, despite the band vocabulary implying comparison with normal."
                ],
            ),
            _parameter(
                "closed_catchment_assumed",
                engine_source,
                "boolean",
                1.0,
                [
                    "No lateral groundwater or irrigation-import term. Storage change is the residual and absorbs "
                    "any water the catchment imports or exports."
                ],
            ),
        ]
    )
    return items


def recharge_stress_evidence(
    *,
    rainfall_monthly: list[MonthlyValue],
    rainfall_normals: dict[int, float],
    ndvi_observations: list[IndexObservation],
    ndvi_monthly: list[MonthlyValue],
    ndvi_baseline_observations: list[IndexObservation],
    ndvi_baseline: list[MonthlyValue],
    surface_water_monthly: list[MonthlyValue],
    surface_water_baseline: list[MonthlyValue],
    start: date,
    end: date,
    baseline_start: date,
    weights: dict,
    computed_in_year: int,
    resolution_flags: list[str],
    satellite_provider: object,
    hydrology_provider: object,
) -> list[EvidenceItem]:
    """Lineage for one `RechargeStressScore`."""
    items = [
        _rainfall_monthly_evidence(rainfall_monthly, start, end, "fetched", satellite_provider),
        _climatology_evidence(rainfall_normals, satellite_provider, computed_in_year),
        _index_evidence(
            "ndvi", SatelliteIndex.NDVI, ndvi_observations, ndvi_monthly, start, end, "fetched",
            satellite_provider, "Report window",
        ),
        EvidenceItem(
            **{
                **_index_evidence(
                    "ndvi", SatelliteIndex.NDVI, ndvi_baseline_observations, ndvi_baseline, baseline_start, end,
                    "fetched", satellite_provider,
                    f"Seasonal baseline ({BASELINE_YEARS} years before the window, plus the window)",
                ).__dict__,
                "quantity": "ndvi_baseline",
            }
        ),
    ]

    for quantity, series, period_start in (
        ("surface_water_percent", surface_water_monthly, start),
        ("surface_water_baseline", surface_water_baseline, baseline_start),
    ):
        if not isinstance(hydrology_provider, hydro.GEEHydrologyProvider):
            items.append(_undescribed("surface_water_percent", hydrology_provider, period_start, end))
            continue
        item = _observation(
            quantity="surface_water_percent",
            collection_id=hydro._SENTINEL1_GRD_COLLECTION,
            band=hydro._SAR_VV_BAND,
            requested_scale_m=hydro._SURFACE_WATER_SCALE_METERS,
            reducer="mean of a 0/1 water mask over polygon, x100",
            temporal_aggregation=(
                "Per calendar month: VV converted dB -> linear power, averaged, converted back to dB; pixel "
                f"classified water where the composite is below {hydro._SAR_VV_WATER_THRESHOLD_DB:g} dB. "
                "Sentinel-2 MNDWI is computed alongside for a logged agreement check only; it does not "
                "change this value."
            ),
            period_start=period_start,
            period_end=end,
            observations_expected=len(series),
            observations_used=_used(series),
            acquisition_dates=None,
            retrieval="fetched",
            extra_limitations=[
                "Surface water below ~0.2-0.3 ha is below reliable detection.",
                "High-relief terrain degrades the fixed threshold; this catchment's relief is NOT assessed "
                "because no DEM is read.",
                *(f"Catchment flagged {flag}." for flag in resolution_flags),
            ],
        )
        items.append(EvidenceItem(**{**item.__dict__, "quantity": quantity}))

    source = "app/services/hydrology/recharge_stress.py"
    items.extend(
        [
            _parameter(
                "recharge_stress_weights",
                "app/services/hydrology/water_report_generator.py",
                "dimensionless",
                None,
                [
                    "Factor weights "
                    + ", ".join(f"{getattr(k, 'value', k)}={v:.3f}" for k, v in weights.items())
                    + ". Equal weighting: no methodology document specifies otherwise and none was calibrated."
                ],
            ),
            _parameter(
                "neutral_score_when_uncomputable",
                source,
                "score (0-100)",
                float(recharge_stress._NEUTRAL_SCORE),
                [
                    "A factor that cannot be computed (missing data, too few baseline samples) is scored "
                    f"{recharge_stress._NEUTRAL_SCORE:g} and averaged in at full weight, as if it were a "
                    "measurement. Known defect, scheduled for the confidence/sufficiency work."
                ],
            ),
            _parameter(
                "baseline_years",
                "app/services/risk/seasonal.py",
                "years",
                float(BASELINE_YEARS),
                ["Bounded by Sentinel-2 L2A availability from ~2017; below the 10+ years VCI conventionally wants."],
            ),
            _parameter(
                "min_baseline_samples",
                "app/services/risk/seasonal.py",
                "samples per calendar month",
                float(MIN_BASELINE_SAMPLES),
                ["Below this, the seasonal factor is treated as uncomputable (and then scored neutral)."],
            ),
            _parameter(
                "sar_vv_water_threshold_db",
                "app/services/hydrology/gee_hydrology_provider.py",
                "dB",
                hydro._SAR_VV_WATER_THRESHOLD_DB,
                ["Global literature default (Twele et al. 2016). Not calibrated for Indian catchments."],
            ),
            _parameter(
                "cloud_probability_threshold",
                "app/services/satellite/_gee_common.py",
                "percent",
                float(_gee_common.CLOUD_PROBABILITY_THRESHOLD),
                ["Pixels at or above this s2cloudless probability are masked. Not calibrated."],
            ),
        ]
    )
    return items


# ---------------------------------------------------------------------
# Service 1 — farm climate risk
# ---------------------------------------------------------------------
def risk_score_evidence(
    *,
    index_observations: dict[SatelliteIndex, tuple[list[IndexObservation], list[MonthlyValue], str]],
    baseline_observations: dict[SatelliteIndex, tuple[list[IndexObservation], list[MonthlyValue], str]],
    rainfall_observations: list[IndexObservation],
    rainfall_monthly: list[MonthlyValue],
    rainfall_retrieval: str,
    rainfall_normals: dict[int, float],
    jrc_period: tuple[date, date],
    start: date,
    end: date,
    baseline_start: date,
    weights: dict,
    weights_version_id: str,
    floor_threshold: float,
    computed_in_year: int,
    satellite_provider: object,
) -> list[EvidenceItem]:
    """Lineage for one Service 1 `RiskScore`.

    `index_observations` and `baseline_observations` map each optical index
    to (raw observations with scene dates, the aligned monthly series,
    "fetched" | "cache").
    """
    items: list[EvidenceItem] = []
    for index, (observations, monthly, retrieval) in index_observations.items():
        items.append(
            _index_evidence(
                index.value, index, observations, monthly, start, end, retrieval, satellite_provider, "Report window"
            )
        )
    for index, (observations, monthly, retrieval) in baseline_observations.items():
        item = _index_evidence(
            index.value, index, observations, monthly, baseline_start, end, retrieval, satellite_provider,
            f"Seasonal baseline ({BASELINE_YEARS} years before the window, plus the window)",
        )
        items.append(EvidenceItem(**{**item.__dict__, "quantity": f"{index.value}_baseline"}))

    items.append(_rainfall_monthly_evidence(rainfall_monthly, start, end, rainfall_retrieval, satellite_provider))
    items.append(_climatology_evidence(rainfall_normals, satellite_provider, computed_in_year))

    if isinstance(satellite_provider, gee.GeeProvider):
        jrc_start, jrc_end = jrc_period
        items.append(
            _observation(
                quantity="jrc_occurrence_percent",
                collection_id=gee._JRC_SURFACE_WATER,
                band="occurrence",
                requested_scale_m=gee._JRC_SCALE_METERS,
                reducer="unweighted mean over polygon after unmask(0)",
                temporal_aggregation="Static summary of the full Landsat record; not a time series.",
                period_start=jrc_start,
                period_end=jrc_end,
                observations_expected=1,
                observations_used=1,
                acquisition_dates=None,
                retrieval="fetched",
                extra_limitations=[
                    "Used directly as flood-exposure risk, but measures how often water was PRESENT, not how "
                    "flood-prone the land is.",
                    "Record ends December 2021; nothing since is reflected.",
                ],
            )
        )
    else:
        items.append(_undescribed("jrc_occurrence_percent", satellite_provider, *jrc_period))

    source = "app/services/risk/engine.py"
    items.extend(
        [
            _parameter(
                "risk_factor_weights",
                f"config_weight:{weights_version_id}",
                "dimensionless",
                None,
                [
                    "Weights "
                    + ", ".join(f"{getattr(k, 'value', k)}={v:.3f}" for k, v in weights.items())
                    + ". Not calibrated against loan outcomes."
                ],
            ),
            _parameter(
                "floor_threshold",
                f"config_weight:{weights_version_id}",
                "score (0-100)",
                floor_threshold,
                ["Any single factor at or above this forces the overall band to at least HIGH. Not calibrated."],
            ),
            _parameter(
                "band_thresholds",
                source,
                "score (0-100)",
                None,
                [
                    "Equal quartiles: "
                    + ", ".join(f"{b.value} <= {v:g}" for v, b in risk_engine._BAND_THRESHOLDS)
                    + ". A convention, not a calibrated cut-off."
                ],
            ),
            _parameter(
                "neutral_score_when_uncomputable",
                source,
                "score (0-100)",
                float(risk_engine._NEUTRAL_SCORE),
                [
                    "A factor that cannot be computed is scored "
                    f"{risk_engine._NEUTRAL_SCORE:g} and averaged in at full weight, as if measured, while "
                    "confidence measures only optical series completeness and does not see it. Known defect, "
                    "scheduled for the confidence/sufficiency work."
                ],
            ),
            _parameter(
                "recent_months_for_rainfall_anomaly",
                source,
                "months",
                float(risk_engine._RECENT_MONTHS_FOR_RAINFALL),
                ["Rainfall anomaly compares only the last three months with their normals."],
            ),
            _parameter(
                "baseline_years",
                "app/services/risk/seasonal.py",
                "years",
                float(BASELINE_YEARS),
                ["Bounded by Sentinel-2 L2A availability from ~2017."],
            ),
            _parameter(
                "min_baseline_samples",
                "app/services/risk/seasonal.py",
                "samples per calendar month",
                float(MIN_BASELINE_SAMPLES),
                ["Below this, the seasonal factor is treated as uncomputable (and then scored neutral)."],
            ),
            _parameter(
                "cloud_probability_threshold",
                "app/services/satellite/_gee_common.py",
                "percent",
                float(_gee_common.CLOUD_PROBABILITY_THRESHOLD),
                ["Pixels at or above this s2cloudless probability are masked. Not calibrated."],
            ),
        ]
    )
    return items
