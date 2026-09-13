"""Importing this package registers every model on Base.metadata — required
so Alembic (and the offline DDL-compile tests) see the complete schema.
"""

from app.models.admin import AdminBoundary, Branch, VillageBranchLookup
from app.models.catchment import Catchment
from app.models.cgwb import CgwbGroundwaterObservation
from app.models.evidence import EvidenceRecord, ValidationFinding, ValidationRun
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.loan import FarmerIdentity, Loan
from app.models.organization import Organization
from app.models.risk import ConfigWeight, RiskFactorScore, RiskRollup, RiskScore
from app.models.satellite import SatelliteObservation
from app.models.user import AppUser
from app.models.water_balance import RechargeStressScore, WaterBalanceResult

__all__ = [
    "AdminBoundary",
    "Branch",
    "VillageBranchLookup",
    "Catchment",
    "CgwbGroundwaterObservation",
    "EvidenceRecord",
    "ValidationRun",
    "ValidationFinding",
    "FarmPolygon",
    "FarmerIdentity",
    "Loan",
    "Organization",
    "SatelliteObservation",
    "ConfigWeight",
    "RiskScore",
    "RiskFactorScore",
    "RiskRollup",
    "Job",
    "AppUser",
    "WaterBalanceResult",
    "RechargeStressScore",
]
