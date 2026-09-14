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

WHAT CHANGED IN PHASE C, AND WHY
--------------------------------
A factor that could not be computed used to score a neutral 50 and enter the
weighted average at full weight, as though it had been measured. The only
Service 1 assessment in production reported "Moderate, 83% confidence" with
three of its four factors at that fallback: the one measured value was a JRC
occurrence of 0.0.

Now:
1. An uncomputable factor has `score=None` and records why, per sub-signal.
2. The overall score is the weighted average of COMPUTED factors only.
3. If computed factors carry too little of the configured weight, there is
   no overall score at all. Re-averaging whatever survived would have turned
   that production assessment into "Low" on one number — as unjustified as
   the "Moderate" it replaces. Whether a composite is statistically
   meaningful is a property of the model, so it is decided here; whether the
   evidence is enough for a given loan is decided separately, against a
   stated policy, in app/services/sufficiency/.
4. `model_confidence` reports what is statistically known about the estimate,
   including — explicitly — what is not.
"""

from __future__ import annotations

from app.models.enums import RiskBand, RiskFactor
from app.services.risk.confidence import (
    CONFIDENCE_LEVEL,
    combine_mean_intervals,
    percentile_risk_interval,
    weighted_interval,
)
from app.services.risk.models import (
    FactorResult,
    ModelConfidence,
    MonthlyValue,
    ObservationBundle,
    RiskEngineConfig,
    RiskResult,
    SubSignal,
)
from app.services.risk.seasonal import (
    SeasonalDetail,
    latest_valid_observation,
    same_calendar_month_values,
    seasonal_percentile_detail,
    seasonal_vci_detail,
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

_RECENT_MONTHS_FOR_RAINFALL = 3

# A composite is reported only when computed factors carry at least this
# share of the configured weight AND at least `_MIN_FACTORS_FOR_COMPOSITE`
# factors are computed. With four equal weights that means two factors.
#
# Why these values: one factor is not a composite — it is that factor, and
# presenting it under the composite's name hides three unmeasured risks.
# Half the weight is the smallest share at which the measured factors
# outweigh the unmeasured ones. These are model judgements, NOT calibrated
# against outcomes; they are recorded in every result's lineage.
_MIN_WEIGHT_COVERAGE = 0.5
_MIN_FACTORS_FOR_COMPOSITE = 2

# Why a rainfall anomaly could not be computed. Stable strings: persisted.
_NO_RECENT_RAINFALL = "no_rainfall_in_recent_months"
_NO_RAINFALL_NORMALS = "no_rainfall_normals_for_recent_months"


def _band_for_score(score: float) -> RiskBand:
    for upper_bound, band in _BAND_THRESHOLDS:
        if score <= upper_bound:
            return band
    return RiskBand.VERY_HIGH


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _valid_values(series: list[MonthlyValue]) -> list[float]:
    return [m.value for m in series if m.value is not None]


def _latest_valid(series: list[MonthlyValue]) -> float | None:
    for observation in reversed(series):
        if observation.value is not None:
            return observation.value
    return None


def _series_completeness(series: list[MonthlyValue]) -> float:
    if not series:
        return 0.0
    return len(_valid_values(series)) / len(series)


def _rainfall_ratio_detail(
    rainfall_monthly: list[MonthlyValue],
    normal_by_month: dict[int, float],
    recent_months: int,
) -> tuple[float | None, str | None]:
    """Sum of the most recent `recent_months` of rainfall, divided by the
    sum of the same calendar months' historical normals. Comparing against
    the matching calendar months (not an annual average) is what makes this
    a seasonally-aware anomaly rather than a naive flat comparison —
    rainfall in Maharashtra is highly monsoon-seasonal.

    Returns (ratio, missing_reason)."""
    recent = rainfall_monthly[-recent_months:] if rainfall_monthly else []
    with_rain = [o for o in recent if o.value is not None]
    if not with_rain:
        return None, _NO_RECENT_RAINFALL
    actual_total = 0.0
    normal_total = 0.0
    for observation in with_rain:
        normal = normal_by_month.get(observation.period_start.month)
        if normal is None or normal <= 0:
            continue
        actual_total += observation.value
        normal_total += normal
    if normal_total <= 0:
        return None, _NO_RAINFALL_NORMALS
    return actual_total / normal_total, None


def _baseline_sample_count(current: list[MonthlyValue], baseline: list[MonthlyValue]) -> int:
    """How many baseline observations share the latest reading's calendar
    month — surfaced in raw_inputs so a reviewer can see the evidence a
    percentile rests on rather than inferring it."""
    latest = latest_valid_observation(current)
    if latest is None:
        return 0
    return len(same_calendar_month_values(baseline, latest.period_start.month))


def _percentile_sub_signal(name: str, detail: SeasonalDetail) -> SubSignal:
    if detail.value is None:
        return SubSignal(
            name=name,
            risk=None,
            missing_reason=detail.missing_reason,
            samples=detail.samples,
            reading_period=detail.reading_period,
        )
    return SubSignal(
        name=name,
        risk=100.0 - detail.value,
        interval=percentile_risk_interval(detail.favourable_share, detail.samples),
        samples=detail.samples,
        reading_period=detail.reading_period,
    )


def _factor(factor: RiskFactor, sub_signals: list[SubSignal], raw_inputs: dict) -> FactorResult:
    """Equal-weighted mean of the computable sub-signals — a v1
    implementation detail, not a scientific claim about relative importance.
    No computable sub-signal means no score, never a neutral stand-in."""
    computed = [s for s in sub_signals if s.risk is not None]
    raw_inputs = {
        **raw_inputs,
        "sub_signals_computed": len(computed),
        "sub_signals_total": len(sub_signals),
    }
    if not computed:
        return FactorResult(factor=factor, score=None, band=None, raw_inputs=raw_inputs, sub_signals=sub_signals)

    score = sum(s.risk for s in computed) / len(computed)
    interval, coverage = combine_mean_intervals([s.risk for s in computed], [s.interval for s in computed])
    raw_inputs["interval_coverage"] = coverage
    return FactorResult(
        factor=factor,
        score=score,
        band=_band_for_score(score),
        raw_inputs=raw_inputs,
        sub_signals=sub_signals,
        interval=interval,
    )


def _score_vegetation_stability(bundle: ObservationBundle) -> FactorResult:
    """Risk rises as current NDVI falls toward the low end of what THIS
    CALENDAR MONTH has looked like across the baseline years.

    Previously ranked against the farm's own 3-year history with the
    month left free, which in a monsoon climate ranks a reading by where
    it sits in the seasonal cycle: every pre-monsoon assessment scored as
    high vegetation risk, every monsoon one as low, regardless of whether
    the year was actually poor. See app/services/risk/seasonal.py.
    """
    detail = seasonal_percentile_detail(bundle.ndvi_monthly, bundle.ndvi_baseline)
    return _factor(
        RiskFactor.VEGETATION_STABILITY,
        [_percentile_sub_signal("ndvi_percentile", detail)],
        {
            "current_ndvi": _latest_valid(bundle.ndvi_monthly),
            "ndvi_percentile": detail.value,
            # Samples for the compared calendar month, not total months
            # in the series — the number that actually determines whether
            # the percentile means anything.
            "baseline_samples": detail.samples,
        },
    )


def _score_water_availability(bundle: ObservationBundle) -> FactorResult:
    """Composite of MNDWI (primary — surface water presence), NDMI
    (supporting — crop moisture stress), and recent rainfall vs. normal,
    per the approved methodology (docs/DECISIONS.md).

    Both indices are ranked against the same calendar month across the
    baseline years. MNDWI and NDMI are, if anything, MORE seasonal than NDVI
    — surface water and canopy moisture track the monsoon directly.
    """
    mndwi = seasonal_percentile_detail(bundle.mndwi_monthly, bundle.mndwi_baseline)
    ndmi = seasonal_percentile_detail(bundle.ndmi_monthly, bundle.ndmi_baseline)
    ratio, rain_missing = _rainfall_ratio_detail(
        bundle.rainfall_monthly, bundle.rainfall_normal_by_month, _RECENT_MONTHS_FOR_RAINFALL
    )
    rainfall_risk = _clamp(100.0 - (ratio * 50.0), 0.0, 100.0) if ratio is not None else None

    mndwi_signal = _percentile_sub_signal("mndwi_percentile", mndwi)
    ndmi_signal = _percentile_sub_signal("ndmi_percentile", ndmi)
    return _factor(
        RiskFactor.WATER_AVAILABILITY,
        [
            mndwi_signal,
            ndmi_signal,
            SubSignal(name="rainfall_anomaly", risk=rainfall_risk, missing_reason=rain_missing),
        ],
        {
            "mndwi_current": _latest_valid(bundle.mndwi_monthly),
            "mndwi_sub_risk": mndwi_signal.risk,
            "ndmi_current": _latest_valid(bundle.ndmi_monthly),
            "ndmi_sub_risk": ndmi_signal.risk,
            "rainfall_ratio_to_normal": ratio,
            "rainfall_sub_risk": rainfall_risk,
        },
    )


def _score_drought_risk(bundle: ObservationBundle) -> FactorResult:
    """Combines the Vegetation Condition Index (VCI — Kogan 1995, the
    standard published formula) with a seasonally-aware rainfall anomaly,
    both against the SAME CALENDAR MONTH in other years.

    Neither sub-signal has an uncertainty model, so this factor never
    carries an interval. That is stated, not hidden."""
    vci = seasonal_vci_detail(bundle.ndvi_monthly, bundle.ndvi_baseline)
    vci_risk = _clamp(100.0 - vci.value, 0.0, 100.0) if vci.value is not None else None
    ratio, rain_missing = _rainfall_ratio_detail(
        bundle.rainfall_monthly, bundle.rainfall_normal_by_month, _RECENT_MONTHS_FOR_RAINFALL
    )
    # Below-normal rainfall drives drought risk up; above-normal drives it
    # toward zero (clamped — drought risk cannot go negative).
    rainfall_anomaly_risk = _clamp(100.0 - (ratio * 50.0), 0.0, 100.0) if ratio is not None else None

    return _factor(
        RiskFactor.DROUGHT_RISK,
        [
            SubSignal(
                name="vci",
                risk=vci_risk,
                missing_reason=vci.missing_reason,
                samples=vci.samples,
                reading_period=vci.reading_period,
            ),
            SubSignal(name="rainfall_anomaly", risk=rainfall_anomaly_risk, missing_reason=rain_missing),
        ],
        {
            "vci": vci.value,
            "vci_risk": vci_risk,
            "rainfall_ratio_to_normal": ratio,
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
    ratio, rain_missing = _rainfall_ratio_detail(
        bundle.rainfall_monthly, bundle.rainfall_normal_by_month, _RECENT_MONTHS_FOR_RAINFALL
    )
    flood_rain_risk = _clamp((ratio - 1.0) * 100.0, 0.0, 100.0) if ratio is not None else None

    return _factor(
        RiskFactor.FLOOD_EXPOSURE,
        [
            SubSignal(name="jrc_occurrence", risk=jrc_risk),
            SubSignal(name="flood_rainfall_anomaly", risk=flood_rain_risk, missing_reason=rain_missing),
        ],
        {
            "jrc_water_occurrence_percent": bundle.jrc_water_occurrence_percent,
            "rainfall_ratio_to_normal": ratio,
            "flood_rain_risk": flood_rain_risk,
        },
    )


def _compute_confidence(bundle: ObservationBundle) -> float:
    """OPTICAL DATA COMPLETENESS, under a legacy name — not model confidence
    and not decision sufficiency. The fraction of expected monthly optical
    observations that were actually usable, averaged across the three
    optical indices. Rainfall (CHIRPS) and JRC are not cloud-limited the same
    way, so they are excluded."""
    completeness = [
        _series_completeness(bundle.ndvi_monthly),
        _series_completeness(bundle.mndwi_monthly),
        _series_completeness(bundle.ndmi_monthly),
    ]
    return (sum(completeness) / len(completeness)) * 100.0


def _model_confidence(
    factors: list[FactorResult], config: RiskEngineConfig, estimable: bool, weight_coverage: float
) -> ModelConfidence:
    computed = [f for f in factors if f.computed]
    interval, coverage = (None, "none")
    if estimable:
        interval, coverage = weighted_interval(
            [f.score for f in computed],
            [f.interval for f in computed],
            [config.weights.get(f.factor, 0.0) for f in computed],
        )
    # A factor-level partial interval makes the composite partial too.
    if coverage == "full" and any(f.raw_inputs.get("interval_coverage") == "partial" for f in computed):
        coverage = "partial"

    without_interval = [f.factor.value.replace("_", " ") for f in computed if f.interval is None]
    not_computed = [f.factor.value.replace("_", " ") for f in factors if not f.computed]
    parts = [f"{len(computed)} of {len(factors)} factors computed ({weight_coverage:.0%} of the configured weight)."]
    if not_computed:
        parts.append(f"Not computed: {', '.join(not_computed)}.")
    if not estimable:
        parts.append(
            f"No overall score: a composite needs at least {_MIN_FACTORS_FOR_COMPOSITE} computed factors carrying "
            f"{_MIN_WEIGHT_COVERAGE:.0%} of the weight."
        )
    elif coverage == "none":
        parts.append("No uncertainty interval can be given: no computed factor has an uncertainty model.")
    else:
        lo, hi = interval
        parts.append(
            f"{CONFIDENCE_LEVEL:.0%} interval {lo:.0f}-{hi:.0f}, from baseline-sampling uncertainty in the seasonal "
            "percentile signals only."
        )
        if without_interval:
            parts.append(f"No uncertainty model for: {', '.join(without_interval)}.")
        parts.append(
            "Measurement error in every satellite product is not included, so the true uncertainty is wider than "
            "this interval."
        )

    return ModelConfidence(
        factors_computed=len(computed),
        factors_total=len(factors),
        weight_coverage=weight_coverage,
        overall_estimable=estimable,
        overall_interval=interval,
        interval_coverage=coverage,
        confidence_level=CONFIDENCE_LEVEL,
        statement=" ".join(parts),
    )


class RiskEngine:
    """Stateless — safe to reuse a single instance across requests."""

    MODEL_VERSION = "rule-engine-v2"

    def compute(self, bundle: ObservationBundle, config: RiskEngineConfig) -> RiskResult:
        """Compute the four factor scores, the weighted overall score of the
        computed factors with the approved floor rule applied, optical data
        completeness, and model confidence. Deterministic: the same bundle
        and config always produce the same result.
        """
        factors = [
            _score_vegetation_stability(bundle),
            _score_water_availability(bundle),
            _score_drought_risk(bundle),
            _score_flood_exposure(bundle),
        ]

        total_weight = sum(config.weights.get(f.factor, 0.0) for f in factors)
        computed = [f for f in factors if f.computed]
        computed_weight = sum(config.weights.get(f.factor, 0.0) for f in computed)
        weight_coverage = computed_weight / total_weight if total_weight > 0 else 0.0
        estimable = (
            len(computed) >= _MIN_FACTORS_FOR_COMPOSITE
            and computed_weight > 0
            and weight_coverage >= _MIN_WEIGHT_COVERAGE
        )

        overall_score = None
        weighted_average = None
        if estimable:
            weighted_average = sum(f.score * config.weights.get(f.factor, 0.0) for f in computed) / computed_weight
            # Approved floor rule: any single computed factor at/above the
            # severe threshold forces the overall result to at least the
            # High band — and the numeric score is raised to match, so the
            # displayed score and band never contradict each other.
            any_factor_severe = any(f.score >= config.floor_threshold for f in computed)
            high_band_floor = next(bound for bound, band in _BAND_THRESHOLDS if band == RiskBand.HIGH)
            # high_band_floor is the *upper* bound of MODERATE (50.0); the
            # lowest score that still maps to HIGH is just above it.
            overall_score = max(weighted_average, high_band_floor + 0.01) if any_factor_severe else weighted_average
            overall_score = _clamp(overall_score, 0.0, 100.0)

        return RiskResult(
            overall_score=overall_score,
            overall_band=_band_for_score(overall_score) if overall_score is not None else None,
            confidence=_compute_confidence(bundle),
            factors=factors,
            model_version=self.MODEL_VERSION,
            weights_version_id=config.weights_version_id,
            weighted_average_score=weighted_average,
            model_confidence=_model_confidence(factors, config, estimable, weight_coverage),
        )
