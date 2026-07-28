"""The Water Balance Engine — pure, deterministic, zero I/O (Blueprint v2
D4), mirroring `RiskEngine`'s exact contract (`app/services/risk/engine.py`).
`compute()` implements the MVP P - ET - Q = dS mass balance (ticket
M2-002b) over `WaterBalanceBundle`'s 3-year monthly series.

Architectural note, stated here because a request for "repository wiring"
could otherwise be misread: this engine will never accept a database
session, ORM repository, or Earth Engine provider as a dependency —
Blueprint v2 D4 requires it to stay zero-I/O, exactly like `RiskEngine`.
Assembling a `WaterBalanceBundle` from real data (satellite_observation
rows, a catchment's resolution_flags) and persisting a
`WaterBalanceEngineResult` afterward are both orchestrator
responsibilities (a later ticket, M5's `water_report_generator.py`) —
the same separation `report_generator.py` already uses for `RiskEngine`
today. "Wiring" this engine to a repository happens *around* it, never
*inside* it.

NAMED MVP SIMPLIFICATIONS (Blueprint v2 D4/Part 4/Part 10 — stated here in
`compute()`'s own docstring too, not just this document, per D4's explicit
requirement):

1. **Closed-catchment mass balance** — no lateral subsurface groundwater
   flow term. `bundle.closed_catchment_assumed` records this; the engine
   does not attempt to model or correct for it.
2. **Gross catchment `Q`** — the runoff term is not net of any internal
   recharge-structure capture (check dams, percolation tanks). A
   structure's captured volume has no term in this balance.
3. **Runoff via a single, fixed representative Curve Number** — see
   `_CURVE_NUMBER` below. The bundle carries no soil/land-use input (no
   provider in this codebase fetches one yet), so a real,
   catchment-specific CN cannot be computed; this is a further named
   simplification layered on top of 1-2, not a hidden one.
4. **Storage-change banding uses fixed mm thresholds**, not a genuine
   climatology-relative percentile/z-score (Blueprint v2 D5's stated
   intent) — see `_STORAGE_CHANGE_BAND_THRESHOLDS` below for why.
"""

from __future__ import annotations

import logging

from app.models.enums import CalibrationStatus, StorageChangeBand
from app.services.hydrology.models import WaterBalanceBundle, WaterBalanceConfig, WaterBalanceEngineResult
from app.services.risk.models import MonthlyValue

logger = logging.getLogger(__name__)

# SCS Curve Number method (USDA-SCS National Engineering Handbook, 1972)
# — the runoff methodology Blueprint v2 Part 4/Part 10 names explicitly,
# cited there as reasonably valid for semi-arid Western Maharashtra
# catchments per the region-qualified validation study in Blueprint v2's
# Sources (the same study ticket M2-005's golden-dataset test will
# regress against). Applied per calendar month, not per discrete storm
# event — the method's own documented weakness (storm duration ignored)
# that Blueprint v2's Sources table already names, not a new one
# introduced here.
#
# A single, fixed, representative CN stands in for a real
# catchment-specific soil/land-use-derived value: no provider in this
# codebase fetches soil/land-use data yet, and WaterBalanceBundle carries
# no such field, so this is a further named, deliberate MVP
# simplification (see module docstring, point 3). 75 is a representative
# mid-range value for row-crop agriculture in fair hydrologic condition
# on Hydrologic Soil Group C — broadly typical of the Deccan/Marathwada
# black-cotton-soil catchments this service targets first — NOT locally
# calibrated per catchment, the same "named literature default, not
# locally calibrated" discipline gee_hydrology_provider.py already
# applies to its own SAR/MNDWI thresholds.
_CURVE_NUMBER = 75.0

# Standard SCS initial-abstraction ratio (Ia = lambda * S), lambda = 0.2
# — the conventional default the method's own literature uses, and the
# specific assumption Blueprint v2's Sources table names as "often wrong"
# in practice but not replaced with a locally-derived value at MVP.
_INITIAL_ABSTRACTION_RATIO = 0.2

