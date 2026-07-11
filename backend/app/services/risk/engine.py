"""The Risk Engine — pure, deterministic, zero I/O (Blueprint §07).

`RiskEngine.compute()` never touches a database, makes an HTTP call, reads
a file, or calls Earth Engine. It is a function from
`(ObservationBundle, RiskEngineConfig)` to `RiskResult` — nothing more.
This is what makes it fully unit-testable and what will let a future
ML-backed engine implement the identical contract and run in parallel with
this one for validation before any cutover (docs/DECISIONS.md).

Score convention: every score in this module — per-factor and overall —
represents *risk*, where higher means worse, consistent with the
`RiskBand` enum's own naming (LOW ... VERY_HIGH). Vegetation/water indices
measure favorable conditions, so each is inverted before use; see the
per-factor docstrings below for the exact reasoning.
"""

from __future__ import annotations

from app.models.enums import RiskBand, RiskFactor
from app.services.risk.models import (
    FactorResult,
    MonthlyValue,
    ObservationBundle,
    RiskEngineConfig,
    RiskResult,
)

# v1 default score->band cutoffs (equal quartiles). Kept as a documented
# constant rather than a config field: the approved config surface for M1
# is factor weights + floor threshold only (Blueprint §07); adding a second
# configurable dimension here would be scope beyond the approved plan.
_BAND_THRESHOLDS: tuple[tuple[float, RiskBand], ...] = (
    (25.0, RiskBand.LOW),
    (50.0, RiskBand.MODERATE),
    (75.0, RiskBand.HIGH),
    (100.0, RiskBand.VERY_HIGH),
)

_NEUTRAL_SCORE = 50.0
_RECENT_MONTHS_FOR_RAINFALL = 3


def _band_for_score(score: float) -> RiskBand:
    for upper_bound, band in _BAND_THRESHOLDS:
        if score <= upper_bound:
            return band
    return RiskBand.VERY_HIGH


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _valid_values(series: list[MonthlyValue]) -> list[float]:
    return [m.value for m in series if m.value is not None]


def _percentile_rank(current: float, history: list[float]) -> float:
    """Percentage of historical values at or below `current`. Standard
    rank-based percentile — used to place the most recent observation
    within the farm's own 3-year distribution (approved methodology:
    "percentile rank against the farm's own 3-year range")."""
    if not history:
        return _NEUTRAL_SCORE
    at_or_below = sum(1 for v in history if v <= current)
    return (at_or_below / len(history)) * 100.0


def _latest_valid(series: list[MonthlyValue]) -> float | None:
    for observation in reversed(series):
        if observation.value is not None:
            return observation.value
    return None


def _series_completeness(series: list[MonthlyValue]) -> float:
    if not series:
        return 0.0
    return len(_valid_values(series)) / len(series)


def _rainfall_ratio(
    rainfall_monthly: list[MonthlyValue],
    normal_by_month: dict[int, float],
    recent_months: int,
) -> float | None:
    """Sum of the most recent `recent_months` of rainfall, divided by the
    sum of the same calendar months' historical normals. Comparing against
    the matching calendar months (not an annual average) is what makes this
    a seasonally-aware anomaly rather than a naive flat comparison —
    rainfall in Maharashtra is highly monsoon-seasonal."""
    recent = rainfall_monthly[-recent_months:] if rainfall_monthly else []
    actual_total = 0.0
    normal_total = 0.0
    have_data = False
    for observation in recent:
        if observation.value is None:
            continue
        month = observation.period_start.month
        normal = normal_by_month.get(month)
        if normal is None or normal <= 0:
            continue
        actual_total += observation.value
        normal_total += normal
        have_data = True
    if not have_data or normal_total <= 0:
        return None
    return actual_total / normal_total


