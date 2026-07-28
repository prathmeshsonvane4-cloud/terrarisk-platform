"""Add the catchment table — Water Intelligence's catchment-scale polygon
(Blueprint v2 Part 5, ticket M0-003).

MULTIPOLYGON, not POLYGON: a real watershed is not guaranteed to be simply
connected (TDR §4). Area and vertex-count CHECK constraints are part of
this CREATE TABLE, not a follow-up migration — a catchment large or
complex enough to threaten a safe GEE reduceRegion budget must never be
persisted in the first place (Blueprint v2 D9).

Revision ID: 0006_catchment
Revises: 0005_organization
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_catchment"
down_revision: str | None = "0005_organization"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    delineation_method = postgresql.ENUM("manual", "upload", "auto_dem", name="delineation_method")

    # delineation_method is used on exactly one column, so create_table's
    # default behavior of auto-emitting CREATE TYPE for an inline enum
    # column is sufficient — calling .create() here too would double-emit
    # CREATE TYPE and fail (0001_initial_schema's documented convention).
    #
    # No explicit GIST index statements for geometry/pour_point: GeoAlchemy2
    # auto-creates one (named idx_<table>_<column>) for every geometry
    # column the moment op.create_table runs — adding an explicit one here
    # produces a duplicate index, exactly the bug 0001_initial_schema already
    # hit and documented.
    op.create_table(
        "catchment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=True
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("geometry", geoalchemy2.Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False),
        sa.Column("area_ha", sa.Numeric(10, 4), nullable=False),
        sa.Column("delineation_method", delineation_method, nullable=False, server_default="manual"),
        sa.Column("pour_point", geoalchemy2.Geometry(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column(
            "admin_boundary_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("admin_boundary.id"), nullable=True
        ),
        sa.Column("resolution_flags", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id"), nullable=False),
        sa.CheckConstraint("area_ha BETWEEN 0.5 AND 50000", name="chk_catchment_area"),
        sa.CheckConstraint("ST_NPoints(geometry) <= 2000", name="chk_catchment_vertex_count"),
    )
    op.create_index("ix_catchment_organization_id", "catchment", ["organization_id"])
    op.create_index("ix_catchment_admin_boundary_id", "catchment", ["admin_boundary_id"])


def downgrade() -> None:
    op.drop_index("ix_catchment_admin_boundary_id", table_name="catchment")
    op.drop_index("ix_catchment_organization_id", table_name="catchment")
    op.drop_table("catchment")
    postgresql.ENUM(name="delineation_method").drop(op.get_bind(), checkfirst=True)
