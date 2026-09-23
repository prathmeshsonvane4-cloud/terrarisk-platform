"""A continuous daily time series for any farm, from every free sensor.

    python ml/timeseries.py --point 18.5527,76.4970 --start 2025-10-01 --end 2026-09-22
    python ml/timeseries.py --field shera-02 --plot
    python ml/timeseries.py --all-fields          # every field in the label set, plus a summary

Pulls every usable observation of the field from Sentinel-2 (10 m, three
satellites), Landsat 8 and 9 (30 m), and Sentinel-1 radar (10 m, sees
through cloud), and turns them into one value per day — with every day
labelled for what it actually is.

WHAT "DAILY" CAN AND CANNOT MEAN
--------------------------------
No free sensor sees a one-acre field clearly every day. Measured over the
Shera block for Sep 2025 - Sep 2026: Sentinel-2 imaged it every 4.1 days,
Landsat 8/9 every ~9 days combined, Sentinel-1 every ~13 days (one
descending track; since July 2026 only Sentinel-1D covers it). MODIS is
daily but its 250 m pixel is 6 hectares — larger than most farms here — so
it is deliberately not used. Clouds then remove a large share of the
optical passes, most of all in the monsoon.

So the daily series is observations plus interpolation, and it says which
is which on every day:

  observed          a cloud-free optical view that day
  interpolated      no view that day, but one within MAX_INTERPOLATION_DAYS
  radar_estimated   optical gap too long, filled from Sentinel-1 through a
                    model fitted on this field's own optical/radar pairs —
                    only when that model is demonstrably good
  harvest_between_views
                    after the last view of the standing crop and before the
                    first view of the cut: the day of the harvest is unknown,
                    so no value is given
  no_data           none of the above; the value is left empty

Daily values, even on observed days, are the smoothed curve. The raw value
of every view is kept in the observations file.

A lender reading "NDVI 0.62 today" must be able to tell whether it was
seen today or inferred from a view twelve days ago. `days_to_view` gives
that on every row.

HOW THE SENSORS ARE MADE COMPARABLE
-----------------------------------
- Clouds: Sentinel-2 uses Google's Cloud Score+ (cs_cdf >= 0.60), which
  catches the haze and thin cloud the older s2cloudless mask let through —
  one such pass (15 May 2026) dropped every field in the block at once.
  Landsat uses its own QA band (cloud, dilated cloud, cirrus, shadow).
  A scene counts only if at least 80% of the field was clear.
- Landsat vs Sentinel-2: on small fields the difference is mostly not
  spectral but spatial — a 30 m Landsat pixel also sees the neighbours,
  which squeezes its range toward the local average (on shera-02,
  Sentinel-2 = -0.22 + 1.45 x Landsat). The mapping is MEASURED on each
  field from days both saw it, as a straight line when that beats a
  constant offset on held-out pairs, and Landsat views then count half.
- Radar: backscatter is averaged in linear power (never dB), converted to
  gamma-nought with the local incidence angle so passes at different
  angles compare, and kept separate per orbit track.
- Harvests: found as an abrupt fall between consecutive views (standing
  canopy >= 0.45, a drop of >= 0.20 to stubble <= 0.40, no rebound), and
  the curve is fitted separately on each side. The first version smoothed
  straight across the cut and spread shera-02's one-week harvest over six
  weeks; a lender reading that curve would have dated the harvest wrong.
- Smoothing: a Whittaker smoother (Eilers 2003), made robust with Tukey's
  biweight (Garcia 2010) so a single odd pass is down-weighted rather than
  followed, with its strength chosen by leave-one-out cross-validation
  within each stretch. Odd passes stay in the output, marked; the error is
  reported both without and with them.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from statistics import median

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

sys.path.insert(0, str(Path(__file__).parent))

CLEAR_FRACTION_MIN = 0.8
CLOUD_SCORE_PLUS_CLEAR = 0.60   # Google's recommended cs_cdf threshold
MAX_INTERPOLATION_DAYS = 10     # beyond this from any view, a value is not "interpolated"
RADAR_FILL_DAYS = 7             # a radar-estimated day must be this close to a radar pass
LAMBDA_CANDIDATES = (1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000)

# A radar-to-NDVI model is used only if it predicts this field's own
# optical NDVI well out of sample. Below this it would be inventing a
# canopy, and an empty day is more honest than a confident wrong one.
RADAR_MODEL_MIN_PAIRS = 8
RADAR_MODEL_MIN_R2 = 0.5
RADAR_PAIR_WINDOW_DAYS = 3

# A Landsat/Sentinel-2 offset is only applied when enough same-field pairs
# support it; otherwise the two are used as they come, and the report says so.
CROSS_SENSOR_MIN_PAIRS = 4
CROSS_SENSOR_MIN_PAIRS_LINEAR = 6
CROSS_SENSOR_WINDOW_DAYS = 1
# Even after calibration a 30 m Landsat pixel over a small field carries
# some of its neighbours, so its views count half a Sentinel-2 view.
LANDSAT_WEIGHT = 0.5

# A harvest, at the resolution of individual views. The same physical
# thresholds as the monthly detector in compare_fields.py — a standing
# canopy at or above 0.45, a fall of at least 0.20, landing at stubble at or
# below 0.40, and no rebound to a canopy at the next view.
BREAK_CANOPY_NDVI = 0.45
BREAK_DROP_NDVI = 0.20
BREAK_STUBBLE_NDVI = 0.40

# Robust smoothing: Tukey's biweight on the residuals, re-fitted a few
# times (Garcia 2010), so one strange pass cannot drag the curve. A view
# whose final weight falls below OUTLIER_WEIGHT is reported as an outlier.
ROBUST_ITERATIONS = 3
TUKEY_C = 4.685
OUTLIER_WEIGHT = 0.1


# ----------------------------------------------------------------------
# Pure functions: no Earth Engine, unit-tested
# ----------------------------------------------------------------------


@dataclass
class Observation:
    day: date
    sensor: str                      # "S2", "L8", "L9", "S1"
    platform: str = ""
    ndvi: float | None = None
    ndre: float | None = None
    evi: float | None = None
    vv_db: float | None = None
    vh_db: float | None = None
    rvi: float | None = None
    orbit: str = ""
    clear_fraction: float | None = None
    pixels: int | None = None

    @property
    def optical(self) -> bool:
        return self.sensor in ("S2", "L8", "L9")


def whittaker(values: np.ndarray, weights: np.ndarray, smoothing: float) -> np.ndarray:
    """Whittaker smoother, second-order penalty.

    Minimises sum(w * (y - z)^2) + lambda * sum((second difference of z)^2).
    Days with weight 0 are gaps: the smoother fills them from the curve's
    shape either side, rather than from a straight line or a zero.
    """
    n = len(values)
    difference = sparse.diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(n - 2, n))
    system = sparse.diags(weights) + smoothing * (difference.T @ difference)
    return spsolve(system.tocsc(), weights * np.nan_to_num(values))


def choose_smoothing(values: np.ndarray, weights: np.ndarray, candidates=LAMBDA_CANDIDATES) -> tuple[float, float]:
    """Pick lambda by leave-one-out: hide each observation in turn, predict
    it from the rest, keep the lambda with the smallest error.

    Returns (lambda, root-mean-square prediction error in NDVI units) — the
    error is the honest answer to "how far off is an interpolated day?".
    """
    observed = np.flatnonzero(weights > 0)
    if len(observed) < 5:
        return candidates[len(candidates) // 2], float("nan")
    best = None
    for candidate in candidates:
        errors = []
        for index in observed:
            held = weights.copy()
            held[index] = 0.0
            errors.append(whittaker(values, held, candidate)[index] - values[index])
        rmse = float(np.sqrt(np.mean(np.square(errors))))
        if best is None or rmse < best[1]:
            best = (candidate, rmse)
    return best


@dataclass
class Calibration:
    """How Landsat NDVI is mapped onto Sentinel-2's scale for this field."""

    intercept: float = 0.0
    slope: float = 1.0
    pairs: int = 0
    method: str = "none"                 # "none", "offset" or "linear"
    error_offset: float = float("nan")   # leave-one-out error with a constant offset
    error_linear: float = float("nan")   # leave-one-out error with a straight line

    def apply(self, landsat_ndvi: float) -> float:
        return self.intercept + self.slope * landsat_ndvi


