"""Pure data types for the Water Balance Engine (Blueprint v2 Part 4/D4).

Nothing in this module touches a database, the network, or the filesystem.
`WaterBalanceBundle` is the engine's only input shape; `WaterBalanceConfig`
configures one call; `WaterBalanceEngineResult` is its only output shape —
the exact same three-part contract `risk/models.py` already establishes
for `RiskEngine` (`ObservationBundle` / `RiskEngineConfig` / `RiskResult`),
reused here rather than re-invented.

MonthlyValue is imported from risk/models.py, not redefined: the shape
("one monthly composite observation, value is None when the period had no
usable satellite pass") is identical for water balance series and is a
generic time-series concept, not risk-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models.enums import CalibrationStatus, StorageChangeBand
from app.services.risk.models import MonthlyValue

__all__ = ["WaterBalanceBundle", "WaterBalanceConfig", "WaterBalanceEngineResult"]


@dataclass(frozen=True)
class WaterBalanceBundle:
    """Everything the Water Balance Engine needs to compute one catchment's
    water balance for one period. Assembled by the report generator (a
    later ticket, M5) from cached `satellite_observation` rows and the
    catchment's own `resolution_flags` — the engine itself never knows
    where this data came from or which catchment it belongs to, mirroring
    `ObservationBundle`'s exact contract.

    Deliberately excludes a runoff series: unlike rainfall and ET, runoff
    is not a raw satellite observation — it is *derived* (SCS Curve
    Number method, per Blueprint v2 Part 4/Part 10) purely from this
    bundle's own `rainfall_monthly`, using a single fixed representative
    Curve Number (`engine.py`'s `_CURVE_NUMBER`) rather than real
    per-catchment soil/land-use inputs — no provider fetches those yet,
    so this bundle carries no field for them. See `engine.py`'s module
    docstring ("NAMED MVP SIMPLIFICATIONS") for the full rationale.
    """

    period_start: date
    period_end: date
    rainfall_monthly: list[MonthlyValue]
    et_monthly: list[MonthlyValue]
    # Copied from catchment.resolution_flags at compute time (Blueprint v2
    # Part 5) — e.g. ["rainfall_sub_pixel", "et_sub_pixel",
    # "high_relief_terrain"]. Plain strings, not an enum: these are
    # advisory flags for report rendering, not a controlled value the
    # engine branches on.
    resolution_flags: list[str]
    # Always True for MVP — the water balance equation has no lateral
    # groundwater flow term (Blueprint v2 D4/TDR §2's closed-catchment
    # finding). A parameter, not a hardcoded engine constant, so a future
    # lateral-flow-aware model can set it False without changing the
    # bundle's shape.
    closed_catchment_assumed: bool = True


@dataclass(frozen=True)
class WaterBalanceConfig:
    """Configuration for one `WaterBalanceEngine.compute()` call.

    Deliberately minimal compared to `RiskEngineConfig`: the water balance
    is an arithmetic mass balance (P - ET - Q = dS), not a weighted
    composite, so unlike `RiskEngineConfig` there are no `weights` or
    `floor_threshold` to configure — see `WaterBalanceResult`'s docstring
    (M0-004) for why `weights_version_id` does not belong to this engine
    at all. Exists as its own type, not a bare string, so the engine's
    public signature does not need to change shape the day a real
    configurable parameter (e.g. a curve-number calibration factor) is
    added by a later ticket.
    """

    model_version: str


@dataclass(frozen=True)
class WaterBalanceEngineResult:
    """The Water Balance Engine's only output shape (Blueprint v2 Part 5/
    D5). Field-for-field, this maps directly onto
    `app.models.water_balance.WaterBalanceResult`'s columns — see that
    model (M0-004) for the full rationale behind each one, in particular:
    `storage_change_band` is the MVP headline figure; `storage_change_mm`
    is technical-view-only and is always paired with `calibration_status`,
    which defaults to `UNCALIBRATED` for every generic MVP customer.
    """

    storage_change_band: StorageChangeBand
    storage_change_mm: float | None
    rainfall_mm: float | None
    et_mm: float | None
    runoff_mm: float | None
    # 0-100, fraction of usable cloud-free composites — the existing
    # Service 1 confidence concept, not to be confused with
    # calibration_status below (Blueprint v2 D5).
    data_completeness: float
    calibration_status: CalibrationStatus
    closed_catchment_assumed: bool
    resolution_flags: list[str]
    model_version: str
