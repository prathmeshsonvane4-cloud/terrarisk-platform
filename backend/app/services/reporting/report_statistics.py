"""Derived historical statistics, trend, monitoring cadence, and assessment
quality — REPORT V2, Pages 1-3.

Everything here is computed from data the engine already persisted: the
monthly `SatelliteObservation` series (already fetched into `ReportSeries`,
just not previously turned into summary statistics) and, for trend, a
second already-computed `RiskScore` row (the farm's prior assessment, if
one exists). Nothing here calls Earth Engine, the database, or invents a
number no observation backs — same "derive, never fabricate" boundary as
the rest of app/services/reporting.

Kept as pure functions over plain values (no ORM/session access) so this
module has the same testability as report_text.py/recommendation.py —
callers (app/api/reports.py) do the one DB query for the prior assessment
and pass plain numbers in.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from app.models.enums import RiskBand
from app.schemas.report import ObservationPoint

# Monitoring cadence and assessment-quality bucketing are new, fixed
# product-level constants, same status as RECOMMENDATION_CONFIDENCE_THRESHOLD
# (recommendation.py) and _BAND_THRESHOLDS (risk/engine.py) — documented
# here for founder review, trivially adjustable without touching any other
# logic.
_QUALITY_BUCKETS: tuple[tuple[float, str], ...] = (
    (90.0, "Excellent"),
    (70.0, "Good"),
    (50.0, "Fair"),
    (0.0, "Limited"),
)

_MONITORING_CADENCE_BY_BAND: dict[RiskBand, str] = {
    RiskBand.LOW: "Annual reassessment",
    RiskBand.MODERATE: "Semi-annual reassessment (6 months)",
    RiskBand.HIGH: "Quarterly reassessment",
    RiskBand.VERY_HIGH: "Immediate field verification, then monthly monitoring until resolved",
}


@dataclass(frozen=True)
class HistoricalStats:
    """Current / median / min / max / percentile for one monthly index
    series, computed fresh from the already-persisted observations — real
    derived data, not a new satellite call and not a stored field."""

    current: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    percentile: float | None
    months_of_history: int


_NO_HISTORY = HistoricalStats(None, None, None, None, None, 0)


def historical_stats(points: list[ObservationPoint]) -> HistoricalStats:
    if not points:
        return _NO_HISTORY

    values = [p.value for p in points]
    current = values[-1]
    at_or_below = sum(1 for v in values if v <= current)
    percentile = (at_or_below / len(values)) * 100.0

    return HistoricalStats(
        current=current,
        median=statistics.median(values),
        minimum=min(values),
        maximum=max(values),
        percentile=percentile,
        months_of_history=len(points),
    )


@dataclass(frozen=True)
class Trend:
    """Comparison against the farm's own prior assessment — never a
    forecast, always backward-looking against a real prior number."""

    available: bool
    delta: float | None = None
    direction: str = "unavailable"  # "up" | "down" | "flat" | "unavailable"
    previous_value: float | None = None


def trend(current: float | None, previous: float | None) -> Trend:
    """`previous=None` means this farm has no earlier assessment — the
    honest answer is "no trend available," never an assumed baseline. The
    same holds when either side was not computed."""
    if current is None or previous is None:
        return Trend(available=False)

    delta = current - previous
    if abs(delta) < 0.01:
        direction = "flat"
    else:
        direction = "up" if delta > 0 else "down"
    return Trend(available=True, delta=delta, direction=direction, previous_value=previous)


def assessment_quality_label(confidence: float) -> str:
    for threshold, label in _QUALITY_BUCKETS:
        if confidence >= threshold:
            return label
    return "Limited"


def monitoring_cadence(overall_band: RiskBand | None, confidence: float, confidence_threshold: float) -> str:
    """How often this farm should be reassessed — directly answers "how
    often should this farm be monitored?" Low confidence overrides a
    favorable band: a Low-risk score built on sparse data still warrants
    closer monitoring than a Low-risk score with strong data behind it."""
    # No overall score is treated like low confidence: nothing supports a
    # relaxed cadence.
    if overall_band is None or confidence < confidence_threshold:
        return _MONITORING_CADENCE_BY_BAND[RiskBand.VERY_HIGH]
    return _MONITORING_CADENCE_BY_BAND[overall_band]