def landsat_pairs(observations: list[Observation]) -> list[tuple[float, float]]:
    """(Sentinel-2 NDVI, Landsat NDVI) for every Landsat view that has a
    Sentinel-2 view of the same field within CROSS_SENSOR_WINDOW_DAYS."""
    s2 = [o for o in observations if o.sensor == "S2" and o.ndvi is not None]
    pairs = []
    for scene in (o for o in observations if o.sensor in ("L8", "L9") and o.ndvi is not None):
        near = [o for o in s2 if abs((o.day - scene.day).days) <= CROSS_SENSOR_WINDOW_DAYS]
        if near:
            closest = min(near, key=lambda o: abs((o.day - scene.day).days))
            pairs.append((closest.ndvi, scene.ndvi))
    return pairs


def cross_sensor_calibration(observations: list[Observation]) -> Calibration:
    """Map Landsat NDVI onto Sentinel-2's scale, measured on this field.

    A 30 m Landsat pixel over a small field also sees the neighbours, which
    pulls every value toward the local average. On shera-02, Sentinel-2 =
    -0.22 + 1.45 x Landsat. A constant offset cannot undo that: its mean
    came out at -0.001 because Landsat read too low at high NDVI and too
    high at low NDVI — two errors cancelling. So a straight line is used
    when there are enough pairs and it predicts held-out pairs better than
    the offset does; otherwise the offset; otherwise nothing.
    """
    pairs = landsat_pairs(observations)
    if len(pairs) < CROSS_SENSOR_MIN_PAIRS:
        return Calibration(pairs=len(pairs))
    data = np.array(pairs, dtype=float)
    s2, landsat = data[:, 0], data[:, 1]

    offset_errors, linear_errors = [], []
    for held in range(len(data)):
        keep = np.arange(len(data)) != held
        offset_errors.append(s2[held] - (landsat[held] + np.mean(s2[keep] - landsat[keep])))
        if len(data) >= CROSS_SENSOR_MIN_PAIRS_LINEAR:
            slope, intercept = np.polyfit(landsat[keep], s2[keep], 1)
            linear_errors.append(s2[held] - (intercept + slope * landsat[held]))
    error_offset = float(np.sqrt(np.mean(np.square(offset_errors))))
    offset = float(np.mean(s2 - landsat))

    if linear_errors:
        error_linear = float(np.sqrt(np.mean(np.square(linear_errors))))
        slope, intercept = np.polyfit(landsat, s2, 1)
        if error_linear < error_offset and 0.5 <= slope <= 2.5:
            return Calibration(float(intercept), float(slope), len(pairs), "linear", error_offset, error_linear)
        return Calibration(offset, 1.0, len(pairs), "offset", error_offset, error_linear)
    return Calibration(offset, 1.0, len(pairs), "offset", error_offset)


