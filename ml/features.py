"""Phenology features from a monthly index series.

Pure functions, no Earth Engine, no I/O — so the logic that decides what
"sugarcane-shaped" means is testable without a network call.

WHY DURATION, NOT MINIMUM
-------------------------
The first version of this keyed on minimum NDVI, on the reasoning that
sugarcane runs 12-18 months and never goes bare. That is true of RATOON
cane and false of PLANT cane.

A real plot settled it. A 0.6 acre field in Shera, planted 20 December
2025, bottomed out at NDVI 0.19 in January — indistinguishable from bare
soil, because that is exactly what it was while the cane was below
detection. A minimum-NDVI rule would have called it "not sugarcane", and
would have missed every newly planted field in the district.

What actually separates cane is how LONG it stays green. That same plot
was continuously above 0.3 from February to August and still climbing at
eight months. Soybean or tur runs about four months and then the field
goes bare. So the features here describe the shape and duration of the
green period rather than its floor.

MISSING MONTHS ARE NOT ZEROES
-----------------------------
Over Maharashtra the monsoon routinely erases the optical record: on that
same plot, July and August 2026 had fourteen Sentinel-2 passes between
them and not one usable observation. A missing month means "we did not
see", never "nothing was growing", and a gap must not be allowed to break
a green run that certainly continued through it.
"""

from __future__ import annotations

from statistics import fmean

Series = list[float | None]

# A field is "green" above this. 0.30 sits above bare soil (~0.15) and
# below any established canopy, and is the threshold at which the Shera
# plot's plant cane separated cleanly from its own bare-soil months.
GREEN_THRESHOLD = 0.30

# A gap this long or shorter between two green months is treated as
# still-green. Two months covers a full monsoon optical blackout;
# stretching it further would start inventing crops through a genuine
# fallow period.
MAX_GAP_MONTHS = 2

# When cane is planted around Latur, stated by the founder (who farms
# here) on 21 Sep 2026: November through March, rarely outside it. Used
# ONLY to flag a green-up that falls outside the window — most often
# ratoon regrowth after a harvest, sometimes another long-duration crop.
# It never moves or overrides an observed date: the observation is the
# evidence, and this is the sanity check on it.
PLANTING_MONTHS = (11, 12, 1, 2, 3)

# Months in which a canopy can FIRST become visible from a November-March
# planting. Planting is not emergence: the first two fields labelled
# (Shera, planted December 2025) stayed below NDVI 0.30 until April, four
# months later, because a winter planting grows slowly until the heat
# arrives. So a green-up anywhere from November to June is consistent
# with a local planting, and only July-October is not.
#
# Inside this window a green-up cannot be told apart from ratoon regrowth
# by the curve alone — a field cut in March regrows immediately and looks
# the same. The code says so rather than picking one.
EMERGENCE_MONTHS = (11, 12, 1, 2, 3, 4, 5, 6)


def interpolate_gaps(series: Series, max_gap: int = MAX_GAP_MONTHS) -> Series:
    """Fill short interior gaps by linear interpolation between known
    neighbours. Leading and trailing gaps stay unknown — there is nothing
    on one side to interpolate from, and guessing beyond the observed
    record is how a model learns to hallucinate a season.
    """
    filled: Series = list(series)
    known = [index for index, value in enumerate(series) if value is not None]
    if len(known) < 2:
        return filled

    for left, right in zip(known, known[1:]):
        gap = right - left - 1
        if gap == 0 or gap > max_gap:
            continue
        start, end = series[left], series[right]
        assert start is not None and end is not None
        for step in range(1, gap + 1):
            filled[left + step] = start + (end - start) * step / (gap + 1)
    return filled


