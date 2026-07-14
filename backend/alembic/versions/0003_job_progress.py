"""Add job.progress (JSONB, nullable) — structured per-stage execution
timeline for report generation (M2B P8, Product Design v2 B2).

Purely additive: nullable column, no backfill. Existing rows (and every
non-report job type) simply have progress = NULL; the API and frontend
both already treat a missing timeline as "nothing to show" rather than an
error.

Revision ID: 0003_job_progress
Revises: 0002_drop_dup_email_idx
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_job_progress"
down_revision: str | None = "0002_drop_dup_email_idx"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job", sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("job", "progress")
