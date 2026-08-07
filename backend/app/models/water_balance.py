import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import BaselineWindow, CalibrationStatus, StorageChangeBand, StressBand
from app.models.mixins import UUIDPrimaryKeyMixin, pg_enum


class WaterBalanceResult(Base, UUIDPrimaryKeyMixin):
    """Catchment-scale water balance (P - ET - Q = dS), sibling to RiskScore
    (Water Intelligence, Blueprint v2 Part 5) — append-only, never updated
    in place, same pattern as RiskScore. UUIDPrimaryKeyMixin only, not
    CreatedAtMixin: computed_at (explicitly set by the caller, mirroring
    RiskScore.computed_at) already carries "when was this computed," so a
    separate generic created_at would be redundant on an append-only,
    always-computed row.

    No weights_version_id (TDR §6; Blueprint v2 schema fix): a P-ET-Q=dS
    mass balance is an arithmetic sum of physical terms, not a weighted
    composite the way RiskEngine's four-factor score is. v1 copied this
    field from RiskScore's shape without checking whether it applied
    here — it doesn't. Do not reintroduce it: weights genuinely belong only
    on RechargeStressScore (M0-005), which is a real weighted composite.
    """

    __tablename__ = "water_balance_result"
    __table_args__ = (
        Index("ix_water_balance_result_catchment_id_period_start", "catchment_id", "period_start"),
    )

    catchment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("catchment.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # Individual water-balance terms — nullable, since a partial fetch
    # failure (e.g. rainfall succeeded, ET failed) should still let what's
    # known persist rather than block on every term being present
    # (incremental-persistence requirement, Blueprint v2 Part 3 M5 — the
    # generator itself is a later ticket, but the schema must allow it now).
    rainfall_mm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    et_mm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    runoff_mm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    # The residual. Technical-view only, never the report headline — see
    # storage_change_band below (Blueprint v2 D5's v2 fix).
    storage_change_mm: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Per-water-year P/ET/Q/dS for the year-wise view (migration 0011).
    # JSONB rather than a child table: a short, fixed-shape list always
    # read whole with its parent report and never queried on its own.
    #
    # Nullable because reports written before 0011 genuinely do not have
    # it — the monthly series they were derived from was not persisted,
    # so there is nothing to backfill from and any value would be
    # invented. Null means "not computed", never "no change".
    annual: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # The actual MVP headline figure — a qualitative, climatology-relative
    # descriptor, not the mm residual above: an unvalidated residual should
    # not be a report's headline number (Blueprint v2 D5).
    storage_change_band: Mapped[StorageChangeBand] = mapped_column(
        pg_enum(StorageChangeBand, "storage_change_band"), nullable=False
    )
    # 0-100, the existing Service 1 confidence concept (fraction of usable
    # cloud-free composites) — a different axis from calibration_status
    # below, deliberately never blended into one number (Blueprint v2 D5).
    data_completeness: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    # Deliberately separate from data_completeness. Defaults to
    # UNCALIBRATED, and per Blueprint v2 Risk Register #7 has no path to
    # leave that state for a generic MVP customer — stated here, not hidden.
    calibration_status: Mapped[CalibrationStatus] = mapped_column(
        pg_enum(CalibrationStatus, "calibration_status"), nullable=False, default=CalibrationStatus.UNCALIBRATED
    )
    # Always true in MVP — the water balance equation has no lateral
    # groundwater flow term. The column exists so a future model that adds
    # one can be told apart from this one in the same table (Blueprint v2
    # Part 4/Part 10; TDR §2's closed-catchment finding).
    closed_catchment_assumed: Mapped[bool] = mapped_column(nullable=False, default=True)
    # Copied from catchment.resolution_flags at compute time — immutable
    # per result, so a later change to the catchment's own flags doesn't
    # silently rewrite the caveats an already-issued report relied on.
    resolution_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # No default, deliberately: unlike RiskScore.model_version
    # ("rule-engine-v1"), no WaterBalanceEngine exists yet (that's M2) —
    # inventing a default version string for an engine that doesn't exist
    # would be a fabricated value, not a real one.
    model_version: Mapped[str] = mapped_column(nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RechargeStressScore(Base, UUIDPrimaryKeyMixin):
    """Catchment-scale recharge-stress classification, sibling to
    RiskFactorScore (Water Intelligence, Blueprint v2 Part 5) —
    percentile-ranked composite of rainfall anomaly, VCI, and surface-water
    trend (Blueprint v2 D6), benchmarked against the 30-year CHIRPS
    climatology by default, not a short trailing window (D6's v2 baseline
    fix — see baseline_window below). UUIDPrimaryKeyMixin only, not
    CreatedAtMixin: like WaterBalanceResult in this same file, computed_at
    is an explicit, caller-set field carrying "when was this computed,"
    making a separate generic created_at redundant.

    weights_version_id belongs here, unlike on WaterBalanceResult above
    (TDR §6; Blueprint v2 schema fix): this genuinely IS a weighted
    composite — rainfall anomaly, VCI, and surface-water trend are combined
    under a configurable weighting, the same shape as RiskEngine's
    four-factor score, which is exactly why RiskScore has this FK too.
    WaterBalanceResult's P-ET-Q=dS mass balance has no such weighting to
    version, which is why v1's copy of this field onto that table was a
    modeling error and was removed there (see WaterBalanceResult's
    docstring, M0-004). Nullable here, not NOT NULL like RiskScore's: this
    ticket only creates the schema — no engine populates this table yet
    (recharge-stress scoring is a later ticket) — and it stays nullable
    even after that, alongside every other supporting/evidence field below
    (rainfall_anomaly_ratio, vci, surface_water_trend, cgwb_category),
    consistent with only the core outcome fields (stress_score, stress_band,
    baseline_window, catchment_id, computed_at) being required.
    """

    __tablename__ = "recharge_stress_score"
    __table_args__ = (
        Index("ix_recharge_stress_score_catchment_id_computed_at", "catchment_id", "computed_at"),
    )

    catchment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("catchment.id"), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 0-100, higher = more stressed — same scale convention as RiskScore/
    # RiskFactorScore, deliberately not inverted just because this is a
    # different domain.
    stress_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    stress_band: Mapped[StressBand] = mapped_column(pg_enum(StressBand, "stress_band"), nullable=False)
    # Which historical window this score was benchmarked against.
    # CLIMATOLOGY_30YR by default (Blueprint v2 D6's v2 fix) — a short
    # trailing window can silently redefine "normal" as "already stressed"
    # if the recent years happen to be a drought sequence.
    baseline_window: Mapped[BaselineWindow] = mapped_column(
        pg_enum(BaselineWindow, "baseline_window"), nullable=False, default=BaselineWindow.CLIMATOLOGY_30YR
    )
    # Sub-signal detail behind the composite score — nullable individually,
    # same "persist what's known" reasoning as WaterBalanceResult's
    # individual mm terms.
    rainfall_anomaly_ratio: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    vci: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    surface_water_trend: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    # Context only, sourced + dated, never blended numerically into
    # stress_score — block-scale CGWB category is far coarser than a
    # catchment (Blueprint v2 Part 4). Plain string, not our own enum: this
    # is external government vocabulary, not a value this schema defines.
    cgwb_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cgwb_category_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    weights_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("config_weight.id"), nullable=True
    )
    # Mirrors RiskFactorScore.raw_inputs exactly — retains the actual
    # sub-computation detail (e.g. any percentile-rank intermediate values
    # from the D6 scoring method) behind the final score, not just the
    # final number.
    raw_inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
