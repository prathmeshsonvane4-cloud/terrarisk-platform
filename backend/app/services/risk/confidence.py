"""Statistical intervals for risk scores — pure, zero I/O (Phase C).

WHAT IS QUANTIFIED
------------------
One source of uncertainty, and only one: **baseline sampling** in the
seasonal percentile signals (NDVI, MNDWI, NDMI).

A seasonal percentile asks where this month's reading sits among the same
calendar month in earlier years. With n baseline years, the number that fall
below the reading is a draw from Binomial(n, q), where q is the reading's
true quantile in that month's long-run distribution. Eight years — the most
Sentinel-2 allows — pins q down only loosely, and that looseness is a real,
computable property of the estimate.

The interval on q is the **Wilson score interval** (Wilson, 1927): closed
form, well behaved at the small n and extreme proportions this platform
routinely sees, and needing no special functions. Ties are counted half, as
in the point estimate.

WHAT IS NOT QUANTIFIED — stated on every result
-----------------------------------------------
- VCI: a min-max position, not a rank; its sampling distribution has no
  simple closed form and is not estimated.
- Rainfall anomaly and JRC occurrence: no uncertainty model.
- Measurement error in every product — CHIRPS, Sentinel-2, Sentinel-1, JRC.
- Correlation between factors, beyond the conservative choice below.

So any interval produced here is a LOWER BOUND on the true uncertainty. That
is the claim this module makes, and it must not be presented as more.
Propagating the rest is a later roadmap phase.
"""

from __future__ import annotations

import math

__all__ = [
    "CONFIDENCE_LEVEL",
    "combine_mean_intervals",
    "percentile_risk_interval",
    "weighted_interval",
    "wilson_interval",
]

# 90%, two-sided. A reporting convention chosen here, not a calibrated or
# externally mandated level. Recorded in every result's lineage so it can be
# changed visibly.
CONFIDENCE_LEVEL = 0.90
_Z = 1.6448536269514722  # standard normal quantile at 0.95


def wilson_interval(proportion: float, n: int, z: float = _Z) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, clipped to [0, 1]."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0.0 <= proportion <= 1.0:
        raise ValueError("proportion must be within [0, 1]")
    z2 = z * z
    denominator = 1.0 + z2 / n
    centre = (proportion + z2 / (2.0 * n)) / denominator
    half_width = (z * math.sqrt(proportion * (1.0 - proportion) / n + z2 / (4.0 * n * n))) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def percentile_risk_interval(favourable_share: float, samples: int) -> tuple[float, float]:
    """Interval on a percentile-derived risk score (risk = 100 - percentile).

    A HIGH share at or below the reading means a HIGH percentile and a LOW
    risk, so the bounds swap when converting.
    """
    low_share, high_share = wilson_interval(favourable_share, samples)
    return 100.0 * (1.0 - high_share), 100.0 * (1.0 - low_share)


def combine_mean_intervals(values: list[float], intervals: list[tuple[float, float] | None]) -> tuple[tuple[float, float] | None, str]:
    """Interval on the mean of several sub-signals.

    Sub-signals with an interval contribute it; those without contribute
    their point value. Bounds are averaged directly, which treats the
    sub-signals as perfectly correlated — the widest assumption, chosen
    because nothing here justifies a narrower one.

    Returns (interval, coverage) where coverage is "full", "partial" or
    "none". A "partial" interval knowingly omits the uncertainty of the
    point-valued sub-signals.
    """
    if not values:
        return None, "none"
    with_interval = sum(1 for interval in intervals if interval is not None)
    if with_interval == 0:
        return None, "none"
    lows = [interval[0] if interval else value for value, interval in zip(values, intervals, strict=True)]
    highs = [interval[1] if interval else value for value, interval in zip(values, intervals, strict=True)]
    coverage = "full" if with_interval == len(values) else "partial"
    return (sum(lows) / len(lows), sum(highs) / len(highs)), coverage


def weighted_interval(
    scores: list[float], intervals: list[tuple[float, float] | None], weights: list[float]
) -> tuple[tuple[float, float] | None, str]:
    """Interval on a weighted average of factor scores — same conservative
    perfect-correlation bound and the same coverage vocabulary as
    `combine_mean_intervals`."""
    total = sum(weights)
    if not scores or total <= 0:
        return None, "none"
    with_interval = sum(1 for interval in intervals if interval is not None)
    if with_interval == 0:
        return None, "none"
    low = sum(w * (i[0] if i else s) for s, i, w in zip(scores, intervals, weights, strict=True)) / total
    high = sum(w * (i[1] if i else s) for s, i, w in zip(scores, intervals, weights, strict=True)) / total
    return (low, high), "full" if with_interval == len(scores) else "partial"
