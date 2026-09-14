"""Decision sufficiency (evidence-aware roadmap, Phase C — item 3).

Whether the evidence behind an assessment is adequate for a decision of a
given stakes tier, with a stated reason for every shortfall. Kept strictly
separate from model confidence, which is a statistical property of the
estimate and is computed by the risk engine.
"""

from app.services.sufficiency.evaluate import (
    DecisionSufficiency,
    EvidenceFacts,
    Inadequacy,
    TierVerdict,
    evaluate_sufficiency,
)
from app.services.sufficiency.policy import DEFAULT_POLICY, StakesTier, SufficiencyPolicy, TierRequirement

__all__ = [
    "DEFAULT_POLICY",
    "DecisionSufficiency",
    "EvidenceFacts",
    "Inadequacy",
    "StakesTier",
    "SufficiencyPolicy",
    "TierRequirement",
    "TierVerdict",
    "evaluate_sufficiency",
]