def find_breaks(view_days: list[date], values: list[float], season=None) -> list[tuple[date, date]]:
    """Harvests in a sequence of views, as (last day seen standing, first
    day seen cut). The harvest itself happened somewhere between the two;
    nothing in the imagery says exactly when.

    `season`, if given, is a test on the month label ("2026-06") of the first
    cut view. For sugarcane it is the crushing season, November to April:
    on 23 Sep 2026 two ratoon fields showed a "second harvest" on 19-29 June
    2026 — six-month-old regrowth, on the same dates in both fields, at the
    monsoon onset — which was cloud the mask missed, not a cut.
    """
    breaks = []
    floor = 0   # views before the last cut never count as "standing" again
    for i in range(len(values) - 1):
        # The view just before a cut must itself still show a canopy.
        # Without this, the median of the last three views keeps reading
        # "standing" for two views after a harvest and finds it twice.
        if values[i] <= BREAK_STUBBLE_NDVI:
            continue
        standing = median(values[max(floor, i - 2):i + 1])
        cut = values[i + 1]
        if standing < BREAK_CANOPY_NDVI or cut > BREAK_STUBBLE_NDVI or standing - cut < BREAK_DROP_NDVI:
            continue
        if i + 2 < len(values) and values[i + 2] >= BREAK_CANOPY_NDVI:
            continue  # back to a canopy at the next view: a bad pass, not a cut
        if season is not None and not season(view_days[i + 1].strftime("%Y-%m")):
            continue
        breaks.append((view_days[i], view_days[i + 1]))
        floor = i + 1
    return breaks


def tukey_weights(residuals: np.ndarray) -> np.ndarray:
    """Tukey biweight: 1 near the curve, falling to 0 for gross outliers,
    scaled by the median absolute deviation so no noise level is assumed."""
    scale = 1.4826 * np.median(np.abs(residuals - np.median(residuals)))
    if scale == 0:
        return np.ones_like(residuals)
    u = residuals / (TUKEY_C * scale)
    weights = (1 - u ** 2) ** 2
    weights[np.abs(u) >= 1] = 0.0
    return weights


def smooth_segment(values: np.ndarray, weights: np.ndarray, smoothing: float) -> tuple[np.ndarray, np.ndarray]:
    """Robust Whittaker over one stretch between harvests.

    Returns the curve and each day's final robust weight (1 where there was
    no view). Weights are floored rather than zeroed so the system stays
    solvable even if most views in a short stretch disagree.
    """
    observed = weights > 0
    robust = np.ones(len(values))
    if observed.sum() == 0:
        return np.full(len(values), np.nan), robust
    if observed.sum() == 1:
        return np.full(len(values), float(values[observed][0])), robust
    curve = whittaker(values, weights, smoothing)
    if observed.sum() < 4:
        return curve, robust
    for _ in range(ROBUST_ITERATIONS):
        robust[observed] = np.maximum(tukey_weights(values[observed] - curve[observed]), 1e-4)
        curve = whittaker(values, weights * robust, smoothing)
    return curve, robust


