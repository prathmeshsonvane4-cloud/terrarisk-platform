"""Tests for the physical validation harness.

The fixture that matters most in this file is `_maski_result()`: a
water balance carrying the two worst pre-audit defects at once (ET ~4x
low, runoff from monthly-aggregated SCS-CN). The pipeline that produced
numbers like these passed the whole suite. The point of this file is
that these do not pass the harness.
"""

from __future__ import annotations

import pytest

from app.models.enums import CalibrationStatus, StorageChangeBand
from app.services.hydrology.models import AnnualWaterBalance, WaterBalanceEngineResult
from app.services.validation import (
    AgroClimaticZone,
    Severity,
    classify_zone_by_rainfall,
    validate_water_balance,
)


def _result(
    *,
    rainfall_mm: float | None,
    et_mm: float | None,
    runoff_mm: float | None,
    storage_change_mm: float | None = None,
    annual: list[AnnualWaterBalance] | None = None,
) -> WaterBalanceEngineResult:
    """A result with the engine's own residual definition applied, unless
    `storage_change_mm` is given explicitly — which the identity test
    does, precisely to simulate an engine whose arithmetic has drifted."""
    if storage_change_mm is None and None not in (rainfall_mm, et_mm, runoff_mm):
        storage_change_mm = rainfall_mm - et_mm - runoff_mm
    return WaterBalanceEngineResult(
        storage_change_band=StorageChangeBand.NORMAL,
        storage_change_mm=storage_change_mm,
        rainfall_mm=rainfall_mm,
        et_mm=et_mm,
        runoff_mm=runoff_mm,
        data_completeness=100.0,
        calibration_status=CalibrationStatus.UNCALIBRATED,
        closed_catchment_assumed=True,
        resolution_flags=[],
        model_version="test",
        annual=annual or [],
    )


def _years(rainfall_per_year: list[float]) -> list[AnnualWaterBalance]:
    return [
        AnnualWaterBalance(
            label=f"202{i}-2{i + 1}",
            start_year=2020 + i,
            months_covered=12,
            rainfall_mm=rainfall,
            et_mm=None,
            runoff_mm=None,
            storage_change_mm=None,
        )
        for i, rainfall in enumerate(rainfall_per_year)
    ]


def _checks_that_failed(report) -> set[str]:
    return {f.check for f in report.findings if f.is_failure}


# A balance that sits comfortably inside every semi-arid envelope:
# 550 mm/yr, ET 75% of rainfall, runoff coefficient 15%.
def _plausible_semi_arid() -> WaterBalanceEngineResult:
    return _result(
        rainfall_mm=1650.0,
        et_mm=1237.5,
        runoff_mm=247.5,
        annual=_years([550.0, 550.0, 550.0]),
    )


# ---------------------------------------------------------------------
# The regression fixture. Pre-audit figures, and they are wrong.
# ---------------------------------------------------------------------
def _maski_result() -> WaterBalanceEngineResult:
    """Maski catchment, 233.48 ha, as quoted in the Sep 2026 project brief.

    PROVENANCE, CORRECTED 13 Sep 2026: these figures were originally
    described here as a production report. They are not. None of the five
    Maski balances stored in production match them — all five put ET at
    77-78% of rainfall and pass this harness. These numbers pre-date the
    hydrology audit fixes (same 1,692 mm rainfall, but ET and runoff from
    the defective methods). They remain the right fixture because they are
    exactly what those defects produce.

    Over the 3-year window: rainfall 1692.3 mm, ET 339.9 mm, runoff
    688.1 mm, recharge (the residual) 664.3 mm. Per year that is 564 mm
    of rainfall — entirely reasonable for Raichur — against 113 mm of
    ET, a 41% runoff coefficient, and 39% of all rainfall reported as
    recharge.

    For semi-arid Deccan those last three are not defensible. ET should
    be the largest term in the balance and is instead the smallest; the
    ~4x shortfall matches the MOD16A2 8-day-composite defect exactly,
    and because storage change is the residual, the missing ET reappears
    as recharge the catchment has no physical claim to.
    """
    return _result(
        rainfall_mm=1692.3,
        et_mm=339.9,
        runoff_mm=688.1,
        storage_change_mm=664.3,
        annual=_years([564.1, 564.1, 564.1]),
    )


