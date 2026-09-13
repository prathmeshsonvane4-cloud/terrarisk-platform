import enum


class BoundaryLevel(str, enum.Enum):
    STATE = "state"
    DISTRICT = "district"
    TALUKA = "taluka"
    VILLAGE = "village"


class UserRole(str, enum.Enum):
    CREDIT_OFFICER = "credit_officer"
    BRANCH_MANAGER = "branch_manager"
    RISK_OFFICER = "risk_officer"
    CEO = "ceo"
    CHAIRMAN = "chairman"
    # Water Intelligence (docs/Water_Intelligence_Service_Blueprint.md, D8) —
    # generic roles for non-bank customers (CSR teams, NABARD consultants,
    # watershed NGOs, government departments), added by extension rather
    # than forcing those users into a bank-shaped role above.
    PROGRAMME_OFFICER = "programme_officer"
    PROGRAMME_ADMIN = "programme_admin"


class RiskEntityType(str, enum.Enum):
    """What a risk_score / risk_factor_score / risk_rollup row is about.

    FARM and ADMIN_BOUNDARY (village/taluka/district) share this type set
    because both are scored by the same engine contract — see Blueprint §07.

    CATCHMENT (Water Intelligence, docs/Water_Intelligence_Service_Blueprint.md
    D3) was added here rather than in a new parallel enum, reusing
    satellite_observation's existing polymorphic (entity_type, entity_id)
    cache keying. Named tech debt, accepted deliberately, not overlooked:
    a catchment isn't "risk" the way a farm loan is, so this enum's name is
    now a slightly awkward fit for what it holds — renaming it would touch
    working Service 1 code for cosmetic benefit only, so the debt is
    recorded here instead (Blueprint v2 D3; Risk Register #4).
    """

    FARM = "farm"
    VILLAGE = "village"
    BRANCH = "branch"
    DISTRICT = "district"
    CATCHMENT = "catchment"


