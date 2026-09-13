"""Evidence provenance and lineage (evidence-aware roadmap, Phase B —
item 5): every number a result depends on, traceable to its source.

`lineage.py` describes inputs (pure); `persistence.py` writes them in the
caller's transaction. See `app/models/evidence.py` for the schema and the
honesty rules it encodes.
"""

from app.services.provenance.lineage import (
    EvidenceItem,
    recharge_stress_evidence,
    risk_score_evidence,
    water_balance_evidence,
)
from app.services.provenance.persistence import HARNESS_VERSION, add_evidence, add_validation_run

__all__ = [
    "HARNESS_VERSION",
    "EvidenceItem",
    "add_evidence",
    "add_validation_run",
    "recharge_stress_evidence",
    "risk_score_evidence",
    "water_balance_evidence",
]
