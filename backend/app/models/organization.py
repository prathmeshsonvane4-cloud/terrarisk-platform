from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import OrganizationType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class Organization(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Water Intelligence tenant (Blueprint v2 D8).

    Schema-ready for multi-tenancy; MVP does not yet enforce any
    application-layer tenant isolation (no per-request org-scoped query
    filtering, no org-admin surface). Each MVP deployment serves exactly one
    organization, matching how Service 1 already operates — this table
    exists now so a future move to shared multi-tenancy is a column already
    populated, not a backfill-and-migration exercise on live data. See
    docs/Water_Intelligence_Service_Blueprint.md, "Multi-tenancy" (Part 1)
    and D8 for the full rationale, including the explicit trigger condition
    for when application-layer isolation becomes a hard requirement.
    """

    __tablename__ = "organization"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_type: Mapped[OrganizationType] = mapped_column(pg_enum(OrganizationType, "organization_type"), nullable=False)
