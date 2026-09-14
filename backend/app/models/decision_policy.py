"""Versioned decision policy (evidence-aware roadmap, Phase C).

The requirements an assessment's evidence must meet for each stakes tier
(`app/services/sufficiency/policy.py` describes and validates the payload).

Like `config_weight`: never edited in place. Changing a requirement means
inserting a new row with a later `effective_from`, so every stored verdict
can be read against the exact policy that produced it via
`risk_score.decision_policy_id`. The action thresholds of the decision-output
work will be added to this same table rather than a parallel one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class DecisionPolicy(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "decision_policy"

    version: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Validated against SufficiencyPolicy at load time; an unknown key fails.
    sufficiency_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # "uncalibrated" until a bank has agreed the requirements; stored rather
    # than implied so no verdict can look more authoritative than its policy.
    calibration_status: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True
    )
