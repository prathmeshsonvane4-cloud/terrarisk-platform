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