# Fixed, named mm thresholds — an MVP stand-in for a genuine
# climatology-relative percentile/z-score banding (Blueprint v2 D5's
# stated intent, Part 4's "3-year monthly water balance... climatology-
# relative band"). WaterBalanceBundle carries no fetched rainfall/ET
# climatology baseline (unlike SatelliteDataProvider's
# get_rainfall_climatology(), HydrologyDataProvider has no equivalent
# method), so a real per-catchment historical distribution is not
# available to compute a genuine z-score/percentile against yet — this is
# a named, reviewable limitation, not a silently-precise number, mirroring
# the discipline already applied to the SAR/MNDWI thresholds. Ascending
# order; each entry's mm value is the INCLUSIVE upper bound for that band
# — mirrors RiskEngine's own `_BAND_THRESHOLDS` shape/convention exactly.
_STORAGE_CHANGE_BAND_THRESHOLDS: tuple[tuple[float, StorageChangeBand], ...] = (
    (-150.0, StorageChangeBand.MUCH_BELOW_NORMAL),
    (-50.0, StorageChangeBand.BELOW_NORMAL),
    (50.0, StorageChangeBand.NORMAL),
    (150.0, StorageChangeBand.ABOVE_NORMAL),
)

# Mirrors RiskEngine's `_NEUTRAL_SCORE` fallback-when-no-data convention:
# when storage_change_mm cannot be computed at all (every rainfall/ET
# month is missing), the engine still returns a deterministic band rather
# than raising or leaving the field unset — `storage_change_band` is not
# `Optional` on WaterBalanceEngineResult. `data_completeness` (which will
# be at or near 0 in this case) is what tells a caller/report layer not
# to trust the band — the same separation of concerns RiskEngine already
# relies on, not a new pattern invented here.
_NEUTRAL_STORAGE_CHANGE_BAND = StorageChangeBand.NORMAL


def _valid_values(series: list[MonthlyValue]) -> list[float]:
    return [m.value for m in series if m.value is not None]


def _series_completeness(series: list[MonthlyValue]) -> float:
    if not series:
        return 0.0
    return len(_valid_values(series)) / len(series)


def _sum_or_none(series: list[MonthlyValue]) -> float | None:
    """Sums only the valid (non-`None`) values in a monthly series.
    Returns `None`, never `0.0`, when there is nothing valid to sum — a
    catchment with zero usable months has no data, not a measured zero,
    the same "missing is missing" convention this codebase already
    applies at the per-month level, extended here to the aggregate."""
    valid = _valid_values(series)
    return sum(valid) if valid else None


def _monthly_runoff_mm(rainfall_mm: float) -> float:
    """SCS Curve Number runoff for one month's rainfall total. Q = (P -
    Ia)^2 / (P - Ia + S) for P > Ia, else 0 — the standard SCS-CN formula,
    S and Ia derived from `_CURVE_NUMBER`/`_INITIAL_ABSTRACTION_RATIO`
    above."""
    max_retention_mm = (25400.0 / _CURVE_NUMBER) - 254.0
    initial_abstraction_mm = _INITIAL_ABSTRACTION_RATIO * max_retention_mm
    if rainfall_mm <= initial_abstraction_mm:
        return 0.0
    excess = rainfall_mm - initial_abstraction_mm
    return (excess * excess) / (excess + max_retention_mm)


def _total_runoff_mm(rainfall_monthly: list[MonthlyValue]) -> float | None:
    """Total runoff over the bundle's period: SCS-CN runoff computed
    independently for each month with a valid rainfall reading, then
    summed — `None` when no month has a valid rainfall reading, mirroring
    `_sum_or_none()`'s convention (runoff cannot be derived from a
    rainfall value that doesn't exist)."""
    valid_rainfall = _valid_values(rainfall_monthly)
    if not valid_rainfall:
        return None
    return sum(_monthly_runoff_mm(p) for p in valid_rainfall)


def _band_for_storage_change(storage_change_mm: float) -> StorageChangeBand:
    for upper_bound, band in _STORAGE_CHANGE_BAND_THRESHOLDS:
        if storage_change_mm <= upper_bound:
            return band
    return StorageChangeBand.MUCH_ABOVE_NORMAL


