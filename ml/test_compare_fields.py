"""Tests for harvest and regrowth detection.

A harvest is the signature that matters most here: the 23 September 2026
batch was fourteen ratoon fields, each identified by the farmer through
the date its previous crop was cut. If the cut cannot be found in the
curve, none of those labels can be checked against the imagery.
"""

from __future__ import annotations

import pytest

from compare_fields import correlation, cut_month, regrowth_month

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
