"""Pure data types for the Risk Engine (Blueprint §07).

Nothing in this module touches a database, the network, or the filesystem.
`ObservationBundle` is the engine's only input shape; `RiskResult` is its
only output shape. Keeping these as plain dataclasses — not ORM models —
is what makes `RiskEngine.compute()` trivially unit-testable and safe to
later run in parallel with a future ML-backed engine implementing the same
contract (see docs/DECISIONS.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.enums import RiskBand, RiskFactor


@dataclass(frozen=True)
class MonthlyValue:
    """One monthly composite observation. `value` is `None` when the period
    had no usable satellite pass (e.g. persistent cloud cover) — the engine
    treats missing months as missing, never as zero."""

    period_start: date
    value: float | None


@dataclass(frozen=True)
class ObservationBundle:
    """Everything the Risk Engine needs to score one farm (or admin
    boundary) for one lookback window. Assembled by the report generator
    from cached/fetched `SatelliteObservation` rows — the engine itself
    never knows where this data came from.

    Monthly series are expected to cover the same lookback window (36
    months for the approved 3-year/monthly-composite methodology), oldest
    first. `rainfall_normal_by_month` maps calendar month (1-12) to the
    long-term CHIRPS historical mean for that month, used for the
    SPI-style seasonal rainfall anomaly — comparing a given month's
    rainfall to the *same calendar month's* historical normal, not to an
    annual average, since rainfall is highly seasonal in Maharashtra.
    """

    ndvi_monthly: list[MonthlyValue]
    mndwi_monthly: list[MonthlyValue]
    ndmi_monthly: list[MonthlyValue]
    rainfall_monthly: list[MonthlyValue]
    rainfall_normal_by_month: dict[int, float]
    jrc_water_occurrence_percent: float
    # Multi-year climatological baselines (app/services/risk/seasonal.py's
    # BASELINE_YEARS), used ONLY to answer "is this month's reading
    # unusual FOR THIS MONTH?" — never for the report's own displayed
    # window, which stays the 36-month series above.
    #
    # These exist because VCI and every percentile-rank factor previously
    # ranked a reading against its own recent history with the calendar
    # month left free, which measures seasonal position rather than
    # anomaly (see seasonal.py). Rainfall already had its equivalent in
    # `rainfall_normal_by_month`; these are the same idea for the optical
    # indices, kept as full series rather than pre-reduced means because
    # a percentile needs the distribution, not just its centre.
    #
    # Default to empty so an existing caller still constructs a valid
    # bundle; the scorers then report those factors as not computable
    # rather than silently falling back to the mixed-month comparison
    # this field exists to replace.
    ndvi_baseline: list[MonthlyValue] = field(default_factory=list)
    mndwi_baseline: list[MonthlyValue] = field(default_factory=list)
    ndmi_baseline: list[MonthlyValue] = field(default_factory=list)


@dataclass(frozen=True)
class RiskEngineConfig:
    """The subset of a `config_weight` DB row the pure engine needs,
    translated into engine-native types by the caller. The engine never
    reads the database itself."""

    weights: dict[RiskFactor, float]
    floor_threshold: float
    model_version: str
    weights_version_id: str


@dataclass(frozen=True)
class FactorResult:
    factor: RiskFactor
    score: float
    band: RiskBand
    raw_inputs: dict[str, float | int | None] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskResult:
    overall_score: float
    overall_band: RiskBand
    confidence: float
    factors: list[FactorResult]
    model_version: str
    weights_version_id: str
    # The plain weighted average of factor scores, BEFORE the floor rule
    # (Blueprint §07) can raise it — persisted so the Method tab can show
    # honest score anatomy (M2B P9): when this differs from overall_score,
    # the floor rule fired, and the UI must say so rather than implying
    # the four contribution bars simply sum to the composite.
    weighted_average_score: float