class WaterBalanceEngine:
    """Stateless — safe to reuse a single instance across requests,
    exactly like `RiskEngine`. Behaviour is injected per call via
    `WaterBalanceBundle`/`WaterBalanceConfig`, not held as instance state
    — the same dependency-injection shape `RiskEngine.compute(bundle,
    config)` already uses, not a new pattern invented for this engine.
    """

    # Follows RiskEngine.MODEL_VERSION's exact convention: the engine
    # stamps its OWN canonical version onto every result, regardless of
    # whatever WaterBalanceConfig.model_version the caller supplied (that
    # field exists for the caller's own record-keeping/validation, not to
    # be echoed back — RiskEngine.compute() has this identical asymmetry
    # with RiskEngineConfig.model_version).
    MODEL_VERSION = "water-balance-engine-v1"

    def compute(self, bundle: WaterBalanceBundle, config: WaterBalanceConfig) -> WaterBalanceEngineResult:
        """Compute the water balance for one catchment/period: P - ET - Q
        = dS, aggregated over the bundle's full 3-year monthly series.
        Deterministic — the same bundle and config always produce the
        same result.

        Implements a **closed-catchment mass balance** — no lateral
        subsurface flow term — and its runoff term is **gross catchment
        `Q`, not net of any internal recharge-structure capture** (see
        the module docstring's "NAMED MVP SIMPLIFICATIONS" for these and
        the Curve Number / banding simplifications alongside them).

        Validation runs unconditionally so a caller passing a malformed
        bundle or config gets a specific, actionable error rather than a
        silent wrong answer.
        """
        self._validate_bundle(bundle)
        self._validate_config(config)

        logger.info(
            "water_balance_compute_called",
            extra={
                "period_start": bundle.period_start.isoformat(),
                "period_end": bundle.period_end.isoformat(),
                "model_version": config.model_version,
            },
        )

        rainfall_mm = _sum_or_none(bundle.rainfall_monthly)
        et_mm = _sum_or_none(bundle.et_monthly)
        runoff_mm = _total_runoff_mm(bundle.rainfall_monthly)

        storage_change_mm = None
        if rainfall_mm is not None and et_mm is not None and runoff_mm is not None:
            storage_change_mm = rainfall_mm - et_mm - runoff_mm

        storage_change_band = (
            _band_for_storage_change(storage_change_mm)
            if storage_change_mm is not None
            else _NEUTRAL_STORAGE_CHANGE_BAND
        )

        # Mirrors RiskEngine._compute_confidence()'s exact reasoning:
        # ET (MODIS, fill/QC-masked — see gee_hydrology_provider.py)
        # is the cloud/fill-limited series here, the same role NDVI/
        # MNDWI/NDMI play for RiskEngine. Rainfall (CHIRPS) is
        # intentionally excluded for the same reason RiskEngine excludes
        # it: CHIRPS is not cloud-limited the same way.
        data_completeness = _series_completeness(bundle.et_monthly) * 100.0

        return WaterBalanceEngineResult(
            storage_change_band=storage_change_band,
            storage_change_mm=storage_change_mm,
            rainfall_mm=rainfall_mm,
            et_mm=et_mm,
            runoff_mm=runoff_mm,
            data_completeness=data_completeness,
            # Always UNCALIBRATED for MVP (Blueprint v2 D5): there is no
            # ground-truth field data source wired into any provider yet
            # for any generic customer — not a placeholder, the Blueprint's
            # own stated MVP decision.
            calibration_status=CalibrationStatus.UNCALIBRATED,
            closed_catchment_assumed=bundle.closed_catchment_assumed,
            # Copied through, not re-derived: resolution_flags are
            # computed once at catchment-creation time from area_ha/DEM
            # relief (Blueprint v2 Part 5) — inputs this bundle
            # deliberately does not carry (D4: the engine is zero-I/O and
            # has no DEM access). WaterBalanceBundle's own docstring
            # already establishes this as a pass-through field, "advisory
            # flags for report rendering, not a controlled value the
            # engine branches on" — copied (not aliased) so the result is
            # never accidentally mutated through a shared list reference.
            resolution_flags=list(bundle.resolution_flags),
            model_version=self.MODEL_VERSION,
        )

    @staticmethod
    def _validate_bundle(bundle: WaterBalanceBundle) -> None:
        if bundle is None:
            raise ValueError("WaterBalanceBundle is required")
        if bundle.period_start > bundle.period_end:
            raise ValueError(
                f"period_start ({bundle.period_start}) must not be after period_end ({bundle.period_end})"
            )
        if not isinstance(bundle.rainfall_monthly, list):
            raise TypeError("rainfall_monthly must be a list of MonthlyValue")
        if not isinstance(bundle.et_monthly, list):
            raise TypeError("et_monthly must be a list of MonthlyValue")
        if not isinstance(bundle.resolution_flags, list):
            raise TypeError("resolution_flags must be a list of str")

    @staticmethod
    def _validate_config(config: WaterBalanceConfig) -> None:
        if config is None:
            raise ValueError("WaterBalanceConfig is required")
        if not config.model_version:
            raise ValueError("WaterBalanceConfig.model_version must be a non-empty string")