def _score_vegetation_stability(bundle: ObservationBundle) -> FactorResult:
    """Risk rises as current NDVI falls toward the low end of the farm's
    own 3-year range — a healthy, near-historical-peak NDVI is low risk."""
    history = _valid_values(bundle.ndvi_monthly)
    current = _latest_valid(bundle.ndvi_monthly)

    if current is None or len(history) < 2:
        score = _NEUTRAL_SCORE
        percentile = None
    else:
        percentile = _percentile_rank(current, history)
        score = 100.0 - percentile

    return FactorResult(
        factor=RiskFactor.VEGETATION_STABILITY,
        score=score,
        band=_band_for_score(score),
        raw_inputs={"current_ndvi": current, "ndvi_percentile": percentile, "history_months": len(history)},
    )


def _score_water_availability(bundle: ObservationBundle) -> FactorResult:
    """Composite of MNDWI (primary — surface water presence), NDMI
    (supporting — crop moisture stress), and recent rainfall vs. normal,
    per the approved methodology (docs/DECISIONS.md). Each sub-signal is
    normalized to a 0-100 risk score, then averaged equally — a v1
    implementation detail, not a scientific claim about relative
    importance; adjustable in code without a schema change if recalibrated.
    """
    mndwi_history = _valid_values(bundle.mndwi_monthly)
    mndwi_current = _latest_valid(bundle.mndwi_monthly)
    mndwi_risk = 100.0 - _percentile_rank(mndwi_current, mndwi_history) if mndwi_current is not None and mndwi_history else None

    ndmi_history = _valid_values(bundle.ndmi_monthly)
    ndmi_current = _latest_valid(bundle.ndmi_monthly)
    ndmi_risk = 100.0 - _percentile_rank(ndmi_current, ndmi_history) if ndmi_current is not None and ndmi_history else None

    rainfall_ratio = _rainfall_ratio(bundle.rainfall_monthly, bundle.rainfall_normal_by_month, _RECENT_MONTHS_FOR_RAINFALL)
    rainfall_risk = _clamp(100.0 - (rainfall_ratio * 50.0), 0.0, 100.0) if rainfall_ratio is not None else None

    sub_scores = [s for s in (mndwi_risk, ndmi_risk, rainfall_risk) if s is not None]
    score = sum(sub_scores) / len(sub_scores) if sub_scores else _NEUTRAL_SCORE

    return FactorResult(
        factor=RiskFactor.WATER_AVAILABILITY,
        score=score,
        band=_band_for_score(score),
        raw_inputs={
            "mndwi_current": mndwi_current,
            "mndwi_sub_risk": mndwi_risk,
            "ndmi_current": ndmi_current,
            "ndmi_sub_risk": ndmi_risk,
            "rainfall_ratio_to_normal": rainfall_ratio,
            "rainfall_sub_risk": rainfall_risk,
        },
    )


def _score_drought_risk(bundle: ObservationBundle) -> FactorResult:
    """Combines the Vegetation Condition Index (VCI — Kogan 1995, the
    standard published formula) with a seasonally-aware rainfall anomaly.
    VCI needs no scientific judgment call: it is the farm's current NDVI
    positioned within its own historical min-max range."""
    ndvi_history = _valid_values(bundle.ndvi_monthly)
    ndvi_current = _latest_valid(bundle.ndvi_monthly)

    vci_risk = None
    vci = None
    if ndvi_current is not None and ndvi_history:
        ndvi_min, ndvi_max = min(ndvi_history), max(ndvi_history)
        if ndvi_max > ndvi_min:
            vci = ((ndvi_current - ndvi_min) / (ndvi_max - ndvi_min)) * 100.0
            vci_risk = 100.0 - vci

    rainfall_ratio = _rainfall_ratio(bundle.rainfall_monthly, bundle.rainfall_normal_by_month, _RECENT_MONTHS_FOR_RAINFALL)
    # Below-normal rainfall drives drought risk up; above-normal drives it
    # toward zero (clamped — drought risk cannot go negative).
    rainfall_anomaly_risk = _clamp(100.0 - (rainfall_ratio * 50.0), 0.0, 100.0) if rainfall_ratio is not None else None

    sub_scores = [s for s in (vci_risk, rainfall_anomaly_risk) if s is not None]
    score = sum(sub_scores) / len(sub_scores) if sub_scores else _NEUTRAL_SCORE

    return FactorResult(
        factor=RiskFactor.DROUGHT_RISK,
        score=score,
        band=_band_for_score(score),
        raw_inputs={
            "vci": vci,
            "vci_risk": vci_risk,
            "rainfall_ratio_to_normal": rainfall_ratio,
            "rainfall_anomaly_risk": rainfall_anomaly_risk,
        },
    )