def choose_segmented_smoothing(values: np.ndarray, weights: np.ndarray, segments: list[tuple[int, int]],
                               candidates=LAMBDA_CANDIDATES) -> tuple[float, float, float]:
    """Leave-one-out choice of lambda, respecting harvest breaks.

    Each view is hidden in turn and predicted from the rest of ITS OWN
    stretch — a prediction across a harvest would be judged against a
    field that no longer exists. The error is reported over views the
    robust fit did not flag as outliers: that is the typical error of an
    interpolated day, not the error on a hazy pass.
    """
    if int((weights > 0).sum()) < 5:
        return candidates[len(candidates) // 2], float("nan"), float("nan")
    best = None
    for candidate in candidates:
        errors, trusted = [], []
        for lo, hi in segments:
            seg_values, seg_weights = values[lo:hi], weights[lo:hi]
            _, robust = smooth_segment(seg_values, seg_weights, candidate)
            for offset in np.flatnonzero(seg_weights > 0):
                held = seg_weights.copy()
                held[offset] = 0.0
                prediction, _ = smooth_segment(seg_values, held, candidate)
                if np.isnan(prediction[offset]):
                    continue
                errors.append(prediction[offset] - seg_values[offset])
                trusted.append(robust[offset] >= OUTLIER_WEIGHT)
        if not errors:
            continue
        kept = np.array(errors)[np.array(trusted, dtype=bool)]
        if kept.size == 0:
            continue
        rmse = float(np.sqrt(np.mean(np.square(kept))))
        rmse_all = float(np.sqrt(np.mean(np.square(errors))))
        if best is None or rmse < best[1]:
            best = (candidate, rmse, rmse_all)
    return best if best else (candidates[len(candidates) // 2], float("nan"), float("nan"))


def days_to_nearest(days: list[date], target: date) -> int | None:
    if not days:
        return None
    return min(abs((d - target).days) for d in days)


@dataclass
class RadarModel:
    intercept: float
    vh_coefficient: float
    vv_coefficient: float
    r2_out_of_sample: float
    pairs: int
    usable: bool
    reason: str = ""

    def predict(self, vh_db: float, vv_db: float) -> float:
        return self.intercept + self.vh_coefficient * vh_db + self.vv_coefficient * vv_db


def fit_radar_model(pairs: list[tuple[float, float, float]]) -> RadarModel:
    """NDVI ~ a + b*VH + c*VV, from (ndvi, vh_db, vv_db) pairs on this field.

    Judged by leave-one-out R^2, never by the fit to its own points: with a
    dozen pairs, in-sample R^2 flatters almost any model.
    """
    if len(pairs) < RADAR_MODEL_MIN_PAIRS:
        return RadarModel(0, 0, 0, float("nan"), len(pairs), False,
                          f"only {len(pairs)} optical/radar pairs, need {RADAR_MODEL_MIN_PAIRS}")
    data = np.array(pairs, dtype=float)
    y, X = data[:, 0], np.column_stack([np.ones(len(data)), data[:, 1], data[:, 2]])
    predictions = []
    for index in range(len(data)):
        keep = np.arange(len(data)) != index
        coefficients, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None)
        predictions.append(X[index] @ coefficients)
    residual = np.sum((y - np.array(predictions)) ** 2)
    total = np.sum((y - y.mean()) ** 2)
    r2 = 1 - residual / total if total > 0 else float("nan")
    coefficients, *_ = np.linalg.lstsq(X, y, rcond=None)
    usable = bool(r2 >= RADAR_MODEL_MIN_R2)
    reason = "" if usable else f"out-of-sample R² {r2:.2f} is below {RADAR_MODEL_MIN_R2}"
    return RadarModel(float(coefficients[0]), float(coefficients[1]), float(coefficients[2]),
                      float(r2), len(pairs), usable, reason)


@dataclass
class DailySeries:
    days: list[date]
    ndvi: list[float | None]
    flag: list[str]
    days_to_view: list[int | None]
    smoothing: float
    interpolation_rmse: float          # held-out error on views not flagged as outliers
    interpolation_rmse_all: float      # the same, counting every view — the pessimistic figure
    calibration: Calibration
    breaks: list[tuple[date, date]] = field(default_factory=list)
    outliers: list[date] = field(default_factory=list)
    radar_model: RadarModel | None = None
    notes: list[str] = field(default_factory=list)


def build_daily(observations: list[Observation], start: date, end: date, harvest_season=None) -> DailySeries:
    """Fuse every observation into one labelled value per day.

    Order of operations: calibrate Landsat onto Sentinel-2's scale; find
    harvests in the sequence of views; smooth each stretch between harvests
    on its own, robustly, with the strength chosen by cross-validation;
    label every day; fill from radar only where the optical record cannot
    support a value and only with a radar model that has proved itself.
    """
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    index = {d: i for i, d in enumerate(days)}
    notes: list[str] = []

    calibration = cross_sensor_calibration(observations)
    if calibration.method == "linear":
        notes.append(f"Landsat mapped onto Sentinel-2: S2 = {calibration.intercept:+.3f} + "
                     f"{calibration.slope:.2f} x Landsat ({calibration.pairs} pairs; held-out error "
                     f"{calibration.error_linear:.3f}, against {calibration.error_offset:.3f} with an offset)")
    elif calibration.method == "offset":
        notes.append(f"Landsat adjusted by {calibration.intercept:+.3f} ({calibration.pairs} pairs)")
    else:
        notes.append(f"Landsat not calibrated: {calibration.pairs} same-day pair(s), need {CROSS_SENSOR_MIN_PAIRS}")

    values = np.full(len(days), np.nan)
    weights = np.zeros(len(days))
    for obs in observations:
        if not obs.optical or obs.ndvi is None or obs.day not in index:
            continue
        landsat = obs.sensor in ("L8", "L9")
        value = calibration.apply(obs.ndvi) if landsat else obs.ndvi
        weight = LANDSAT_WEIGHT if landsat else 1.0
        i = index[obs.day]
        if weights[i] > 0:
            values[i] = (values[i] * weights[i] + value * weight) / (weights[i] + weight)
            weights[i] += weight
        else:
            values[i], weights[i] = value, weight

    view_days = [days[i] for i in np.flatnonzero(weights > 0)]
    breaks = find_breaks(view_days, [float(values[index[d]]) for d in view_days], season=harvest_season)

    # Stretches between harvests. Days strictly between the last view of the
    # standing crop and the first view of the cut belong to neither.
    segments: list[tuple[int, int]] = []
    in_harvest_gap = np.zeros(len(days), dtype=bool)
    lo = 0
    for standing, cut in breaks:
        segments.append((lo, index[standing] + 1))
        in_harvest_gap[index[standing] + 1:index[cut]] = True
        lo = index[cut]
    segments.append((lo, len(days)))
    for standing, cut in breaks:
        notes.append(f"harvest between {standing} (last seen standing) and {cut} (first seen cut)")

    smoothing, rmse, rmse_all = choose_segmented_smoothing(values, weights, segments)
    curve = np.full(len(days), np.nan)
    robust = np.ones(len(days))
    segment_of = np.full(len(days), -1)
    for number, (lo, hi) in enumerate(segments):
        curve[lo:hi], robust[lo:hi] = smooth_segment(values[lo:hi], weights[lo:hi], smoothing)
        segment_of[lo:hi] = number
    outliers = [days[i] for i in np.flatnonzero((weights > 0) & (robust < OUTLIER_WEIGHT))]
    if outliers:
        notes.append(f"{len(outliers)} view(s) down-weighted as outliers: "
                     + ", ".join(d.isoformat() for d in outliers))

    views_by_segment: dict[int, list[date]] = {}
    for d in view_days:
        views_by_segment.setdefault(int(segment_of[index[d]]), []).append(d)

    ndvi: list[float | None] = []
    flags: list[str] = []
    distances: list[int | None] = []
    for i, day in enumerate(days):
        # Distance to a view in the SAME stretch — a view of the standing
        # crop says nothing about the field after it was cut.
        distance = days_to_nearest(views_by_segment.get(int(segment_of[i]), []), day)
        distances.append(distance)
        if in_harvest_gap[i]:
            ndvi.append(None)
            flags.append("harvest_between_views")
        elif weights[i] > 0:
            ndvi.append(float(curve[i]))
            flags.append("observed")
        elif distance is not None and distance <= MAX_INTERPOLATION_DAYS and not np.isnan(curve[i]):
            ndvi.append(float(curve[i]))
            flags.append("interpolated")
        else:
            ndvi.append(None)
            flags.append("no_data")

    radar = [o for o in observations if o.sensor == "S1" and o.vh_db is not None and o.vv_db is not None]
    model = None
    if radar:
        pairs = []
        for obs in radar:
            if obs.day not in index or in_harvest_gap[index[obs.day]]:
                continue
            near = [d for d in view_days if abs((d - obs.day).days) <= RADAR_PAIR_WINDOW_DAYS]
            if near and not np.isnan(curve[index[obs.day]]):
                pairs.append((float(curve[index[obs.day]]), obs.vh_db, obs.vv_db))
        model = fit_radar_model(pairs)
        if model.usable:
            filled = 0
            for i, day in enumerate(days):
                if flags[i] != "no_data":
                    continue
                nearest = min(radar, key=lambda o: abs((o.day - day).days))
                if abs((nearest.day - day).days) <= RADAR_FILL_DAYS:
                    ndvi[i] = model.predict(nearest.vh_db, nearest.vv_db)
                    flags[i] = "radar_estimated"
                    filled += 1
            notes.append(f"radar filled {filled} day(s); model out-of-sample R² {model.r2_out_of_sample:.2f} "
                         f"on {model.pairs} pairs")
        else:
            notes.append(f"radar not used to fill gaps: {model.reason}")

    return DailySeries(days, ndvi, flags, distances, smoothing, rmse, rmse_all, calibration, breaks, outliers,
                       model, notes)


def availability(series: DailySeries, observations: list[Observation]) -> list[dict]:
    """Per month: how many views, and what share of days was each kind."""
    months: dict[str, dict] = {}
    for day, flag in zip(series.days, series.flag):
        key = day.strftime("%Y-%m")
        entry = months.setdefault(key, {"month": key, "days": 0, "observed": 0, "interpolated": 0,
                                        "radar_estimated": 0, "harvest_between_views": 0, "no_data": 0,
                                        "s2": 0, "landsat": 0, "s1": 0})
        entry["days"] += 1
        entry[flag] += 1
    for obs in observations:
        key = obs.day.strftime("%Y-%m")
        if key not in months:
            continue
        if obs.sensor == "S2" and obs.ndvi is not None:
            months[key]["s2"] += 1
        elif obs.sensor in ("L8", "L9") and obs.ndvi is not None:
            months[key]["landsat"] += 1
        elif obs.sensor == "S1":
            months[key]["s1"] += 1
    return list(months.values())


# ----------------------------------------------------------------------
# Earth Engine: fetching the observations
# ----------------------------------------------------------------------


def initialise(key_path: Path, project: str) -> None:
    import ee

    email = json.loads(key_path.read_text())["client_email"]
    ee.Initialize(ee.ServiceAccountCredentials(email, str(key_path)), project=project)


def fetch_observations(geometry: dict, start: date, end: date, edge_buffer: float) -> list[Observation]:
    import ee

    region = ee.Geometry(geometry).buffer(-edge_buffer)
    everything = ee.Image.constant(1).rename("all")
    begin, finish = start.isoformat(), (end + timedelta(days=1)).isoformat()
    observations: list[Observation] = []

    # --- Sentinel-2, Cloud Score+ ---------------------------------------
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region).filterDate(begin, finish)
          .linkCollection(ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"), ["cs_cdf"]))

    def s2_stats(image):
        image = ee.Image(image)
        clear = image.select("cs_cdf").gte(CLOUD_SCORE_PLUS_CLEAR)
        reflectance = image.divide(10000)
        indices = (
            image.normalizedDifference(["B8", "B4"]).rename("ndvi")
            .addBands(image.normalizedDifference(["B8A", "B5"]).rename("ndre"))
            .addBands(reflectance.expression(
                "2.5 * ((n - r) / (n + 6 * r - 7.5 * b + 1))",
                {"n": reflectance.select("B8"), "r": reflectance.select("B4"), "b": reflectance.select("B2")},
            ).rename("evi"))
            .updateMask(clear)
        )
        stats = indices.addBands(everything).reduceRegion(
            ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True), region, 10, maxPixels=1e8)
        return ee.Feature(None, stats).set({"date": image.date().format("YYYY-MM-dd"),
                                             "platform": image.get("SPACECRAFT_NAME")})

    for f in s2.map(s2_stats).getInfo()["features"]:
        p = f["properties"]
        total, clear = p.get("all_count") or 0, p.get("ndvi_count") or 0
        if not total or p.get("ndvi_mean") is None or clear / total < CLEAR_FRACTION_MIN:
            continue
        observations.append(Observation(date.fromisoformat(p["date"]), "S2", p.get("platform", ""),
                                        ndvi=p["ndvi_mean"], ndre=p.get("ndre_mean"), evi=p.get("evi_mean"),
                                        clear_fraction=clear / total, pixels=total))

    # --- Landsat 8 and 9, Collection 2 Level 2 --------------------------
    for sensor, collection_id in (("L8", "LANDSAT/LC08/C02/T1_L2"), ("L9", "LANDSAT/LC09/C02/T1_L2")):
        landsat = ee.ImageCollection(collection_id).filterBounds(region).filterDate(begin, finish)

        def landsat_stats(image):
            image = ee.Image(image)
            qa = image.select("QA_PIXEL")
            # bits: 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow
            clear = qa.bitwiseAnd(0b11110).eq(0)
            sr = image.select(["SR_B4", "SR_B5"]).multiply(0.0000275).add(-0.2)
            ndvi = sr.normalizedDifference(["SR_B5", "SR_B4"]).rename("ndvi").updateMask(clear)
            stats = ndvi.addBands(everything).reduceRegion(
                ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True), region, 30, maxPixels=1e8)
            return ee.Feature(None, stats).set({"date": image.date().format("YYYY-MM-dd")})

        for f in landsat.map(landsat_stats).getInfo()["features"]:
            p = f["properties"]
            total, clear = p.get("all_count") or 0, p.get("ndvi_count") or 0
            if not total or p.get("ndvi_mean") is None or clear / total < CLEAR_FRACTION_MIN:
                continue
            observations.append(Observation(date.fromisoformat(p["date"]), sensor, sensor, ndvi=p["ndvi_mean"],
                                            clear_fraction=clear / total, pixels=total))

    # --- Sentinel-1, gamma-nought, per orbit ----------------------------
    s1 = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region).filterDate(begin, finish)
          .filter(ee.Filter.eq("instrumentMode", "IW"))
          .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
          .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH")))

    def s1_stats(image):
        image = ee.Image(image)
        cosine = image.select("angle").multiply(math.pi / 180).cos()
        # dB -> linear sigma0 -> gamma0 = sigma0 / cos(incidence); averaged in linear power
        gamma = image.select(["VV", "VH"]).divide(10).multiply(math.log(10)).exp().divide(cosine)
        stats = gamma.reduceRegion(ee.Reducer.mean(), region, 10, maxPixels=1e8)
        return ee.Feature(None, stats).set({
            "date": image.date().format("YYYY-MM-dd"),
            "platform": image.get("platform_number"),
            "orbit": ee.String(image.get("orbitProperties_pass")).cat("-").cat(
                ee.Number(image.get("relativeOrbitNumber_start")).format("%d")),
        })

    for f in s1.map(s1_stats).getInfo()["features"]:
        p = f["properties"]
        vv, vh = p.get("VV"), p.get("VH")
        if not vv or not vh:
            continue
        observations.append(Observation(date.fromisoformat(p["date"]), "S1", f"S1{p.get('platform', '')}",
                                        vv_db=10 * math.log10(vv), vh_db=10 * math.log10(vh),
                                        rvi=4 * vh / (vv + vh), orbit=p.get("orbit", "")))

    return sorted(observations, key=lambda o: (o.day, o.sensor))


