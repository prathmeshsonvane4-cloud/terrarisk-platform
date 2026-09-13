"""Tests for how the water report orchestrator runs the validation harness.

Kept separate from test_water_report_generator.py, whose end-to-end
orchestration tests need a live PostGIS and skip without one. Those
skips are why this file exists: the only tests that reached the
validation call site were skipping in every environment without Docker,
so the wiring was shipping with no test that actually ran it. These
exercise `_zone_for` and `_validate` directly, with no database.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import uuid4

from app.models.enums import CalibrationStatus, StorageChangeBand
from app.services.hydrology.models import WaterBalanceBundle, WaterBalanceEngineResult
from app.services.hydrology.water_report_generator import _validate, _zone_for
from app.services.risk.models import MonthlyValue
from app.services.validation import AgroClimaticZone

# A 30-year CHIRPS climatology shaped like Raichur: ~560 mm/yr, almost
# all of it June-October.
_RAICHUR_NORMALS = {
    1: 2.0, 2: 3.0, 3: 6.0, 4: 18.0, 5: 38.0, 6: 72.0,
    7: 95.0, 8: 110.0, 9: 125.0, 10: 70.0, 11: 16.0, 12: 5.0,
}


def _bundle(et_per_month: float) -> WaterBalanceBundle:
    months = [date(2023 + (m // 12), (m % 12) + 1, 1) for m in range(12)]
    return WaterBalanceBundle(
        period_start=months[0],
        period_end=months[-1],
        rainfall_monthly=[MonthlyValue(d, 47.0) for d in months],
        et_monthly=[MonthlyValue(d, et_per_month) for d in months],
        rainfall_daily=[MonthlyValue(d, 12.0) for d in months],
        resolution_flags=[],
    )


def _result(*, rainfall: float, et: float, runoff: float) -> WaterBalanceEngineResult:
    return WaterBalanceEngineResult(
        storage_change_band=StorageChangeBand.NORMAL,
        storage_change_mm=rainfall - et - runoff,
        rainfall_mm=rainfall,
        et_mm=et,
        runoff_mm=runoff,
        data_completeness=100.0,
        calibration_status=CalibrationStatus.UNCALIBRATED,
        closed_catchment_assumed=True,
        resolution_flags=[],
        model_version="test",
    )


class TestZoneFromClimatology:
    def test_a_raichur_climatology_is_semi_arid(self):
        assert _zone_for(_RAICHUR_NORMALS) is AgroClimaticZone.SEMI_ARID

    def test_a_partial_climatology_is_not_extrapolated_into_a_year(self):
        """Eleven months of normals is not an annual total, and
        classifying on it would silently understate rainfall by a month
        and could drop a catchment into a drier zone."""
        eleven = {k: v for k, v in _RAICHUR_NORMALS.items() if k != 8}
        assert _zone_for(eleven) is AgroClimaticZone.UNKNOWN

    def test_an_empty_climatology_yields_unknown(self):
        assert _zone_for({}) is AgroClimaticZone.UNKNOWN


class TestValidateAtTheCallSite:
    def test_the_pre_audit_maski_defect_fails_at_the_call_site_and_logs_at_warning_or_above(self, caplog):
        """The pre-audit Maski figures, through the real orchestrator helper.
        This is the test that proves the harness is live in the pipeline
        rather than merely importable."""
        caplog.set_level(logging.INFO, logger="app.services.hydrology.water_report_generator")
        report = _validate(
            _bundle(et_per_month=9.4),
            _result(rainfall=1692.3, et=339.9, runoff=688.1),
            AgroClimaticZone.SEMI_ARID,
            uuid4(),
        )
        assert report.failed
        record = next(r for r in caplog.records if r.message == "water_report_physical_validation")
        assert record.levelno >= logging.WARNING
        assert record.failed is True

    def test_series_findings_and_balance_findings_arrive_in_one_report(self):
        """The ET series is flagged at ingestion AND the balance it
        produced is flagged downstream. One report, so the cause and its
        symptoms are read together."""
        report = _validate(
            _bundle(et_per_month=9.4),
            _result(rainfall=1692.3, et=339.9, runoff=688.1),
            AgroClimaticZone.SEMI_ARID,
            uuid4(),
        )
        checks = {f.check for f in report.findings if f.is_failure}
        assert "series_median_plausible" in checks
        assert "et_fraction_of_rainfall" in checks

    def test_a_plausible_balance_logs_at_info_and_does_not_fail(self, caplog):
        caplog.set_level(logging.INFO, logger="app.services.hydrology.water_report_generator")
        report = _validate(
            _bundle(et_per_month=103.0),
            _result(rainfall=1650.0, et=1237.5, runoff=247.5),
            AgroClimaticZone.SEMI_ARID,
            uuid4(),
        )
        assert not report.failed
        record = next(r for r in caplog.records if r.message == "water_report_physical_validation")
        assert record.levelno == logging.INFO

    def test_an_arithmetic_error_escalates_the_log_to_error(self, caplog):
        caplog.set_level(logging.INFO, logger="app.services.hydrology.water_report_generator")
        _validate(
            _bundle(et_per_month=103.0),
            _result(rainfall=500.0, et=100.0, runoff=600.0),
            AgroClimaticZone.SEMI_ARID,
            uuid4(),
        )
        record = next(r for r in caplog.records if r.message == "water_report_physical_validation")
        assert record.levelno == logging.ERROR
