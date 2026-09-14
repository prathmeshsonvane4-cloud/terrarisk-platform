"""Decision sufficiency — is the evidence adequate for a decision of this
kind? Pure, zero I/O.

Distinct from model confidence by construction. Model confidence
(`RiskResult.model_confidence`) is a statistical property of the estimate and
knows nothing about decisions. Sufficiency takes that estimate, the evidence
behind it and a stated policy, and answers per stakes tier — with a concrete
sentence for every reason the evidence falls short.

Nothing here recommends an action. PROCEED / VERIFY / WAIT / ESCALATE /
ABSTAIN is the decision-output work that follows, and it will read these
verdicts.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date

from app.models.enums import EvidenceValidation
from app.services.risk.models import FactorResult, RiskResult
from app.services.risk.seasonal import MIN_BASELINE_SAMPLES
from app.services.sufficiency.policy import StakesTier, SufficiencyPolicy, TierRequirement

__all__ = [
    "DecisionSufficiency",
    "EvidenceFacts",
    "Inadequacy",
    "TierVerdict",
    "evaluate_sufficiency",
]

# CHIRPS native cell, hectares. A farm smaller than this receives a regional
# rainfall value.
_CHIRPS_CELL_HA = 3000.0


@dataclass(frozen=True)
class EvidenceFacts:
    """What sufficiency needs that the engine result does not carry."""

    window_last_period: date
    # Latest monthly period with a usable optical (NDVI) reading. None: none.
    latest_optical_period: date | None
    error_findings: int
    warning_findings: int
    # validation_status of every input in the result's lineage.
    input_validation_statuses: list[EvidenceValidation]
    farm_area_ha: float | None = None


@dataclass(frozen=True)
class Inadequacy:
    code: str
    statement: str
    factor: str | None = None


@dataclass(frozen=True)
class TierVerdict:
    tier: StakesTier
    sufficient: bool
    description: str
    # Every requirement of this tier the evidence does not meet.
    inadequacies: list[Inadequacy] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionSufficiency:
    policy_version: str
    calibration_status: str
    tiers: list[TierVerdict]
    # Limits that apply whatever the tier and never block on their own.
    caveats: list[Inadequacy]
    statement: str


_SIGNAL_LABELS = {
    "ndvi_percentile": "NDVI",
    "mndwi_percentile": "MNDWI",
    "ndmi_percentile": "NDMI",
    "vci": "the Vegetation Condition Index",
    "rainfall_anomaly": "the rainfall anomaly",
    "flood_rainfall_anomaly": "the flood rainfall anomaly",
    "jrc_occurrence": "JRC surface-water history",
}


def _label(factor: FactorResult) -> str:
    return factor.factor.value.replace("_", " ").capitalize()


def _signal_statement(factor: FactorResult, signal) -> str:
    label = _SIGNAL_LABELS.get(signal.name, signal.name)
    month = calendar.month_name[signal.reading_period.month] if signal.reading_period else None
    reason = signal.missing_reason
    if reason == "baseline_samples_below_minimum":
        return (
            f"{_label(factor)}: {label} could not be ranked — {signal.samples} year(s) of {month or 'same-month'} "
            f"imagery in the baseline, {MIN_BASELINE_SAMPLES} needed."
        )
    if reason == "no_current_reading":
        return f"{_label(factor)}: no usable {label} reading in the assessment window."
    if reason == "degenerate_baseline_range":
        return f"{_label(factor)}: {label} is undefined — the baseline shows no variation for {month or 'that month'}."
    if reason == "no_rainfall_in_recent_months":
        return f"{_label(factor)}: {label} is unavailable — no rainfall for the last three months of the window."
    if reason == "no_rainfall_normals_for_recent_months":
        return f"{_label(factor)}: {label} is unavailable — no rainfall climatology for those months."
    return f"{_label(factor)}: {label} could not be computed ({reason})."


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def _check_tier(
    tier: StakesTier, requirement: TierRequirement, result: RiskResult, facts: EvidenceFacts
) -> TierVerdict:
    gaps: list[Inadequacy] = []
    mc = result.model_confidence
    computed = [f for f in result.factors if f.computed]

    if requirement.require_overall_estimate and result.overall_score is None:
        gaps.append(Inadequacy("no_overall_estimate", "No overall risk score could be estimated. " + mc.statement))

    if len(computed) < requirement.min_factors_computed:
        missing = [f for f in result.factors if not f.computed]
        gaps.append(
            Inadequacy(
                "too_few_factors",
                f"{len(computed)} of {len(result.factors)} risk factors computed; {requirement.min_factors_computed} needed.",
            )
        )
        for factor in missing:
            for signal in factor.sub_signals:
                gaps.append(Inadequacy("factor_not_computed", _signal_statement(factor, signal), factor.factor.value))

    if requirement.require_all_sub_signals:
        for factor in computed:
            for signal in factor.sub_signals:
                if signal.risk is None:
                    gaps.append(Inadequacy("sub_signal_missing", _signal_statement(factor, signal), factor.factor.value))

    if result.confidence < requirement.min_data_completeness:
        gaps.append(
            Inadequacy(
                "low_data_completeness",
                f"Only {result.confidence:.0f}% of expected monthly optical observations were usable; "
                f"{requirement.min_data_completeness:.0f}% needed.",
            )
        )

    if facts.error_findings > requirement.max_error_findings:
        gaps.append(
            Inadequacy("validation_errors", f"{facts.error_findings} input validation error(s) — values that are not physically possible.")
        )
    if requirement.max_warning_findings is not None and facts.warning_findings > requirement.max_warning_findings:
        gaps.append(Inadequacy("validation_warnings", f"{facts.warning_findings} input validation warning(s)."))

    if requirement.max_latest_optical_age_months is not None:
        if facts.latest_optical_period is None:
            gaps.append(Inadequacy("no_recent_optical", "No usable optical reading anywhere in the window."))
        else:
            age = _months_between(facts.latest_optical_period, facts.window_last_period)
            if age > requirement.max_latest_optical_age_months:
                latest = f"{calendar.month_name[facts.latest_optical_period.month]} {facts.latest_optical_period.year}"
                gaps.append(
                    Inadequacy(
                        "stale_optical",
                        f"The latest usable optical reading is from {latest}, {age} month(s) before the window ends; "
                        f"at most {requirement.max_latest_optical_age_months} allowed. Later months were lost to cloud.",
                    )
                )

    if mc.overall_interval is None:
        if requirement.require_uncertainty_estimate and result.overall_score is not None:
            gaps.append(Inadequacy("no_uncertainty_estimate", "No uncertainty interval exists for the overall score."))
    elif requirement.max_interval_width is not None:
        low, high = mc.overall_interval
        if high - low > requirement.max_interval_width:
            gaps.append(
                Inadequacy(
                    "interval_too_wide",
                    f"The {mc.confidence_level:.0%} interval on the overall score spans {high - low:.0f} points "
                    f"({low:.0f}-{high:.0f}); at most {requirement.max_interval_width:.0f} allowed — and that interval "
                    "already understates the true uncertainty.",
                )
            )

    if requirement.require_validated_evidence and not any(
        status in (EvidenceValidation.CROSS_CHECKED, EvidenceValidation.FIELD_VALIDATED)
        for status in facts.input_validation_statuses
    ):
        gaps.append(
            Inadequacy(
                "no_validated_evidence",
                "No input has been cross-checked against an independent source or validated in the field, and the "
                "method has not been back-tested against loan outcomes. A field visit is the only way to meet this.",
            )
        )

    return TierVerdict(tier=tier, sufficient=not gaps, description=requirement.description, inadequacies=gaps)


def _caveats(result: RiskResult, facts: EvidenceFacts) -> list[Inadequacy]:
    caveats = [
        Inadequacy(
            "jrc_measures_presence",
            "Flood exposure rests on how often water has been present on this land since 1984, not on how "
            "flood-prone it is; the record ends in 2021.",
            "flood_exposure",
        )
    ]
    if facts.farm_area_ha is not None and facts.farm_area_ha < _CHIRPS_CELL_HA:
        caveats.append(
            Inadequacy(
                "rainfall_regional",
                f"Rainfall is the value of a ~{_CHIRPS_CELL_HA:,.0f} ha CHIRPS cell; this {facts.farm_area_ha:g} ha farm "
                "has no rainfall measurement of its own.",
            )
        )
    if result.model_confidence and result.model_confidence.interval_coverage != "full":
        caveats.append(
            Inadequacy(
                "uncertainty_partial",
                "Uncertainty is quantified only for baseline sampling in the seasonal percentile signals; "
                "measurement error is not included.",
            )
        )
    return caveats


def evaluate_sufficiency(result: RiskResult, facts: EvidenceFacts, policy: SufficiencyPolicy) -> DecisionSufficiency:
    if result.model_confidence is None:
        raise ValueError("sufficiency needs the result's model confidence; the engine did not provide it")

    verdicts = [_check_tier(tier, policy.requirement(tier), result, facts) for tier in StakesTier]
    sufficient = [v.tier.value for v in verdicts if v.sufficient]
    if len(sufficient) == len(verdicts):
        statement = "The evidence meets the stated requirements for low-, medium- and high-stakes decisions."
    elif sufficient:
        statement = (
            f"The evidence is sufficient for {', '.join(sufficient)}-stakes decisions only. "
            f"Not sufficient for {', '.join(v.tier.value for v in verdicts if not v.sufficient)}."
        )
    else:
        statement = "The evidence is not sufficient for a decision at any stakes tier."
    statement += f" Policy {policy.version} is {policy.calibration_status}: set by the platform, not agreed with a bank."

    return DecisionSufficiency(
        policy_version=policy.version,
        calibration_status=policy.calibration_status,
        tiers=verdicts,
        caveats=_caveats(result, facts),
        statement=statement,
    )