class RiskBand(str, enum.Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class RiskFactor(str, enum.Enum):
    VEGETATION_STABILITY = "vegetation_stability"
    WATER_AVAILABILITY = "water_availability"
    DROUGHT_RISK = "drought_risk"
    FLOOD_EXPOSURE = "flood_exposure"


class SatelliteIndexType(str, enum.Enum):
    NDVI = "ndvi"
    MNDWI = "mndwi"
    NDMI = "ndmi"
    RAINFALL = "rainfall"
    JRC_WATER_OCCURRENCE = "jrc_water_occurrence"
    # Water Intelligence (docs/Water_Intelligence_Service_Blueprint.md, D3) —
    # reuses satellite_observation's existing cache rather than a parallel table.
    ET = "et"
    SURFACE_WATER_SAR = "surface_water_sar"
    SURFACE_WATER_MNDWI = "surface_water_mndwi"


class JobType(str, enum.Enum):
    FARM_REPORT = "farm_report"
    PORTFOLIO_AGGREGATION = "portfolio_aggregation"
    # Water Intelligence (docs/Water_Intelligence_Service_Blueprint.md, Part 5) —
    # reuses the shared Job model and BackgroundTask pattern unchanged (D7).
    CATCHMENT_WATER_REPORT = "catchment_water_report"
    CATCHMENT_BOUNDARY_UPLOAD = "catchment_boundary_upload"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Water Intelligence (docs/Water_Intelligence_Service_Blueprint.md, ticket
# M0-001) — new standalone enums. Not yet attached to any model/column; that
# happens in later M0 tickets (M0-002 through M0-006), which is why none of
# these appear in a pg_enum() call anywhere else in this codebase yet.
# ---------------------------------------------------------------------------


class DelineationMethod(str, enum.Enum):
    """How a catchment's boundary was obtained (Blueprint v2 Part 5).

    AUTO_DEM is Phase 2 (D2) — reserved here now so the column that will use
    it doesn't need a later migration to add a value it was always going to
    need.
    """

    MANUAL = "manual"
    UPLOAD = "upload"
    AUTO_DEM = "auto_dem"


class CalibrationStatus(str, enum.Enum):
    """Whether a water_balance_result has ever been checked against real
    field data (Blueprint v2 D5) — deliberately separate from the
    data_completeness confidence score, which measures satellite data
    quality, not calibration. Defaults to UNCALIBRATED in MVP for every
    generic customer; see Blueprint v2 Risk Register #7.
    """

    UNCALIBRATED = "uncalibrated"
    PARTIALLY_CALIBRATED = "partially_calibrated"
    FIELD_CALIBRATED = "field_calibrated"


class StressBand(str, enum.Enum):
    """Recharge-stress classification (Blueprint v2 Part 4) — mirrors
    RiskBand's exact vocabulary rather than inventing new terminology, since
    recharge-stress scoring reuses RiskEngine's percentile-rank statistical
    shape (Blueprint v2 D6)."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class StorageChangeBand(str, enum.Enum):
    """The MVP headline figure for a water balance result (Blueprint v2 D5).
    The underlying mm value and its confidence interval are computed and
    stored, but shown only in the technical/detailed report view, never
    as the headline, because the mm figure is an unvalidated residual for
    every generic customer at MVP (calibration_status defaults to
    UNCALIBRATED).

    NOT climatology-relative, despite the member names. Blueprint v2 D5
    intended a percentile/z-score against the catchment's own history,
    but no provider fetches that historical distribution, so the bands
    are cut at fixed +/-50 and +/-150 mm thresholds
    (`WaterBalanceEngine._STORAGE_CHANGE_BAND_THRESHOLDS`). The member
    names are kept because they are persisted values and renaming them is
    a migration; the presentation layer deliberately labels them by sign
    and magnitude instead ("Large net gain", not "Much above normal" —
    see the frontend's STORAGE_CHANGE_BANDS), because a fixed-threshold
    result cannot support a claim about what is normal HERE."""

    MUCH_BELOW_NORMAL = "much_below_normal"
    BELOW_NORMAL = "below_normal"
    NORMAL = "normal"
    ABOVE_NORMAL = "above_normal"
    MUCH_ABOVE_NORMAL = "much_above_normal"


class BaselineWindow(str, enum.Enum):
    """Which historical window a recharge-stress or storage-change figure
    was benchmarked against (Blueprint v2 Part 4). Recharge-stress scoring
    uses CLIMATOLOGY_30YR, not TRAILING_3YR — a deliberate v2 fix: a short
    trailing window can silently redefine "normal" as "already stressed" if
    the recent years happen to be a drought sequence."""

    CLIMATOLOGY_30YR = "climatology_30yr"
    TRAILING_3YR = "trailing_3yr"


class OrganizationType(str, enum.Enum):
    """The kind of organisation a Water Intelligence tenant is (Blueprint v2
    D8) — schema-ready for multi-tenancy; not yet enforced by any
    application-layer tenant-isolation logic in MVP."""

    CSR = "csr"
    NGO = "ngo"
    NABARD = "nabard"
    GOVERNMENT = "government"
    INTERNATIONAL_DEV = "international_dev"
    OTHER = "other"


# ---------------------------------------------------------------------
# Evidence provenance and validation (evidence-aware roadmap, Phase B).
#
# These are stored as plain strings behind database CHECK constraints
# generated from these classes — NOT as native Postgres enum types like
# the ones above. The evidence vocabulary is expected to grow through the
# remaining roadmap phases, and every value added to a native enum needs
# its own ALTER TYPE migration that fails silently if forgotten (see
# 0010_extend_existing_enums). A CHECK constraint built from the class
# still rejects unknown values at the database, and extending it is a
# single constraint replacement. See docs/DECISIONS.md, Phase B.
# ---------------------------------------------------------------------


class EvidenceKind(str, enum.Enum):
    # A value read from a remote-sensing product.
    OBSERVATION = "observation"
    # A constant the method assumes: a Curve Number, a threshold, a weight.
    PARAMETER = "parameter"


class EvidenceValidation(str, enum.Enum):
    """How far one input has actually been validated.

    There is deliberately NO level for "passed plausibility checks".
    A value inside a literature envelope has not been validated — it has
    failed to look broken — and a label implying otherwise would breach
    the rule that unvalidated outputs are labelled unvalidated.
    Plausibility results live in validation_run / validation_finding.
    """

    UNVALIDATED = "unvalidated"
    # Agrees with an independent estimate of the same quantity within a
    # stated tolerance. Carries its own caveat about how independent.
    CROSS_CHECKED = "cross_checked"
    # Compared against ground-truth measurement for this location.
    FIELD_VALIDATED = "field_validated"


class EvidenceResultTable(str, enum.Enum):
    """Which result table an evidence or validation row describes.
    Polymorphic by design, mirroring risk_score.entity_type."""

    WATER_BALANCE_RESULT = "water_balance_result"
    RECHARGE_STRESS_SCORE = "recharge_stress_score"
    RISK_SCORE = "risk_score"


class FindingSeverity(str, enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