# ----------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------


def field_geometry(args) -> tuple[str, dict]:
    if args.field:
        for feature in json.loads(Path(args.labels).read_text(encoding="utf-8"))["features"]:
            if feature["properties"]["field_id"] == args.field:
                return args.field, feature["geometry"]
        sys.exit(f"{args.field} is not in {args.labels}")
    from add_label import square_around

    lat, lon = (float(v) for v in args.point.split(","))
    return f"{lat:.6f}_{lon:.6f}", {"type": "Polygon", "coordinates": [square_around(lat, lon, args.radius)]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--point", help="lat,lon of a field centre")
    where.add_argument("--field", help="a field_id from the label set")
    where.add_argument("--all-fields", action="store_true", help="every field in the label set")
    parser.add_argument("--radius", type=float, default=25.0, help="half-width of the square around --point, m")
    parser.add_argument("--labels", default="ml/labels.geojson")
    parser.add_argument("--start", default=(date.today() - timedelta(days=365)).isoformat())
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--edge-buffer", type=float, default=5.0)
    parser.add_argument("--out-dir", type=Path, default=Path("ml/output"))
    parser.add_argument("--key", type=Path, default=Path("terrarisk-platform-bfc1102a3c63.json"))
    parser.add_argument("--project", default="terrarisk-platform")
    parser.add_argument("--plot", action="store_true")
    parser.add_argument(
        "--any-season",
        action="store_true",
        help="Look for harvests in every month. By default only November-April, the sugarcane "
        "crushing season, is searched — for a soybean or cotton field, pass this.",
    )
    args = parser.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    initialise(args.key, args.project)

    if args.all_fields:
        run_all_fields(args, start, end)
        return

    name, geometry = field_geometry(args)
    observations = fetch_observations(geometry, start, end, args.edge_buffer)
    series = build_daily(observations, start, end, harvest_season=season_filter(args))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    obs_path = args.out_dir / f"{name}_observations.csv"
    with obs_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "sensor", "platform", "ndvi", "ndre", "evi", "vv_db", "vh_db", "rvi",
                         "orbit", "clear_fraction", "pixels"])
        for o in observations:
            writer.writerow([o.day, o.sensor, o.platform, o.ndvi, o.ndre, o.evi, o.vv_db, o.vh_db, o.rvi,
                             o.orbit, o.clear_fraction, o.pixels])
    daily_path = args.out_dir / f"{name}_daily.csv"
    with daily_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "ndvi", "flag", "days_to_view"])
        for day, value, flag, distance in zip(series.days, series.ndvi, series.flag, series.days_to_view):
            writer.writerow([day, "" if value is None else round(value, 4), flag, distance])

    optical = [o for o in observations if o.optical]
    radar = [o for o in observations if o.sensor == "S1"]
    view_days = sorted({o.day for o in optical})
    gaps = [(b - a).days for a, b in zip(view_days, view_days[1:])]
    print(f"{name}: {start} to {end}")
    print(f"  clear optical views: {len(view_days)} days "
          f"(S2 {sum(o.sensor == 'S2' for o in optical)}, "
          f"Landsat {sum(o.sensor in ('L8', 'L9') for o in optical)}) | radar passes: {len(radar)}")
    if gaps:
        print(f"  gap between clear views: median {median(gaps):.0f} d, longest {max(gaps)} d")
    counts = {flag: series.flag.count(flag)
              for flag in ("observed", "interpolated", "radar_estimated", "harvest_between_views", "no_data")}
    total = len(series.days)
    print("  days: " + " | ".join(f"{k} {v} ({v / total:.0%})" for k, v in counts.items()))
    print(f"  smoothing lambda {series.smoothing:g}; held-out error of an interpolated day "
          f"±{series.interpolation_rmse:.3f} NDVI on normal views, ±{series.interpolation_rmse_all:.3f} "
          f"counting every view")
    for note in series.notes:
        print(f"  {note}")
    print("\n  month     S2  Landsat  S1   observed  interpolated  radar  no_data")
    for row in availability(series, observations):
        print(f"  {row['month']}  {row['s2']:3d}  {row['landsat']:5d}  {row['s1']:4d}   {row['observed']:6d}  "
              f"{row['interpolated']:10d}  {row['radar_estimated']:6d}  {row['no_data']:6d}")
    print(f"\n  wrote {obs_path} and {daily_path}")

    if args.plot:
        from timeseries_plot import plot_series

        print(f"  plot: {plot_series(name, series, observations, args.out_dir)}")


