"""Add risk_score.observation_window_start/end and weighted_average_score
(all nullable) — Evidence & Method tab provenance (M2B P9, Product Design
v2 §7.5).

Purely additive: nullable columns, no backfill. Pre-existing risk_score
rows simply have no window/anatomy detail; the API and frontend both
treat that as "not available for this older report," never an error —
the same pattern established for job.progress in M2B P8.

Revision ID: 0004_report_evidence_fields
Revises: 0003_job_progress
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_report_evidence_fields"
down_revision: str | None = "0003_job_progress"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("risk_score", sa.Column("observation_window_start", sa.Date(), nullable=True))
    op.add_column("risk_score", sa.Column("observation_window_end", sa.Date(), nullable=True))
    op.add_column("risk_score", sa.Column("weighted_average_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("risk_score", "weighted_average_score")
    op.drop_column("risk_score", "observation_window_end")
    op.drop_column("risk_score", "observation_window_start")
