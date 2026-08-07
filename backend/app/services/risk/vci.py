"""Vegetation Condition Index (Kogan, 1995), shared by both services.

Lives beside `MonthlyValue` (models.py) and is imported by Water
Intelligence's recharge-stress engine as well as Service 1's risk engine
— the same sharing route `MonthlyValue` itself already uses. It is one
function rather than two because the two engines previously carried
independent copies of this calculation, described in
`recharge_stress.py` as "identical formula to
`RiskEngine._score_drought_risk()`'s vci", and they were identically
wrong. A defect that has to be found twice will eventually be fixed once.

WHAT WAS WRONG
--------------
VCI positions a current NDVI reading within its historical range:

    VCI = 100 * (NDVI - NDVI_min) / (NDVI_max - NDVI_min)

Both engines took `NDVI_min`/`NDVI_max` over every month in the
observation window, mixed together. In a monsoon climate that range is
the SEASONAL AMPLITUDE — the gap between a bare pre-monsoon field and a
standing monsoon crop — not the year-to-year variability the index is
defined against.

The consequence is not a small bias, it is a different quantity. A
reading taken in a dry month sits near the seasonal floor and scores
VCI ~ 0 ("severe vegetation stress") in a completely normal year; the
same catchment measured mid-monsoon scores VCI ~ 100 in a drought year.
The output tracked WHERE IN THE SEASON the report happened to be run.

Kogan's definition compares a period against the SAME period in other
years. This module does that: a July reading is ranked against every
other July on record, never against April.

This repository already states the principle for the other seasonal
input — see `SatelliteDataProvider.get_rainfall_climatology`: "Compared
against the *same calendar month* in get_rainfall_series(), never
against an annual average, since rainfall here is highly
monsoon-seasonal." NDVI simply never had it applied.

NAMED LIMITATION
----------------
Kogan's VCI expects a long climatological record (10+ years, ideally
20-30) so that min/max approximate true extremes. This service fetches a
3-year window, giving ~3 samples per calendar month, so the range is
seasonally CORRECT but statistically thin: with three samples the
current reading is often itself the min or the max, which pins VCI at 0
or 100.

That coarseness is real and is not hidden — `MIN_SAMPLES_FOR_VCI` below
refuses to produce a number at all rather than computing one from two
points. The genuine fix is a multi-year NDVI baseline fetch, which is a
provider change and a materially larger Earth Engine cost, not a
constant to adjust here. A coarse-but-valid comparison is still strictly
better than a precise-looking invalid one.
"""

from __future__ import annotations

from app.services.risk.models import MonthlyValue

__all__ = ["MIN_SAMPLES_FOR_VCI", "compute_seasonal_vci"]

# Below three samples for the calendar month, min/max describe nothing:
# with two points the current reading is necessarily one of them, so VCI
# can only ever be exactly 0 or exactly 100 — a number with the shape of
# a measurement and none of the content. Callers treat None as "not
# computable" and fall back to their own neutral handling, which is the
# same convention they already use for a fully missing series.
MIN_SAMPLES_FOR_VCI = 3


def compute_seasonal_vci(ndvi_monthly: list[MonthlyValue]) -> float | None:
    """VCI for the most recent valid NDVI reading, ranked against the
    same calendar month in every other year of the series.

    Returns None when it cannot be computed honestly: no valid readings,
    too few samples for that calendar month, or a degenerate range (every
    sample identical, which would divide by zero).
    """
    latest = _latest_valid_observation(ndvi_monthly)
    if latest is None:
        return None

    same_calendar_month = [
        observation.value
        for observation in ndvi_monthly
        if observation.value is not None and observation.period_start.month == latest.period_start.month
    ]
    if len(same_calendar_month) < MIN_SAMPLES_FOR_VCI:
        return None

    lowest, highest = min(same_calendar_month), max(same_calendar_month)
    if highest <= lowest:
        return None

    return ((latest.value - lowest) / (highest - lowest)) * 100.0


def _latest_valid_observation(ndvi_monthly: list[MonthlyValue]) -> MonthlyValue | None:
    """The most recent observation carrying a real value.

    Returns the observation, not the bare float, because the calendar
    month is what selects the comparison set — the whole point of this
    module.
    """
    for observation in reversed(ndvi_monthly):
        if observation.value is not None:
            return observation
    return None