def season_filter(args):
    if args.any_season:
        return None
    from compare_fields import in_harvest_season

    return in_harvest_season


def run_all_fields(args, start: date, end: date) -> None:
    """Every labelled field: its own daily file, and one summary row each."""
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))["features"]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for feature in labels:
        properties = feature["properties"]
        name = properties["field_id"]
        observations = fetch_observations(feature["geometry"], start, end, args.edge_buffer)
        series = build_daily(observations, start, end, harvest_season=season_filter(args))
        with (args.out_dir / f"{name}_daily.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "ndvi", "flag", "days_to_view"])
            for day, value, flag, distance in zip(series.days, series.ndvi, series.flag, series.days_to_view):
                writer.writerow([day, "" if value is None else round(value, 4), flag, distance])
        if args.plot:
            from timeseries_plot import plot_series

            plot_series(name, series, observations, args.out_dir)

        views = sorted({o.day for o in observations if o.optical})
        gaps = [(b - a).days for a, b in zip(views, views[1:])]
        total = len(series.days)
        row = {
            "field_id": name,
            "cane_type": properties.get("cane_type", ""),
            "stated_cycle_start": properties.get("planted", ""),
            "clear_views": len(views),
            "median_gap_days": median(gaps) if gaps else "",
            "longest_gap_days": max(gaps) if gaps else "",
            "radar_passes": sum(o.sensor == "S1" for o in observations),
            "observed_pct": round(100 * series.flag.count("observed") / total),
            "interpolated_pct": round(100 * series.flag.count("interpolated") / total),
            "no_data_pct": round(100 * series.flag.count("no_data") / total),
            "harvests_seen": "; ".join(f"{a}..{b}" for a, b in series.breaks),
            "error_normal": round(series.interpolation_rmse, 3),
            "error_all": round(series.interpolation_rmse_all, 3),
            "outlier_views": len(series.outliers),
            "landsat_calibration": (f"{series.calibration.method} {series.calibration.intercept:+.2f}"
                                    f"{'' if series.calibration.method != 'linear' else f' x{series.calibration.slope:.2f}'}"),
            "radar_model_r2": ("" if series.radar_model is None
                               else round(series.radar_model.r2_out_of_sample, 2)),
        }
        summary.append(row)
        print(f"  {name}: {row['clear_views']} views, median gap {row['median_gap_days']} d, "
              f"harvest {row['harvests_seen'] or 'none'} (stated {row['stated_cycle_start']}), "
              f"error ±{row['error_normal']}/{row['error_all']}", flush=True)

    path = args.out_dir / "summary.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