def _score_flood_exposure(bundle: ObservationBundle) -> FactorResult:
    """JRC Global Surface Water history (already a 0-100 occurrence scale,
    used directly as historical flood-proneness risk) combined with a
    rainfall-anomaly signal in the *opposite* direction from drought:
    above-normal rainfall drives flood risk up. SAR-based event detection
    is deferred post-MVP (see SatelliteDataProvider.get_sar_backscatter_series)."""
    jrc_risk = _clamp(bundle.jrc_water_occurrence_percent, 0.0, 100.0)

    rainfall_ratio = _rainfall_ratio(bundle.rainfall_monthly, bundle.rainfall_normal_by_month, _RECENT_MONTHS_FOR_RAINFALL)
    flood_rain_risk = _clamp((rainfall_ratio - 1.0) * 100.0, 0.0, 100.0) if rainfall_ratio is not None else None

    sub_scores = [s for s in (jrc_risk, flood_rain_risk) if s is not None]
    score = sum(sub_scores) / len(sub_scores) if sub_scores else _NEUTRAL_SCORE

    return FactorResult(
        factor=RiskFactor.FLOOD_EXPOSURE,
        score=score,
        band=_band_for_score(score),
        raw_inputs={
            "jrc_water_occurrence_percent": bundle.jrc_water_occurrence_percent,
            "rainfall_ratio_to_normal": rainfall_ratio,
            "flood_rain_risk": flood_rain_risk,
        },
    )


def _compute_confidence(bundle: ObservationBundle) -> float:
    """Reflects data quality, not risk: the fraction of expected monthly
    optical observations that were actually usable (not lost to cloud
    cover), averaged across the three optical indices. Rainfall (CHIRPS)
    and JRC water history are not cloud-limited the same way, so they are
    intentionally excluded from this calculation."""
    completeness = [
        _series_completeness(bundle.ndvi_monthly),
        _series_completeness(bundle.mndwi_monthly),
        _series_completeness(bundle.ndmi_monthly),
    ]
    return (sum(completeness) / len(completeness)) * 100.0


class RiskEngine:
    """Stateless — safe to reuse a single instance across requests."""

    MODEL_VERSION = "rule-engine-v1"

    def compute(self, bundle: ObservationBundle, config: RiskEngineConfig) -> RiskResult:
        """Compute all four factor scores, the weighted overall score with
        the approved floor rule applied, and a data-quality confidence
        value. Deterministic: the same bundle and config always produce
        the same result.
        """
        factors = [
            _score_vegetation_stability(bundle),
            _score_water_availability(bundle),
            _score_drought_risk(bundle),
            _score_flood_exposure(bundle),
        ]

        weighted_sum = sum(f.score * config.weights.get(f.factor, 0.0) for f in factors)
        total_weight = sum(config.weights.get(f.factor, 0.0) for f in factors)
        weighted_average = weighted_sum / total_weight if total_weight > 0 else _NEUTRAL_SCORE

        # Approved floor rule: any single factor at/above the shared severe
        # threshold forces the overall result to at least the High band —
        # and the numeric score is raised to match, so the displayed score
        # and band never contradict each other.
        any_factor_severe = any(f.score >= config.floor_threshold for f in factors)
        high_band_floor = next(bound for bound, band in _BAND_THRESHOLDS if band == RiskBand.HIGH)
        # high_band_floor is the *upper* bound of MODERATE (50.0); the
        # lowest score that still maps to HIGH is just above it.
        overall_score = max(weighted_average, high_band_floor + 0.01) if any_factor_severe else weighted_average
        overall_score = _clamp(overall_score, 0.0, 100.0)

        return RiskResult(
            overall_score=overall_score,
            overall_band=_band_for_score(overall_score),
            confidence=_compute_confidence(bundle),
            factors=factors,
            model_version=self.MODEL_VERSION,
            weights_version_id=config.weights_version_id,
        )
