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
3b. **No antecedent moisture condition (AMC) adjustment.** SCS-CN is
   applied per day at a fixed CN, so a catchment's CN does not rise
   through a wet spell or fall through a dry one. This underestimates
   late-monsoon runoff. Fixing it needs soil data and a domain-reviewed
   AMC threshold table, not a guessed constant — see `_total_runoff_mm`.
4. **Storage-change banding uses fixed mm thresholds**, not a genuine
   climatology-relative percentile/z-score (Blueprint v2 D5's stated
   intent) — see `_STORAGE_CHANGE_BAND_THRESHOLDS` below for why.
"""

from __future__ import annotations

import logging
from datetime import date

from app.models.enums import CalibrationStatus, StorageChangeBand
from app.services.hydrology.models import (
    AnnualWaterBalance,
    WaterBalanceBundle,
    WaterBalanceConfig,
    WaterBalanceEngineResult,
)
from app.services.risk.models import MonthlyValue

logger = logging.getLogger(__name__)

# SCS Curve Number method (USDA-SCS National Engineering Handbook, 1972)
# — the runoff methodology Blueprint v2 Part 4/Part 10 names explicitly,
# cited there as reasonably valid for semi-arid Western Maharashtra
# catchments per the region-qualified validation study in Blueprint v2's
# Sources (the same study ticket M2-005's golden-dataset test regresses
# against). Applied PER STORM EVENT (one per rainy day), which is the
# timestep the method is defined for — see `_event_runoff_mm`.
#
# A single, fixed, representative CN stands in for a real
# catchment-specific soil/land-use-derived value: no provider in this
# codebase fetches soil/land-use data yet, and WaterBalanceBundle carries
# no such field, so this is a named, deliberate MVP simplification (see
# module docstring, point 3).
#
# 89 is the NRCS TR-55 Table 2-2a value for row crops, straight row,
# GOOD hydrologic condition, on Hydrologic Soil Group D.
#
# HSG D is the correct group for this service's first target geography.
# Deccan/Marathwada black cotton soils are vertisols: high-clay,
# shrink-swell soils that seal once wetted and have very low saturated
# infiltration, which is NRCS's own definition of group D. (Their dry
# cracks give high INITIAL infiltration, which is why they are sometimes
# given a dual C/D rating — but D is the standard assignment for the
# wetted, runoff-producing condition this term models.)
#
# This corrects a real defect, not a preference: the previous value of 75
# was described in this same comment as "Hydrologic Soil Group C," but
# TR-55 gives 85 for row crops on group C — 75 is closer to a group B
# (well-drained sandy loam) value. The catchment was therefore modelled
# as roughly two soil groups more permeable than Deccan vertisols
# actually are, suppressing runoff and pushing the unexplained residual
# into storage change.
#
# Still NOT locally calibrated per catchment — the same "named
# literature default, not locally calibrated" discipline
# gee_hydrology_provider.py applies to its own SAR/MNDWI thresholds.
_CURVE_NUMBER = 89.0

# Standard SCS initial-abstraction ratio (Ia = lambda * S), lambda = 0.2
# — the conventional default the method's own literature uses, and the
# specific assumption Blueprint v2's Sources table names as "often wrong"
# in practice but not replaced with a locally-derived value at MVP.
#
# DELIBERATELY LEFT AT THE STANDARD 0.2. A substantial body of work
# (notably Hawkins et al., and much of the Indian rainfall-runoff
# literature) argues lambda ~= 0.05 fits observed events better, and
# moving to it would raise runoff further. That is a RESEARCH REVISION,
# not the standard method, and adopting it would silently re-tune the
# headline water balance to a non-standard parameterisation. It is a
# calibration decision for a domain reviewer with local event data, not
# a default to change quietly — the same reason `_CURVE_NUMBER` stays an
# uncalibrated published table value rather than a fitted one.
#
# Note the interaction with CN, which is why this is worth stating: Ia
# scales with S, so raising CN to 89 already dropped Ia from ~16.9 mm to
# ~6.3 mm. Many more daily depths now clear the abstraction threshold
# and generate runoff, without touching lambda at all.
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


def _event_runoff_mm(rainfall_mm: float, curve_number: float = _CURVE_NUMBER) -> float:
    """SCS Curve Number runoff for ONE STORM EVENT's rainfall depth. Q =
    (P - Ia)^2 / (P - Ia + S) for P > Ia, else 0 — the standard SCS-CN
    formula, S and Ia derived from `_CURVE_NUMBER`/
    `_INITIAL_ABSTRACTION_RATIO` above.

    The name matters. This formula is defined for a single storm's depth
    and is NOT additive over time: Q(200 mm) is not the sum of the Q of
    the ten 20 mm days that produced it — it is roughly 100x larger,
    because Ia is subtracted once per event rather than once per day.
    Passing an accumulated total here (a month, a season) silently models
    the whole period as one giant storm.

    `_total_runoff_mm()` below is the only production caller and passes
    daily depths, one event per day.

    `curve_number` is injectable purely so the formula can be validated
    against a published worked example at THAT example's CN, independent
    of whatever regional CN this service currently defaults to. Those are
    two separate questions — "is the formula transcribed correctly?" and
    "is our soil-group assignment right?" — and coupling them means
    changing the regional default either breaks the formula check for the
    wrong reason or, worse, quietly redefines the reference it validates
    against. Production always uses the default.
    """
    max_retention_mm = (25400.0 / curve_number) - 254.0
    initial_abstraction_mm = _INITIAL_ABSTRACTION_RATIO * max_retention_mm
    if rainfall_mm <= initial_abstraction_mm:
        return 0.0
    excess = rainfall_mm - initial_abstraction_mm
    return (excess * excess) / (excess + max_retention_mm)


def _total_runoff_mm(rainfall_daily: list[MonthlyValue]) -> float | None:
    """Total runoff over the bundle's period: SCS-CN applied per DAY
    (one storm event per rainy day), then summed.

    `None` when no daily rainfall is available at all, mirroring
    `_sum_or_none()`'s convention — runoff cannot be derived from
    rainfall that doesn't exist. Critically, this returns None rather
    than falling back to `rainfall_monthly`: that fallback is precisely
    the defect this signature change exists to make unrepresentable (see
    `WaterBalanceBundle.rainfall_daily`). A missing-runoff month is
    visible to the caller via `data_completeness`; a silently
    100x-overestimated one is not.

    NAMED LIMITATION (not fixed here): a fixed CN with no antecedent
    moisture condition (AMC I/II/III) adjustment. Real CN rises in a wet
    spell and falls in a dry one, so consecutive monsoon days are
    modelled as drier than they are. This underestimates late-monsoon
    runoff, in the opposite direction to the monthly-aggregation defect
    it replaces, and is a far smaller error — but it is an error, and it
    needs soil data plus a domain-reviewed AMC threshold table to fix
    properly rather than a guessed constant.
    """
    depths = [d.value for d in rainfall_daily if d.value is not None]
    if not depths:
        return None
    return sum(_event_runoff_mm(depth) for depth in depths)


# The Indian water year runs June to May: a monsoon and the dry season it
# feeds belong to the same hydrological year. Splitting on 1 January would
# cut every monsoon in half and make consecutive years look alternately
# wet and dry for no physical reason.
_WATER_YEAR_START_MONTH = 6


def _water_year_start(period: date) -> int:
    """The calendar year in which this period's water year began."""
    return period.year if period.month >= _WATER_YEAR_START_MONTH else period.year - 1


