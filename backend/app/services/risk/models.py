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
class SubSignal:
    """One input to a factor's score, and whether it could be computed.

    A factor is an average of sub-signals (water availability averages
    MNDWI, NDMI and rainfall). Before Phase C, a sub-signal that could not
    be computed simply dropped out of that average, so a factor built from
    one of its three signals looked identical to one built from all three.
    Recording each one is what lets confidence and sufficiency see the gap.
    """

    name: str
    # 0-100 risk contribution. None when not computable.
    risk: float | None
    missing_reason: str | None = None
    # A statistical interval on `risk`, where the method supports one — see
    # app/services/risk/confidence.py. None means not estimated, not zero.
    interval: tuple[float, float] | None = None
    # Baseline samples behind a seasonal statistic; None where not applicable.
    samples: int | None = None
    # The monthly period of the reading a seasonal statistic ranked, so a
    # shortfall can be stated as "3 years of July imagery", not "3 samples".
    reading_period: date | None = None


@dataclass(frozen=True)
class FactorResult:
    factor: RiskFactor
    # None when no sub-signal could be computed. Before Phase C this was a
    # neutral 50, averaged into the overall score at full weight as though it
    # had been measured — the single production assessment was three-quarters
    # made of those. A factor that was not measured now says so.
    score: float | None
    band: RiskBand | None
    raw_inputs: dict[str, float | int | str | None] = field(default_factory=dict)
    sub_signals: list[SubSignal] = field(default_factory=list)
    # Interval on `score` built from the sub-signals that have one. See
    # ModelConfidence.interval_coverage for how complete it is.
    interval: tuple[float, float] | None = None

    @property
    def computed(self) -> bool:
        return self.score is not None


@dataclass(frozen=True)
class ModelConfidence:
    """A statistical property of the estimate — how well determined it is by
    the data it used. Deliberately says nothing about whether that is enough
    for any particular decision; that is `decision_sufficiency`, computed
    separately against a stated policy.

    Only baseline-sampling uncertainty in the seasonal percentile signals is
    quantified today. VCI, rainfall anomaly and JRC occurrence have no
    uncertainty model, and no measurement error from any product is included.
    `interval_coverage` and `statement` say so on every result.
    """

    factors_computed: int
    factors_total: int
    # Share of the configured factor weight carried by computed factors, 0-1.
    weight_coverage: float
    # Whether a composite score is statistically meaningful at all. When
    # False, the overall score is None rather than an average of whatever
    # happened to be computable.
    overall_estimable: bool
    overall_interval: tuple[float, float] | None
    # "full": every computed factor has an interval. "partial": some do, and
    # the interval understates the true uncertainty. "none": no interval.
    interval_coverage: str
    confidence_level: float
    statement: str


@dataclass(frozen=True)
class RiskResult:
    # None when the composite cannot be estimated. See ModelConfidence.
    overall_score: float | None
    overall_band: RiskBand | None
    # LEGACY NAME: this is optical data completeness — the share of expected
    # monthly Sentinel-2 composites that were usable — not model confidence
    # and not decision sufficiency. Kept under this name because the API,
    # database and every report read it; see `model_confidence` for the
    # statistical property and the sufficiency evaluator for the other.
    confidence: float
    factors: list[FactorResult]
    model_version: str
    weights_version_id: str
    # The plain weighted average of computed factor scores, BEFORE the floor
    # rule (Blueprint §07) can raise it — persisted so the Method tab can
    # show honest score anatomy (M2B P9): when this differs from
    # overall_score, the floor rule fired. None when not estimable.
    weighted_average_score: float | None
    model_confidence: ModelConfidence | None = None
