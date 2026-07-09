"""Importing this package registers every model on Base.metadata — required
so Alembic (and the offline DDL-compile tests) see the complete schema.
"""

from app.models.admin import AdminBoundary, Branch, VillageBranchLookup
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.loan import FarmerIdentity, Loan
from app.models.risk import ConfigWeight, RiskFactorScore, RiskRollup, RiskScore
from app.models.satellite import SatelliteObservation
from app.models.user import AppUser

__all__ = [
    "AdminBoundary",
    "Branch",
    "VillageBranchLookup",
    "FarmPolygon",
    "FarmerIdentity",
    "Loan",
    "SatelliteObservation",
    "ConfigWeight",
    "RiskScore",
    "RiskFactorScore",
    "RiskRollup",
    "Job",
    "AppUser",
]
