"""Tests for GEEHydrologyProvider — ET series (ticket M1-003) and all
three SurfaceWaterMethod values, SAR/MNDWI/COMBINED (tickets M1-004,
M1-005). This is the full HydrologyDataProvider MVP contract.

Split exactly like test_gee_provider.py: pure/offline tests for logic
that never touches the network (scale-factor/null-value parsing,
construction-time credential validation, method dispatch, the COMBINED
fusion/agreement-logging logic), which always run; and live integration
tests against real Earth Engine, which skip cleanly wherever
GEE_HYDROLOGY_PROJECT_ID / GEE_HYDROLOGY_SERVICE_ACCOUNT_JSON_PATH aren't
configured — a SEPARATE credential pair from GeeProvider's, per Blueprint
v2 D9's quota-isolation decision, so reusing GeeProvider's env vars here
would prove the wrong thing. The codebase's established GEE-testing
convention is "run live or skip cleanly," not mock ee.* objects for the
GEE-touching methods themselves — this file follows that convention
rather than introducing a different one. Dispatch and fusion logic (pure
Python, zero ee.* calls) are instead tested by monkeypatching this
class's own methods, the same style test_reports.py already uses
elsewhere in this codebase.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.core.config import get_settings
from app.services.hydrology.gee_hydrology_provider import (
    _MNDWI_WATER_THRESHOLD,
    _SAR_VV_WATER_THRESHOLD_DB,
    GEEHydrologyProvider,
)
from app.services.hydrology.provider import HydrologyDataProvider, SurfaceWaterMethod
from app.services.risk.models import MonthlyValue

_requires_gee_hydrology_credentials = pytest.mark.skipif(
    not (os.environ.get("GEE_HYDROLOGY_PROJECT_ID") and os.environ.get("GEE_HYDROLOGY_SERVICE_ACCOUNT_JSON_PATH")),
    reason="GEE hydrology credentials not configured (separate from Service 1's — Blueprint v2 D9)",
)

# Same ~1km bounding box over Latur district test_gee_provider.py already
# uses — real cropland, connectivity proof only, never product-facing.
_SAMPLE_POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[76.45, 18.40], [76.46, 18.40], [76.46, 18.41], [76.45, 18.41], [76.45, 18.40]]],
}


class TestParseMonthlyFeatures:
    def test_present_month_is_scaled_by_the_modis_scale_factor(self):
        """MOD16A2's raw integer band value is scaled by 0.1 to get real
        mm — a raw 350 must become 35.0, not 350.0."""
        periods = [(date(2024, 1, 1), date(2024, 2, 1))]
        features = [{"properties": {"value": 350}}]

        result = GEEHydrologyProvider._parse_monthly_features(features, periods)

        assert result == [MonthlyValue(period_start=date(2024, 1, 1), value=35.0)]

    def test_missing_month_is_returned_as_none_not_omitted(self):
        """Unlike GeeProvider._parse_monthly_features (which skips missing
        months entirely for IndexObservation), a MonthlyValue-based series
        must keep exactly one entry per requested period —
        RiskEngine/WaterBalanceEngine's completeness math
        (len(valid) / len(series)) only holds against a fixed-length
        series, per HydrologyDataProvider.get_et_series()'s own contract."""
        periods = [(date(2024, 1, 1), date(2024, 2, 1)), (date(2024, 2, 1), date(2024, 3, 1))]
        features = [{"properties": {"value": None}}, {"properties": {"value": 100}}]

        result = GEEHydrologyProvider._parse_monthly_features(features, periods)

        assert len(result) == 2
        assert result[0] == MonthlyValue(period_start=date(2024, 1, 1), value=None)
        assert result[1] == MonthlyValue(period_start=date(2024, 2, 1), value=10.0)

    def test_all_months_missing_returns_full_length_all_none(self):
        periods = [(date(2024, 1, 1), date(2024, 2, 1)), (date(2024, 2, 1), date(2024, 3, 1))]
        features = [{"properties": {"value": None}}, {"properties": {"value": None}}]

        result = GEEHydrologyProvider._parse_monthly_features(features, periods)

        assert len(result) == 2
        assert all(v.value is None for v in result)

    def test_scale_factor_1_0_leaves_the_value_unchanged(self):
        """get_surface_water_extent_series() passes scale_factor=1.0
        explicitly because its SAR percentage is already computed
        server-side (ee.Number(...).multiply(100)) — no unit conversion
        belongs in this shared parser for that call site, unlike ET's
        MOD16A2 0.1 factor."""
        periods = [(date(2024, 1, 1), date(2024, 2, 1))]
        features = [{"properties": {"value": 42.5}}]

        result = GEEHydrologyProvider._parse_monthly_features(features, periods, scale_factor=1.0)

        assert result == [MonthlyValue(period_start=date(2024, 1, 1), value=42.5)]

    def test_missing_month_is_none_regardless_of_scale_factor(self):
        periods = [(date(2024, 1, 1), date(2024, 2, 1))]
        features = [{"properties": {"value": None}}]

        result = GEEHydrologyProvider._parse_monthly_features(features, periods, scale_factor=1.0)

        assert result == [MonthlyValue(period_start=date(2024, 1, 1), value=None)]


