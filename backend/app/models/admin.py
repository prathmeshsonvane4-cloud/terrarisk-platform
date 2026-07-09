import uuid

from geoalchemy2 import Geometry
from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import BoundaryLevel
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class AdminBoundary(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """State -> district -> taluka -> village hierarchy (Blueprint §05).

    Source-agnostic: populated today from the M0 sample fixture, later from
    real Bhuvan/ISRO data via the same loader with no schema change
    (see docs/DECISIONS.md).
    """

    __tablename__ = "admin_boundary"
    __table_args__ = (UniqueConstraint("level", "name", "parent_id", name="uq_admin_boundary_level_name_parent"),)

    level: Mapped[BoundaryLevel] = mapped_column(Enum(BoundaryLevel, name="boundary_level"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("admin_boundary.id"), nullable=True, index=True
    )
    lgd_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Precise geometry drives area/analytical calculations; the simplified
    # copy is what map layers render, so browser performance never depends
    # on shapefile resolution (CTO review finding, carried into the blueprint).
    geometry: Mapped[str] = mapped_column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False)
    geometry_simplified: Mapped[str | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=True
    )


class Branch(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Bank branch registry."""

    __tablename__ = "branch"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    district_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("admin_boundary.id"), nullable=True
    )


class VillageBranchLookup(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Configurable village -> branch mapping (Blueprint §01/§04 decision).

    Keyed on the full (state, district, taluka, village) tuple, never on
    village name alone — duplicate village names across talukas are a real
    problem in Indian administrative data. Replaceable wholesale once DCCB
    provides official branch service-area boundaries.
    """

    __tablename__ = "village_branch_lookup"
    __table_args__ = (
        UniqueConstraint("state", "district", "taluka", "village", name="uq_village_branch_lookup_tuple"),
    )

    state: Mapped[str] = mapped_column(String(255), nullable=False)
    district: Mapped[str] = mapped_column(String(255), nullable=False)
    taluka: Mapped[str] = mapped_column(String(255), nullable=False)
    village: Mapped[str] = mapped_column(String(255), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("branch.id"), nullable=False)
