import uuid

from sqlalchemy import ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class FarmerIdentity(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """PII lives here and only here (Blueprint §04 / CTO review finding).

    Deliberately isolated from `loan` and every analytical table so a future
    compliance requirement (data residency, RBI data-handling expectations)
    never forces a rewrite of the risk/dashboard tables that depend on loan.
    Access to this table should carry a stricter permission than general
    loan/risk queries once role-based access is implemented (M2+).
    """

    __tablename__ = "farmer_identity"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kcc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Loan(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Portfolio record (Service 2). No PII fields live directly on this
    table — only a reference to farmer_identity."""

    __tablename__ = "loan"

    farmer_identity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farmer_identity.id"), nullable=False
    )
    farm_polygon_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farm_polygon.id"), nullable=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("branch.id"), nullable=False)

    # Raw village name as it appeared in the uploaded CSV, kept alongside the
    # resolved branch_id so a bad village_branch_lookup match is traceable
    # back to the source row during validation review (Blueprint §02/§03).
    village_name: Mapped[str] = mapped_column(String(255), nullable=False)
    crop: Mapped[str] = mapped_column(String(128), nullable=False)
    outstanding_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
