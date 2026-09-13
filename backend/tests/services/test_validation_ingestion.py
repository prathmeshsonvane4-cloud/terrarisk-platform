"""Tests for ingestion-time unit and scale assertions, and for the
product registry.

The registry tests are not ceremony. Two of the defects the audit found
were code comments that confidently stated the wrong thing about a
product; pinning the registry's own claims in tests is what stops the
same drift happening to its replacement.
"""

from __future__ import annotations

import pytest

from app.services.validation import (
    DELIVERED_SERIES,
    PRODUCTS,
    Severity,
    Verification,
    spec_for,
    validate_product_is_audited,
    validate_series,
)

# Real MOD16A2-derived monthly ET for a semi-arid Deccan catchment,
# correctly converted to monthly totals: roughly 30-90 mm/month with a
# monsoon peak. Deliberately unremarkable — the point of the fixture
# below is that the SAME series divided by 4 is caught.
_HEALTHY_ET = [42.0, 38.0, 45.0, 61.0, 78.0, 95.0, 88.0, 74.0, 66.0, 51.0, 44.0, 40.0]

# The same series with the 8-day-composite-to-monthly conversion missing:
# every value is ~1/3.9 of what it should be. Individually each value is
# a perfectly possible monthly ET, which is exactly why no per-value
# range check catches it and the median check must.
_ET_MISSING_MONTHLY_CONVERSION = [round(v / 3.875, 1) for v in _HEALTHY_ET]


class TestScaleErrorDetection:
    """The failure mode the whole module exists for."""

    def test_a_correctly_converted_et_series_passes(self):
        report = validate_series("et_monthly_mm", list(_HEALTHY_ET))
        assert not report.failed
        assert report.checks_run == 2

    def test_a_uniformly_scaled_et_series_is_caught_by_the_median(self):
        """Every individual value here is a possible monthly ET. Only the
        central tendency gives it away — which is why the median check
        exists alongside the range check rather than instead of it."""
        report = validate_series("et_monthly_mm", list(_ET_MISSING_MONTHLY_CONVERSION))
        assert report.failed
        finding = next(f for f in report.warnings if f.check == "series_median_plausible")
        assert "8-day composite" in finding.message

    def test_no_individual_value_in_that_series_breaks_the_hard_range(self):
        """Pins the reason the median check is load-bearing: a hard-range
        check alone would report this series as clean."""
        assert all(0.0 <= v <= 450.0 for v in _ET_MISSING_MONTHLY_CONVERSION)
        report = validate_series("et_monthly_mm", list(_ET_MISSING_MONTHLY_CONVERSION))
        assert not [f for f in report.findings if f.check == "series_within_hard_range"]

    def test_an_unscaled_et_series_breaks_the_hard_range(self):
        """The 0.1 scale factor omitted entirely: values 10x too large,
        now impossible rather than merely implausible."""
        report = validate_series("et_monthly_mm", [v * 10 for v in _HEALTHY_ET])
        assert "series_within_hard_range" in {f.check for f in report.errors}


class TestHardRanges:
    def test_an_impossible_ndvi_is_an_error(self):
        report = validate_series("ndvi", [0.3, 0.5, 12.0])
        finding = next(f for f in report.errors if f.check == "series_within_hard_range")
        assert finding.severity is Severity.ERROR

    def test_a_single_absurd_value_hidden_in_a_sane_series_is_still_caught(self):
        """This is the case a downstream monthly total would average
        away into plausibility."""
        report = validate_series("rainfall_daily_mm", [0.0, 3.2, 11.0, 4000.0, 0.0])
        assert report.failed

    def test_negative_rainfall_is_an_error_not_a_measurement(self):
        report = validate_series("rainfall_monthly_mm", [120.0, -9999.0, 45.0])
        assert "series_within_hard_range" in {f.check for f in report.errors}

    def test_many_offenders_are_summarised_rather_than_itemised(self):
        report = validate_series("ndvi", [5.0] * 30)
        assert len(report.errors) == 1
        assert "and 27 more" in report.errors[0].message

    def test_surface_water_percent_cannot_exceed_one_hundred(self):
        assert validate_series("surface_water_percent", [12.0, 140.0]).failed


class TestHonestAbsence:
    def test_nulls_are_skipped_not_read_as_zero(self):
        report = validate_series("et_monthly_mm", [42.0, None, 61.0, None, 78.0])
        assert not report.failed

    def test_an_all_null_series_reports_that_nothing_was_checked(self):
        report = validate_series("et_monthly_mm", [None, None, None])
        assert report.checks_run == 0
        assert "no usable values" in report.findings[0].message

    def test_an_unregistered_series_is_a_warning_not_a_silent_pass(self):
        report = validate_series("soil_moisture_mm", [1.0, 2.0])
        assert report.failed
        assert "nobody has audited" in report.findings[0].message

    def test_a_series_with_no_median_expectation_records_the_skip(self):
        report = validate_series("rainfall_monthly_mm", [0.0, 0.0, 250.0])
        assert report.checks_skipped == 1
        assert not report.failed


