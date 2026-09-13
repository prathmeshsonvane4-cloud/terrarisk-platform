"""Add evidence provenance and validation tables (evidence-aware roadmap,
Phase B — item 5).

- evidence_record: per-input lineage for every result — source product,
  version, band, units, native vs requested resolution, reducer, temporal
  aggregation, acquisition dates, known limitations, validation status.
- validation_run / validation_finding: the physical validation harness's
  findings, persisted with the result instead of living only in a log.

Vocabulary columns are strings behind CHECK constraints rather than native
Postgres enum types. The evidence vocabulary will grow across the remaining
roadmap phases, and each value added to a native enum needs its own
ALTER TYPE migration that fails silently until first use if forgotten (see
0010_extend_existing_enums). The CHECK expressions are written out
literally here, matching app/models/evidence.py; test_schema_ddl.py asserts
the model-generated constraints admit exactly the Python enum values.

No backfill of evidence_record. Results computed before this migration
depended on parameters that cannot be recovered from stored rows, and any
reconstructed lineage would be invented. Validation findings CAN be derived
honestly from stored values and are backfilled separately by
scripts/backfill_validation.py, marked source='backfill'.

Revision ID: 0012_evidence_provenance
Revises: 0011_water_balance_annual
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_evidence_provenance"
down_revision = "0011_water_balance_annual"
branch_labels = None
depends_on = None

_RESULT_TABLES = "'water_balance_result', 'recharge_stress_score', 'risk_score'"


def upgrade() -> None:
    op.create_table(
        "evidence_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("result_table", sa.String(64), nullable=False),
        sa.Column("result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("quantity", sa.String(64), nullable=False),
        sa.Column("source", sa.String(160), nullable=False),
        sa.Column("product_version", sa.String(64), nullable=True),
        sa.Column("band", sa.String(64), nullable=True),
        sa.Column("units", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.Column("native_resolution_m", sa.Numeric(10, 2), nullable=True),
        sa.Column("requested_scale_m", sa.Numeric(10, 2), nullable=True),
        sa.Column("resampled", sa.Boolean(), nullable=True),
        sa.Column("reducer", sa.String(160), nullable=True),
        sa.Column("temporal_aggregation", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("observations_expected", sa.Integer(), nullable=True),
        sa.Column("observations_used", sa.Integer(), nullable=True),
        sa.Column("acquisition_dates", postgresql.JSONB(), nullable=True),
        sa.Column("retrieval", sa.String(16), nullable=True),
        sa.Column("known_limitations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("validation_status", sa.String(32), nullable=False, server_default="unvalidated"),
        sa.Column("spec_verified_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"result_table IN ({_RESULT_TABLES})", name="ck_evidence_record_result_table"),
        sa.CheckConstraint("kind IN ('observation', 'parameter')", name="ck_evidence_record_kind"),
        sa.CheckConstraint(
            "validation_status IN ('unvalidated', 'cross_checked', 'field_validated')",
            name="ck_evidence_record_validation",
        ),
        sa.CheckConstraint(
            "observations_used IS NULL OR observations_expected IS NULL OR observations_used <= observations_expected",
            name="ck_evidence_record_observation_counts",
        ),
    )
    op.create_index("ix_evidence_record_result", "evidence_record", ["result_table", "result_id"])

    op.create_table(
        "validation_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("result_table", sa.String(64), nullable=False),
        sa.Column("result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("harness_version", sa.String(32), nullable=False),
        sa.Column("agro_climatic_zone", sa.String(32), nullable=False),
        sa.Column("checks_run", sa.Integer(), nullable=False),
        sa.Column("checks_skipped", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"result_table IN ({_RESULT_TABLES})", name="ck_validation_run_result_table"),
        sa.CheckConstraint("source IN ('pipeline', 'backfill')", name="ck_validation_run_source"),
        sa.CheckConstraint(
            "checks_run >= 0 AND checks_skipped >= 0 AND error_count >= 0 AND warning_count >= 0",
            name="ck_validation_run_counts",
        ),
    )
    op.create_index("ix_validation_run_result", "validation_run", ["result_table", "result_id"])

    op.create_table(
        "validation_finding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "validation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("validation_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_name", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(160), nullable=False),
        sa.Column("observed", sa.Numeric(18, 6), nullable=True),
        sa.Column("expected", sa.Text(), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
        sa.CheckConstraint("severity IN ('error', 'warning', 'info')", name="ck_validation_finding_severity"),
    )
    op.create_index("ix_validation_finding_run", "validation_finding", ["validation_run_id"])


def downgrade() -> None:
    op.drop_index("ix_validation_finding_run", table_name="validation_finding")
    op.drop_table("validation_finding")
    op.drop_index("ix_validation_run_result", table_name="validation_run")
    op.drop_table("validation_run")
    op.drop_index("ix_evidence_record_result", table_name="evidence_record")
    op.drop_table("evidence_record")
