"""Evidence provenance and validation records (evidence-aware roadmap,
Phase B — item 5).

Three tables:

- `evidence_record`: one row per input a result depended on — each
  remote-sensing series and each assumed method parameter — with enough
  lineage to trace the number back to its source without reading code.
- `validation_run`: one row per validation pass over a result.
- `validation_finding`: the individual findings from that pass.

POLYMORPHIC, LIKE risk_score
----------------------------
Rows reference their result by `(result_table, result_id)`, not a foreign
key, exactly as `risk_score` references `(entity_type, entity_id)`. One
lineage table serves every result table in both services; per-table
foreign keys would need three nullable FKs and a constraint that exactly
one is set, for no query the product makes.

THE HONESTY RULES THIS SCHEMA ENCODES
-------------------------------------
- `evidence_record.validation_status` has no "plausibility checked" level.
  See `EvidenceValidation`.
- `acquisition_dates` NULL means **not recorded**; an empty list means
  **recorded, and there were none**. The two must never be conflated — a
  provider that does not return scene dates is not a provider that
  observed nothing.
- `spec_verified_on` NULL means the product specification behind this row
  was never checked against its catalog.
- A result computed before this table existed has NO evidence rows, and
  none are backfilled. Its parameters (which Curve Number was in force on
  that day, for instance) cannot be recovered, and a reconstructed lineage
  would be fabricated. Absence of evidence rows reads as "provenance not
  recorded", and the API says so.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import EvidenceKind, EvidenceResultTable, EvidenceValidation, FindingSeverity
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


def _in_values(column: str, enum_cls) -> str:
    """A CHECK expression admitting exactly the enum's values — generated
    from the class so the database and Python vocabularies cannot drift."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"


class EvidenceRecord(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "evidence_record"
    __table_args__ = (
        Index("ix_evidence_record_result", "result_table", "result_id"),
        CheckConstraint(_in_values("result_table", EvidenceResultTable), name="ck_evidence_record_result_table"),
        CheckConstraint(_in_values("kind", EvidenceKind), name="ck_evidence_record_kind"),
        CheckConstraint(_in_values("validation_status", EvidenceValidation), name="ck_evidence_record_validation"),
        CheckConstraint(
            "observations_used IS NULL OR observations_expected IS NULL OR observations_used <= observations_expected",
            name="ck_evidence_record_observation_counts",
        ),
    )

    result_table: Mapped[str] = mapped_column(String(64), nullable=False)
    result_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    # What this input is, in the vocabulary of the method that consumed it:
    # "et_monthly_mm", "curve_number", "sar_vv_water_threshold_db".
    quantity: Mapped[str] = mapped_column(String(64), nullable=False)
    # Earth Engine collection id for an observation; the module that
    # defines the constant for a parameter.
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    product_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    band: Mapped[str | None] = mapped_column(String(64), nullable=True)
    units: Mapped[str] = mapped_column(String(64), nullable=False)
    # Set for a scalar parameter (Curve Number 89). Null for a series —
    # the series itself lives with the result or in satellite_observation.
    value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)

    # Spatial lineage. `resampled` is True when the requested scale differs
    # from the product's native pixel size — the value was not read natively.
    native_resolution_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    requested_scale_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    resampled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # How pixels became one number: "mean over polygon",
    # "unweighted mean after unmask(0)".
    reducer: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # Temporal lineage.
    temporal_aggregation: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    observations_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observations_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NULL = not recorded. [] = recorded, none. See module docstring.
    acquisition_dates: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # "fetched" | "cache" — whether this run retrieved the data or reused a
    # previous retrieval. Cached data can be stale in ways fresh data is not
    # (CHIRPS revises recent months after first publication).
    retrieval: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Known limitations of this input for THIS result: product-level
    # caveats plus any location-specific ones (sub-pixel catchment,
    # outside the product's validated range).
    known_limitations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EvidenceValidation.UNVALIDATED.value
    )
    spec_verified_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class ValidationRun(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "validation_run"
    __table_args__ = (
        Index("ix_validation_run_result", "result_table", "result_id"),
        CheckConstraint(_in_values("result_table", EvidenceResultTable), name="ck_validation_run_result_table"),
        CheckConstraint("source IN ('pipeline', 'backfill')", name="ck_validation_run_source"),
        CheckConstraint(
            "checks_run >= 0 AND checks_skipped >= 0 AND error_count >= 0 AND warning_count >= 0",
            name="ck_validation_run_counts",
        ),
    )

    result_table: Mapped[str] = mapped_column(String(64), nullable=False)
    result_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    # Bumped whenever a check, envelope or tolerance changes, so a finding
    # can always be read against the rules that produced it.
    harness_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # Kept as text: the zone vocabulary belongs to the validation harness,
    # not to the schema.
    agro_climatic_zone: Mapped[str] = mapped_column(String(32), nullable=False)
    checks_run: Mapped[int] = mapped_column(Integer, nullable=False)
    checks_skipped: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # "pipeline" when run as the result was computed; "backfill" when run
    # later against stored values (rounded, and possibly produced by an
    # older engine).
    source: Mapped[str] = mapped_column(String(16), nullable=False)

    # Load-bearing, not a convenience. Without a declared relationship the
    # unit of work has no dependency between the two tables and may insert
    # a finding before its run exists, which Postgres rejects on the foreign
    # key. That happened: the first live-database run of the water report
    # failed exactly this way, and Service 1 only escaped because its test
    # data happened to produce no findings. Findings must be attached
    # through this collection, never added to the session on their own.
    # selectin, not lazy: an implicit lazy load on an async session raises.
    findings: Mapped[list[ValidationFinding]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )


class ValidationFinding(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "validation_finding"
    __table_args__ = (
        Index("ix_validation_finding_run", "validation_run_id"),
        CheckConstraint(_in_values("severity", FindingSeverity), name="ck_validation_finding_severity"),
    )

    validation_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("validation_run.id", ondelete="CASCADE"), nullable=False
    )
    # `check` is a reserved word in SQL.
    check_name: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    observed: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    expected: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")

    run: Mapped[ValidationRun] = relationship(back_populates="findings")
