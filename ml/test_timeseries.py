"""Tests for the daily fusion. No Earth Engine: every case is a series
built by hand, so each rule — what counts as observed, when a gap is too
long to interpolate, when radar is trusted — is checked on its own."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from timeseries import (
    MAX_INTERPOLATION_DAYS,
    Observation,
    build_daily,
    choose_smoothing,
    cross_sensor_calibration,
    find_breaks,
    fit_radar_model,
    smooth_segment,
    whittaker,
)

START = date(2026, 1, 1)


def s2(day_offset: int, ndvi: float) -> Observation:
    return Observation(START + timedelta(days=day_offset), "S2", "Sentinel-2B", ndvi=ndvi)


def test_whittaker_leaves_a_straight_line_alone():
    """A second-difference penalty costs nothing on a straight line, so a
    perfectly linear green-up must come back unchanged."""
    values = np.linspace(0.2, 0.8, 50)
    weights = np.ones(50)
    assert np.allclose(whittaker(values, weights, 100.0), values, atol=1e-6)


def test_whittaker_fills_a_gap_from_the_curve_either_side():
    values = np.linspace(0.2, 0.8, 50)
    weights = np.ones(50)
    weights[20:30] = 0.0
    values[20:30] = np.nan
    filled = whittaker(values, weights, 10.0)
    assert np.allclose(filled[20:30], np.linspace(0.2, 0.8, 50)[20:30], atol=1e-3)


def test_leave_one_out_prefers_little_smoothing_for_a_sharp_harvest():
    """A cut is a step. A heavy smoother would round it off and predict
    held-out points badly, so cross-validation should not pick it."""
    values = np.full(120, np.nan)
    weights = np.zeros(120)
    for day in range(0, 120, 5):
        values[day] = 0.75 if day < 60 else 0.25
        weights[day] = 1.0
    chosen, _ = choose_smoothing(values, weights)
    assert chosen <= 30


def landsat(day_offset: int, ndvi: float) -> Observation:
    return Observation(START + timedelta(days=day_offset), "L8", "L8", ndvi=ndvi)


def test_too_few_pairs_means_no_calibration():
    obs = [s2(0, 0.60), landsat(0, 0.55), s2(10, 0.70), landsat(11, 0.66)]
    assert cross_sensor_calibration(obs).method == "none"


def test_a_constant_bias_is_corrected_with_an_offset():
    obs = []
    for k, level in enumerate([0.3, 0.4, 0.5, 0.6, 0.7]):
        obs += [s2(10 * k, level), landsat(10 * k, level - 0.05)]
    calibration = cross_sensor_calibration(obs)
    assert calibration.method == "offset"
    assert calibration.apply(0.45) == pytest.approx(0.50, abs=1e-6)


def test_mixed_pixel_compression_is_corrected_with_a_line():
    """The real case: Landsat's 30 m pixel pulls values toward the local
    average, so its range is squeezed. A constant offset averages to ~0
    and fixes nothing; a straight line undoes the squeeze."""
    rng = np.random.default_rng(3)
    obs = []
    for k in range(12):
        true = 0.25 + 0.05 * k
        obs += [s2(10 * k, true), landsat(10 * k, 0.15 + 0.69 * true + float(rng.normal(0, 0.005)))]
    calibration = cross_sensor_calibration(obs)
    assert calibration.method == "linear"
    assert calibration.slope == pytest.approx(1 / 0.69, rel=0.05)
    assert calibration.error_linear < calibration.error_offset


def test_days_are_labelled_observed_interpolated_or_no_data():
    obs = [s2(0, 0.30), s2(5, 0.35), s2(10, 0.40), s2(60, 0.70)]
    series = build_daily(obs, START, START + timedelta(days=60))
    assert series.flag[0] == "observed"
    assert series.flag[7] == "interpolated"
    # day 35 is 25 days from any view: too far to call interpolated
    assert series.flag[35] == "no_data" and series.ndvi[35] is None
    assert series.days_to_view[35] == 25


def test_nothing_further_than_the_interpolation_limit_gets_a_value():
    obs = [s2(0, 0.3), s2(40, 0.7)]
    series = build_daily(obs, START, START + timedelta(days=40))
    for value, flag, distance in zip(series.ndvi, series.flag, series.days_to_view):
        if distance > MAX_INTERPOLATION_DAYS:
            assert value is None and flag == "no_data"


def test_radar_model_is_refused_with_too_few_pairs():
    model = fit_radar_model([(0.5, -15.0, -9.0)] * 3)
    assert not model.usable and "pairs" in model.reason


def test_radar_model_is_refused_when_radar_does_not_predict_ndvi():
    rng = np.random.default_rng(0)
    pairs = [(float(rng.uniform(0.2, 0.8)), float(rng.uniform(-22, -14)), float(rng.uniform(-13, -7)))
             for _ in range(20)]
    model = fit_radar_model(pairs)
    assert not model.usable


def test_radar_model_is_accepted_when_it_genuinely_predicts():
    rng = np.random.default_rng(1)
    pairs = []
    for _ in range(20):
        vh = float(rng.uniform(-22, -14))
        vv = float(rng.uniform(-13, -7))
        pairs.append((0.06 * vh + 1.8 + float(rng.normal(0, 0.02)), vh, vv))
    model = fit_radar_model(pairs)
    assert model.usable and model.r2_out_of_sample > 0.8


def test_two_views_on_one_day_are_averaged_not_double_counted():
    obs = [s2(0, 0.40), Observation(START, "L8", "L8", ndvi=0.50), s2(5, 0.45), s2(10, 0.5)]
    series = build_daily(obs, START, START + timedelta(days=10))
    assert series.flag[0] == "observed"



def test_a_harvest_is_found_between_the_last_standing_and_first_cut_view():
    days = [START + timedelta(days=5 * k) for k in range(10)]
    values = [0.72, 0.74, 0.71, 0.73, 0.28, 0.27, 0.30, 0.33, 0.36, 0.40]
    assert find_breaks(days, values) == [(days[3], days[4])]


def test_a_single_low_pass_between_canopy_views_is_not_a_harvest():
    days = [START + timedelta(days=5 * k) for k in range(6)]
    assert find_breaks(days, [0.72, 0.74, 0.25, 0.73, 0.72, 0.74]) == []


def test_a_gradual_decline_is_not_a_harvest():
    """Senescence or drought lowers NDVI over weeks; no single step of
    0.20 means no cut."""
    days = [START + timedelta(days=5 * k) for k in range(10)]
    assert find_breaks(days, [0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30]) == []


def test_the_harvest_step_survives_smoothing():
    """The failure seen on shera-02: one smooth curve across the cut spread
    a one-week harvest over six weeks. Segmenting at the break keeps the
    levels either side intact."""
    obs = [s2(5 * k, 0.72) for k in range(8)] + [s2(40 + 5 * k, 0.27 + 0.01 * k) for k in range(8)]
    series = build_daily(obs, START, START + timedelta(days=75))
    assert len(series.breaks) == 1
    assert series.ndvi[35] == pytest.approx(0.72, abs=0.03)   # last standing view
    assert series.ndvi[40] == pytest.approx(0.27, abs=0.03)   # first cut view
    assert all(f == "harvest_between_views" for f in series.flag[36:40])
    assert all(v is None for v in series.ndvi[36:40])


def test_one_strange_pass_does_not_drag_the_curve():
    """Cloud Score+ called 20 Apr, 19 Jun and 11 Jul 2026 fully clear, yet
    each sat 0.11-0.20 off its neighbours. The robust fit must discount a
    pass like that instead of bending toward it."""
    values = np.full(60, np.nan)
    weights = np.zeros(60)
    for day in range(0, 60, 4):
        values[day], weights[day] = 0.50, 1.0
    values[28] = 0.70
    curve, robust = smooth_segment(values, weights, 1000.0)
    assert robust[28] < 0.1
    assert curve[28] == pytest.approx(0.50, abs=0.02)


def test_a_monsoon_drop_is_not_a_harvest_when_the_season_is_enforced():
    """Two ratoon fields 'harvested' again on 19-29 June 2026 — the same
    dates in both, at the monsoon onset. With the crushing season enforced
    that is not a break; without it, it would be."""
    from compare_fields import in_harvest_season

    days = [date(2026, 5, 20) + timedelta(days=5 * k) for k in range(10)]
    values = [0.55, 0.56, 0.58, 0.57, 0.59, 0.30, 0.32, 0.35, 0.40, 0.44]  # drop lands on 14 June
    assert find_breaks(days, values) != []
    assert find_breaks(days, values, season=in_harvest_season) == []
