"""Add the organization table — Water Intelligence multi-tenancy (Blueprint
v2 D8, ticket M0-002).

Schema-ready for multi-tenancy, not yet enforced: no other table gets an
organization_id in this migration (that starts with catchment, M0-003).
This migration only stands up the tenant table itself.

Revision ID: 0005_organization
Revises: 0004_report_evidence_fields
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_organization"
down_revision: str | None = "0004_report_evidence_fields"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    organization_type = postgresql.ENUM(
        "csr", "ngo", "nabard", "government", "international_dev", "other", name="organization_type"
    )

    # organization_type is used on exactly one column, so create_table's
    # default behavior of auto-emitting CREATE TYPE for an inline enum
    # column is sufficient — calling .create() here too would double-emit
    # CREATE TYPE and fail (the same convention 0001_initial_schema
    # established and documented).
    op.create_table(
        "organization",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("org_type", organization_type, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("organization")
    postgresql.ENUM(name="organization_type").drop(op.get_bind(), checkfirst=True)