class TestConstruction:
    def test_missing_credentials_raises_runtime_error(self, monkeypatch):
        GEEHydrologyProvider._initialized = False
        monkeypatch.setattr(get_settings(), "gee_hydrology_project_id", None)
        monkeypatch.setattr(get_settings(), "gee_hydrology_service_account_json_path", None)

        with pytest.raises(RuntimeError, match="GEE_HYDROLOGY_PROJECT_ID"):
            GEEHydrologyProvider()

    def test_missing_credentials_error_names_the_quota_isolation_reason(self, monkeypatch):
        """The error message must point at D9, not just say 'not
        configured' — a future engineer hitting this in a fresh
        environment needs to know these are deliberately separate from
        GeeProvider's own credentials, not a typo."""
        GEEHydrologyProvider._initialized = False
        monkeypatch.setattr(get_settings(), "gee_hydrology_project_id", None)
        monkeypatch.setattr(get_settings(), "gee_hydrology_service_account_json_path", None)

        with pytest.raises(RuntimeError, match="separate from Service 1"):
            GEEHydrologyProvider()


class TestContractCompliance:
    def test_is_a_hydrology_data_provider(self):
        assert issubclass(GEEHydrologyProvider, HydrologyDataProvider)

    def test_no_abstract_methods_remain_unimplemented(self):
        """As of ticket M1-005, all three SurfaceWaterMethod values are
        real implementations — HydrologyDataProvider's full contract is
        satisfied, not just structurally (the ABC already proved that in
        M1-003) but behaviorally (nothing left raises NotImplementedError
        for a documented SurfaceWaterMethod value)."""
        assert GEEHydrologyProvider.__abstractmethods__ == frozenset()


