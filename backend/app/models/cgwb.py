from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class CgwbGroundwaterObservation(Base, UUIDPrimaryKeyMixin):
    """CGWB groundwater-category ingestion staging table (Water
    Intelligence, Blueprint v2 Part 5) — storage layer only.

    This ticket (M0-006) creates the table and nothing else: no CSV
    importer, no CGWB/WRIS download logic, no scheduler, no API, no
    processing engine. Those belong to M3 (recharge-stress scoring + CGWB
    ingestion), and per the Implementation Plan's M3-002 research spike,
    ingestion code cannot be written responsibly until the real CGWB/WRIS
    access mechanism (API vs. bulk download, actual response shape) is
    confirmed — writing an importer against an assumed API shape now would
    be exactly the mistake that spike exists to prevent.

    No foreign key to catchment, deliberately: one CGWB block observation
    spans many catchments, and the relationship is spatial (a catchment's
    containing block, found by a spatial join on block_geometry), not a
    stored reference — that lookup happens at score-computation time (M3),
    not here.

    category is a plain string, not a Postgres enum: CGWB's own vocabulary
    (Safe/Semi-Critical/Critical/Over-Exploited) is external government
    data this schema doesn't own or control — the same reasoning already
    applied to RechargeStressScore.cgwb_category (M0-005).
    """

    __tablename__ = "cgwb_groundwater_observation"
    __table_args__ = (UniqueConstraint("block_code", "assessment_period", name="uq_cgwb_block_period"),)

    # CGWB assessment-unit identifier (block/mandal/taluka scale).
    block_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nullable until a boundary source is confirmed at M3 (Blueprint v2
    # Part 5) — the same "schema-ready before the mechanism exists" pattern
    # already used for Catchment.pour_point (M0-003).
    block_geometry: Mapped[str | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    # CGWB's own period label (e.g. "2024"), not a Date — CGWB's published
    # period granularity isn't always a clean calendar year.
    assessment_period: Mapped[str] = mapped_column(String(32), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Traceability back to the published CGWB/WRIS release this row came
    # from — every ingested value must be able to point at where it was
    # sourced, matching this project's provenance-on-every-number principle.
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