def green_runs(series: Series, threshold: float = GREEN_THRESHOLD) -> list[int]:
    """Lengths of each consecutive above-threshold stretch, gaps filled.

    An annual crop gives one short run, or two for a double-cropped
    field. Sugarcane gives one long one.
    """
    filled = interpolate_gaps(series)
    runs: list[int] = []
    current = 0
    for value in filled:
        if value is not None and value >= threshold:
            current += 1
        else:
            if current:
                runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def _slope(values: list[float]) -> float:
    """Least-squares slope per month. Describes how fast the canopy built
    — cane ramps gradually over months, a short-duration crop spikes."""
    count = len(values)
    if count < 2:
        return 0.0
    mean_x = (count - 1) / 2
    mean_y = fmean(values)
    numerator = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values))
    denominator = sum((index - mean_x) ** 2 for index in range(count))
    return numerator / denominator if denominator else 0.0


def greenup_index(series: Series, threshold: float = GREEN_THRESHOLD) -> int | None:
    """Index of the month the canopy last started from bare ground.

    Age is measured from here, not from the start of the observation
    window: a field planted before the window opens has no visible
    green-up in it, and pretending otherwise would date every established
    field to the day we started looking.

    "Started" means a rise from below the threshold to above it and
    staying there for at least two months — a single cloudy month's
    artefact is not a planting. The LAST such rise is used, because a
    harvested field that regrew as ratoon is a new cycle with a new age.
    """
    filled = interpolate_gaps(series)
    onset = None
    for index in range(1, len(filled)):
        previous, current = filled[index - 1], filled[index]
        if previous is None or current is None:
            continue
        if previous < threshold <= current:
            ahead = [v for v in filled[index : index + 2] if v is not None]
            if len(ahead) >= 2 and all(v >= threshold for v in ahead):
                onset = index
    return onset


def age_features(ndvi: Series, threshold: float = GREEN_THRESHOLD) -> dict[str, float | None]:
    """How far through its cycle the crop is, in months.

    `months_since_greenup` is the honest, directly observed quantity: how
    long the canopy has been continuously green. For cane planted inside
    the observation window it IS the age, give or take the weeks between
    planting and the canopy crossing the detection threshold — on the
    Shera plot, cane planted 20 December 2025 sat at bare-soil NDVI until
    February, so an age read this way runs about two months young.

    `greenup_observed` says whether the start was actually seen. When it
    is 0 the field was already green when the window opened, the age is a
    lower bound, and nothing here should be read as "this cane is N months
    old" — only "at least N".
    """
    filled = interpolate_gaps(ndvi)
    last = len(filled) - 1
    onset = greenup_index(ndvi, threshold)

    if onset is None:
        green_months = [i for i, v in enumerate(filled) if v is not None and v >= threshold]
        if not green_months:
            return {"months_since_greenup": None, "greenup_observed": 0, "age_is_lower_bound": 1}
        # Green from the first observed month: the cycle began before we
        # were looking, so all we can say is "at least this long".
        return {
            "months_since_greenup": last - green_months[0] + 1,
            "greenup_observed": 0,
            "age_is_lower_bound": 1,
        }

    return {
        "months_since_greenup": last - onset + 1,
        "greenup_observed": 1,
        "age_is_lower_bound": 0,
    }


