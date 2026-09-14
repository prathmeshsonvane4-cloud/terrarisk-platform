"""Separate model confidence from decision sufficiency; stop storing invented
scores; record what the cache has actually fetched (evidence-aware roadmap,
Phase C — item 3).

1. observation_fetch — the date ranges actually fetched per farm and index.
   The cache previously treated any stored row inside a requested range as
   a complete hit, which silently truncated every farm's eight-year seasonal
   baseline to its three-year report window.
2. decision_policy — versioned sufficiency requirements per stakes tier,
   seeded with sufficiency-v1 (uncalibrated). Never edited in place.
3. risk_score — overall_score and overall_band become nullable: a composite
   that cannot be estimated is stored as absent, not as an average of
   whatever survived. Adds model_confidence, decision_sufficiency and the
   policy that produced the verdict.
4. risk_factor_score — value and band become nullable: an uncomputed factor
   was previously stored as a neutral 50. Adds computed and the interval.

Existing rows are left as they are. The one production assessment computed
under the old engine keeps its stored values, with model_version
rule-engine-v1 telling it apart; it is recomputed separately, appended, not
rewritten.

The policy seed is written out literally rather than imported from app code,
so this migration stays a fixed record of what was seeded. test_schema_ddl.py
pins it to app.services.sufficiency.DEFAULT_POLICY.

Revision ID: 0013_confidence_and_sufficiency
Revises: 0012_evidence_provenance
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_confidence_and_sufficiency"
down_revision = "0012_evidence_provenance"
branch_labels = None
depends_on = None

SUFFICIENCY_V1 = {
    "version": "sufficiency-v1",
    "calibration_status": "uncalibrated",
    "tiers": {
        "low": {
            "description": (
                "Small, short-tenor exposure that is easy to reverse — for example renewing a seasonal "
                "crop loan for an existing borrower."
            ),
            "min_factors_computed": 2,
            "require_overall_estimate": True,
            "min_data_completeness": 40.0,
            "max_error_findings": 0,
            "max_warning_findings": None,
            "max_latest_optical_age_months": 4,
            "max_interval_width": None,
            "require_uncertainty_estimate": False,
            "require_all_sub_signals": False,
            "require_validated_evidence": False,
        },
        "medium": {
            "description": "A typical new or enhanced crop-loan limit.",
            "min_factors_computed": 4,
            "require_overall_estimate": True,
            "min_data_completeness": 60.0,
            "max_error_findings": 0,
            "max_warning_findings": 0,
            "max_latest_optical_age_months": 3,
            "max_interval_width": 40.0,
            "require_uncertainty_estimate": False,
            "require_all_sub_signals": False,
            "require_validated_evidence": False,
        },
        "high": {
            "description": (
                "Large or long-tenor exposure, or one that is hard to reverse — for example a term loan "
                "secured on the farm's future output."
            ),
            "min_factors_computed": 4,
            "require_overall_estimate": True,
            "min_data_completeness": 75.0,
            "max_error_findings": 0,
            "max_warning_findings": 0,
            "max_latest_optical_age_months": 2,
            "max_interval_width": 25.0,
            "require_uncertainty_estimate": True,
            "require_all_sub_signals": True,
            "require_validated_evidence": True,
        },
    },
}


def upgrade() -> None:
    op.create_table(
        "observation_fetch",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_type",
            postgresql.ENUM(name="observation_entity_type", create_type=False),
            nullable=False,
        ),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "index_type",
            postgresql.ENUM(name="satellite_index_type", create_type=False),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("periods_returned", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("period_start < period_end", name="ck_observation_fetch_range"),
        sa.CheckConstraint("periods_returned >= 0", name="ck_observation_fetch_periods"),
    )
    op.create_index("ix_observation_fetch_lookup", "observation_fetch", ["entity_type", "entity_id", "index_type"])

    op.create_table(
        "decision_policy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False, unique=True),
        sa.Column("sufficiency_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("calibration_status", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO decision_policy (id, version, sufficiency_requirements, calibration_status, notes, effective_from) "
            "VALUES (CAST(:id AS uuid), :version, CAST(:requirements AS jsonb), :calibration, :notes, now())"
        ).bindparams(
            id=str(uuid.UUID("3f1c2b9e-7a44-4d0e-9b61-5c2f0a8d1e01")),
            version=SUFFICIENCY_V1["version"],
            requirements=json.dumps(SUFFICIENCY_V1),
            calibration=SUFFICIENCY_V1["calibration_status"],
            notes=(
                "First statement of sufficiency policy, set by the platform. Not derived from loan outcomes and "
                "not agreed with any bank."
            ),
        )
    )

    op.alter_column("risk_score", "overall_score", existing_type=sa.Float(), nullable=True)
    op.alter_column(
        "risk_score", "overall_band", existing_type=postgresql.ENUM(name="risk_band", create_type=False), nullable=True
    )
    op.add_column("risk_score", sa.Column("model_confidence", postgresql.JSONB(), nullable=True))
    op.add_column("risk_score", sa.Column("decision_sufficiency", postgresql.JSONB(), nullable=True))
    op.add_column(
        "risk_score",
        sa.Column("decision_policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("decision_policy.id"), nullable=True),
    )

    op.alter_column("risk_factor_score", "value", existing_type=sa.Float(), nullable=True)
    op.alter_column(
        "risk_factor_score",
        "band",
        existing_type=postgresql.ENUM(name="risk_factor_band", create_type=False),
        nullable=True,
    )
    op.add_column(
        "risk_factor_score", sa.Column("computed", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("risk_factor_score", sa.Column("interval_low", sa.Float(), nullable=True))
    op.add_column("risk_factor_score", sa.Column("interval_high", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_risk_factor_score_computed_has_value",
        "risk_factor_score",
        "(computed AND value IS NOT NULL AND band IS NOT NULL) OR (NOT computed AND value IS NULL AND band IS NULL)",
    )


def downgrade() -> None:
    # Refuses rather than inventing values: restoring NOT NULL would require
    # writing a score into every row that honestly has none — the neutral
    # stand-in this migration exists to remove.
    bind = op.get_bind()
    uncomputed = bind.execute(sa.text("SELECT count(*) FROM risk_factor_score WHERE value IS NULL")).scalar()
    unestimated = bind.execute(sa.text("SELECT count(*) FROM risk_score WHERE overall_score IS NULL")).scalar()
    if uncomputed or unestimated:
        raise RuntimeError(
            f"Cannot downgrade: {uncomputed} factor score(s) and {unestimated} overall score(s) are honestly absent, "
            "and restoring NOT NULL would require inventing them."
        )

    op.drop_constraint("ck_risk_factor_score_computed_has_value", "risk_factor_score", type_="check")
    op.drop_column("risk_factor_score", "interval_high")
    op.drop_column("risk_factor_score", "interval_low")
    op.drop_column("risk_factor_score", "computed")
    op.alter_column(
        "risk_factor_score",
        "band",
        existing_type=postgresql.ENUM(name="risk_factor_band", create_type=False),
        nullable=False,
    )
    op.alter_column("risk_factor_score", "value", existing_type=sa.Float(), nullable=False)

    op.drop_column("risk_score", "decision_policy_id")
    op.drop_column("risk_score", "decision_sufficiency")
    op.drop_column("risk_score", "model_confidence")
    op.alter_column(
        "risk_score", "overall_band", existing_type=postgresql.ENUM(name="risk_band", create_type=False), nullable=False
    )
    op.alter_column("risk_score", "overall_score", existing_type=sa.Float(), nullable=False)

    op.drop_table("decision_policy")
    op.drop_index("ix_observation_fetch_lookup", table_name="observation_fetch")
    op.drop_table("observation_fetch")
