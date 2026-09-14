"""The Recharge-Stress Engine — pure, deterministic, zero I/O (Blueprint
v2 D6), cloning `RiskEngine`'s statistical shape (percentile-rank/ratio/
min-max scoring + weighted composite) rather than importing its code —
the same "clone the shape, not the code" convention `WaterBalanceEngine`
already established for a second, independent engine in this codebase.

SCORING METHODOLOGY (Blueprint v2 D6, and the `recharge_stress_score`
table's own docstring, M0-005): a weighted composite of exactly three
factors — **rainfall anomaly**, **VCI** (Vegetation Condition Index), and
**surface-water trend** — benchmarked against the 30-year CHIRPS
climatology by default (`BaselineWindow.CLIMATOLOGY_30YR`), not a short
trailing window (D6's v2 fix: a recent drought sequence must not silently
redefine "normal" as "already stressed").

Each factor reuses an ALREADY-ESTABLISHED formula from `RiskEngine`,
cloned (not imported) into this module:
- Rainfall anomaly: the same ratio-based comparison
  (`risk/engine.py::_rainfall_ratio`) `RiskEngine._score_drought_risk()`
  already uses for its own rainfall-anomaly sub-signal — a scalar
  "normal" (one CHIRPS-climatology mean per calendar month) has no
  distribution to rank against, so a ratio, not `_percentile_rank()`, is
  the correct existing tool for this specific comparison — exactly the
  tool RiskEngine itself already reaches for in the identical situation.
- VCI: the exact Kogan (1995) min-max formula
  `RiskEngine._score_drought_risk()` already implements — current NDVI
  positioned within its own historical min-max range, not
  `_percentile_rank()` either (VCI's own published definition is min-max
  normalization, not rank-based).
- Surface-water trend: `_percentile_rank()` reused literally — the one
  factor here whose input (`surface_water_monthly`, a real historical
  series from `HydrologyDataProvider.get_surface_water_extent_series()`)
  has an actual distribution to rank against, the same shape
  `RiskEngine._score_vegetation_stability()` already uses for NDVI. This
  is the literal reuse ticket M3-001 asks for ("reuse the repository's
  existing percentile-ranking approach where appropriate").

=====================================================================
DISCOVERED DISCREPANCY, FLAGGED AND RESOLVED — read before changing this
file's factor list
=====================================================================

Ticket M3-001's own instructions describe the engine computing stress
from "storage change, groundwater anomaly, and surface-water
persistence." That is NOT what Blueprint v2 approved. Blueprint v2 D6,
Part 4/9's numbered limitations, and the `recharge_stress_score` table's
own columns (`rainfall_anomaly_ratio`, `vci`, `surface_water_trend`) all
agree on three DIFFERENT factors: rainfall anomaly, VCI, and surface-water
trend. Critically, Blueprint v2 explicitly and repeatedly states
groundwater data must **never be blended numerically** into this score:
"CGWB groundwater categories are block-scale context, not a
catchment-scale measurement, and are never blended numerically into the
recharge-stress score" (Part 9, limitation 9) — and the MIT-reviewer's
own bolded sentence in Part 1: "every groundwater-adjacent output is
either a CGWB cross-check ... or a relative stress-screening index built
from surface indicators." Implementing "groundwater anomaly" as a
weighted scoring input would directly violate this named, TDR-reviewed
architectural decision. This engine implements Blueprint v2's actual,
approved methodology (rainfall anomaly + VCI + surface-water trend) —
CGWB data has no numeric role here at all, not even as an optional
factor with zero weight. "Storage change" (a `WaterBalanceEngine`
output) also has no role here: Blueprint keeps the two engines' outputs
separate, cross-checked only via a QA-log comparison (Part 9's
"cross-dataset consistency" check), never blended into one score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models.enums import BaselineWindow, StressBand
from app.services.hydrology.models import InsufficientEvidenceError
from app.services.risk.models import MonthlyValue
from app.services.risk.seasonal import seasonal_percentile_rank, seasonal_vci

__all__ = [
    "RechargeStressBundle",
    "RechargeStressConfig",
    "RechargeStressEngine",
    "RechargeStressEngineResult",
    "RechargeStressFactor",
]


class RechargeStressFactor(str, Enum):
    """The three Blueprint v2 D6 factors — a local enum (not added to
    `app.models.enums`, per this ticket's "no schema changes"
    constraint): these are engine-internal weight-dict keys, not a
    persisted Postgres enum type, the same reasoning
    `hydrology/provider.py`'s `SurfaceWaterMethod` already uses for a
    domain-vocabulary enum that doesn't need a DB column of its own."""

    RAINFALL_ANOMALY = "rainfall_anomaly"
    VEGETATION_CONDITION = "vegetation_condition"
    SURFACE_WATER_TREND = "surface_water_trend"


