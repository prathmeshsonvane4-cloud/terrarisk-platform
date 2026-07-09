import uuid

from geoalchemy2 import Geometry
from sqlalchemy import ForeignKey, Numeric, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class FarmPolygon(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Officer-drawn farm boundary (Blueprint §01 Service 1 — manual polygon
    is the deliberate MVP approach; no cadastral data yet)."""

    __tablename__ = "farm_polygon"

    village_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("admin_boundary.id"), nullable=False)
    geometry: Mapped[str] = mapped_column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)

    # Authoritative area, always recomputed server-side via ST_Area on
    # submit — the officer's on-screen preview is never trusted as the
    # record of truth (Blueprint §05).
    area_ha: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)

    drawn_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
