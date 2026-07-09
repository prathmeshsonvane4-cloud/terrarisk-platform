import uuid
from datetime import date

from sqlalchemy import Date, Enum, Float, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import RiskEntityType, SatelliteIndexType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class SatelliteObservation(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Cached Earth Engine output (Blueprint §06).

    Keyed on (entity_type, entity_id, index_type, period) so a repeat report
    request for the same farm/period never recomputes against GEE — this
    matters for cost the moment commercial GEE billing applies, and for
    latency always. entity_id references farm_polygon.id or
    admin_boundary.id depending on entity_type; not a hard FK because it is
    intentionally polymorphic across those two tables (mirrors risk_score).
    """

    __tablename__ = "satellite_observation"

    entity_type: Mapped[RiskEntityType] = mapped_column(
        Enum(RiskEntityType, name="observation_entity_type"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    index_type: Mapped[SatelliteIndexType] = mapped_column(
        Enum(SatelliteIndexType, name="satellite_index_type"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    # Which actual satellite passes fed this value — the data-lineage
    # requirement from Blueprint §08 starts at the point of computation, not
    # as an afterthought in the report renderer.
    source_dates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
