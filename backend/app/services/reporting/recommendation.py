"""Credit Recommendation logic (Product Design v2 §1.1 P7 / §7.5) — a
direct Python port of the dashboard's `recommendation.ts`, following the
exact "fixed template over already-computed backend outputs, never
invented advice" discipline `report_text.py` already established for the
narrative/driver sentences.

REPORT V2 finding: this logic existed only in the frontend — the PDF has
never had a Recommendation block (docs/DECISIONS.md's M2B P9 entry
explicitly flags this as deferred, not forgotten). Ported here verbatim,
not reworded: the postures below are a founder-approved, already-pinned
product principle (review postures, e.g. "escalate to branch-manager
review" — never a loan-approval verdict like "not recommended", which
would silently reverse the explicit anti-goal "not a lending decision
engine"). Confirmed with the founder before implementation that this PDF
redesign reuses this wording as-is rather than adopting verdict-style
language.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import RiskBand
from app.schemas.report import ReportResponse
from app.services.reporting.report_text import FACTOR_LABELS, factor_driver_text, js_round, report_narrative

# Below this confidence, the recommended action carries an "indicative
# only" qualifier. Not part of the versioned risk-engine config — a fixed
# product-level constant, exactly like the engine's own _BAND_THRESHOLDS.
# Mirrors frontend/src/features/report/recommendation.ts's identical
# constant and reasoning verbatim.
RECOMMENDATION_CONFIDENCE_THRESHOLD = 70

# Fixed posture per band — deterministic, never generated. The credit
# decision remains the bank's; this states a review posture, not a
# lending instruction. Verbatim from ACTION_BY_BAND in recommendation.ts.
ACTION_BY_BAND: dict[RiskBand, str] = {
    RiskBand.LOW: "Standard appraisal. No climate-driven escalation required.",
    RiskBand.MODERATE: "Standard appraisal. Note the leading risk factor below in the loan file.",
    RiskBand.HIGH: "Escalate to branch-manager review. Consider risk-adjusted terms.",
    RiskBand.VERY_HIGH: "Refer to branch manager. Recommend independent field verification before sanction.",
}

# When no overall score could be estimated (rule-engine-v2 onward).
NO_OVERALL_SCORE_ACTION = (
    "No overall risk score could be estimated from the available satellite evidence. Do not rely on this report "
    "for a credit decision; verify the farm in the field."
)

# Whether the posture itself calls for a field officer, independent of the
# indicative-only confidence qualifier (which also implies verification is
# warranted — see field_verification_recommended below).
_FIELD_VERIFICATION_BANDS = {RiskBand.VERY_HIGH}


@dataclass(frozen=True)
class PrimaryDriver:
    factor: str
    label: str
    value: float
    text: str


@dataclass(frozen=True)
class Recommendation:
    # Reuses the existing pinned narrative — one summary, never two
    # competing descriptions of the same score.
    summary: str
    # Every factor scored High or Very High, worst first — empty when
    # nothing scored that severely, never padded to avoid an empty list.
    primary_drivers: list[PrimaryDriver] = field(default_factory=list)
    action: str = ""
    is_indicative_only: bool = False


def build_recommendation(report: ReportResponse) -> Recommendation:
    """The Recommendation block: Assessment Summary / Primary Drivers /
    Recommended Action, derived ONLY from already-computed backend outputs
    (overall_band, confidence, factor scores) — no new inference, no
    invented advice."""
    primary_drivers = [
        PrimaryDriver(
            factor=f.factor.value,
            label=FACTOR_LABELS[f.factor],
            value=f.value,
            text=factor_driver_text(f),
        )
        for f in sorted(
            (f for f in report.factors if f.value is not None and f.band in (RiskBand.HIGH, RiskBand.VERY_HIGH)),
            key=lambda f: f.value,
            reverse=True,
        )
    ]

    if report.overall_band is None:
        # No composite could be estimated. There is no band posture to give,
        # and inventing one would restore the defect Phase C removed.
        return Recommendation(
            summary=report_narrative(report),
            primary_drivers=primary_drivers,
            action=NO_OVERALL_SCORE_ACTION,
            is_indicative_only=True,
        )

    is_indicative_only = report.confidence < RECOMMENDATION_CONFIDENCE_THRESHOLD
    posture = ACTION_BY_BAND[report.overall_band]
    action = (
        f"Indicative only — limited satellite data available (data completeness {js_round(report.confidence)}%). "
        f"{posture}"
        if is_indicative_only
        else posture
    )

    return Recommendation(
        summary=report_narrative(report),
        primary_drivers=primary_drivers,
        action=action,
        is_indicative_only=is_indicative_only,
    )


def field_verification_recommended(report: ReportResponse, recommendation: Recommendation) -> bool:
    """Answers "should I send a field officer?" directly — real, band- and
    confidence-derived, never a separate/competing judgment from the
    posture text above."""
    return (
        report.overall_band is None
        or report.overall_band in _FIELD_VERIFICATION_BANDS
        or recommendation.is_indicative_only
    )


def recommendation_why_bullets(report: ReportResponse, recommendation: Recommendation) -> list[str]:
    """Up to 5 bullets explaining the recommendation — primary drivers
    first (worst factor first, same ordering as primary_drivers), then the
    confidence caveat if indicative-only, then the standing disclaimer.
    Every bullet is either a primary driver's own arithmetic-fact sentence
    or a fixed disclosure line — never a new causal claim."""
    bullets = [f"{driver.label}: {driver.text}" for driver in recommendation.primary_drivers]
    if report.overall_band is None:
        uncomputed = [FACTOR_LABELS[f.factor] for f in report.factors if f.value is None]
        bullets.append(f"Not computed: {', '.join(uncomputed)}." if uncomputed else "No overall score could be estimated.")
    elif recommendation.is_indicative_only:
        bullets.append(
            f"Data completeness is {js_round(report.confidence)}%, below the "
            f"{RECOMMENDATION_CONFIDENCE_THRESHOLD}% threshold for a standard-confidence recommendation."
        )
    if not bullets:
        bullets.append("No factor scored High or Very High risk.")
    bullets.append("Decision support only — the credit decision remains with the bank.")
    return bullets[:5]