def _annual_breakdown(
    rainfall_monthly: list[MonthlyValue],
    et_monthly: list[MonthlyValue],
    rainfall_daily: list[MonthlyValue],
) -> list[AnnualWaterBalance]:
    """Per-water-year P, ET, Q and dS, oldest first.

    Runoff is recomputed per year from that year's DAILY depths rather
    than apportioned from the period total. Apportioning by rainfall share
    would be wrong in a way that matters here: SCS-CN is non-linear, so a
    wet year generates disproportionately more runoff than its share of
    rainfall, and a proportional split would flatten exactly the
    year-to-year contrast this view exists to show.

    A year is emitted whenever it has any rainfall or ET data at all,
    carrying `months_covered` so the caller can distinguish a genuine dry
    year from a partial one at the edge of the window.
    """
    years: set[int] = set()
    for observation in (*rainfall_monthly, *et_monthly):
        if observation.value is not None:
            years.add(_water_year_start(observation.period_start))

    breakdown: list[AnnualWaterBalance] = []
    for year in sorted(years):
        rain = [o for o in rainfall_monthly if o.value is not None and _water_year_start(o.period_start) == year]
        et = [o for o in et_monthly if o.value is not None and _water_year_start(o.period_start) == year]
        daily = [d.value for d in rainfall_daily if d.value is not None and _water_year_start(d.period_start) == year]

        rainfall_mm = sum(o.value for o in rain) if rain else None
        et_mm = sum(o.value for o in et) if et else None
        runoff_mm = sum(_event_runoff_mm(depth) for depth in daily) if daily else None
        storage_change_mm = (
            rainfall_mm - et_mm - runoff_mm
            if rainfall_mm is not None and et_mm is not None and runoff_mm is not None
            else None
        )

        breakdown.append(
            AnnualWaterBalance(
                label=f"{year}-{str(year + 1)[-2:]}",
                start_year=year,
                # Distinct months observed, not row count: rainfall and ET
                # can cover different months, and a year is only as
                # complete as the union of what was actually seen.
                months_covered=len({o.period_start.month for o in (*rain, *et)}),
                rainfall_mm=rainfall_mm,
                et_mm=et_mm,
                runoff_mm=runoff_mm,
                storage_change_mm=storage_change_mm,
            )
        )
    return breakdown


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
        runoff_mm = _total_runoff_mm(bundle.rainfall_daily)

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
            # Same inputs, resolved per water year — the period totals
            # above answer "what happened over the window", this answers
            # "is it getting better or worse", which is the question a
            # watershed programme actually acts on.
            annual=_annual_breakdown(bundle.rainfall_monthly, bundle.et_monthly, bundle.rainfall_daily),
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
