"""Add the cgwb_groundwater_observation table — Water Intelligence's CGWB
raw ingestion staging table (Blueprint v2 Part 5, ticket M0-006).

Storage layer only: this migration creates the table and nothing else. No
importer, no CGWB/WRIS download logic, no scheduler, no API — those belong
to M3, and per the Implementation Plan's M3-002 research spike, cannot be
built until the real CGWB/WRIS access mechanism is confirmed.

No new Postgres enum type: category is a plain VARCHAR, not our own enum —
CGWB's vocabulary is external government data this schema doesn't own.

Revision ID: 0009_cgwb_observation
Revises: 0008_recharge_stress_score
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_cgwb_observation"
down_revision: str | None = "0008_recharge_stress_score"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # No explicit GIST index statement for block_geometry: GeoAlchemy2
    # auto-creates one (named idx_<table>_<column>) for every geometry
    # column the moment op.create_table runs — adding an explicit one here
    # produces a duplicate index, exactly the bug 0001_initial_schema
    # already hit and documented. The UNIQUE constraint below likewise
    # auto-creates its own backing index; no separate op.create_index call
    # is needed for (block_code, assessment_period) lookups.
    op.create_table(
        "cgwb_groundwater_observation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("block_code", sa.String(64), nullable=False),
        sa.Column("block_geometry", geoalchemy2.Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=True),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("assessment_period", sa.String(32), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.UniqueConstraint("block_code", "assessment_period", name="uq_cgwb_block_period"),
    )


def downgrade() -> None:
    op.drop_table("cgwb_groundwater_observation")
