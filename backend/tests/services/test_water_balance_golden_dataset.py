"""Golden-dataset scientific regression tests for WaterBalanceEngine
(ticket M2-005).

Every other WaterBalanceEngine test (test_water_balance_engine.py) proves
the CODE is correct — that the engine faithfully implements whatever
arithmetic engine.py's source says it should. This file's job is
different and narrower, per the Implementation Plan's own framing: prove
the SCIENCE is right, by checking specific numeric outputs against a
reference this codebase did not derive itself. If a future refactor
changes the runoff formula, a threshold, or the aggregation logic in a
way that silently drifts from the published method, the tests in
test_water_balance_engine.py will happily keep passing (they only check
internal consistency) — the tests in THIS file are the ones designed to
break.

=====================================================================
REFERENCE SOURCE — read this before touching any expected value below
=====================================================================

Blueprint v2's Sources cite a specific paper for Curve Number validity in
this service's target region: "Validating Curve Number estimation
approaches: A case study of an urbanizing watershed from Western
Maharashtra, India" (Modeling Earth Systems and Environment, 2023,
https://link.springer.com/article/10.1007/s40808-023-01855-7 — the exact
URL already in Blueprint v2's Sources list). Blueprint v2 itself
paraphrases that paper's finding as: standard SCS-CN tables did not vary
significantly from event-based (empirical) rainfall-runoff data for most
of the basins tested in that watershed.

**What this ticket could NOT do, stated plainly rather than worked
around:** the paper itself is paywalled (Springer; confirmed by a live
fetch attempt during this ticket, which was redirected to a login/
authorization page). Its underlying per-basin numeric table (rainfall
depths, empirical vs. tabular CN, computed runoff) was not accessible.
**This file does not fabricate numbers and attribute them to that paper.**
Presenting an invented number as if it were extracted from a specific
cited study would be scientifically dishonest — exactly the failure mode
this whole project's ✓/⚠ methodology discipline exists to prevent.

**What this file validates instead, and why that is still a real,
meaningful check:** the Western Maharashtra paper's own finding is that
the STANDARD SCS-CN method (the NRCS/USDA-SCS national tables and
formula) is regionally valid for this service's target geography — it is
not proposing a different formula, only confirming the standard one
applies here. `TestCurveNumberAgainstNrcsReference` below validates this
codebase's implementation against the standard method's own canonical
source: the USDA Natural Resources Conservation Service's published
worked example (National Engineering Handbook Part 630, Chapter 10 —
"Estimation of Direct Runoff from Storm Rainfall"), independently
confirmed via a live search during this ticket and cross-checked by hand
computation below (see that class's own docstring for the exact
numbers and the verification arithmetic). This is the correct, honest
scope for a golden-dataset test built on what could actually be
verified: it proves this codebase's formula transcription matches the
standard method exactly, which is the method the regional paper found
valid for Western Maharashtra — a real, traceable chain, not a
substituted one.

**Recommended follow-up, not this ticket's job:** if the Western
Maharashtra paper's specific numeric table becomes available (library
access, a preprint, or a data request to the authors), add a second
test class here with that paper's own basin-level rainfall/CN/runoff
triples, cited by table/figure number as this file's own established
convention already requires.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.enums import CalibrationStatus, StorageChangeBand
from app.services.hydrology.engine import (
    _CURVE_NUMBER,
    _INITIAL_ABSTRACTION_RATIO,
    _event_runoff_mm,
    WaterBalanceEngine,
)
from app.services.hydrology.models import WaterBalanceBundle, WaterBalanceConfig
from app.services.risk.models import MonthlyValue

_INCHES_TO_MM = 25.4


def _bundle_for_months(rainfall_mm: list[float], et_mm: list[float], resolution_flags: list[str] | None = None) -> WaterBalanceBundle:
    months = [date(2023 + (m // 12), (m % 12) + 1, 1) for m in range(len(rainfall_mm))]
    return WaterBalanceBundle(
        period_start=months[0],
        period_end=months[-1],
        rainfall_monthly=[MonthlyValue(period_start=d, value=v) for d, v in zip(months, rainfall_mm, strict=True)],
        et_monthly=[MonthlyValue(period_start=d, value=v) for d, v in zip(months, et_mm, strict=True)],
        # One storm event per month, at the month's full depth. This
        # deliberately reproduces the OLD monthly-aggregation behaviour
        # for the mass-balance tests below, whose expected P/ET/Q/dS
        # figures were derived against it — keeping them a check on the
        # engine's arithmetic (does P - ET - Q = dS close?) rather than
        # silently turning them into a check on the runoff timestep,
        # which `TestCurveNumberAgainstNrcsReference` covers directly and
        # per-event, as the NRCS method intends.
        rainfall_daily=[MonthlyValue(period_start=d, value=v) for d, v in zip(months, rainfall_mm, strict=True)],
        resolution_flags=resolution_flags or [],
    )


def _config() -> WaterBalanceConfig:
    return WaterBalanceConfig(model_version="golden-dataset-caller")


def _independent_scs_cn_runoff(rainfall_mm: float, curve_number: float = _CURVE_NUMBER) -> float:
    """Independent re-derivation of the published SCS-CN formula for one
    storm event, written out from the method's own definition rather than
    by calling `_event_runoff_mm` — so it is genuinely capable of
    disagreeing with the implementation under test.

    S = 25400/CN - 254 (mm), Ia = lambda * S, Q = (P-Ia)^2 / (P-Ia+S)
    for P > Ia, else 0.
    """
    s = (25400.0 / curve_number) - 254.0
    ia = _INITIAL_ABSTRACTION_RATIO * s
    if rainfall_mm <= ia:
        return 0.0
    excess = rainfall_mm - ia
    return (excess * excess) / (excess + s)


class TestCurveNumberAgainstNrcsReference:
    """USDA NRCS's own canonical worked example for the SCS Curve Number
    method: rainfall P = 5.1 in, CN = 75, direct runoff Q = 2.53 in.

    Source: USDA Natural Resources Conservation Service, National
    Engineering Handbook Part 630, Chapter 10, "Estimation of Direct
    Runoff from Storm Rainfall" — this exact P=5.1in/CN=75 example is
    reproduced across multiple NRCS-derived hydrology training materials
    (confirmed via live web search during this ticket; the primary PDF at
    https://irrigationtoolbox.com/NEH/Part630_Hydrology/H_210_630_10.pdf
    could not be text-extracted directly, so this file relies on the
    widely-reproduced secondary citation of that example rather than a
    direct PDF quote — noted here rather than silently presented as a
    verbatim primary-source excerpt).

    Independently verified below by hand computation using the standard
    formula (S = 1000/CN - 10 in inches; Ia = 0.2S; Q = (P-Ia)^2/(P-Ia+S)
    for P > Ia): S = 1000/75 - 10 = 3.3333 in, Ia = 0.6667 in,
    Q = (5.1-0.6667)^2 / (5.1-0.6667+3.3333) = 19.664/7.7667 = 2.5314 in
    — matching the cited 2.53 in figure to the precision that figure was
    itself reported at. This independent hand-check, not just the
    citation, is what makes this a real cross-check rather than a
    trusted magic number.

    This class validates the FORMULA TRANSCRIPTION ONLY, at the worked
    example's own CN=75, passed explicitly. It is deliberately
    independent of `_CURVE_NUMBER`, this service's regional default.

    Those two things were originally coupled — the default happened to
    also be 75, and this test asserted that equality to stay honest. That
    guard did its job: when `_CURVE_NUMBER` moved to 89 (NRCS TR-55's
    value for row crops on Hydrologic Soil Group D, the correct group for
    Deccan black cotton vertisols), this test failed loudly instead of
    silently revalidating a reference it no longer matched. The fix is to
    separate the questions rather than re-pin the reference: "is
    Q = (P-Ia)^2/(P-Ia+S) transcribed correctly?" is answered here at
    CN=75 forever, while "is our soil-group assignment right?" is a
    calibration question no published worked example can settle.
    """

    def test_matches_the_nrcs_worked_example_within_rounding_tolerance(self):
        rainfall_mm = 5.1 * _INCHES_TO_MM  # 129.54 mm, an exact unit conversion
        expected_runoff_mm = 2.53 * _INCHES_TO_MM  # 64.262 mm, per the cited NRCS example

        # CN=75 explicitly: the worked example's own value, NOT whatever
        # regional default this service currently ships.
        actual_runoff_mm = _event_runoff_mm(rainfall_mm, curve_number=75.0)

        # Tolerance rationale: the cited reference figure (2.53 in) is
        # itself only reported to 2 decimal places — a rounding
        # uncertainty of up to +/-0.005 in (+/-0.127 mm). 0.5 mm gives a
        # comfortable margin above that without being loose enough to
        # hide a real formula error (a wrong Ia/S coefficient would miss
        # by several mm, not fractions of one).
        assert actual_runoff_mm == pytest.approx(expected_runoff_mm, abs=0.5)

    def test_full_engine_reproduces_the_same_value_through_compute(self):
        """The same single-event reference point, exercised through the
        full public `compute()` path (bundle -> engine -> result), not
        just the private helper — proves the aggregation step doesn't
        distort a single-event reference value.

        Unlike the pure-formula test above, this one necessarily runs at
        the SHIPPING `_CURVE_NUMBER`, because `compute()` has no CN
        injection point (deliberately — production must not be able to
        pick a CN per call). So the expected value is derived here from
        `_scs_cn_runoff`, this file's own independent re-derivation of
        the published formula, rather than from the NRCS example's 2.53
        in figure, which only holds at CN=75. What this still proves, and
        what it is here for, is that no aggregation/unit step between
        bundle and result distorts a single event's runoff.
        """
        rainfall_mm = 5.1 * _INCHES_TO_MM
        bundle = _bundle_for_months(rainfall_mm=[rainfall_mm], et_mm=[0.0])

        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.runoff_mm == pytest.approx(_independent_scs_cn_runoff(rainfall_mm))


class TestWaterBalanceAgainstIndependentComputation:
    """dS = P - ET - Q, checked against a reference value computed by an
    independent script (not by calling any WaterBalanceEngine code) run
    during this ticket — see the literal numbers in the docstring below,
    reproducible by anyone reading this test."""

    def test_three_month_bundle_matches_independently_computed_residual(self):
        """rainfall = [120, 45, 200] mm as three storm events, ET = [35,
        20, 60] mm, CN = 89.

        Independently recomputed (standalone script, run when
        `_CURVE_NUMBER` moved 75 -> 89 for Hydrologic Soil Group D):
          S  = 25400/89 - 254 = 31.39325842696627 mm
          Ia = 0.2 * S        =  6.278651685393254 mm
          per-event runoff = [89.11952664781016, 21.384172071696067,
                              166.7060229277371]
          rainfall_mm = 365.0, et_mm = 115.0, runoff_mm = 277.2097216472433
          storage_change_mm = 365.0 - 115.0 - 277.2097216472433
                            = -27.209721647243327

        Note the sign flip against the previous CN=75 pinning (+61.25):
        modelling this catchment on the correct, far less permeable soil
        group turns a small apparent storage GAIN into a small storage
        LOSS on identical rainfall and ET. That sensitivity is the whole
        reason this value is pinned — the residual dS is the smallest
        term in the balance and therefore the one most distorted by an
        error in any of the larger ones.
        """
        bundle = _bundle_for_months(rainfall_mm=[120.0, 45.0, 200.0], et_mm=[35.0, 20.0, 60.0])

        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.rainfall_mm == pytest.approx(365.0)
        assert result.et_mm == pytest.approx(115.0)
        assert result.runoff_mm == pytest.approx(277.2097216472433)
        assert result.storage_change_mm == pytest.approx(-27.209721647243327)


class TestBoundaryConditions:
    def test_zero_rainfall_produces_exactly_zero_runoff(self):
        """P=0 is always <= Ia (Ia > 0 for any CN < 100) — Q=0 by
        definition of the piecewise formula, an exact algebraic result,
        not a floating-point coincidence, so this asserts exact equality
        rather than pytest.approx."""
        assert _event_runoff_mm(0.0) == 0.0

    def test_rainfall_exactly_at_initial_abstraction_produces_zero_runoff(self):
        """The formula's own boundary: P == Ia is defined as the
        non-runoff-producing case (Q=0), not the start of the quadratic
        term — this is the exact inclusive/exclusive boundary a
        transcription bug (using strict < instead of <=, or vice versa)
        would get wrong."""
        s = (25400.0 / _CURVE_NUMBER) - 254.0
        ia = _INITIAL_ABSTRACTION_RATIO * s

        assert _event_runoff_mm(ia) == 0.0
        # Just above the boundary must be strictly positive, proving the
        # boundary is a genuine threshold, not an off-by-something that
        # makes the whole function return 0 everywhere.
        assert _event_runoff_mm(ia + 0.01) > 0.0

    def test_extreme_rainfall_approaches_but_never_reaches_total_runoff(self):
        """Documented mathematical property of the SCS-CN formula (not a
        cited external figure — a directly verifiable asymptotic limit):
        as P -> infinity, Q/P -> 1, since the fixed retention S becomes
        negligible relative to P. At P=5000mm (a deliberately unrealistic
        stress value — no real Indian monsoon month approaches this),
        Q/P should exceed 0.95, and Q must remain strictly less than P
        (runoff can never exceed rainfall)."""
        extreme_rainfall_mm = 5000.0
        runoff_mm = _event_runoff_mm(extreme_rainfall_mm)

        assert runoff_mm < extreme_rainfall_mm
        assert (runoff_mm / extreme_rainfall_mm) > 0.95

    def test_prolonged_drought_produces_an_exact_deeply_negative_residual(self):
        """12 consecutive months of zero rainfall (a prolonged drought) —
        every runoff value is exactly 0 (per the zero-rainfall boundary
        above), so the residual reduces to exactly -sum(ET), an exact
        result, not an approximation."""
        et_values = [50.0] * 12
        bundle = _bundle_for_months(rainfall_mm=[0.0] * 12, et_mm=et_values)

        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.rainfall_mm == 0.0
        assert result.runoff_mm == 0.0
        assert result.et_mm == pytest.approx(sum(et_values))
        assert result.storage_change_mm == pytest.approx(-sum(et_values))
        assert result.storage_change_band == StorageChangeBand.MUCH_BELOW_NORMAL


class TestNumericalStability:
    def test_golden_bundle_is_deterministic_across_repeated_calls(self):
        bundle = _bundle_for_months(rainfall_mm=[120.0, 45.0, 200.0], et_mm=[35.0, 20.0, 60.0])
        config = _config()
        engine = WaterBalanceEngine()

        results = [engine.compute(bundle, config) for _ in range(10)]

        assert all(r == results[0] for r in results)

    def test_nrcs_reference_point_is_deterministic(self):
        rainfall_mm = 5.1 * _INCHES_TO_MM
        assert _event_runoff_mm(rainfall_mm) == _event_runoff_mm(rainfall_mm)


class TestPinnedGoldenResult:
    """Regression protection: every field of WaterBalanceEngineResult for
    one fixed, documented bundle, pinned to an exact expected value —
    exactly as test_report_text.py/test_report_pdf.py pin exact report
    text (Blueprint v2's own testing-strategy convention, "twin tests").
    A future refactor that silently changes the runoff formula, a band
    threshold, the completeness calculation, or the aggregation logic
    will fail THIS test even if every other test in the suite still
    passes, because this test's expected values were computed
    independently (see TestWaterBalanceAgainstIndependentComputation's
    docstring for the same underlying numbers and how they were
    derived) and hardcoded here, not re-derived from the engine at test
    time.
    """

    def test_pinned_result_for_the_documented_golden_bundle(self):
        bundle = _bundle_for_months(
            rainfall_mm=[120.0, 45.0, 200.0],
            et_mm=[35.0, 20.0, 60.0],
            resolution_flags=["rainfall_sub_pixel"],
        )

        result = WaterBalanceEngine().compute(bundle, _config())

        assert result.rainfall_mm == pytest.approx(365.0)
        assert result.et_mm == pytest.approx(115.0)
        assert result.runoff_mm == pytest.approx(277.2097216472433)
        assert result.storage_change_mm == pytest.approx(-27.209721647243327)
        # Was ABOVE_NORMAL at CN=75. -27.21 mm falls in the -50..+50 mm
        # NORMAL band, so correcting the soil group moves this bundle
        # across a band boundary as well as flipping the sign — the
        # band, not just the number, is sensitive to CN.
        assert result.storage_change_band == StorageChangeBand.NORMAL
        assert result.data_completeness == pytest.approx(100.0)
        assert result.calibration_status == CalibrationStatus.UNCALIBRATED
        assert result.closed_catchment_assumed is True
        assert result.resolution_flags == ["rainfall_sub_pixel"]
        assert result.model_version == WaterBalanceEngine.MODEL_VERSION
