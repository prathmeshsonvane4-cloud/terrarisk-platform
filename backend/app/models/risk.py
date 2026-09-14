import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import RiskBand, RiskEntityType, RiskFactor
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


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
        pg_enum(RiskEntityType, "risk_entity_type"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    # Nullable since migration 0013: a composite that cannot be estimated is
    # stored as absent, never as an average of whatever happened to survive.
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_band: Mapped[RiskBand | None] = mapped_column(pg_enum(RiskBand, "risk_band"), nullable=True)
    # LEGACY NAME: optical data completeness, not model confidence and not
    # decision sufficiency — see model_confidence and decision_sufficiency.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # A statistical property of the estimate (RiskResult.model_confidence).
    model_confidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Whether the evidence suffices per stakes tier, with reasons, under the
    # policy recorded in decision_policy_id.
    decision_sufficiency: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    decision_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("decision_policy.id"), nullable=True
    )

    # Distinguishes rule-engine vs a future ML-sourced score — without this,
    # a historical "High Risk" row is ambiguous about which model produced
    # it (CTO review finding).
    model_version: Mapped[str] = mapped_column(nullable=False, default="rule-engine-v1")
    weights_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("config_weight.id"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # M2B P9 — Evidence tab provenance. Nullable: rows computed before this
    # column existed simply have no window/anatomy detail to show, handled
    # gracefully by both the API and the frontend, exactly like job.progress
    # (M2B P8). The window is the exact (start, end) _run_pipeline actually
    # queried Earth Engine with — persisted once at compute time, never
    # re-derived, so "expected months" can never drift from what really
    # happened even if the pipeline's window arithmetic changes later.
    observation_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    observation_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The plain weighted average BEFORE the floor rule — see RiskResult's
    # docstring. Null only for legacy rows.
    weighted_average_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class RiskFactorScore(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Per-factor breakdown, one row per compute (Blueprint §07).

    raw_inputs retains the actual NDVI/MNDWI/NDMI/rainfall values behind the
    factor score, not just the final 0-100 number — this is what lets the
    data double as future ML training features without touching ingestion.
    """

    __tablename__ = "risk_factor_score"
    __table_args__ = (
        CheckConstraint(
            "(computed AND value IS NOT NULL AND band IS NOT NULL) OR (NOT computed AND value IS NULL AND band IS NULL)",
            name="ck_risk_factor_score_computed_has_value",
        ),
    )

    risk_score_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("risk_score.id"), nullable=False)
    factor: Mapped[RiskFactor] = mapped_column(pg_enum(RiskFactor, "risk_factor"), nullable=False)
    # Null when the factor could not be computed. Before migration 0013 this
    # was a neutral 50 presented as a measurement.
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    band: Mapped[RiskBand | None] = mapped_column(pg_enum(RiskBand, "risk_factor_band"), nullable=True)
    computed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Statistical interval on `value` where the method supports one.
    interval_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    interval_high: Mapped[float | None] = mapped_column(Float, nullable=True)
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
        pg_enum(RiskEntityType, "rollup_entity_type"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    exposure_amount: Mapped[float] = mapped_column(Float, nullable=False)
    risk_band: Mapped[RiskBand] = mapped_column(pg_enum(RiskBand, "rollup_risk_band"), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
