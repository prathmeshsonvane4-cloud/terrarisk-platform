import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import RiskBand, RiskEntityType, RiskFactor
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class ConfigWeight(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Versioned risk-engine configuration (Blueprint §07).

    Never edited in place — calibrating weights or floor thresholds means
    inserting a new row, not a code change or an UPDATE. `risk_score` rows
    reference whichever version was active when they were computed, so a
    rules-vs-future-ML comparison on identical farms is a query, not an
    archaeology project.
    """

    __tablename__ = "config_weight"

    # {"vegetation_stability": 0.25, "water_availability": 0.25, ...}
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {"vegetation_stability": 85, ...} — per-factor score that triggers the
    # overall-score floor rule regardless of the weighted average.
    floor_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)


class RiskScore(Base, UUIDPrimaryKeyMixin):
    """Append-only — never updated in place (Blueprint §04/§07).

    The "current" score for an entity is just its latest row by
    computed_at; history comes for free from the same table. entity_id
    references farm_polygon.id or admin_boundary.id depending on
    entity_type — intentionally polymorphic, see SatelliteObservation.
    """

    __tablename__ = "risk_score"

    entity_type: Mapped[RiskEntityType] = mapped_column(
        Enum(RiskEntityType, name="risk_entity_type"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    overall_band: Mapped[RiskBand] = mapped_column(Enum(RiskBand, name="risk_band"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # Distinguishes rule-engine vs a future ML-sourced score — without this,
    # a historical "High Risk" row is ambiguous about which model produced
    # it (CTO review finding).
    model_version: Mapped[str] = mapped_column(nullable=False, default="rule-engine-v1")
    weights_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("config_weight.id"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RiskFactorScore(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Per-factor breakdown, one row per compute (Blueprint §07).

    raw_inputs retains the actual NDVI/MNDWI/NDMI/rainfall values behind the
    factor score, not just the final 0-100 number — this is what lets the
    data double as future ML training features without touching ingestion.
    """

    __tablename__ = "risk_factor_score"

    risk_score_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("risk_score.id"), nullable=False)
    factor: Mapped[RiskFactor] = mapped_column(Enum(RiskFactor, name="risk_factor"), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[RiskBand] = mapped_column(Enum(RiskBand, name="risk_factor_band"), nullable=False)
    raw_inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class RiskRollup(Base, UUIDPrimaryKeyMixin):
    """Precomputed portfolio aggregate (Blueprint §04/§09).

    One table with an entity_type discriminator rather than three physically
    separate village/branch/district tables — same columns at every level,
    so a single table is simpler to query and maintain without losing any
    of the three rollup levels the blueprint describes (documented as an
    implementation-level simplification in docs/DECISIONS.md, not an
    architecture change). Dashboards read this table — never a live
    per-request aggregation.
    """

    __tablename__ = "risk_rollup"

    entity_type: Mapped[RiskEntityType] = mapped_column(
        Enum(RiskEntityType, name="rollup_entity_type"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    exposure_amount: Mapped[float] = mapped_column(Float, nullable=False)
    risk_band: Mapped[RiskBand] = mapped_column(Enum(RiskBand, name="rollup_risk_band"), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
