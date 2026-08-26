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


def phenology_features(
    ndvi: Series,
    ndmi: Series | None = None,
    vv: Series | None = None,
    vh: Series | None = None,
    threshold: float = GREEN_THRESHOLD,
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
    for name, radar in (("vv", vv), ("vh", vh)):
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

    return features


__all__ = [
    "GREEN_THRESHOLD",
    "MAX_GAP_MONTHS",
    "green_runs",
    "interpolate_gaps",
    "phenology_features",
]
