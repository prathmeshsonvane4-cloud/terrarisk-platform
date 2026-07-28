import uuid

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import DelineationMethod
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class Catchment(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """User-defined watershed/farm-cluster boundary (Water Intelligence,
    Blueprint v2 Part 5) — the catchment-scale sibling of FarmPolygon.

    Geometry is MULTIPOLYGON, not POLYGON: unlike a single farm field, a
    real watershed is not guaranteed to be simply connected (TDR §4 —
    v1 mistakenly typed this POLYGON by copying FarmPolygon's shape without
    re-checking the assumption still held).

    The two CHECK constraints exist specifically so an oversized or overly
    complex catchment can never be persisted in the first place — GEE's
    reduceRegion has no safe way to handle an unbounded polygon, so the
    bound is enforced at the database layer, not discovered mid-computation
    (Blueprint v2 D9). area_ha is always server-recomputed via
    ST_Area(geography cast) at the API layer, exactly like FarmPolygon.area_ha
    — the CHECK constraint is the last line of defense, not the primary
    validation path.
    """

    __tablename__ = "catchment"
    __table_args__ = (
        CheckConstraint("area_ha BETWEEN 0.5 AND 50000", name="chk_catchment_area"),
        CheckConstraint("ST_NPoints(geometry) <= 2000", name="chk_catchment_vertex_count"),
    )

    # Nullable in MVP — schema-ready for multi-tenancy, not yet enforced by
    # any application-layer isolation (Blueprint v2 D8; see Organization).
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geometry: Mapped[str] = mapped_column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False)
    area_ha: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    delineation_method: Mapped[DelineationMethod] = mapped_column(
        pg_enum(DelineationMethod, "delineation_method"), nullable=False, default=DelineationMethod.MANUAL
    )
    # Nullable — populated only when delineation_method is AUTO_DEM (Phase 2,
    # Blueprint v2 D2). The column exists now so Phase 2 doesn't need its own
    # migration to add it.
    pour_point: Mapped[str | None] = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    # Nullable — optional link for village-level aggregation, not required
    # for a catchment to exist on its own.
    admin_boundary_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("admin_boundary.id"), nullable=True, index=True
    )
    # e.g. ["rainfall_sub_pixel", "et_sub_pixel", "high_relief_terrain"] —
    # computed once at creation and reused by every downstream report, so
    # the resolution/terrain caveat is derived once, not recomputed per
    # report (Blueprint v2 Part 4/Part 5, TDR-driven v2 addition).
    resolution_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