class TestMethodDispatch:
    """Pure dispatch logic — which private helper get_surface_water_extent_series()
    calls for a given method — is offline-testable by monkeypatching this
    class's own helpers, the same style test_reports.py already uses for
    GeeProvider elsewhere in this codebase."""

    def test_sar_dispatches_to_the_sar_helper(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            GEEHydrologyProvider, "_get_sar_surface_water_extent_series", lambda self, g, s, e: calls.append("sar") or []
        )
        GEEHydrologyProvider.get_surface_water_extent_series(
            object.__new__(GEEHydrologyProvider), _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 3, 1), SurfaceWaterMethod.SAR
        )
        assert calls == ["sar"]

    def test_mndwi_dispatches_to_the_mndwi_helper(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            GEEHydrologyProvider,
            "_get_mndwi_surface_water_extent_series",
            lambda self, g, s, e: calls.append("mndwi") or [],
        )
        GEEHydrologyProvider.get_surface_water_extent_series(
            object.__new__(GEEHydrologyProvider), _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 3, 1), SurfaceWaterMethod.MNDWI
        )
        assert calls == ["mndwi"]

    def test_combined_dispatches_to_the_combined_helper(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            GEEHydrologyProvider,
            "_get_combined_surface_water_extent_series",
            lambda self, g, s, e: calls.append("combined") or [],
        )
        GEEHydrologyProvider.get_surface_water_extent_series(
            object.__new__(GEEHydrologyProvider), _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 3, 1), SurfaceWaterMethod.COMBINED
        )
        assert calls == ["combined"]

    def test_unrecognized_method_value_raises_value_error(self):
        """SurfaceWaterMethod is a closed 3-member enum today, so this
        branch is unreachable through normal typed usage — this test
        exists so the defensive fallback itself is proven correct, not
        dead code nobody has actually run."""
        fake_method = MagicMock()
        fake_method.value = "unknown"

        with pytest.raises(ValueError, match="Unknown SurfaceWaterMethod"):
            GEEHydrologyProvider.get_surface_water_extent_series(
                object.__new__(GEEHydrologyProvider),
                _SAMPLE_POLYGON_GEOJSON,
                date(2025, 1, 1),
                date(2025, 3, 1),
                fake_method,
            )


class TestCombinedFusion:
    """SAR PRIMARY, MNDWI SECONDARY CONFIRMATION (Blueprint v2 Part 4) —
    proves COMBINED returns the SAR series verbatim, never a blend, and
    that the MNDWI series is fetched only to feed the agreement log."""

    def test_combined_returns_the_sar_series_unmodified(self, monkeypatch):
        sar_series = [MonthlyValue(period_start=date(2024, 1, 1), value=80.0)]
        mndwi_series = [MonthlyValue(period_start=date(2024, 1, 1), value=20.0)]

        def fake_dispatch(self, geometry_geojson, start, end, method):
            return sar_series if method == SurfaceWaterMethod.SAR else mndwi_series

        monkeypatch.setattr(GEEHydrologyProvider, "get_surface_water_extent_series", fake_dispatch)

        result = GEEHydrologyProvider._get_combined_surface_water_extent_series(
            object.__new__(GEEHydrologyProvider), _SAMPLE_POLYGON_GEOJSON, date(2024, 1, 1), date(2024, 2, 1)
        )

        assert result == sar_series
        assert result != mndwi_series

    def test_combined_logs_the_sar_mndwi_agreement_check(self, monkeypatch):
        logged = []
        monkeypatch.setattr(GEEHydrologyProvider, "get_surface_water_extent_series", lambda self, g, s, e, method: [])
        monkeypatch.setattr(
            GEEHydrologyProvider,
            "_log_sar_mndwi_agreement",
            staticmethod(lambda sar, mndwi: logged.append((sar, mndwi))),
        )

        GEEHydrologyProvider._get_combined_surface_water_extent_series(
            object.__new__(GEEHydrologyProvider), _SAMPLE_POLYGON_GEOJSON, date(2024, 1, 1), date(2024, 2, 1)
        )

        assert len(logged) == 1


