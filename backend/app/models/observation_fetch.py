"""What has actually been fetched from Earth Engine — the cache's own
coverage record (evidence-aware roadmap, Phase C).

`satellite_observation` stores one row per month that returned a value.
A month with no usable scene has no row, by design. That makes the rows
alone unable to answer "has this range been fetched?": a missing July can
mean "fetched, and July was cloud" or "never asked for".

The Service 1 pipeline used the rows alone, treating ANY cached row inside
a requested range as a complete cache hit. The seasonal baseline window
(eight years before the report window, plus the window) contains the report
window, so on every farm's first assessment the baseline request found the
report-window rows it had just cached, called that a hit, and never fetched
the other eight years. Every calendar month then had at most three baseline
samples, below the five a percentile needs, and three of the four risk
factors fell back to a neutral 50. The only Service 1 assessment in
production was built that way.

This table is the distinction the rows cannot make — the same "not recorded
versus recorded as none" rule `evidence_record.acquisition_dates` follows.
A range is a cache hit only if a fetch covering all of it is recorded here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import RiskEntityType, SatelliteIndexType
from app.models.mixins import UUIDPrimaryKeyMixin, pg_enum


class ObservationFetch(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "observation_fetch"
    __table_args__ = (
        Index("ix_observation_fetch_lookup", "entity_type", "entity_id", "index_type"),
        CheckConstraint("period_start < period_end", name="ck_observation_fetch_range"),
        CheckConstraint("periods_returned >= 0", name="ck_observation_fetch_periods"),
    )

    # Reuses satellite_observation's existing Postgres enum types rather
    # than creating parallel ones: these columns mean exactly the same thing.
    entity_type: Mapped[RiskEntityType] = mapped_column(
        pg_enum(RiskEntityType, "observation_entity_type"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    index_type: Mapped[SatelliteIndexType] = mapped_column(
        pg_enum(SatelliteIndexType, "satellite_index_type"), nullable=False
    )
    # The requested range, [period_start, period_end) — what was asked for,
    # not what came back.
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # How many monthly values the provider returned for that range. Fewer
    # than the months requested is normal: cloud, or an unpublished month.
    periods_returned: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