class TestMaskiRegression:
    """The whole harness justifies itself here or not at all."""

    def test_the_pre_audit_maski_balance_fails_validation(self):
        report = validate_water_balance(
            _maski_result(), zone=AgroClimaticZone.SEMI_ARID, subject="maski"
        )
        assert report.failed, (
            "The Maski balance passed validation. It reports ET at 20% of rainfall for a "
            "semi-arid Deccan catchment; if this passes, the harness is not doing its job."
        )

    def test_it_flags_all_three_symptoms_not_just_one(self):
        """One upstream defect, three visible symptoms. A harness that
        caught only the residual would send someone to fix the wrong
        number."""
        report = validate_water_balance(_maski_result(), zone=AgroClimaticZone.SEMI_ARID)
        assert _checks_that_failed(report) >= {
            "et_fraction_of_rainfall",
            "runoff_coefficient",
            "storage_change_fraction",
        }

    def test_it_names_the_et_term_as_the_cause_rather_than_the_residual(self):
        report = validate_water_balance(_maski_result(), zone=AgroClimaticZone.SEMI_ARID)
        attribution = [f for f in report.findings if f.check == "residual_absorbs_et_error"]
        assert len(attribution) == 1
        assert "Investigate the ET term first" in attribution[0].message

    def test_the_zone_assignment_itself_is_not_the_problem(self):
        """564 mm/yr genuinely is semi-arid, so the envelope being applied
        is the right one — which is what makes the ratio failures
        meaningful rather than an artefact of a mislabelled catchment."""
        report = validate_water_balance(_maski_result(), zone=AgroClimaticZone.SEMI_ARID)
        assert "annual_rainfall_matches_zone" not in _checks_that_failed(report)
        assert classify_zone_by_rainfall(564.1) is AgroClimaticZone.SEMI_ARID


class TestPhysicalInvariants:
    """Violations of physics — ERROR everywhere, no zone required."""

    def test_a_plausible_balance_produces_no_failures(self):
        report = validate_water_balance(_plausible_semi_arid(), zone=AgroClimaticZone.SEMI_ARID)
        assert not report.failed
        assert report.checks_run > 0, "a report with zero checks run is not a passing report"

    def test_runoff_exceeding_rainfall_is_an_error(self):
        report = validate_water_balance(
            _result(rainfall_mm=500.0, et_mm=100.0, runoff_mm=600.0),
            zone=AgroClimaticZone.SEMI_ARID,
        )
        assert "runoff_not_exceeding_rainfall" in {f.check for f in report.errors}

    def test_a_negative_term_is_an_error(self):
        report = validate_water_balance(
            _result(rainfall_mm=500.0, et_mm=-10.0, runoff_mm=50.0),
            zone=AgroClimaticZone.SEMI_ARID,
        )
        assert "non_negative" in {f.check for f in report.errors}

    def test_et_above_rainfall_in_a_water_limited_zone_is_flagged(self):
        """Possible only with an import the closed-catchment balance does
        not model — so it is a warning about the assumption, not an
        arithmetic error."""
        report = validate_water_balance(
            _result(rainfall_mm=500.0, et_mm=600.0, runoff_mm=0.0),
            zone=AgroClimaticZone.SEMI_ARID,
        )
        finding = next(
            f for f in report.findings if f.check == "et_not_exceeding_rainfall_when_water_limited"
        )
        assert finding.severity is Severity.WARNING
        assert "closed" in finding.message

    def test_the_same_ratio_is_not_flagged_as_an_import_in_a_humid_zone(self):
        report = validate_water_balance(
            _result(rainfall_mm=2000.0, et_mm=800.0, runoff_mm=900.0),
            zone=AgroClimaticZone.HUMID,
        )
        assert "et_not_exceeding_rainfall_when_water_limited" not in {f.check for f in report.findings}


class TestIdentityGuard:
    """The identity check is a refactor guard, and the tests say so."""

    def test_a_drifted_identity_is_reported_as_a_code_regression(self):
        report = validate_water_balance(
            _result(rainfall_mm=1000.0, et_mm=600.0, runoff_mm=200.0, storage_change_mm=150.0),
            zone=AgroClimaticZone.SEMI_ARID,
        )
        finding = next(f for f in report.errors if f.check == "water_balance_identity")
        assert "code regression, not a physical finding" in finding.message

    def test_the_engines_own_residual_always_satisfies_it(self):
        """Documents the vacuity honestly: this passes by construction,
        which is exactly why it is not evidence that the balance closes.
        See water_balance.py's module docstring."""
        report = validate_water_balance(_maski_result(), zone=AgroClimaticZone.SEMI_ARID)
        assert "water_balance_identity" not in {f.check for f in report.errors}


