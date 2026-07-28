"""Add the water_balance_result table — Water Intelligence's catchment-scale
water balance, sibling to risk_score (Blueprint v2 Part 5, ticket M0-004).

Deliberately has no weights_version_id column (TDR §6): a P-ET-Q=dS mass
balance is an arithmetic sum of physical terms, not a weighted composite
the way risk_score's four-factor score is. v1 of the blueprint copied this
field from risk_score's shape without checking whether it applied here —
it doesn't. Weights genuinely belong only on recharge_stress_score
(M0-005), not here — do not add this column back.

Revision ID: 0007_water_balance_result
Revises: 0006_catchment
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_water_balance_result"
down_revision: str | None = "0006_catchment"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    storage_change_band = postgresql.ENUM(
        "much_below_normal",
        "below_normal",
        "normal",
        "above_normal",
        "much_above_normal",
        name="storage_change_band",
    )
    calibration_status = postgresql.ENUM(
        "uncalibrated", "partially_calibrated", "field_calibrated", name="calibration_status"
    )

    # Both enums are used on exactly one column each, so create_table's
    # default behavior of auto-emitting CREATE TYPE for an inline enum
    # column is sufficient — calling .create() here too would double-emit
    # CREATE TYPE and fail (0001_initial_schema's documented convention).
    op.create_table(
        "water_balance_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("catchment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("catchment.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("rainfall_mm", sa.Numeric(10, 2), nullable=True),
        sa.Column("et_mm", sa.Numeric(10, 2), nullable=True),
        sa.Column("runoff_mm", sa.Numeric(10, 2), nullable=True),
        sa.Column("storage_change_mm", sa.Numeric(10, 2), nullable=True),
        sa.Column("storage_change_band", storage_change_band, nullable=False),
        sa.Column("data_completeness", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "calibration_status", calibration_status, nullable=False, server_default="uncalibrated"
        ),
        sa.Column("closed_catchment_assumed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("resolution_flags", postgresql.JSONB, nullable=False, server_default="[]"),
        # No server_default: unlike risk_score.model_version ("rule-engine-v1"),
        # no WaterBalanceEngine exists yet — see model docstring.
        sa.Column("model_version", sa.String, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_water_balance_result_catchment_id_period_start",
        "water_balance_result",
        ["catchment_id", "period_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_water_balance_result_catchment_id_period_start", table_name="water_balance_result")
    op.drop_table("water_balance_result")

    bind = op.get_bind()
    postgresql.ENUM(name="calibration_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="storage_change_band").drop(bind, checkfirst=True)
