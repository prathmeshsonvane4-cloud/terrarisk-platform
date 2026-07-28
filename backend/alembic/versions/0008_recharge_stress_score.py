"""Add the recharge_stress_score table — Water Intelligence's catchment-scale
recharge-stress classification, sibling to risk_factor_score (Blueprint v2
Part 5, ticket M0-005).

Has weights_version_id, unlike water_balance_result (M0-004): this genuinely
is a weighted composite (rainfall anomaly + VCI + surface-water trend),
the same shape as risk_score's four-factor weighting, which is exactly why
this field was moved here in Blueprint v2 rather than staying on
water_balance_result's mass balance, which has nothing to weight (TDR §6).

Revision ID: 0008_recharge_stress_score
Revises: 0007_water_balance_result
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_recharge_stress_score"
down_revision: str | None = "0007_water_balance_result"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    stress_band = postgresql.ENUM("low", "moderate", "high", "very_high", name="stress_band")
    baseline_window = postgresql.ENUM("climatology_30yr", "trailing_3yr", name="baseline_window")

    # Both enums are used on exactly one column each, so create_table's
    # default behavior of auto-emitting CREATE TYPE for an inline enum
    # column is sufficient — calling .create() here too would double-emit
    # CREATE TYPE and fail (0001_initial_schema's documented convention).
    op.create_table(
        "recharge_stress_score",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("catchment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("catchment.id"), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stress_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("stress_band", stress_band, nullable=False),
        sa.Column("baseline_window", baseline_window, nullable=False, server_default="climatology_30yr"),
        sa.Column("rainfall_anomaly_ratio", sa.Numeric(6, 3), nullable=True),
        sa.Column("vci", sa.Numeric(5, 2), nullable=True),
        sa.Column("surface_water_trend", sa.Numeric(6, 3), nullable=True),
        sa.Column("cgwb_category", sa.String(64), nullable=True),
        sa.Column("cgwb_category_as_of", sa.Date(), nullable=True),
        sa.Column(
            "weights_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("config_weight.id"), nullable=True
        ),
        sa.Column("raw_inputs", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_recharge_stress_score_catchment_id_computed_at",
        "recharge_stress_score",
        ["catchment_id", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recharge_stress_score_catchment_id_computed_at", table_name="recharge_stress_score")
    op.drop_table("recharge_stress_score")

    bind = op.get_bind()
    postgresql.ENUM(name="baseline_window").drop(bind, checkfirst=True)
    postgresql.ENUM(name="stress_band").drop(bind, checkfirst=True)
