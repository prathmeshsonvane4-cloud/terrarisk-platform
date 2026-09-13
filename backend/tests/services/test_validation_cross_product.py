"""Tests for cross-product consistency checks.

Anchored on a real measurement: MOD16A2 (current method) and PML_V2 on a
Maski-area polygon, water year 2022-23 — 500 mm vs 811 mm of ET against
610 mm of rainfall. See cross_product.py's docstring.
"""

from __future__ import annotations

import inspect

import pytest

from app.services.validation import (
    Severity,
    relative_difference,
    validate_cross_product_agreement,
)

_MASKI_MOD16A2_MM = 499.6
_MASKI_PML_V2_MM = 811.5


def _maski(tolerance: float, **kwargs):
    return validate_cross_product_agreement(
        quantity="et_mm",
        primary_name="MOD16A2",
        primary_value=_MASKI_MOD16A2_MM,
        secondary_name="PML_V2",
        secondary_value=_MASKI_PML_V2_MM,
        tolerance=tolerance,
        **kwargs,
    )


class TestTheToleranceIsAlwaysADecision:
    def test_there_is_no_default_tolerance(self):
        """Removing this test to add a default is removing the design."""
        tolerance = inspect.signature(validate_cross_product_agreement).parameters["tolerance"]
        assert tolerance.default is inspect.Parameter.empty

    def test_a_zero_or_negative_tolerance_is_refused(self):
        with pytest.raises(ValueError):
            _maski(tolerance=0.0)

    def test_the_tolerance_used_is_recorded_in_the_finding(self):
        finding = _maski(tolerance=0.25).warnings[0]
        assert "25% tolerance" in finding.message
        assert "not a calibrated bound" in finding.source


class TestMaskiMeasurement:
    def test_the_two_products_disagree_by_about_48_percent(self):
        assert relative_difference(_MASKI_MOD16A2_MM, _MASKI_PML_V2_MM) == pytest.approx(0.476, abs=0.005)

    def test_a_conventional_sounding_tolerance_fails_this_site(self):
        report = _maski(tolerance=0.25)
        assert report.failed
        assert report.warnings[0].severity is Severity.WARNING

    def test_a_tolerance_wide_enough_to_pass_it_is_very_wide(self):
        """Pins what passing Maski would cost: a tolerance near 50%,
        which is why the choice is left to a person."""
        assert not _maski(tolerance=0.50).failed
        assert _maski(tolerance=0.45).failed

    def test_the_finding_refuses_to_say_which_product_is_right(self):
        assert "nothing in this check says which" in _maski(tolerance=0.25).warnings[0].message


class TestHonestCaveats:
    def test_partial_independence_is_stated_on_every_disagreement(self):
        assert "not sensor independence" in _maski(tolerance=0.25).warnings[0].message

    def test_an_uncovered_window_is_reported_even_when_the_products_agree(self):
        report = validate_cross_product_agreement(
            quantity="et_mm",
            primary_name="MOD16A2",
            primary_value=500.0,
            secondary_name="PML_V22a",
            secondary_value=510.0,
            tolerance=0.25,
            uncovered_span="Jan 2025 - Aug 2026",
        )
        assert not report.failed
        assert "validates only the overlapping period" in report.findings[0].message

    def test_a_missing_secondary_value_skips_rather_than_passes(self):
        report = validate_cross_product_agreement(
            quantity="et_mm",
            primary_name="MOD16A2",
            primary_value=500.0,
            secondary_name="PML_V22a",
            secondary_value=None,
            tolerance=0.25,
        )
        assert report.checks_run == 0
        assert report.checks_skipped == 1


class TestRelativeDifference:
    def test_it_is_symmetric(self):
        """|a-b|/a would give 62% or 38% for the same pair depending on
        which product is called primary."""
        assert relative_difference(500.0, 811.0) == relative_difference(811.0, 500.0)

    def test_two_zeros_are_undefined_not_in_agreement(self):
        assert relative_difference(0.0, 0.0) is None