class TestProductRegistry:
    def test_every_product_the_code_reads_is_registered(self):
        """The collection ids hardcoded across the providers. If one is
        added without a registry entry, this fails — which is the whole
        mechanism preventing an unaudited seventh data source."""
        for collection_id in (
            "MODIS/061/MOD16A2",
            "UCSB-CHG/CHIRPS/DAILY",
            "JRC/GSW1_4/GlobalSurfaceWater",
            "COPERNICUS/S2_SR_HARMONIZED",
            "COPERNICUS/S2_CLOUD_PROBABILITY",
            "COPERNICUS/S1_GRD",
        ):
            assert spec_for(collection_id) is not None, f"{collection_id} is unaudited"

    def test_an_unregistered_product_is_flagged(self):
        report = validate_product_is_audited("ECMWF/ERA5_LAND/HOURLY")
        assert report.failed
        assert "no entry in the product registry" in report.findings[0].message

    def test_open_defects_surface_as_warnings_rather_than_sitting_in_a_docstring(self):
        report = validate_product_is_audited("JRC/GSW1_4/GlobalSurfaceWater")
        assert report.failed
        assert any("not flood proneness" in f.message for f in report.warnings)

    def test_resolved_defects_are_kept_on_record_but_do_not_raise_warnings(self):
        """A fixed defect that kept warning forever would train everyone
        to ignore the warnings — the opposite of failing loudly."""
        spec = PRODUCTS["JRC/GSW1_4/GlobalSurfaceWater"]
        assert any("unweighted" in d for d in spec.resolved_defects)
        report = validate_product_is_audited("JRC/GSW1_4/GlobalSurfaceWater")
        assert not any("unweighted" in f.message for f in report.findings)

    def test_mod16a2_has_no_open_defects_after_the_mask_fix(self):
        assert not validate_product_is_audited("MODIS/061/MOD16A2").failed

    def test_every_spec_records_where_it_was_verified(self):
        for spec in PRODUCTS.values():
            if spec.verified_against is Verification.CATALOG:
                assert spec.verified_on is not None, f"{spec.collection_id} claims catalog verification with no date"
                assert spec.source_url, f"{spec.collection_id} claims catalog verification with no source"

    @pytest.mark.parametrize(
        ("collection_id", "band", "expected_scale"),
        [
            ("MODIS/061/MOD16A2", "ET", 0.1),
            ("UCSB-CHG/CHIRPS/DAILY", "precipitation", 1.0),
            ("JRC/GSW1_4/GlobalSurfaceWater", "occurrence", 1.0),
            ("COPERNICUS/S2_SR_HARMONIZED", "B8", 1e-4),
        ],
    )
    def test_scale_factors_match_the_published_specifications(self, collection_id, band, expected_scale):
        assert PRODUCTS[collection_id].bands[band].scale_factor == expected_scale

    def test_the_mod16a2_valid_range_ceiling_is_the_documented_one(self):
        """32700, not 32760 and not 32761 — and the provider must mask at
        the same number the registry records, or the registry is
        documentation that has already drifted from the code."""
        from app.services.hydrology.gee_hydrology_provider import _ET_VALID_MAX

        assert PRODUCTS["MODIS/061/MOD16A2"].bands["ET"].valid_range == (-32767.0, 32700.0)
        assert _ET_VALID_MAX == PRODUCTS["MODIS/061/MOD16A2"].bands["ET"].valid_range[1]

    def test_the_jrc_read_unmasks_and_uses_an_unweighted_mean(self):
        """Structural regression guard for a server-side Earth Engine
        expression, which cannot run offline. Deliberately blunt: if
        either call disappears from get_water_history, the double bias
        is back, and this should fail before anyone has to rediscover it
        on a live polygon. The live measurement lives in
        docs/GEE_Product_Audit_2026.md."""
        import inspect

        from app.services.satellite.gee_provider import GeeProvider

        source = inspect.getsource(GeeProvider.get_water_history)
        code = source.split('"""')[-1]  # the body after the docstring
        assert ".unmask(0)" in code
        assert ".unweighted()" in code

    def test_jrc_coverage_runs_to_the_end_of_2021(self):
        """The provider reports 1 Jan 2021. The dataset ends 31 Dec 2021."""
        from datetime import date

        assert PRODUCTS["JRC/GSW1_4/GlobalSurfaceWater"].record_end == date(2021, 12, 31)

    def test_the_jrc_masking_trap_is_recorded_against_the_band(self):
        notes = PRODUCTS["JRC/GSW1_4/GlobalSurfaceWater"].bands["occurrence"]
        assert "masked, not zero" in notes.no_data
        assert "unweighted" in notes.notes

    def test_sentinel1_is_recorded_as_logarithmic(self):
        assert "LOGARITHMIC" in PRODUCTS["COPERNICUS/S1_GRD"].bands["VV"].notes

    def test_every_delivered_series_states_its_units_and_source(self):
        for expectation in DELIVERED_SERIES.values():
            assert expectation.units
            assert expectation.source
