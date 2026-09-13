"""Physical validation of a computed water balance.

Every other test in this repository asks "did the code do what the source
says?". This module asks "is the answer physically possible, and is it
plausible for where this catchment actually is?" — the question the
MOD16A2 defect passed 442 tests without ever being asked.

=====================================================================
WHAT "CLOSURE" CAN AND CANNOT MEAN HERE — READ BEFORE ADDING A CHECK
=====================================================================

The obvious check is water balance closure: assert that
`P - ET - Q - dS` falls within a tolerance and fail loudly otherwise.
**That check is vacuous against this engine, and implementing it as
though it were meaningful would be fabricated validation.**

`WaterBalanceEngine.compute()` defines storage change as the residual:

    storage_change_mm = rainfall_mm - et_mm - runoff_mm

so `P - ET - Q - dS == 0` identically, at machine precision, for every
catchment, always. There is no independent measurement of dS to disagree
with, and no lateral-flow term R at all — the closed-catchment
assumption (Blueprint v2 D4, Part 10 limitation 3) means R is defined to
be zero rather than estimated. A tolerance test on that identity would
report a passing closure check on every run including the ones that are
badly wrong, which is worse than having no check.

`_check_identity()` below still asserts the identity — but as a
REFACTOR GUARD, labelled as one. It catches a future change that breaks
the arithmetic; it says nothing about whether the science is right, and
its docstring says so, so nobody reads a green run as closure evidence.

**Real closure validation needs an independent estimate of a term.** Two
routes exist and neither is free:

1. A second ET product (PML_V2 is the practical candidate: 500 m,
   8-day, in GEE, a different algorithm from MOD16A2). Disagreement
   between two independent estimates of the same quantity IS a
   falsifiable check. Honest limitation: PML_V2 is also MODIS-driven,
   so this is algorithm independence, not sensor independence, and any
   agreement it produces is weaker evidence than "two independent
   datasets" suggests.
2. An independent dS from GRACE. Excluded — native resolution ~300 km
   against catchments of a few km2 (Blueprint v2 Part 0). Not viable at
   any point on this roadmap.

Until route 1 ships, what this module provides is **plausibility, not
closure**: per-term and per-ratio envelopes that catch a term wrong by a
large factor. That is a weaker guarantee than the word "closure"
implies, and it is stated in those terms everywhere it is reported.

What plausibility bounds DO catch, demonstrably: a production Raichur
water balance reporting ET at 20% of rainfall, runoff at 41%, and a
residual at 39% trips three separate warnings here — the ET term is far
below any semi-arid envelope, and because dS is the residual, the
missing ET reappears as implausible recharge. One upstream defect, three
visible symptoms, which is exactly how a residual-based balance fails.
"""

from __future__ import annotations

from app.services.hydrology.models import AnnualWaterBalance, WaterBalanceEngineResult
from app.services.validation.models import Severity, ValidationFinding, ValidationReport
from app.services.validation.zones import AgroClimaticZone, ZoneRanges, ranges_for

__all__ = ["validate_water_balance"]

# The identity is pure floating-point arithmetic over a few dozen sums,
# so the only drift it can accumulate is representation error. 0.01 mm is
# far above that and far below any real defect — a term wrong by a factor
# of anything misses by whole millimetres at minimum.
#
# This tolerance is NOT a physical closure tolerance and must never be
# widened to make a failing balance pass. If this assertion ever fires,
# the engine's arithmetic changed; that is the finding.
_IDENTITY_TOLERANCE_MM = 0.01

# Below this, ratios stop meaning anything: dividing by a near-zero
# rainfall total turns rounding noise into a 400% runoff coefficient.
# A catchment with essentially no rainfall over the window is a data
# problem, reported as its own finding rather than as a cascade of
# spurious ratio failures.
_MIN_RAINFALL_FOR_RATIOS_MM = 10.0

# Zones where ET exceeding precipitation is worth flagging. In an
# energy-limited (humid) catchment the comparison carries much less
# information, and irrigation imports make it a weak signal everywhere —
# hence WARNING, never ERROR.
_WATER_LIMITED_ZONES = frozenset({AgroClimaticZone.ARID, AgroClimaticZone.SEMI_ARID})

