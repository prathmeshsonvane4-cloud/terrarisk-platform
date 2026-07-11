"""Tests for the Earth Engine adapter.

Split into two groups: pure/offline tests for the logic that doesn't touch
the network (period generation, null-observation parsing), which always
run; and live integration tests against real Earth Engine, which skip
cleanly wherever GEE_PROJECT_ID / GEE_SERVICE_ACCOUNT_JSON_PATH aren't
configured (see docs/DECISIONS.md for the setup walkthrough) rather than
failing the suite.
"""

import os
from datetime import date

import pytest

from app.services.satellite.gee_provider import GeeProvider, _monthly_periods
from app.services.satellite.provider import IndexObservation, SatelliteIndex

_requires_gee_credentials = pytest.mark.skipif(
    not (os.environ.get("GEE_PROJECT_ID") and os.environ.get("GEE_SERVICE_ACCOUNT_JSON_PATH")),
    reason="GEE credentials not configured — see docs/DECISIONS.md setup walkthrough",
)

# A ~1km bounding box over Latur district, Maharashtra — real cropland, used
# only to prove connectivity end-to-end, not for any product-facing report.
_SAMPLE_POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[76.45, 18.40], [76.46, 18.40], [76.46, 18.41], [76.45, 18.41], [76.45, 18.40]]],
}


class TestMonthlyPeriods:
    def test_three_year_lookback_produces_36_monthly_periods(self):
        periods = _monthly_periods(date(2023, 1, 15), date(2026, 1, 1))
        assert len(periods) == 36

    def test_periods_are_calendar_month_aligned_regardless_of_start_day(self):
        periods = _monthly_periods(date(2023, 1, 15), date(2023, 3, 1))
        assert periods[0] == (date(2023, 1, 1), date(2023, 2, 1))
        assert periods[1] == (date(2023, 2, 1), date(2023, 3, 1))

    def test_year_boundary_is_handled(self):
        periods = _monthly_periods(date(2023, 11, 1), date(2024, 2, 1))
        assert periods == [
            (date(2023, 11, 1), date(2023, 12, 1)),
            (date(2023, 12, 1), date(2024, 1, 1)),
            (date(2024, 1, 1), date(2024, 2, 1)),
        ]


class TestParseMonthlyFeatures:
    def test_missing_month_is_skipped_not_coerced_to_zero(self):
        """A cloud-blanked month must be omitted, never returned as a
        misleading value=0.0 — callers rely on this to distinguish 'no
        data' from 'measured zero'."""
        periods = [(date(2023, 1, 1), date(2023, 2, 1)), (date(2023, 2, 1), date(2023, 3, 1))]
        features = [{"properties": {"value": None}}, {"properties": {"value": 0.42}}]

        result = GeeProvider._parse_monthly_features(features, periods)

        assert len(result) == 1
        assert result[0] == IndexObservation(period_start=date(2023, 2, 1), period_end=date(2023, 3, 1), value=0.42)

    def test_all_months_present(self):
        periods = [(date(2023, 1, 1), date(2023, 2, 1))]
        features = [{"properties": {"value": 0.5}}]
        result = GeeProvider._parse_monthly_features(features, periods)
        assert len(result) == 1
        assert result[0].value == 0.5


@_requires_gee_credentials
def test_ndvi_monthly_time_series_returns_real_values():
    provider = GeeProvider()
    observations = provider.get_index_time_series(
        _SAMPLE_POLYGON_GEOJSON, SatelliteIndex.NDVI, date(2025, 1, 1), date(2025, 4, 1)
    )
    # Up to 3 monthly composites for a 3-month window; fewer if a month was
    # entirely cloud-blanked, but never more.
    assert 0 <= len(observations) <= 3
    for obs in observations:
        assert -1.0 <= obs.value <= 1.0


@_requires_gee_credentials
def test_rainfall_climatology_returns_all_twelve_months():
    provider = GeeProvider()
    climatology = provider.get_rainfall_climatology(_SAMPLE_POLYGON_GEOJSON)
    assert set(climatology.keys()) == set(range(1, 13))
    assert all(v >= 0 for v in climatology.values())


@_requires_gee_credentials
def test_water_history_returns_a_real_value():
    provider = GeeProvider()
    summary = provider.get_water_history(_SAMPLE_POLYGON_GEOJSON)
    assert 0.0 <= summary.occurrence_percent <= 100.0


def test_sar_backscatter_is_deliberately_unimplemented():
    """Not skipped by the credentials guard — this proves the deferred-SAR
    seam itself, which needs no live GEE connection."""
    with pytest.raises(NotImplementedError, match="deferred post-MVP"):
        GeeProvider.get_sar_backscatter_series(
            object.__new__(GeeProvider), _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 3, 1)
        )
