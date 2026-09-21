"""Tests for phenology feature extraction.

The Shera series below is real: a 0.6 acre plot planted with sugarcane on
20 December 2025, sampled monthly. It is used as a fixture because it
caught a design error no synthetic example would have — see
`test_plant_cane_is_not_separable_by_minimum_ndvi`.

    python -m pytest ml/test_features.py
"""

from __future__ import annotations

import pytest

from features import (
    GREEN_THRESHOLD,
    age_features,
    green_runs,
    greenup_index,
    in_planting_window,
    interpolate_gaps,
    phenology_features,
)

# Nov 2025 - Aug 2026, monthly mean NDVI. Cane planted 20 Dec 2025:
# the previous crop peaks in early December, the field is cleared, and
# the cane climbs from February onward. July and August were entirely
# clouded out; August yielded a single marginal look through a break.
SHERA_PLANT_CANE = [0.31, 0.25, 0.21, 0.34, 0.48, 0.63, 0.58, 0.74, None, 0.59]

# A soybean-shaped kharif crop: sown June, harvested October, then bare.
SOYBEAN = [0.20, 0.35, None, 0.67, 0.45, 0.22, 0.16, 0.15, 0.14, 0.13, 0.15, 0.18]


class TestInterpolateGaps:
    def test_fills_a_short_interior_gap_between_known_neighbours(self) -> None:
        assert interpolate_gaps([0.2, None, 0.4]) == pytest.approx([0.2, 0.3, 0.4])

    def test_leaves_a_long_gap_alone(self) -> None:
        """Beyond the limit, interpolating would invent a season."""
        assert interpolate_gaps([0.2, None, None, None, 0.4], max_gap=2) == [0.2, None, None, None, 0.4]

    def test_leaves_leading_and_trailing_gaps_unknown(self) -> None:
        """There is nothing on one side to interpolate from, and guessing
        past the observed record is how a model learns to hallucinate."""
        assert interpolate_gaps([None, 0.3, 0.4, None]) == [None, 0.3, 0.4, None]

    def test_returns_the_series_unchanged_when_almost_nothing_is_known(self) -> None:
        assert interpolate_gaps([None, 0.3, None]) == [None, 0.3, None]


class TestGreenRuns:
    def test_an_annual_crop_gives_one_short_run(self) -> None:
        """Four months: the gap at index 2 is bridged, correctly — the
        field was green either side of one clouded month."""
        assert green_runs(SOYBEAN) == [4]

    def test_a_double_cropped_field_gives_two_runs(self) -> None:
        series = [0.5, 0.5, 0.1, 0.1, 0.6, 0.6, 0.6]
        assert green_runs(series) == [2, 3]

    def test_a_monsoon_gap_does_not_break_a_run(self) -> None:
        """July and August are routinely lost to cloud over Maharashtra.
        A field green either side of that gap was green through it."""
        assert green_runs([0.5, 0.5, None, 0.5, 0.5]) == [5]

    def test_a_genuine_fallow_period_does_break_a_run(self) -> None:
        assert green_runs([0.5, 0.5, 0.1, 0.5, 0.5]) == [2, 2]


class TestPlantCaneVersusAnnualCrop:
    """The distinction the whole classifier rests on."""

    def test_plant_cane_is_not_separable_by_minimum_ndvi(self) -> None:
        """The error a real field caught.

        Newly planted cane sits at bare-soil NDVI for months while it is
        below detection, so its minimum is no higher than an annual
        crop's. Any rule keyed on the floor misses every new planting.
        """
        cane = phenology_features(SHERA_PLANT_CANE)
        soy = phenology_features(SOYBEAN)

        assert cane["min_ndvi"] < 0.25
        assert cane["min_ndvi"] < soy["min_ndvi"] + 0.10  # no useful separation

    def test_duration_separates_them_clearly(self) -> None:
        cane = phenology_features(SHERA_PLANT_CANE)
        soy = phenology_features(SOYBEAN)

        assert cane["longest_green_run"] >= 7
        assert soy["longest_green_run"] <= 4
        assert cane["longest_green_run"] > soy["longest_green_run"]
        assert cane["green_fraction"] > soy["green_fraction"]

    def test_cane_is_still_green_at_the_end_of_the_window(self) -> None:
        """An annual crop has been harvested by then; cane has not."""
        assert phenology_features(SHERA_PLANT_CANE)["green_at_window_end"] == 1
        assert phenology_features(SOYBEAN)["green_at_window_end"] == 0

    def test_an_annual_crop_ramps_faster_than_cane(self) -> None:
        """Soybean goes trough to peak in a couple of months; cane takes
        far longer, which is a signal in its own right."""
        cane = phenology_features(SHERA_PLANT_CANE)
        soy = phenology_features(SOYBEAN)
        assert cane["months_trough_to_peak"] > soy["months_trough_to_peak"]


