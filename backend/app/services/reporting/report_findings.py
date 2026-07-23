"""Key Findings (Page 1) and per-factor Recommended Action (Page 2 dashboard
cards) — REPORT V2.

Both are small, fixed, deterministic (factor, band) -> phrase tables, same
"arithmetic fact, never invented cause" discipline as report_text.py:
every phrase is a plain-English restatement of a band the engine already
computed, never a new inference. Findings describe WHAT the assessment
found; actions prescribe WHAT the officer should do about it — two
different jobs, kept in two separate tables rather than one field doing
both.
"""

from __future__ import annotations

from app.models.enums import RiskBand, RiskFactor
from app.schemas.report import FactorScoreResponse

KEY_FINDING_PHRASES: dict[RiskFactor, dict[RiskBand, str]] = {
    RiskFactor.VEGETATION_STABILITY: {
        RiskBand.LOW: "Stable, healthy vegetation for this farm",
        RiskBand.MODERATE: "Vegetation showing early signs of stress",
        RiskBand.HIGH: "Vegetation notably below this farm's own history",
        RiskBand.VERY_HIGH: "Vegetation severely below this farm's own history",
    },
    RiskFactor.WATER_AVAILABILITY: {
        RiskBand.LOW: "Healthy surface water and crop moisture",
        RiskBand.MODERATE: "Moderate water stress",
        RiskBand.HIGH: "Significant water stress",
        RiskBand.VERY_HIGH: "Severe water stress",
    },
    RiskFactor.DROUGHT_RISK: {
        RiskBand.LOW: "Low drought risk this season",
        RiskBand.MODERATE: "Below-average moisture — an early drought signal",
        RiskBand.HIGH: "Elevated drought risk",
        RiskBand.VERY_HIGH: "Severe drought conditions indicated",
    },
    RiskFactor.FLOOD_EXPOSURE: {
        RiskBand.LOW: "Low historical flooding on this land",
        RiskBand.MODERATE: "Moderate historical flood exposure",
        RiskBand.HIGH: "High historical flood exposure",
        RiskBand.VERY_HIGH: "Very high historical flood exposure",
    },
}

RECOMMENDED_ACTION_BY_FACTOR_BAND: dict[RiskFactor, dict[RiskBand, str]] = {
    RiskFactor.VEGETATION_STABILITY: {
        RiskBand.LOW: "No action needed — vegetation is consistent with this farm's healthy history.",
        RiskBand.MODERATE: "Monitor vegetation over the next assessment cycle; no immediate action required.",
        RiskBand.HIGH: "Discuss recent field conditions with the farmer; consider a field visit if this persists next season.",
        RiskBand.VERY_HIGH: "Recommend a field visit to confirm crop condition before finalizing terms.",
    },
    RiskFactor.WATER_AVAILABILITY: {
        RiskBand.LOW: "No action needed — surface water and crop moisture are within normal range.",
        RiskBand.MODERATE: "Monitor irrigation availability during the next 30 days.",
        RiskBand.HIGH: "Confirm the farm's irrigation source and backup water access with the farmer.",
        RiskBand.VERY_HIGH: "Verify irrigation access before sanction — water stress is severe.",
    },
    RiskFactor.DROUGHT_RISK: {
        RiskBand.LOW: "No action needed — drought indicators are within normal range.",
        RiskBand.MODERATE: "Note below-average moisture in the loan file; reassess if the next season confirms the trend.",
        RiskBand.HIGH: "Discuss drought contingency (e.g. crop insurance, alternate irrigation) with the farmer.",
        RiskBand.VERY_HIGH: "Recommend field verification of current crop condition before sanction.",
    },
    RiskFactor.FLOOD_EXPOSURE: {
        RiskBand.LOW: "No action needed — this land has a low historical flood-occurrence record.",
        RiskBand.MODERATE: "Note the flood-exposure history in the loan file for future reference.",
        RiskBand.HIGH: "Confirm the farmer's flood-mitigation plan (drainage, elevated storage) if applicable.",
        RiskBand.VERY_HIGH: "Recommend field verification of flood-mitigation measures before sanction.",
    },
}


def key_finding(factor: FactorScoreResponse) -> str:
    return KEY_FINDING_PHRASES[factor.factor][factor.band]


def recommended_action(factor: FactorScoreResponse) -> str:
    return RECOMMENDED_ACTION_BY_FACTOR_BAND[factor.factor][factor.band]


def key_findings_for_report(factors: list[FactorScoreResponse]) -> list[str]:
    """Ordered findings for every factor — Page 1's Key Findings list.
    Always one finding per factor (4 for the current MVP factor set); never
    fewer, never invented beyond what the engine actually scored."""
    return [key_finding(f) for f in factors]
