"""Decision sufficiency policy — what evidence each class of decision needs.

Pure data and validation, zero I/O. The active policy is a versioned row in
`decision_policy` (never edited in place, like `config_weight`); this module
parses it and holds the version-1 defaults the migration seeds.

WHY TIERS AND NOT A LOAN AMOUNT
-------------------------------
Sufficiency is relative to a decision: the same evidence can be adequate for
a small, reversible seasonal crop loan and inadequate for a large term loan.
Loan amount and reversibility become explicit inputs in the decision-output
work that follows. Until they do, every assessment is evaluated against all
three tiers, so the report can already say "sufficient for low-stakes
decisions; not for medium or high, because ...". The mapping from amount and
reversibility to a tier is deliberately NOT defined here — inventing rupee
thresholds before that work would be a policy decision taken by default.

EVERY NUMBER HERE IS UNCALIBRATED
---------------------------------
These requirements are a founder's first statement of policy, written down so
they can be argued with — not values derived from loan outcomes, and not
agreed with any bank. They carry `calibration_status="uncalibrated"`, and so
does every verdict they produce. Changing them means inserting a new policy
version, never editing this file's defaults to make an assessment pass.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DEFAULT_POLICY",
    "StakesTier",
    "SufficiencyPolicy",
    "TierRequirement",
]


class StakesTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TierRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    # How many of the four factors must actually be computed.
    min_factors_computed: int = Field(ge=0, le=4)
    # Whether a composite score must exist at all.
    require_overall_estimate: bool
    # Optical data completeness, percent.
    min_data_completeness: float = Field(ge=0, le=100)
    max_error_findings: int = Field(ge=0)
    # None: warnings do not block this tier.
    max_warning_findings: int | None = Field(default=None, ge=0)
    # Months between the latest usable optical reading and the end of the
    # window. None: staleness does not block this tier.
    max_latest_optical_age_months: int | None = Field(default=None, ge=0)
    # Width of the overall interval, score points, when one exists.
    max_interval_width: float | None = Field(default=None, ge=0)
    # Whether an uncertainty interval must exist at all.
    require_uncertainty_estimate: bool = False
    # Whether every designed sub-signal of every factor must be computed.
    require_all_sub_signals: bool = False
    # Whether at least one input must be cross-checked or field-validated.
    require_validated_evidence: bool = False


class SufficiencyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    calibration_status: str
    tiers: dict[StakesTier, TierRequirement]

    def requirement(self, tier: StakesTier) -> TierRequirement:
        return self.tiers[tier]


DEFAULT_POLICY = SufficiencyPolicy(
    version="sufficiency-v1",
    calibration_status="uncalibrated",
    tiers={
        StakesTier.LOW: TierRequirement(
            description=(
                "Small, short-tenor exposure that is easy to reverse — for example renewing a seasonal crop "
                "loan for an existing borrower."
            ),
            min_factors_computed=2,
            require_overall_estimate=True,
            min_data_completeness=40.0,
            max_error_findings=0,
            max_latest_optical_age_months=4,
        ),
        StakesTier.MEDIUM: TierRequirement(
            description="A typical new or enhanced crop-loan limit.",
            min_factors_computed=4,
            require_overall_estimate=True,
            min_data_completeness=60.0,
            max_error_findings=0,
            max_warning_findings=0,
            max_latest_optical_age_months=3,
            max_interval_width=40.0,
        ),
        StakesTier.HIGH: TierRequirement(
            description=(
                "Large or long-tenor exposure, or one that is hard to reverse — for example a term loan "
                "secured on the farm's future output."
            ),
            min_factors_computed=4,
            require_overall_estimate=True,
            min_data_completeness=75.0,
            max_error_findings=0,
            max_warning_findings=0,
            max_latest_optical_age_months=2,
            max_interval_width=25.0,
            require_uncertainty_estimate=True,
            require_all_sub_signals=True,
            # No input on this platform is validated today, so no high-stakes
            # assessment can be sufficient on satellite evidence alone. That is
            # the intended outcome, not a side effect: nothing here has been
            # back-tested against loan outcomes (Product Design v2 §11 item 3).
            require_validated_evidence=True,
        ),
    },
)