class TestHonestAbsence:
    def test_reports_nothing_when_there_is_almost_no_data(self) -> None:
        """Two cloud-free months cannot describe a season. Returning a
        confident-looking feature row from them would be worse than
        returning nothing."""
        assert phenology_features([0.4, None, None, 0.5]) == {"observed_months": 2}

    def test_never_substitutes_zero_for_a_missing_month(self) -> None:
        """NDVI 0 means bare rock. A clouded month means unknown. A
        feature set that confuses the two is measuring the weather."""
        features = phenology_features([0.5, None, 0.5, 0.5, 0.5])
        assert features["min_ndvi"] == 0.5
        assert features["observed_fraction"] == pytest.approx(0.8)

    def test_optional_bands_are_simply_absent_when_not_supplied(self) -> None:
        features = phenology_features(SOYBEAN)
        assert "mean_ndmi" not in features
        assert "vh_mean" not in features


class TestRadarFeatures:
    def test_summarises_radar_without_exposing_single_passes(self) -> None:
        """Speckle makes one pass untrustworthy on a small plot, so only
        aggregates are exposed."""
        features = phenology_features(
            SOYBEAN, vv=[-10.0, -9.0, -8.0], vh=[-18.0, -17.0, -16.0]
        )
        assert features["vh_mean"] == pytest.approx(-17.0)
        assert features["vh_slope"] == pytest.approx(1.0)
        assert features["vv_vh_difference"] == pytest.approx(8.0)


def test_green_threshold_sits_between_bare_soil_and_canopy() -> None:
    assert 0.15 < GREEN_THRESHOLD < 0.45


# ----------------------------------------------------------------------
# Age: how long the canopy has been green, and whether the start was seen
# ----------------------------------------------------------------------


def test_greenup_is_the_month_the_canopy_left_bare_soil():
    """Plant cane: bare until it emerges, then green and staying green."""
    series = [0.15, 0.16, 0.18, 0.45, 0.62, 0.71, 0.78, 0.80]
    assert greenup_index(series) == 3


def test_a_single_green_month_is_not_a_greenup():
    """One cloudy month's artefact must not be read as a planting."""
    series = [0.15, 0.16, 0.55, 0.14, 0.15, 0.16, 0.15, 0.14]
    assert greenup_index(series) is None


def test_the_last_greenup_wins_because_ratoon_starts_a_new_cycle():
    """Harvested in the middle, regrown after: the age of the crop
    standing now is counted from the regrowth, not the first planting."""
    series = [0.15, 0.50, 0.70, 0.75, 0.12, 0.14, 0.48, 0.66, 0.72]
    assert greenup_index(series) == 6


def test_age_is_counted_from_greenup_to_the_end_of_the_window():
    series = [0.15, 0.16, 0.18, 0.45, 0.62, 0.71, 0.78, 0.80]
    features = age_features(series)
    assert features["months_since_greenup"] == 5
    assert features["greenup_observed"] == 1
    assert features["age_is_lower_bound"] == 0


def test_a_field_already_green_when_the_window_opened_gives_only_a_lower_bound():
    """Nothing here can date a crop that started before we were looking,
    and inventing a date is worse than saying 'at least this long'."""
    series = [0.62, 0.68, 0.72, 0.75, 0.77, 0.79]
    features = age_features(series)
    assert features["months_since_greenup"] == 6
    assert features["greenup_observed"] == 0
    assert features["age_is_lower_bound"] == 1


def test_a_bare_field_has_no_age():
    features = age_features([0.12, 0.14, 0.13, 0.15])
    assert features["months_since_greenup"] is None
    assert features["age_is_lower_bound"] == 1


def test_a_monsoon_gap_does_not_restart_the_age():
    """July and August routinely give no usable optical observation. A
    gap is 'we did not see', so the green run continues through it."""
    series = [0.15, 0.45, 0.65, None, None, 0.74, 0.78]
    assert age_features(series)["months_since_greenup"] == 6


def test_planting_window_is_november_to_march():
    """Stated by the founder for the Latur area, 21 Sep 2026."""
    assert [m for m in range(1, 13) if in_planting_window(m)] == [1, 2, 3, 11, 12]


def test_age_features_are_included_in_the_full_feature_set():
    series = [0.15, 0.16, 0.18, 0.45, 0.62, 0.71, 0.78, 0.80]
    assert phenology_features(series)["months_since_greenup"] == 5
