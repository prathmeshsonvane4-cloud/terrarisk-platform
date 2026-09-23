"""Tests for harvest and regrowth detection.

A harvest is the signature that matters most here: the 23 September 2026
batch was fourteen ratoon fields, each identified by the farmer through
the date its previous crop was cut. If the cut cannot be found in the
curve, none of those labels can be checked against the imagery.
"""

from __future__ import annotations

import pytest

from compare_fields import correlation, cut_month, in_harvest_season, radar_cut_month, regrowth_month

MONTHS = [f"2025-{m:02d}" for m in range(4, 13)] + [f"2026-{m:02d}" for m in range(1, 10)]


def test_finds_the_month_a_standing_crop_went_bare():
    # green through 2025, cut in January 2026, bare after
    series = [0.55, 0.62, 0.70, 0.72, 0.74, 0.73, 0.71, 0.70, 0.69,
              0.22, 0.20, 0.24, 0.28, 0.30, 0.35, 0.40, 0.45, 0.50]
    assert cut_month(MONTHS, series) == "2026-01"


def test_one_cloudy_reading_is_not_a_harvest():
    """A single low month between green months must not be read as a cut,
    or every hazy December becomes a harvest."""
    series = [0.55, 0.62, 0.70, 0.72, 0.20, 0.73, 0.71, 0.70, 0.69,
              0.68, 0.70, 0.72, 0.71, 0.70, 0.69, 0.70, 0.71, 0.70]
    assert cut_month(MONTHS, series) is None


def test_a_field_that_was_never_green_has_no_cut():
    assert cut_month(MONTHS, [0.15] * 18) is None


def test_regrowth_is_the_first_sustained_return_above_the_threshold():
    series = [0.55, 0.62, 0.70, 0.72, 0.74, 0.73, 0.71, 0.70, 0.69,
              0.22, 0.20, 0.24, 0.28, 0.34, 0.40, 0.45, 0.50, 0.55]
    cut = cut_month(MONTHS, series)
    assert cut == "2026-01"
    assert regrowth_month(MONTHS, series, cut) == "2026-05"


def test_regrowth_ignores_a_single_month_bump():
    series = [0.55, 0.62, 0.70, 0.72, 0.74, 0.73, 0.71, 0.70, 0.69,
              0.22, 0.20, 0.45, 0.20, 0.22, 0.40, 0.48, 0.52, 0.58]
    # March's single 0.45 is skipped; the sustained return is June.
    assert regrowth_month(MONTHS, series, "2026-01") == "2026-06"


def test_correlation_needs_enough_overlapping_months():
    """Two fields whose cloud-free months barely overlap cannot be
    compared, and must return nothing rather than a number from three
    points."""
    a = [0.5, None, None, None, 0.6, None, None, None]
    b = [None, 0.4, 0.5, 0.6, None, 0.7, 0.8, 0.9]
    assert correlation(a, b) is None


def test_identical_curves_correlate_at_one():
    series = [0.2, 0.3, 0.45, 0.6, 0.7, 0.75, 0.8, 0.82]
    assert correlation(series, series) == pytest.approx(1.0)


def test_opposite_curves_correlate_negatively():
    rising = [0.2, 0.3, 0.45, 0.6, 0.7, 0.75]
    falling = list(reversed(rising))
    assert correlation(rising, falling) < -0.9


def test_radar_finds_a_harvest_as_a_fall_in_vh():
    # cane canopy around -15 dB, cut in February to bare soil near -22 dB
    vh = [-15.0, -15.5, -14.8, -15.2, -15.0, -14.9, -15.3, -15.1, -15.4,
          -15.2, -22.0, -20.5, -19.0, -18.0, -17.0, -16.5, -16.0, -15.8]
    month, drop = radar_cut_month(MONTHS, vh)
    assert month == "2026-02"
    assert drop > 6


def test_radar_ignores_a_one_month_dip_that_recovers():
    """Wet soil after rain moves VH for a pass or two. A canopy cannot
    regrow in a month, so a dip that recovers is not a cut."""
    vh = [-15.0] * 5 + [-19.0] + [-15.0] * 12
    assert radar_cut_month(MONTHS, vh) is None


def test_season_filter_stops_a_monsoon_dip_being_read_as_the_harvest():
    """The failure seen on real fields: a larger fall in August (soil
    moisture) beats the real January cut unless the search is confined to
    the months cane is actually harvested."""
    # canopy -15 dB; a 6 dB monsoon swing in Aug-Oct; canopy again in
    # Nov-Dec; the real cut in January (5 dB), then slow regrowth.
    vh = [-15.0, -15.0, -15.0, -15.0, -21.0, -21.0, -20.0, -15.0, -15.0,
          -20.0, -19.5, -19.0, -18.5, -18.0, -17.5, -17.0, -16.5, -16.0]
    assert radar_cut_month(MONTHS, vh)[0] == "2025-08"
    assert radar_cut_month(MONTHS, vh, allowed=in_harvest_season)[0] == "2026-01"


def test_harvest_season_is_november_to_april():
    months = [m for m in range(1, 13) if in_harvest_season(f"2026-{m:02d}")]
    assert months == [1, 2, 3, 4, 11, 12]


def test_a_detection_inside_a_stated_range_scores_zero():
    from compare_fields import month_gap
    assert month_gap("2026-01", "2026-01..2026-02") == 0
    assert month_gap("2026-02", "2026-01..2026-02") == 0
    assert month_gap("2025-12", "2026-01..2026-02") == -1
    assert month_gap("2026-04", "2026-01..2026-02") == 2
    assert month_gap("2026-02", "2026-01") == 1
