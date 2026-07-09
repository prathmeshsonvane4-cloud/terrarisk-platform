"""Validates every model compiles to correct PostgreSQL DDL without needing
a live database connection — the closest thing to a migration smoke test
available in an environment with no reachable Postgres/PostGIS instance
(see the M0 milestone summary). Running `alembic upgrade head` against a
real PostGIS database is still the authoritative check and should be done
wherever this suite runs with Docker available.
"""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.database.base import Base
from app.models import (  # noqa: F401 — import registers every table on Base.metadata
    AdminBoundary,
    AppUser,
    Branch,
    ConfigWeight,
    FarmerIdentity,
    FarmPolygon,
    Job,
    Loan,
    RiskFactorScore,
    RiskRollup,
    RiskScore,
    SatelliteObservation,
    VillageBranchLookup,
)

EXPECTED_TABLES = {
    "admin_boundary",
    "branch",
    "village_branch_lookup",
    "app_user",
    "farm_polygon",
    "farmer_identity",
    "loan",
    "satellite_observation",
    "config_weight",
    "risk_score",
    "risk_factor_score",
    "risk_rollup",
    "job",
}


def test_all_blueprint_tables_are_registered():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_every_table_compiles_to_valid_postgres_ddl():
    dialect = postgresql.dialect()
    for name, table in Base.metadata.tables.items():
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "CREATE TABLE" in ddl, f"{name} did not compile to a CREATE TABLE statement"


def test_geometry_columns_use_srid_4326():
    admin_boundary = Base.metadata.tables["admin_boundary"]
    farm_polygon = Base.metadata.tables["farm_polygon"]

    assert admin_boundary.c.geometry.type.srid == 4326
    assert admin_boundary.c.geometry_simplified.type.srid == 4326
    assert farm_polygon.c.geometry.type.srid == 4326


def test_farmer_identity_is_the_only_table_with_pii_columns():
    """Guards the PII-separation design commitment from Blueprint §04 — no
    other table should grow a contact/KCC-ID-shaped column over time
    without a deliberate decision. `name` alone is excluded: branch and
    admin_boundary legitimately have non-PII `name` columns."""
    pii_like_columns = {"contact", "kcc_id"}
    for table_name, table in Base.metadata.tables.items():
        if table_name == "farmer_identity":
            continue
        columns = {c.name for c in table.columns}
        assert not (columns & pii_like_columns), f"{table_name} has unexpected PII-shaped column(s)"