class TestHonestAbsence:
    """A check that did not run must never look like a check that passed."""

    def test_an_unknown_zone_disables_plausibility_and_says_so(self):
        report = validate_water_balance(_maski_result(), zone=AgroClimaticZone.UNKNOWN)
        assert report.checks_skipped >= 4
        note = next(f for f in report.findings if f.check == "zone_assigned")
        assert "NOT for plausibility" in note.message

    def test_the_maski_balance_passes_when_no_zone_is_known(self):
        """Uncomfortable and correct. Without a zone there is no envelope
        to fail against, so the harness reports arithmetic validity only.
        The report must make that obvious rather than reading as a pass —
        which is what the skipped-check note above is for."""
        report = validate_water_balance(_maski_result(), zone=AgroClimaticZone.UNKNOWN)
        assert not report.failed
        assert "checked for arithmetic validity only" in report.findings[-1].message

    def test_a_missing_term_is_recorded_not_silently_skipped(self):
        report = validate_water_balance(
            _result(rainfall_mm=1650.0, et_mm=None, runoff_mm=247.5),
            zone=AgroClimaticZone.SEMI_ARID,
        )
        assert report.checks_skipped >= 1
        assert any(f.check == "term_present" and f.subject == "et_mm" for f in report.findings)

    def test_near_zero_rainfall_skips_ratios_instead_of_dividing_by_it(self):
        report = validate_water_balance(
            _result(rainfall_mm=2.0, et_mm=1.0, runoff_mm=0.0), zone=AgroClimaticZone.ARID
        )
        assert "rainfall_sufficient_for_ratios" in {f.check for f in report.findings}
        assert "runoff_coefficient" not in {f.check for f in report.findings}

    def test_summary_distinguishes_a_clean_run_from_an_empty_one(self):
        clean = validate_water_balance(_plausible_semi_arid(), zone=AgroClimaticZone.SEMI_ARID)
        assert "passed" in clean.summary()
        assert "0 checks" not in clean.summary()


class TestZoneClassification:
    @pytest.mark.parametrize(
        ("rainfall_mm", "expected"),
        [
            (250.0, AgroClimaticZone.ARID),
            (399.9, AgroClimaticZone.ARID),
            (400.0, AgroClimaticZone.SEMI_ARID),
            (564.1, AgroClimaticZone.SEMI_ARID),
            (750.0, AgroClimaticZone.SUB_HUMID),
            (1200.0, AgroClimaticZone.HUMID),
            (3000.0, AgroClimaticZone.HUMID),
        ],
    )
    def test_rainfall_selects_the_moisture_zone(self, rainfall_mm, expected):
        assert classify_zone_by_rainfall(rainfall_mm) is expected

    def test_coastal_is_never_inferred_from_rainfall(self):
        """Proximity to a coast is not a rainfall property. Guessing it
        would apply the wrong envelope to an inland catchment that
        happens to be wet."""
        assert all(
            classify_zone_by_rainfall(mm) is not AgroClimaticZone.COASTAL
            for mm in (100.0, 600.0, 1000.0, 2500.0, 4000.0)
        )

    def test_absent_rainfall_yields_unknown_not_a_default_zone(self):
        assert classify_zone_by_rainfall(None) is AgroClimaticZone.UNKNOWN
        assert classify_zone_by_rainfall(0.0) is AgroClimaticZone.UNKNOWN

    def test_a_mismatched_zone_is_flagged_so_wrong_envelopes_are_visible(self):
        """A humid catchment's rainfall validated against the semi-arid
        envelope: every ratio check above it was applied against bounds
        that never applied."""
        humid_rainfall = _result(
            rainfall_mm=5400.0, et_mm=2160.0, runoff_mm=2430.0, annual=_years([1800.0, 1800.0, 1800.0])
        )
        report = validate_water_balance(humid_rainfall, zone=AgroClimaticZone.SEMI_ARID)
        assert "annual_rainfall_matches_zone" in _checks_that_failed(report)

    def test_a_partial_year_at_the_window_edge_is_not_judged_as_a_dry_year(self):
        partial = AnnualWaterBalance(
            label="2023-24",
            start_year=2023,
            months_covered=4,
            rainfall_mm=95.0,
            et_mm=None,
            runoff_mm=None,
            storage_change_mm=None,
        )
        result = _result(
            rainfall_mm=1650.0, et_mm=1237.5, runoff_mm=247.5, annual=[*_years([550.0, 550.0]), partial]
        )
        report = validate_water_balance(result, zone=AgroClimaticZone.SEMI_ARID)
        assert "annual_rainfall_matches_zone" not in _checks_that_failed(report)