# A water year needs to be complete before its totals can be compared
# against an annual envelope. A 4-month stub at the edge of the
# observation window is not a dry year, and checking it as one would
# generate a warning on every single report.
_COMPLETE_YEAR_MONTHS = 12


def validate_water_balance(
    result: WaterBalanceEngineResult,
    *,
    zone: AgroClimaticZone = AgroClimaticZone.UNKNOWN,
    subject: str = "water_balance",
) -> ValidationReport:
    """Check one computed water balance against physics and against the
    plausible envelope for its agro-climatic zone.

    Returns a report; never raises for a physical failure. See
    `validation/models.py` for why. A malformed `result` — a missing
    attribute, a wrong type — will still raise, because that is a
    programming error rather than a scientific one.

    `zone` defaults to UNKNOWN, which disables every zone-dependent check
    and records each one as skipped. That default is deliberate: a caller
    that has not established the zone gets a visibly incomplete report,
    not a silently permissive one.
    """
    findings: list[ValidationFinding] = []
    run = 0
    skipped = 0

    rainfall = result.rainfall_mm
    et = result.et_mm
    runoff = result.runoff_mm
    storage_change = result.storage_change_mm
    ranges = ranges_for(zone)

    # ---- invariants: true everywhere, no zone needed ----------------
    for name, value in (("rainfall_mm", rainfall), ("et_mm", et), ("runoff_mm", runoff)):
        if value is None:
            skipped += 1
            findings.append(
                ValidationFinding(
                    check="term_present",
                    severity=Severity.INFO,
                    subject=name,
                    message=f"{name} could not be computed for this period; dependent checks skipped.",
                    expected="a non-null value",
                )
            )
            continue
        run += 1
        if value < 0:
            findings.append(
                ValidationFinding(
                    check="non_negative",
                    severity=Severity.ERROR,
                    subject=name,
                    observed=value,
                    message=f"{name} is negative ({value:.2f} mm), which is not physically possible.",
                    expected=">= 0 mm",
                )
            )

    if rainfall is not None and runoff is not None:
        run += 1
        if runoff > rainfall:
            findings.append(
                ValidationFinding(
                    check="runoff_not_exceeding_rainfall",
                    severity=Severity.ERROR,
                    subject="runoff_mm",
                    observed=runoff,
                    message=(
                        f"Runoff ({runoff:.1f} mm) exceeds rainfall ({rainfall:.1f} mm). "
                        "No catchment can shed more water than it receives."
                    ),
                    expected=f"<= rainfall ({rainfall:.1f} mm)",
                )
            )

    run += 1
    identity_finding = _check_identity(rainfall, et, runoff, storage_change)
    if identity_finding is not None:
        findings.append(identity_finding)

    # ---- zone-dependent plausibility --------------------------------
    if ranges is None:
        skipped += 4
        findings.append(
            ValidationFinding(
                check="zone_assigned",
                severity=Severity.INFO,
                subject="agro_climatic_zone",
                message=(
                    "Agro-climatic zone is unknown, so no plausibility envelope applies. "
                    "Four zone-dependent checks were skipped — this balance has been checked "
                    "for arithmetic validity only, NOT for plausibility."
                ),
                expected="a resolved agro-climatic zone",
            )
        )
        return ValidationReport(subject=subject, findings=findings, checks_run=run, checks_skipped=skipped)

    if rainfall is None or rainfall < _MIN_RAINFALL_FOR_RATIOS_MM:
        skipped += 3
        findings.append(
            ValidationFinding(
                check="rainfall_sufficient_for_ratios",
                severity=Severity.WARNING if rainfall is not None else Severity.INFO,
                subject="rainfall_mm",
                observed=rainfall,
                message=(
                    f"Rainfall over the whole period is {rainfall:.1f} mm, below the "
                    f"{_MIN_RAINFALL_FOR_RATIOS_MM:.0f} mm needed for ratio checks to mean anything. "
                    "Ratio-based plausibility checks were skipped."
                    if rainfall is not None
                    else "Rainfall is unavailable; ratio-based plausibility checks were skipped."
                ),
                expected=f">= {_MIN_RAINFALL_FOR_RATIOS_MM:.0f} mm over the period",
            )
        )
    else:
        run, ratio_findings = _check_ratios(rainfall, et, runoff, storage_change, ranges, zone, run)
        findings.extend(ratio_findings)

    run += 1
    findings.extend(_check_annual_rainfall_matches_zone(result.annual, ranges, zone))

    findings.extend(_note_residual_attribution(findings))

    return ValidationReport(subject=subject, findings=findings, checks_run=run, checks_skipped=skipped)


