"""Cross-product consistency: two products estimating the same quantity.

This is the only check in the harness that can falsify a water balance
term against something other than an envelope. `water_balance.py`
explains why a literal closure test is vacuous against this engine; an
independent second estimate of ET is the real substitute.

=====================================================================
THE TOLERANCE HAS NO DEFAULT, AND THAT IS THE DESIGN
=====================================================================

`tolerance` is a required argument. There is deliberately no default,
because the one measurement available says any plausible-sounding
default would be either wrong or quietly permissive:

    Maski-area polygon, water year 2022-23 (measured 13 Sep 2026)
      CHIRPS rainfall                    610 mm
      MOD16A2, current fixed method      500 mm   (ET/P 0.82)
      PML_V2 v018 (Ec + Es + Ei)         811 mm   (ET/P 1.33)
      symmetric relative difference      48%

Two MODIS-driven products, two algorithms, a 48% disagreement on the
same catchment-year. A tolerance of 20-30% — the kind of figure that
sounds reasonable — fails this site. A tolerance of 50% passes it and
then passes nearly anything. Choosing between those is a scientific
judgement about how much ET uncertainty the platform will accept, and
choosing silently, in a default, is exactly the move that turns a check
into decoration.

So the caller states the tolerance, the finding records it, and the
number is visible wherever the result is.

What 48% probably means, stated as hypotheses rather than conclusions:
PML_V2 reporting more ET than rainfall is physically consistent with an
external water import, and Raichur district is heavily canal-irrigated
from the Tungabhadra system — whether this particular polygon lies in a
command area has NOT been checked. If it does, PML_V2 may be seeing
irrigated evapotranspiration that the closed-catchment balance has no
term for. It is equally possible that one algorithm is simply biased
for this land cover. Nothing here distinguishes the two.

=====================================================================
INDEPENDENCE IS PARTIAL — SAY SO EVERY TIME
=====================================================================

MOD16A2 and PML are both driven by MODIS land-surface inputs (PML by
MODIS LAI). Their agreement is **algorithm independence, not sensor
independence**: a shared error in the MODIS inputs moves both together
and would pass this check. Agreement is therefore weaker evidence than
"two independent datasets agree", and every finding produced here says
so rather than leaving the word "independent" to do more work than it
can.

Coverage is also partial: PML_V2 v018 ends 27 Dec 2023 (and is
deprecated); its successor PML_V22a ends 26 Dec 2024. Neither covers the
most recent part of a current three-year report window. A check over a
window the secondary product does not reach must report the uncovered
span, not silently validate the years it happens to have.
"""

from __future__ import annotations

from app.services.validation.models import Severity, ValidationFinding, ValidationReport

__all__ = ["relative_difference", "validate_cross_product_agreement"]

_PARTIAL_INDEPENDENCE_NOTE = (
    "Both products are MODIS-driven: agreement shows algorithm independence, not sensor "
    "independence, and a shared input error would pass this check."
)


def relative_difference(a: float, b: float) -> float | None:
    """|a - b| divided by their mean.

    Symmetric on purpose. `|a - b| / a` makes the answer depend on which
    product was called primary — 62% or 38% for the same Maski pair —
    and the choice of primary is a convention, not a fact about the
    disagreement. Returns None when both are zero, where a relative
    difference is undefined rather than zero.
    """
    mean = (a + b) / 2.0
    if mean == 0:
        return None
    return abs(a - b) / abs(mean)


def validate_cross_product_agreement(
    *,
    quantity: str,
    primary_name: str,
    primary_value: float | None,
    secondary_name: str,
    secondary_value: float | None,
    tolerance: float,
    units: str = "mm",
    partially_independent: bool = True,
    uncovered_span: str = "",
    subject: str | None = None,
) -> ValidationReport:
    """Compare two estimates of one quantity against an explicit tolerance.

    `tolerance` is a fraction (0.25 = 25%) of the symmetric relative
    difference. It is required — see the module docstring for why there
    is no default, and do not add one.

    `uncovered_span` names any part of the assessment window the
    secondary product does not reach. When set, the report says the
    comparison covers only part of the window, whatever the result.
    """
    if tolerance <= 0:
        raise ValueError("tolerance must be positive; a zero tolerance fails every real comparison")

    subject = subject or f"{quantity}:{primary_name}_vs_{secondary_name}"
    findings: list[ValidationFinding] = []
    caveat = _PARTIAL_INDEPENDENCE_NOTE if partially_independent else ""

    if uncovered_span:
        findings.append(
            ValidationFinding(
                check="cross_product_coverage",
                severity=Severity.INFO,
                subject=quantity,
                message=(
                    f"{secondary_name} does not cover {uncovered_span}. The comparison below "
                    "validates only the overlapping period, not the whole assessment window."
                ),
                expected="secondary product covering the full window",
            )
        )

    if primary_value is None or secondary_value is None:
        missing = primary_name if primary_value is None else secondary_name
        findings.append(
            ValidationFinding(
                check="cross_product_agreement",
                severity=Severity.INFO,
                subject=quantity,
                message=f"{missing} has no value for this period; cross-product check skipped.",
                expected="values from both products",
            )
        )
        return ValidationReport(subject=subject, findings=findings, checks_run=0, checks_skipped=1)

    difference = relative_difference(primary_value, secondary_value)
    if difference is None or difference <= tolerance:
        return ValidationReport(subject=subject, findings=findings, checks_run=1)

    findings.append(
        ValidationFinding(
            check="cross_product_agreement",
            severity=Severity.WARNING,
            subject=quantity,
            observed=difference,
            message=(
                f"{primary_name} and {secondary_name} disagree on {quantity} by {difference:.0%} "
                f"({primary_value:.1f} vs {secondary_value:.1f} {units}), beyond the stated "
                f"{tolerance:.0%} tolerance. At least one estimate is wrong for this catchment, "
                "and nothing in this check says which. " + caveat
            ).strip(),
            expected=f"symmetric relative difference <= {tolerance:.0%}",
            source="Tolerance supplied by the caller, not a calibrated bound",
        )
    )
    return ValidationReport(subject=subject, findings=findings, checks_run=1)
