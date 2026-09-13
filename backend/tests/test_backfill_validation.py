"""Tests for scripts/backfill_validation.py's pure core.

The stored rows used here are real production values from 13 Sep 2026:
Maski (passes) and Kanoor (ET above rainfall). Built as unsaved ORM
objects, so no database is needed.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.enums import CalibrationStatus, StorageChangeBand
from app.models.water_balance import WaterBalanceResult
from app.services.validation import AgroClimaticZone, Severity

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from backfill_validation import validate_stored_balance  # noqa: E402


def _stored(*, rainfall, et, runoff, storage_change) -> WaterBalanceResult:
    return WaterBalanceResult(
        id=uuid4(),
        catchment_id=uuid4(),
        period_start=date(2023, 8, 1),
        period_end=date(2026, 8, 1),
        rainfall_mm=rainfall,
        et_mm=et,
        runoff_mm=runoff,
        storage_change_mm=storage_change,
        annual=None,
        storage_change_band=StorageChangeBand.ABOVE_NORMAL,
        data_completeness=97.22,
        calibration_status=CalibrationStatus.UNCALIBRATED,
        closed_catchment_assumed=True,
        resolution_flags=[],
        model_version="water-balance-engine-v1",
        computed_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )


def test_the_stored_production_maski_balance_passes():
    zone, report = validate_stored_balance(_stored(rainfall=1729.86, et=1348.47, runoff=263.10, storage_change=118.29))
    assert zone is AgroClimaticZone.SEMI_ARID
    assert not report.failed


def test_a_stored_balance_with_et_above_rainfall_is_flagged():
    """Kanoor: ET 109% of rainfall. The finding carries the closed-catchment
    explanation, which is the point of persisting it."""
    rainfall = 596.0 * 3
    zone, report = validate_stored_balance(
        _stored(rainfall=rainfall, et=rainfall * 1.09, runoff=rainfall * 0.18, storage_change=rainfall * -0.27)
    )
    assert report.failed
    checks = {f.check for f in report.findings if f.is_failure}
    assert "et_not_exceeding_rainfall_when_water_limited" in checks


def test_rounding_from_stored_columns_is_not_reported_as_an_engine_regression():
    """Drift of exactly 0.01 mm from NUMERIC(10,2) rounding produced 17 false
    ERRORs before the stored-value allowance existed."""
    _, report = validate_stored_balance(_stored(rainfall=1729.86, et=1348.47, runoff=263.10, storage_change=118.30))
    assert "water_balance_identity" not in {f.check for f in report.errors}


def test_every_backfilled_run_records_that_it_differs_from_a_pipeline_run():
    _, report = validate_stored_balance(_stored(rainfall=1729.86, et=1348.47, runoff=263.10, storage_change=118.29))
    basis = report.findings[0]
    assert basis.check == "backfill_zone_basis"
    assert basis.severity is Severity.INFO
    assert "not the 30-year climatology" in basis.message
    assert "none was reconstructed" in basis.message


def test_missing_rainfall_skips_plausibility_rather_than_guessing_a_zone():
    zone, report = validate_stored_balance(_stored(rainfall=None, et=None, runoff=None, storage_change=None))
    assert zone is AgroClimaticZone.UNKNOWN
    assert "no zone could be derived" in report.findings[0].message
