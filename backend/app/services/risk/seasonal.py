"""Seasonal (same-calendar-month) comparison against a multi-year
climatological baseline. Shared by both services' engines.

WHY THIS MODULE EXISTS
----------------------
Every index this platform scores — NDVI, MNDWI, NDMI, SAR surface-water
extent — has a large monsoon seasonal cycle. Ranking a reading against
its own recent history WITHOUT holding the calendar month fixed measures
where in the season the reading falls, not whether conditions are
unusual. A pre-monsoon reading sits near the seasonal floor and scores as
"stressed" in a perfectly ordinary year; the same place measured
mid-monsoon scores healthy in a drought.

That defect was present in five separate scorers across both services,
each with its own copy of the arithmetic. This module is the single
implementation they now share, so the comparison basis cannot drift apart
again.

The principle was already stated in this repository for rainfall —
`SatelliteDataProvider.get_rainfall_climatology`: "Compared against the
*same calendar month* in get_rainfall_series(), never against an annual
average, since rainfall here is highly monsoon-seasonal." Rainfall was
the only input that followed it.

BASELINE LENGTH
---------------
`BASELINE_YEARS` is 8, and that number is a sensor constraint rather than
a preference. Kogan's VCI and a stable percentile climatology both want
10+ years, ideally 20-30. The optical indices come from
`COPERNICUS/S2_SR_HARMONIZED`, whose global Level-2A record only begins
around 2017 — so ~8 years is the longest honest baseline available, and
asking for more would silently return fewer usable months, not more
history. Sentinel-1 (2014-) and MODIS/CHIRPS (2000-/1981-) could support
longer; the optical floor binds.

This is a real, named limitation: 8 samples per calendar month is a
usable climatology, not a robust one. The previous behaviour compared
against ~3 samples drawn from the WRONG months, so this is both longer
and, more importantly, valid.
"""

from __future__ import annotations

from app.services.risk.models import MonthlyValue

__all__ = [
    "BASELINE_YEARS",
    "MIN_BASELINE_SAMPLES",
    "latest_valid_observation",
    "same_calendar_month_values",
    "seasonal_percentile_rank",
    "seasonal_vci",
]

# Bounded by Sentinel-2 L2A global availability (~2017), not chosen.
BASELINE_YEARS = 8

# Below this many samples for the calendar month, neither a min-max range
# nor a percentile carries information: with two or three points the
# current reading is frequently itself the extreme, so the output can
# only land on a handful of values while still LOOKING like a continuous
# measurement. Callers treat None as "not computable" and fall back to
# their own neutral handling — the same path they already use for a
# fully missing series. Refusing to answer is the honest option; the
# alternative is a precise-looking number derived from four points.
MIN_BASELINE_SAMPLES = 5


def latest_valid_observation(series: list[MonthlyValue]) -> MonthlyValue | None:
    """The most recent observation carrying a real value.

    Returns the observation rather than the bare float because its
    calendar month selects the comparison set — the entire point here.
    """
    for observation in reversed(series):
        if observation.value is not None:
            return observation
    return None


def same_calendar_month_values(baseline: list[MonthlyValue], month: int) -> list[float]:
    """Every valid baseline value observed in the given calendar month.

    A July reading is compared against other Julys, never against April.
    """
    return [
        observation.value
        for observation in baseline
        if observation.value is not None and observation.period_start.month == month
    ]


def seasonal_vci(current: list[MonthlyValue], baseline: list[MonthlyValue]) -> float | None:
    """Vegetation Condition Index (Kogan, 1995) for the latest NDVI
    reading, positioned within the range that calendar month has taken
    across the baseline years.

        VCI = 100 * (NDVI - NDVI_min) / (NDVI_max - NDVI_min)

    Returns None when it cannot be computed honestly: no current reading,
    too few baseline samples for that month, or a degenerate range.
    """
    latest = latest_valid_observation(current)
    if latest is None:
        return None

    history = same_calendar_month_values(baseline, latest.period_start.month)
    if len(history) < MIN_BASELINE_SAMPLES:
        return None

    lowest, highest = min(history), max(history)
    if highest <= lowest:
        return None

    # Deliberately NOT clamped to 0-100. A reading outside the baseline's
    # observed range is genuinely unprecedented for that month, and
    # clamping would present a record-breaking value as merely "at the
    # historical extreme". Callers that need a bounded score clamp at
    # their own boundary, where the choice is visible.
    return ((latest.value - lowest) / (highest - lowest)) * 100.0


def seasonal_percentile_rank(current: list[MonthlyValue], baseline: list[MonthlyValue]) -> float | None:
    """Where the latest reading falls within the distribution that
    calendar month has taken across the baseline years, as 0-100.

    Uses the midpoint ("mean rank") convention for ties: values strictly
    below, plus half the values exactly equal. A run of identical
    readings therefore ranks at its own centre rather than at 0 or 100,
    which matters for indices that saturate — a fully dry catchment can
    report the same surface-water extent for many months, and neither
    "lowest on record" nor "highest on record" would be a fair
    description of one of them.

    Returns None when the baseline has too few samples for that month to
    rank against.
    """
    latest = latest_valid_observation(current)
    if latest is None:
        return None

    history = same_calendar_month_values(baseline, latest.period_start.month)
    if len(history) < MIN_BASELINE_SAMPLES:
        return None

    below = sum(1 for value in history if value < latest.value)
    equal = sum(1 for value in history if value == latest.value)
    return ((below + equal / 2.0) / len(history)) * 100.0
