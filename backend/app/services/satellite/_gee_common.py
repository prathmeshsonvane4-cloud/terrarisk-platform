"""Shared, provider-agnostic Earth Engine helpers (tickets M1-002, M1-005).

Extracted out of `gee_provider.py` so a `GEEHydrologyProvider`
(`app/services/hydrology/gee_hydrology_provider.py`) can import these
without creating a `hydrology/` -> `satellite/` dependency in the wrong
direction, and without duplicating them. `monthly_periods()` and
`CLOUD_PROBABILITY_THRESHOLD` are named explicitly by Blueprint v2 D1 as
what a hydrology GEE implementation reuses from "the existing module's
internal helpers." `SENTINEL2_COLLECTION`/`CLOUD_PROBABILITY_COLLECTION`
were added in ticket M1-005 when `GEEHydrologyProvider`'s MNDWI branch
became the second real consumer of the exact Sentinel-2 optical + cloud-
probability collections `gee_provider.py`'s optical indices already use —
the same extraction judgment call D1 makes for the threshold constant,
applied once a second genuine need existed, not spun out speculatively
ahead of one.

This module has zero dependency on `ee`, on `SatelliteDataProvider`, or
on anything under `app/services/hydrology/` — it is pure, importable by
either package without pulling the other one in, which is the entire
reason it exists as its own module rather than living in `gee_provider.py`
or `hydrology/provider.py`.

Zero behavior change from the code this was extracted from — every value
and every line of logic here is unchanged, only relocated.
"""

from __future__ import annotations

from datetime import date

# Approved methodology (docs/DECISIONS.md) — frozen for M1, not a tunable
# left to guesswork: a scene pixel is masked out at or above this cloud
# probability. Reused by any future GEE-backed provider (this codebase's
# or Water Intelligence's) that composites Sentinel-2 optical imagery and
# needs the same s2cloudless-based masking rule.
CLOUD_PROBABILITY_THRESHOLD = 20

# Sentinel-2 surface-reflectance + its matching cloud-probability side
# collection — joined by `system:index` wherever cloud masking is needed.
# Reused unchanged by any provider compositing Sentinel-2 optical imagery,
# not just SatelliteDataProvider implementations.
SENTINEL2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
CLOUD_PROBABILITY_COLLECTION = "COPERNICUS/S2_CLOUD_PROBABILITY"


def monthly_periods(start: date, end: date) -> list[tuple[date, date]]:
    """(period_start, period_end) pairs for each calendar month touching
    [start, end), used as the compositing window for time-series
    generation (Blueprint §06 "Time-series generation": all indices
    composited on the same period boundaries) — reused unchanged by any
    future provider that composites monthly, not just
    `SatelliteDataProvider` implementations."""
    periods: list[tuple[date, date]] = []
    current = date(start.year, start.month, 1)
    while current < end:
        next_month = date(current.year + 1, 1, 1) if current.month == 12 else date(current.year, current.month + 1, 1)
        periods.append((current, next_month))
        current = next_month
    return periods
