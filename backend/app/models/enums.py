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


class RiskEntityType(str, enum.Enum):
    """What a risk_score / risk_factor_score / risk_rollup row is about.

    FARM and ADMIN_BOUNDARY (village/taluka/district) share this type set
    because both are scored by the same engine contract — see Blueprint §07.
    """

    FARM = "farm"
    VILLAGE = "village"
    BRANCH = "branch"
    DISTRICT = "district"


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


class JobType(str, enum.Enum):
    FARM_REPORT = "farm_report"
    PORTFOLIO_AGGREGATION = "portfolio_aggregation"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