@dataclass(frozen=True)
class RechargeStressBundle:
    """Everything the Recharge-Stress Engine needs to score one
    catchment/period. Assembled by a later ticket's orchestrator from
    `SatelliteDataProvider` (rainfall) and `HydrologyDataProvider`
    (surface-water extent) calls plus cached NDVI — the engine itself
    never knows where this data came from, mirroring
    `ObservationBundle`/`WaterBalanceBundle`'s exact contract.

    Deliberately carries NO CGWB/groundwater field — see this module's
    docstring. CGWB context is a persistence-layer concern (a later
    ticket joins `cgwb_groundwater_observation` when writing a
    `RechargeStressScore` row), not an engine input.
    """

    rainfall_monthly: list[MonthlyValue]
    # One CHIRPS-climatology mean per calendar month (1-12) — a scalar
    # baseline, not a distribution, which is exactly why rainfall anomaly
    # below uses a ratio rather than `_percentile_rank()`. Sourced from
    # whichever baseline_window is recorded below; CLIMATOLOGY_30YR per
    # D6's v2 fix is the expected/default case, not a choice this
    # zero-I/O engine makes itself.
    rainfall_normal_by_month: dict[int, float]
    ndvi_monthly: list[MonthlyValue]
    surface_water_monthly: list[MonthlyValue]
    # Multi-year climatological baselines for the two seasonal factors —
    # see app/services/risk/seasonal.py. Rainfall already had its
    # equivalent above (`rainfall_normal_by_month`); NDVI and surface
    # water previously had none and were ranked against their own recent
    # history with the calendar month left free, which measures seasonal
    # position rather than anomaly.
    #
    # Empty by default so an existing caller still builds a valid bundle;
    # the scorers then report those factors as not computable rather than
    # quietly reverting to the mixed-month comparison.
    ndvi_baseline: list[MonthlyValue] = field(default_factory=list)
    surface_water_baseline: list[MonthlyValue] = field(default_factory=list)
    # Recorded, not computed: which window rainfall_normal_by_month (and,
    # by the same D6 v2 fix, the historical framing generally) represents
    # — this zero-I/O engine cannot itself decide or fetch a different
    # window, it only carries the caller's own label through into the
    # result (WaterBalanceBundle.closed_catchment_assumed's exact "a
    # parameter, not a hardcoded constant" reasoning, D4, applies here
    # identically).
    baseline_window: BaselineWindow = BaselineWindow.CLIMATOLOGY_30YR


@dataclass(frozen=True)
class RechargeStressConfig:
    """Configuration for one `RechargeStressEngine.compute()` call — the
    same `weights`/`weights_version_id` shape `RiskEngineConfig` already
    uses, since `recharge_stress_score` genuinely is a weighted composite
    (unlike `WaterBalanceResult` — see that model's own docstring,
    M0-004, for why it explicitly is NOT). No `floor_threshold`: Blueprint
    v2 D6 does not name an equivalent floor rule for recharge stress, and
    this ticket's "do not introduce calibration" instruction is read here
    as "do not add scoring behavior beyond what D6 actually specifies" —
    RiskEngine's floor rule is a named, risk-specific business rule, not
    a generic pattern to carry over uncritically (the same critical
    stance the WaterBalanceEngine's own D4 assumptions took toward
    reusing shapes only where they actually apply).
    """

    weights: dict[RechargeStressFactor, float]
    weights_version_id: str


@dataclass(frozen=True)
class RechargeStressEngineResult:
    """Field-for-field, maps directly onto
    `app.models.water_balance.RechargeStressScore`'s columns (M0-005) —
    see that model for the full column-by-column rationale.

    `confidence` has no destination column on `RechargeStressScore` today
    (unlike `WaterBalanceResult.data_completeness`, its sibling table) —
    a schema gap discovered while implementing this ticket, not
    something this ticket's "no schema changes" constraint permits
    fixing here. It is still computed and returned (required by this
    ticket's own item 5), and also folded into `raw_inputs` (an existing
    JSONB column) so a future persistence-layer ticket has it available
    without needing a new column; a dedicated `data_completeness` column
    is recommended as its own small follow-up ticket, not solved
    speculatively now.
    """

    stress_score: float
    stress_band: StressBand
    baseline_window: BaselineWindow
    rainfall_anomaly_ratio: float | None
    vci: float | None
    surface_water_trend: float | None
    confidence: float
    weights_version_id: str
    raw_inputs: dict = field(default_factory=dict)
    model_version: str = ""


# Cloned from risk/engine.py's exact _BAND_THRESHOLDS shape and numeric
# cutoffs — StressBand's own docstring says it "mirrors RiskBand's exact
# vocabulary... reuses RiskEngine's percentile-rank statistical shape"
# (Blueprint v2 D6), which this reads as: reuse the SAME thresholds, not
# invent new stress-specific ones ("do not tune weights" extends, in
# spirit, to "do not tune thresholds either").
_STRESS_BAND_THRESHOLDS: tuple[tuple[float, StressBand], ...] = (
    (25.0, StressBand.LOW),
    (50.0, StressBand.MODERATE),
    (75.0, StressBand.HIGH),
    (100.0, StressBand.VERY_HIGH),
)