def phenology_features(
    ndvi: Series,
    ndmi: Series | None = None,
    vv: Series | None = None,
    vh: Series | None = None,
    threshold: float = GREEN_THRESHOLD,
    ndre: Series | None = None,
    evi: Series | None = None,
    rvi: Series | None = None,
) -> dict[str, float | None]:
    """Every column the model sees, from one field's monthly series.

    Returns None for anything the data cannot support, never a filler
    value. LightGBM splits on missing natively, so a real absence stays
    an absence rather than becoming a fabricated number.
    """
    observed = [value for value in ndvi if value is not None]
    if len(observed) < 3:
        return {"observed_months": len(observed)}

    filled = interpolate_gaps(ndvi)
    runs = green_runs(ndvi, threshold)
    known_filled = [value for value in filled if value is not None]

    # Still green at the end of the window? An annual crop has been
    # harvested by then; cane has not.
    tail = [value for value in filled[-3:] if value is not None]
    green_at_end = fmean(tail) >= threshold if tail else None

    peak_index = filled.index(max(known_filled))
    trough_before_peak = filled[: peak_index + 1]
    known_before = [value for value in trough_before_peak if value is not None]

    features: dict[str, float | None] = {
        # --- duration: the primary discriminator ---
        "longest_green_run": max(runs) if runs else 0,
        "total_green_months": sum(runs),
        "green_periods": len(runs),
        "green_fraction": sum(runs) / len(filled),
        "green_at_window_end": None if green_at_end is None else int(green_at_end),
        # --- magnitude ---
        "min_ndvi": min(observed),
        "max_ndvi": max(observed),
        "mean_ndvi": fmean(observed),
        "amplitude_ndvi": max(observed) - min(observed),
        "ndvi_integral": sum(known_filled),
        # --- dynamics ---
        "ndvi_slope": _slope(known_filled),
        "months_trough_to_peak": (
            peak_index - known_before.index(min(known_before)) if len(known_before) > 1 else None
        ),
        # --- coverage, so the model can discount thin evidence ---
        "observed_months": len(observed),
        "observed_fraction": len(observed) / len(ndvi),
    }

    if ndmi:
        wet = [value for value in ndmi if value is not None]
        if wet:
            features.update(
                {
                    "min_ndmi": min(wet),
                    "max_ndmi": max(wet),
                    "mean_ndmi": fmean(wet),
                    # Canopy moisture retention: cane holds water long
                    # after an annual crop has dried down.
                    "months_ndmi_positive": sum(1 for value in wet if value > 0),
                }
            )

    # Radar carries the monsoon months optical loses entirely. It is
    # speckle-prone on a small plot, so only aggregate statistics are
    # exposed — a single pass is not trustworthy at this scale.
    for name, radar in (("vv", vv), ("vh", vh), ("rvi", rvi)):
        if not radar:
            continue
        values = [value for value in radar if value is not None]
        if not values:
            continue
        features[f"{name}_mean"] = fmean(values)
        features[f"{name}_slope"] = _slope(values)
        features[f"{name}_range"] = max(values) - min(values)

    if features.get("vv_mean") is not None and features.get("vh_mean") is not None:
        features["vv_vh_difference"] = features["vv_mean"] - features["vh_mean"]

    # Red edge and the broader vegetation index carry what plain NDVI
    # loses once a canopy closes. NDVI saturates around 0.8 — a five-month
    # cane field and a ten-month one both sit near the ceiling, so NDVI
    # alone cannot separate them. NDRE keeps responding after that point,
    # which is why age needs it and detection does not.
    #
    # Both come from Sentinel-2's 20 m bands, not the 10 m ones: on a
    # 0.2 ha plot that is a handful of pixels, so these are worth more on
    # a one-acre field than on a tiny one.
    for name, series in (("ndre", ndre), ("evi", evi)):
        if not series:
            continue
        values = [value for value in series if value is not None]
        if not values:
            continue
        features[f"{name}_mean"] = fmean(values)
        features[f"{name}_max"] = max(values)
        features[f"{name}_slope"] = _slope(values)
        # Growth still accelerating at the end of the window means a young
        # crop; flat at a high value means an established one.
        tail = [value for value in series[-4:] if value is not None]
        if len(tail) >= 2:
            features[f"{name}_slope_recent"] = _slope(tail)

    features.update(age_features(ndvi, threshold))
    return features


def in_planting_window(month: int) -> bool:
    """Is this calendar month (1-12) one in which cane is planted here?"""
    return month in PLANTING_MONTHS


def in_emergence_window(month: int) -> bool:
    """Could a canopy first appear in this month from a local planting?"""
    return month in EMERGENCE_MONTHS


__all__ = [
    "GREEN_THRESHOLD",
    "MAX_GAP_MONTHS",
    "PLANTING_MONTHS",
    "age_features",
    "green_runs",
    "greenup_index",
    "in_planting_window",
    "interpolate_gaps",
    "phenology_features",
]
