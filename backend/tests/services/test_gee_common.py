"""Regression tests for the shared GEE helper module (ticket M1-002).

Proves the extracted module is independently usable — by name, and
without needing `gee_provider.py` at all — since that independence is the
entire point of the extraction (Blueprint v2 D1: a future
GEEHydrologyProvider imports from here, not from gee_provider.py).
Behavioral coverage for these exact values already exists in
test_gee_provider.py's TestMonthlyPeriods class, exercised through the
re-exported `_monthly_periods` name; this file does not duplicate that,
it only proves the canonical module and names work on their own.
"""

from __future__ import annotations

from datetime import date

from app.services.satellite._gee_common import CLOUD_PROBABILITY_THRESHOLD, monthly_periods


class TestSharedModuleIsSelfContained:
    def test_monthly_periods_is_callable_from_the_canonical_module(self):
        periods = monthly_periods(date(2024, 1, 15), date(2024, 4, 1))
        assert periods == [
            (date(2024, 1, 1), date(2024, 2, 1)),
            (date(2024, 2, 1), date(2024, 3, 1)),
            (date(2024, 3, 1), date(2024, 4, 1)),
        ]

    def test_cloud_probability_threshold_matches_the_approved_methodology(self):
        assert CLOUD_PROBABILITY_THRESHOLD == 20


class TestBackwardCompatibleReExport:
    def test_gee_provider_still_exposes_the_original_private_names(self):
        from app.services.satellite.gee_provider import _CLOUD_PROBABILITY_THRESHOLD, _monthly_periods

        assert _monthly_periods is monthly_periods
        assert _CLOUD_PROBABILITY_THRESHOLD == CLOUD_PROBABILITY_THRESHOLD