def _check_identity(
    rainfall: float | None, et: float | None, runoff: float | None, storage_change: float | None
) -> ValidationFinding | None:
    """REFACTOR GUARD, NOT A CLOSURE TEST.

    Asserts `dS == P - ET - Q` to floating-point precision. Because the
    engine *defines* dS that way, this can only fail if someone changes
    the engine's arithmetic — which is worth catching, and is the entire
    value of this check. It is emphatically not evidence that the water
    balance closes against reality: there is no independent measurement
    of dS here to close against. See this module's docstring.
    """
    if None in (rainfall, et, runoff, storage_change):
        return None
    expected = rainfall - et - runoff
    drift = abs(storage_change - expected)
    if drift <= _IDENTITY_TOLERANCE_MM:
        return None
    return ValidationFinding(
        check="water_balance_identity",
        severity=Severity.ERROR,
        subject="storage_change_mm",
        observed=storage_change,
        message=(
            f"Storage change ({storage_change:.4f} mm) no longer equals P - ET - Q "
            f"({expected:.4f} mm); drift {drift:.4f} mm. The engine's arithmetic has changed. "
            "This is a code regression, not a physical finding."
        ),
        expected=f"P - ET - Q = {expected:.4f} mm (within {_IDENTITY_TOLERANCE_MM} mm)",
    )


def _check_ratios(
    rainfall: float,
    et: float | None,
    runoff: float | None,
    storage_change: float | None,
    ranges: ZoneRanges,
    zone: AgroClimaticZone,
    run: int,
) -> tuple[int, list[ValidationFinding]]:
    """ET/P, Q/P and |dS|/P against the zone envelope.

    Ratios are taken over the whole period, not annualised — a ratio is
    already dimensionless, so a three-year total divided by a three-year
    total is directly comparable to an annual expectation.
    """
    findings: list[ValidationFinding] = []

    if et is not None:
        run += 1
        fraction = et / rainfall
        findings.extend(
            _range_finding(
                check="et_fraction_of_rainfall",
                subject="et_mm",
                observed=fraction,
                bounds=ranges.et_fraction,
                zone=zone,
                describe=(
                    f"ET is {fraction:.0%} of rainfall ({et:.1f} of {rainfall:.1f} mm)"
                ),
                consequence=(
                    "Because storage change is computed as the residual, an ET term that is "
                    "too low is reattributed to recharge rather than being visible as missing ET."
                ),
            )
        )
        if zone in _WATER_LIMITED_ZONES and et > rainfall:
            findings.append(
                ValidationFinding(
                    check="et_not_exceeding_rainfall_when_water_limited",
                    severity=Severity.WARNING,
                    subject="et_mm",
                    observed=et,
                    message=(
                        f"ET ({et:.1f} mm) exceeds rainfall ({rainfall:.1f} mm) in a water-limited "
                        f"({zone.value}) catchment. This is only possible with an external water "
                        "import — irrigation, canal supply, or lateral subsurface inflow — none of "
                        "which the closed-catchment balance models. Either the catchment is not "
                        "closed, or a term is wrong."
                    ),
                    expected=f"<= rainfall ({rainfall:.1f} mm) absent an external import",
                    source="Blueprint v2 Part 10, limitation 3 (closed-catchment assumption)",
                )
            )

    if runoff is not None:
        run += 1
        coefficient = runoff / rainfall
        findings.extend(
            _range_finding(
                check="runoff_coefficient",
                subject="runoff_mm",
                observed=coefficient,
                bounds=ranges.runoff_coefficient,
                zone=zone,
                describe=f"Runoff coefficient is {coefficient:.0%} ({runoff:.1f} of {rainfall:.1f} mm)",
                consequence=(
                    "Runoff is derived from a single fixed Curve Number with no antecedent-moisture "
                    "adjustment, so a coefficient outside the zone envelope most often means the "
                    "Curve Number is wrong for this catchment's soil group."
                ),
            )
        )

    if storage_change is not None:
        run += 1
        fraction = abs(storage_change) / rainfall
        findings.extend(
            _range_finding(
                check="storage_change_fraction",
                subject="storage_change_mm",
                observed=fraction,
                bounds=ranges.abs_storage_change_fraction,
                zone=zone,
                describe=(
                    f"Storage change is {fraction:.0%} of rainfall "
                    f"({storage_change:+.1f} of {rainfall:.1f} mm)"
                ),
                consequence=(
                    "Storage change is the residual and absorbs every error in P, ET and Q. A large "
                    "residual is far more often an upstream defect than a real storage signal — "
                    "check the ET and runoff findings above before treating it as physical."
                ),
            )
        )

    return run, findings