_RECENT_MONTHS_FOR_RAINFALL = 3

# PHASE C: there is no neutral score. A factor that cannot be computed used to
# score 50 and enter the weighted average at full weight, so a catchment with
# no usable data reported "Moderate" stress. Each scorer now returns None for
# an uncomputable factor; the composite is the weighted average of computed
# factors; and if none can be computed, InsufficientEvidenceError fails the
# report rather than inventing a result.


def _band_for_stress(score: float) -> StressBand:
    for upper_bound, band in _STRESS_BAND_THRESHOLDS:
        if score <= upper_bound:
            return band
    return StressBand.VERY_HIGH


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


def _rainfall_ratio(rainfall_monthly: list[MonthlyValue], normal_by_month: dict[int, float], recent_months: int) -> float | None:
    """Identical formula to `risk/engine.py::_rainfall_ratio`: sum of the
    most recent `recent_months` of rainfall, divided by the sum of the
    same calendar months' historical normals."""
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


def _ratio_to_stress(ratio: float) -> float:
    """Ratio=1.0 (exactly normal) -> stress 50 (neutral); ratio=0.0 (no
    rainfall at all) -> stress 100 (maximum); ratio>=2.0 -> stress 0.
    Identical shape to `risk/engine.py`'s own rainfall-derived risk
    scores (`rainfall_risk`/`rainfall_anomaly_risk`), reused here for
    both rainfall anomaly and surface-water trend, since both are ratio
    comparisons against a single baseline value."""
    return _clamp(100.0 - (ratio * 50.0), 0.0, 100.0)


def _score_rainfall_anomaly(
    rainfall_monthly: list[MonthlyValue], rainfall_normal_by_month: dict[int, float]
) -> tuple[float | None, float | None]:
    """Returns (stress_score, rainfall_anomaly_ratio), both None when not
    computable. Below-normal rainfall drives stress up, exactly mirroring
    `RiskEngine._score_drought_risk()`'s `rainfall_anomaly_risk`."""
    ratio = _rainfall_ratio(rainfall_monthly, rainfall_normal_by_month, _RECENT_MONTHS_FOR_RAINFALL)
    if ratio is None:
        return None, None
    return _ratio_to_stress(ratio), ratio


def _score_vegetation_condition(
    ndvi_monthly: list[MonthlyValue], ndvi_baseline: list[MonthlyValue]
) -> tuple[float | None, float | None]:
    """Returns (stress_score, vci), both None when not computable. VCI (Kogan, 1995): current NDVI
    positioned within the range observed for the SAME CALENDAR MONTH in
    other years.

    Shares one implementation with `RiskEngine._score_drought_risk()`
    rather than restating the formula — this function and that one
    previously held independent copies that were identically wrong,
    ranking each reading against every month mixed together and so
    measuring seasonal position instead of vegetation stress. See
    `app/services/risk/seasonal.py`.
    """
    vci = seasonal_vci(ndvi_monthly, ndvi_baseline)
    if vci is None:
        return None, None
    return _clamp(100.0 - vci, 0.0, 100.0), vci


def _score_surface_water_trend(
    surface_water_monthly: list[MonthlyValue], surface_water_baseline: list[MonthlyValue]
) -> tuple[float | None, float | None]:
    """Returns (stress_score, surface_water_trend). "Trend" here is the
    current surface-water-extent reading's percentile position within
    its own historical series (`_percentile_rank`, the same shape
    `RiskEngine._score_vegetation_stability()` uses for NDVI) — a stated
    interpretation of "trend" as current-relative-to-own-history
    standing, not a fitted linear-regression slope, chosen because (a)
    it is the literal, direct reuse of this repository's existing
    percentile-ranking approach ticket M3-001 explicitly asks for, and
    (b) `surface_water_monthly` is the one factor input here with a real
    historical distribution to rank against — the exact situation
    `_percentile_rank()` was designed for, unlike the scalar rainfall
    baseline. Persistently high recent water presence relative to
    history -> low stress; a low percentile (currently near or below its
    own historical low) -> high stress."""
    trend = seasonal_percentile_rank(surface_water_monthly, surface_water_baseline)
    if trend is None:
        return None, None
    return _clamp(100.0 - trend, 0.0, 100.0), trend