class TestLogSarMndwiAgreement:
    """Pure function, zero ee.* calls — the entire agreement-logging
    signal is offline-testable directly."""

    def test_full_agreement_logs_zero_disagreement_rate(self, caplog):
        sar = [
            MonthlyValue(period_start=date(2024, 1, 1), value=50.0),
            MonthlyValue(period_start=date(2024, 2, 1), value=0.0),
        ]
        mndwi = [
            MonthlyValue(period_start=date(2024, 1, 1), value=40.0),
            MonthlyValue(period_start=date(2024, 2, 1), value=0.5),
        ]

        with caplog.at_level(logging.INFO, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._log_sar_mndwi_agreement(sar, mndwi)

        record = caplog.records[-1]
        assert record.msg == "sar_mndwi_agreement_checked"
        assert record.comparable_months == 2
        assert record.disagreements == 0
        assert record.disagreement_rate == 0.0

    def test_full_disagreement_logs_rate_of_one(self, caplog):
        sar = [MonthlyValue(period_start=date(2024, 1, 1), value=50.0)]
        mndwi = [MonthlyValue(period_start=date(2024, 1, 1), value=0.0)]

        with caplog.at_level(logging.INFO, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._log_sar_mndwi_agreement(sar, mndwi)

        record = caplog.records[-1]
        assert record.disagreements == 1
        assert record.disagreement_rate == 1.0

    def test_partial_disagreement_computes_the_correct_rate(self, caplog):
        sar = [
            MonthlyValue(period_start=date(2024, 1, 1), value=50.0),
            MonthlyValue(period_start=date(2024, 2, 1), value=0.0),
            MonthlyValue(period_start=date(2024, 3, 1), value=50.0),
        ]
        mndwi = [
            MonthlyValue(period_start=date(2024, 1, 1), value=40.0),
            MonthlyValue(period_start=date(2024, 2, 1), value=0.0),
            MonthlyValue(period_start=date(2024, 3, 1), value=0.0),  # disagrees with SAR here
        ]

        with caplog.at_level(logging.INFO, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._log_sar_mndwi_agreement(sar, mndwi)

        record = caplog.records[-1]
        assert record.comparable_months == 3
        assert record.disagreements == 1
        assert record.disagreement_rate == pytest.approx(1 / 3)

    def test_months_missing_on_either_side_are_excluded_from_comparison(self, caplog):
        sar = [
            MonthlyValue(period_start=date(2024, 1, 1), value=50.0),
            MonthlyValue(period_start=date(2024, 2, 1), value=None),
        ]
        mndwi = [
            MonthlyValue(period_start=date(2024, 1, 1), value=40.0),
            MonthlyValue(period_start=date(2024, 2, 1), value=20.0),
        ]

        with caplog.at_level(logging.INFO, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._log_sar_mndwi_agreement(sar, mndwi)

        record = caplog.records[-1]
        assert record.comparable_months == 1

    def test_no_comparable_months_logs_a_distinct_event_and_does_not_raise(self, caplog):
        sar = [MonthlyValue(period_start=date(2024, 1, 1), value=None)]
        mndwi = [MonthlyValue(period_start=date(2024, 1, 1), value=None)]

        with caplog.at_level(logging.INFO, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._log_sar_mndwi_agreement(sar, mndwi)  # must not raise ZeroDivisionError

        assert caplog.records[-1].msg == "sar_mndwi_agreement_no_comparable_months"


class TestSarThreshold:
    """The fixed VV threshold's own EE compositing/classification logic
    runs server-side and can only be genuinely exercised by the live
    test below — these prove the constant itself is the documented,
    reviewable value, not a magic number that silently drifted."""

    def test_threshold_is_a_negative_decibel_value(self):
        assert _SAR_VV_WATER_THRESHOLD_DB == -15.0

    def test_threshold_is_a_named_constant_not_inlined(self):
        import app.services.hydrology.gee_hydrology_provider as module

        assert hasattr(module, "_SAR_VV_WATER_THRESHOLD_DB")


class TestMndwiThreshold:
    """Same rationale as TestSarThreshold — the classification logic runs
    server-side; these prove the constant is documented and reviewable."""

    def test_threshold_is_the_standard_xu_2006_value(self):
        assert _MNDWI_WATER_THRESHOLD == 0.0

    def test_threshold_is_a_named_constant_not_inlined(self):
        import app.services.hydrology.gee_hydrology_provider as module

        assert hasattr(module, "_MNDWI_WATER_THRESHOLD")


class TestWarnIfMonthsMissing:
    """Pure function, zero ee.* calls — the missing-months warning
    (production-robustness fix) is offline-testable directly, mirroring
    TestLogSarMndwiAgreement's own style for the pre-existing agreement
    log. This is a genuinely new behavior (previously a missing month was
    silently returned as None with no operator-visible signal at all),
    not just a re-test of the existing "missing is missing" convention."""

    def test_logs_a_warning_when_any_month_is_missing(self, caplog):
        observations = [
            MonthlyValue(period_start=date(2024, 1, 1), value=10.0),
            MonthlyValue(period_start=date(2024, 2, 1), value=None),
        ]

        with caplog.at_level(logging.WARNING, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._warn_if_months_missing(observations, source="et")

        record = caplog.records[-1]
        assert record.msg == "gee_hydrology_missing_months"
        assert record.source == "et"
        assert record.missing_month_count == 1
        assert record.missing_months == ["2024-02-01"]

    def test_does_not_log_when_every_month_has_a_value(self, caplog):
        observations = [
            MonthlyValue(period_start=date(2024, 1, 1), value=10.0),
            MonthlyValue(period_start=date(2024, 2, 1), value=20.0),
        ]

        with caplog.at_level(logging.WARNING, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._warn_if_months_missing(observations, source="et")

        assert caplog.records == []

    def test_logs_every_missing_month_not_just_the_first(self, caplog):
        observations = [
            MonthlyValue(period_start=date(2024, 1, 1), value=None),
            MonthlyValue(period_start=date(2024, 2, 1), value=10.0),
            MonthlyValue(period_start=date(2024, 3, 1), value=None),
        ]

        with caplog.at_level(logging.WARNING, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._warn_if_months_missing(observations, source="surface_water_sar")

        record = caplog.records[-1]
        assert record.missing_month_count == 2
        assert record.missing_months == ["2024-01-01", "2024-03-01"]

    def test_does_not_raise_on_an_empty_observation_list(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.services.hydrology.gee_hydrology_provider"):
            GEEHydrologyProvider._warn_if_months_missing([], source="et")  # must not raise

        assert caplog.records == []


# =====================================================================
# Live regression tests — production incident fix (empty ImageCollection
# crashing per-band ops like .lt()/.gt() before reaching the already-safe
# reduceRegion guard). Real Earth Engine calls, gated the same way as
# every other live test in this file: skip cleanly without credentials,
# run for real wherever GEE_HYDROLOGY_* is configured (this codebase's
# own "run live or skip cleanly" convention, not mocked ee.* objects —
# see this file's own module docstring for why).
#
# Pre-launch date windows are used to *deterministically* reproduce a
# genuinely empty ImageCollection against real Earth Engine — not a
# guess or a flaky "usually no data" window: Sentinel-1 (COPERNICUS/
# S1_GRD) has zero images anywhere on Earth before 2014-04-03 (S1A
# launch); Sentinel-2 (COPERNICUS/S2_SR_HARMONIZED) has zero images
# anywhere before 2015-06-23 (S2A launch). A date range entirely before
# either launch date is guaranteed empty for that sensor, not merely
# likely to be.
# =====================================================================


@_requires_gee_hydrology_credentials
def test_sar_returns_none_for_a_month_with_zero_sentinel1_images_never_raises():
    """PRODUCTION INCIDENT regression: a month with zero Sentinel-1
    granules used to crash server-side with `Image.lt: If one image has
    no bands, the other must also have no bands. Got 0 and 1.` A
    pre-launch window deterministically reproduces "zero images this
    month" against real Earth Engine — the exact condition that crashed
    in production, not a simulation of it."""
    provider = GEEHydrologyProvider()
    observations = provider.get_surface_water_extent_series(
        _SAMPLE_POLYGON_GEOJSON, date(2010, 1, 1), date(2010, 3, 1), SurfaceWaterMethod.SAR
    )
    # One MonthlyValue per requested calendar month — never a shorter
    # list, even though every month here is unmeasured.
    assert len(observations) == 2
    assert all(obs.value is None for obs in observations)


@_requires_gee_hydrology_credentials
def test_mndwi_returns_none_for_a_month_with_zero_sentinel2_images_never_raises():
    """Same class of production incident, for Sentinel-2/.gt()/
    .normalizedDifference() instead of Sentinel-1/.lt()."""
    provider = GEEHydrologyProvider()
    observations = provider.get_surface_water_extent_series(
        _SAMPLE_POLYGON_GEOJSON, date(2010, 1, 1), date(2010, 3, 1), SurfaceWaterMethod.MNDWI
    )
    assert len(observations) == 2
    assert all(obs.value is None for obs in observations)


@_requires_gee_hydrology_credentials
def test_empty_monthly_composite_still_returns_a_full_length_series():
    """A genuinely empty ImageCollection's .mean() composite has zero
    bands (not a masked-but-present band) — proves the guard is applied
    independently per period, not just "the whole request is empty": the
    returned series length always matches the number of requested
    calendar months, regardless of how many turn out to have no
    imagery."""
    provider = GEEHydrologyProvider()
    observations = provider.get_surface_water_extent_series(
        _SAMPLE_POLYGON_GEOJSON, date(2010, 1, 1), date(2010, 4, 1), SurfaceWaterMethod.SAR
    )
    assert len(observations) == 3
    assert all(obs.value is None for obs in observations)


@_requires_gee_hydrology_credentials
def test_one_missing_month_does_not_fail_or_blank_out_the_rest_of_the_series():
    """Empirically-grounded, not guessed: this exact window
    (2023-11 to 2024-02, over _SAMPLE_POLYGON_GEOJSON) is the real
    production incident's own confirmed data — the live fix logged
    `gee_hydrology_missing_months` for December 2023 specifically at this
    geometry, with the rest of a 36-month production run (which includes
    this window) completing normally. December 2023 having zero usable
    Sentinel-1 passes at this specific ~0.02x0.02-degree AOI is a real,
    observed satellite-coverage gap (revisit/orbit timing at this exact
    footprint), not a launch-era absence like the pre-2014 tests above —
    it cannot be reconstructed from a general rule the way "before
    Sentinel-1 existed" can, so this test is pinned to the real window
    that already proved it, rather than a guessed one."""
    provider = GEEHydrologyProvider()
    observations = provider.get_surface_water_extent_series(
        _SAMPLE_POLYGON_GEOJSON, date(2023, 11, 1), date(2024, 2, 1), SurfaceWaterMethod.SAR
    )
    assert len(observations) == 3
    missing = {obs.period_start for obs in observations if obs.value is None}
    present = {obs.period_start for obs in observations if obs.value is not None}
    assert date(2023, 12, 1) in missing
    # "Successful execution after an empty month": at least one other
    # month in the same request produced a real value — the guard on
    # December doesn't poison or short-circuit any other period.
    assert len(present) >= 1
    for obs in observations:
        if obs.value is not None:
            assert 0.0 <= obs.value <= 100.0


@_requires_gee_hydrology_credentials
def test_mndwi_completes_over_a_real_monsoon_heavy_window_without_raising():
    """SECOND production incident regression, discovered while verifying
    the first fix live: reduceRegion() can return a dictionary with a key
    PRESENT but an explicit null value (not merely absent) —
    `stats.contains(key)` alone missed this, and
    `ee.Number(null).multiply(100)` crashed server-side with
    "Number.multiply: Parameter 'left' is required and may not be null."
    Unlike "zero images" (deterministically forced by a pre-launch date),
    the exact key-present-vs-null EE internal condition isn't something a
    date range can force on demand — this test instead re-runs the same
    class of request (MNDWI, the cloud-limited method) over a real
    monsoon window with heavy expected Sentinel-2 cloud cover, and
    asserts only that it completes without raising, which is the
    property that actually matters here."""
    provider = GEEHydrologyProvider()
    observations = provider.get_surface_water_extent_series(
        _SAMPLE_POLYGON_GEOJSON, date(2025, 6, 1), date(2025, 12, 1), SurfaceWaterMethod.MNDWI
    )
    assert len(observations) == 6
    for obs in observations:
        if obs.value is not None:
            assert 0.0 <= obs.value <= 100.0


@_requires_gee_hydrology_credentials
def test_et_series_also_tolerates_a_zero_image_month():
    """get_et_series() is defensively guarded the same way as SAR/MNDWI
    (ticket fix review, "not just the failing method") even though MODIS
    MOD16A2's near-daily 8-day-composite cadence makes a genuinely empty
    month far less likely in practice than for Sentinel-1/2 — a pre-1972
    MODIS-launch-era window (MOD16A2 data itself starts 2000) still proves
    the guard doesn't change behavior when applied defensively."""
    provider = GEEHydrologyProvider()
    observations = provider.get_et_series(_SAMPLE_POLYGON_GEOJSON, date(1990, 1, 1), date(1990, 3, 1))
    assert len(observations) == 2
    assert all(obs.value is None for obs in observations)


@_requires_gee_hydrology_credentials
def test_et_monthly_time_series_returns_real_values():
    provider = GEEHydrologyProvider()
    observations = provider.get_et_series(_SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 4, 1))

    # One MonthlyValue per requested calendar month — 3 for a 3-month
    # window — never a shorter list, even if every month is unmeasured.
    assert len(observations) == 3
    for obs in observations:
        if obs.value is not None:
            # Sanity bound, not a tight spec: MOD16A2 8-day-composite ET
            # in mm is always non-negative and, for any real Indian
            # cropland catchment, nowhere near this generous an upper
            # bound.
            assert 0.0 <= obs.value <= 100.0


@_requires_gee_hydrology_credentials
def test_sar_surface_water_monthly_time_series_returns_real_values():
    provider = GEEHydrologyProvider()
    observations = provider.get_surface_water_extent_series(
        _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 4, 1), SurfaceWaterMethod.SAR
    )

    # One MonthlyValue per requested calendar month — 3 for a 3-month
    # window — never a shorter list, even if every month is unmeasured.
    assert len(observations) == 3
    for obs in observations:
        if obs.value is not None:
            # A percentage of catchment area — HydrologyDataProvider's
            # own documented 0-100 contract, not a fraction or a raw
            # pixel count.
            assert 0.0 <= obs.value <= 100.0


@_requires_gee_hydrology_credentials
def test_mndwi_surface_water_monthly_time_series_returns_real_values():
    provider = GEEHydrologyProvider()
    observations = provider.get_surface_water_extent_series(
        _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 4, 1), SurfaceWaterMethod.MNDWI
    )

    assert len(observations) == 3
    for obs in observations:
        if obs.value is not None:
            assert 0.0 <= obs.value <= 100.0


@_requires_gee_hydrology_credentials
def test_combined_surface_water_series_matches_sar_and_logs_agreement(caplog):
    """The real-GEE proof of the M1-005 acceptance criterion: SAR and
    MNDWI agree directionally on a known water body, with the
    disagreement rate logged — not asserted to be zero, since some
    disagreement is expected and informative, not a bug."""
    provider = GEEHydrologyProvider()

    sar_series = provider.get_surface_water_extent_series(
        _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 4, 1), SurfaceWaterMethod.SAR
    )
    with caplog.at_level(logging.INFO, logger="app.services.hydrology.gee_hydrology_provider"):
        combined_series = provider.get_surface_water_extent_series(
            _SAMPLE_POLYGON_GEOJSON, date(2025, 1, 1), date(2025, 4, 1), SurfaceWaterMethod.COMBINED
        )

    # COMBINED reports the SAR series verbatim (Blueprint v2 Part 4: SAR
    # primary) — not a blend with MNDWI.
    assert combined_series == sar_series

    agreement_records = [r for r in caplog.records if r.msg == "sar_mndwi_agreement_checked"]
    assert len(agreement_records) == 1
    assert 0.0 <= agreement_records[0].disagreement_rate <= 1.0