def _range_finding(
    *,
    check: str,
    subject: str,
    observed: float,
    bounds: tuple[float, float],
    zone: AgroClimaticZone,
    describe: str,
    consequence: str,
) -> list[ValidationFinding]:
    low, high = bounds
    if low <= observed <= high:
        return []
    direction = "below" if observed < low else "above"
    return [
        ValidationFinding(
            check=check,
            severity=Severity.WARNING,
            subject=subject,
            observed=observed,
            message=(
                f"{describe} — {direction} the {low:.0%}-{high:.0%} range reported for "
                f"{zone.value.replace('_', '-')} catchments. {consequence}"
            ),
            expected=f"{low:.0%}-{high:.0%} of rainfall for a {zone.value.replace('_', '-')} catchment",
            source="Literature envelope, UNCALIBRATED — see services/validation/zones.py",
        )
    ]


def _check_annual_rainfall_matches_zone(
    annual: list[AnnualWaterBalance], ranges: ZoneRanges, zone: AgroClimaticZone
) -> list[ValidationFinding]:
    """Does each complete water year's rainfall match the zone it was
    assigned to?

    A mismatch usually means the zone assignment is wrong, not that the
    rainfall is — which matters, because every other zone-dependent
    check above is then being applied against the wrong envelope. This
    check exists to stop a mis-assigned zone from silently validating a
    balance against bounds that never applied to it.
    """
    low, high = ranges.rainfall_mm
    findings: list[ValidationFinding] = []
    for year in annual:
        if year.months_covered < _COMPLETE_YEAR_MONTHS or year.rainfall_mm is None:
            continue
        if low <= year.rainfall_mm <= high:
            continue
        findings.append(
            ValidationFinding(
                check="annual_rainfall_matches_zone",
                severity=Severity.WARNING,
                subject=f"annual_rainfall_mm[{year.label}]",
                observed=year.rainfall_mm,
                message=(
                    f"Water year {year.label} received {year.rainfall_mm:.0f} mm, outside the "
                    f"{low:.0f}-{high:.0f} mm range for a {zone.value.replace('_', '-')} catchment. "
                    "The zone assignment is more likely wrong than the rainfall — every other "
                    "zone-dependent check above used this envelope."
                ),
                expected=f"{low:.0f}-{high:.0f} mm/year",
                source="services/validation/zones.py",
            )
        )
    return findings


def _note_residual_attribution(findings: list[ValidationFinding]) -> list[ValidationFinding]:
    """When both ET and the residual are out of range, say so as one
    diagnosis rather than leaving two symptoms to be read separately.

    This is the signature of the MOD16A2 defect and of anything like it:
    the residual absorbs whatever the ET term loses, so the two findings
    are not independent evidence of two problems. Reporting them without
    this note invites someone to "fix" the recharge number.
    """
    failed = {f.check for f in findings if f.is_failure}
    if "et_fraction_of_rainfall" not in failed or "storage_change_fraction" not in failed:
        return []
    return [
        ValidationFinding(
            check="residual_absorbs_et_error",
            severity=Severity.INFO,
            subject="storage_change_mm",
            message=(
                "ET and storage change are BOTH outside their envelopes. These are not two "
                "independent problems: storage change is computed as P - ET - Q, so an ET term "
                "that is too low by X mm produces a storage change too high by exactly X mm. "
                "Investigate the ET term first; the residual will follow it."
            ),
            expected="ET corrected first, then re-check the residual",
        )
    ]