class RechargeStressEngine:
    """Stateless — safe to reuse a single instance across requests,
    exactly like `RiskEngine`/`WaterBalanceEngine`."""

    MODEL_VERSION = "recharge-stress-engine-v2"

    def compute(self, bundle: RechargeStressBundle, config: RechargeStressConfig) -> RechargeStressEngineResult:
        """Compute the recharge-stress score for one catchment/period:
        a weighted composite of rainfall anomaly, VCI, and surface-water
        trend (Blueprint v2 D6). Deterministic — the same bundle and
        config always produce the same result. No floor rule (see
        `RechargeStressConfig`'s docstring for why).
        """
        self._validate_bundle(bundle)
        self._validate_config(config)

        rainfall_stress, rainfall_anomaly_ratio = _score_rainfall_anomaly(
            bundle.rainfall_monthly, bundle.rainfall_normal_by_month
        )
        vegetation_stress, vci = _score_vegetation_condition(bundle.ndvi_monthly, bundle.ndvi_baseline)
        surface_water_stress, surface_water_trend = _score_surface_water_trend(
            bundle.surface_water_monthly, bundle.surface_water_baseline
        )

        factor_scores: dict[RechargeStressFactor, float | None] = {
            RechargeStressFactor.RAINFALL_ANOMALY: rainfall_stress,
            RechargeStressFactor.VEGETATION_CONDITION: vegetation_stress,
            RechargeStressFactor.SURFACE_WATER_TREND: surface_water_stress,
        }

        # The composite of COMPUTED factors only. An uncomputed factor is
        # excluded, never scored neutral and averaged in.
        if sum(config.weights.get(factor, 0.0) for factor in factor_scores) <= 0:
            # A configuration error, not an evidence gap — reported as one.
            raise ValueError("RechargeStressConfig.weights give no weight to any recharge-stress factor")
        computed = {factor: score for factor, score in factor_scores.items() if score is not None}
        computed_weight = sum(config.weights.get(factor, 0.0) for factor in computed)
        if computed_weight <= 0:
            not_computed = [f.value.replace("_", " ") for f, s in factor_scores.items() if s is None]
            raise InsufficientEvidenceError(
                "Recharge stress could not be computed: no usable data for "
                f"{', '.join(not_computed)} for this catchment and period."
            )
        weighted_average = sum(score * config.weights.get(factor, 0.0) for factor, score in computed.items()) / computed_weight
        stress_score = _clamp(weighted_average, 0.0, 100.0)

        # Mirrors RiskEngine._compute_confidence()'s exact reasoning,
        # applied a third time in this codebase (WaterBalanceEngine
        # being the second): NDVI is the cloud-limited optical series
        # here. Rainfall (CHIRPS) is not cloud-limited (excluded, same
        # reason as always). Surface water is excluded too: per
        # Blueprint v2 D1/D9, SAR is the PRIMARY surface-water method and
        # is all-weather/not cloud-limited — the same category as
        # rainfall for this purpose, not the same category as NDVI.
        confidence = _series_completeness(bundle.ndvi_monthly) * 100.0

        return RechargeStressEngineResult(
            stress_score=stress_score,
            stress_band=_band_for_stress(stress_score),
            baseline_window=bundle.baseline_window,
            rainfall_anomaly_ratio=rainfall_anomaly_ratio,
            vci=vci,
            surface_water_trend=surface_water_trend,
            confidence=confidence,
            weights_version_id=config.weights_version_id,
            raw_inputs={
                "rainfall_stress": rainfall_stress,
                "vegetation_stress": vegetation_stress,
                "surface_water_stress": surface_water_stress,
                "weighted_average_score": weighted_average,
                # Legacy name: NDVI data completeness, not model confidence.
                "confidence": confidence,
                "factors_computed": len(computed),
                "factors_total": len(factor_scores),
                "factors_not_computed": [f.value for f, s in factor_scores.items() if s is None],
            },
            model_version=self.MODEL_VERSION,
        )

    @staticmethod
    def _validate_bundle(bundle: RechargeStressBundle) -> None:
        if bundle is None:
            raise ValueError("RechargeStressBundle is required")
        if not isinstance(bundle.rainfall_monthly, list):
            raise TypeError("rainfall_monthly must be a list of MonthlyValue")
        if not isinstance(bundle.rainfall_normal_by_month, dict):
            raise TypeError("rainfall_normal_by_month must be a dict[int, float]")
        if not isinstance(bundle.ndvi_monthly, list):
            raise TypeError("ndvi_monthly must be a list of MonthlyValue")
        if not isinstance(bundle.surface_water_monthly, list):
            raise TypeError("surface_water_monthly must be a list of MonthlyValue")

    @staticmethod
    def _validate_config(config: RechargeStressConfig) -> None:
        if config is None:
            raise ValueError("RechargeStressConfig is required")
        if not isinstance(config.weights, dict):
            raise TypeError("weights must be a dict[RechargeStressFactor, float]")
        if not config.weights_version_id:
            raise ValueError("RechargeStressConfig.weights_version_id must be a non-empty string")
