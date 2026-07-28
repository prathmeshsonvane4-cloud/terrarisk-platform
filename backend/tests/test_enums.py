"""Water Intelligence ticket M0-001 — enum additions.

These new/extended enums aren't attached to any table column yet (that
starts in M0-002 through M0-006), so test_schema_ddl.py's existing
regression test — which scans Base.metadata.tables for SAEnum columns —
can't see them yet. This file exercises pg_enum() directly against the
enum classes themselves, proving the same "bind by value, not by member
name" contract test_schema_ddl.py already guards for every enum already
wired into a table (see test_every_enum_column_binds_by_value_not_by_member_name
there for the historical bug this pattern exists to prevent).

The tests above check that the SQLAlchemy *model* declares the right
values. They cannot catch the actual defect found during M0 -> M1 live
verification: user_role, observation_entity_type, satellite_index_type,
and job_type are PRE-EXISTING Postgres enum types (created in
0001_initial_schema), and extending the Python enum class does nothing to
an already-created Postgres type — a separate ALTER TYPE ... ADD VALUE
migration is required (0010_extend_existing_enums), and until this
regression test existed, nothing would have failed if that migration had
been forgotten, silently, until the first real insert using a new value.
The live-DB test at the bottom of this file checks the actual Postgres
catalog, not just the Python side.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.database.base import AsyncSessionLocal, engine
from app.models.enums import (
    BaselineWindow,
    CalibrationStatus,
    DelineationMethod,
    JobType,
    OrganizationType,
    RiskEntityType,
    SatelliteIndexType,
    StorageChangeBand,
    StressBand,
    UserRole,
)
from app.models.mixins import pg_enum

NEW_STANDALONE_ENUMS = [
    DelineationMethod,
    CalibrationStatus,
    StressBand,
    StorageChangeBand,
    BaselineWindow,
    OrganizationType,
]

# (enum class, members that must still be present after the M0-001 extension)
EXTENDED_ENUMS_WITH_PRE_EXISTING_MEMBERS = [
    (SatelliteIndexType, {"ndvi", "mndwi", "ndmi", "rainfall", "jrc_water_occurrence"}),
    (RiskEntityType, {"farm", "village", "branch", "district"}),
    (JobType, {"farm_report", "portfolio_aggregation"}),
    (UserRole, {"credit_officer", "branch_manager", "risk_officer", "ceo", "chairman"}),
]

EXTENDED_ENUMS_WITH_NEW_MEMBERS = [
    (SatelliteIndexType, {"et", "surface_water_sar", "surface_water_mndwi"}),
    (RiskEntityType, {"catchment"}),
    (JobType, {"catchment_water_report", "catchment_boundary_upload"}),
    (UserRole, {"programme_officer", "programme_admin"}),
]


def test_new_standalone_enums_bind_by_value_via_pg_enum():
    """Every new Water Intelligence enum, passed through pg_enum(), must
    produce a Postgres enum type whose accepted labels are the lowercase
    string *values*, not the Python member names — exactly the contract
    every existing enum in this codebase already relies on."""
    for enum_cls in NEW_STANDALONE_ENUMS:
        sa_enum = pg_enum(enum_cls, f"{enum_cls.__name__.lower()}_enum")
        expected_labels = {member.value for member in enum_cls}
        actual_labels = set(sa_enum.enums)
        assert actual_labels == expected_labels, (
            f"{enum_cls.__name__} binds enum labels {actual_labels} via pg_enum(), "
            f"expected values {expected_labels} (bug: bound by .name, not .value)"
        )


def test_extended_enums_retain_every_pre_existing_member():
    """M0-001 must only add members to SatelliteIndexType, RiskEntityType,
    JobType, and UserRole — this is the direct proof that none of the four
    extended enums lost or renamed a value Service 1 already depends on."""
    for enum_cls, expected_pre_existing in EXTENDED_ENUMS_WITH_PRE_EXISTING_MEMBERS:
        actual_values = {member.value for member in enum_cls}
        missing = expected_pre_existing - actual_values
        assert not missing, f"{enum_cls.__name__} is missing pre-existing member(s): {missing}"


def test_extended_enums_include_new_water_intelligence_members():
    """The mirror image of the test above — proves the new members this
    ticket is actually responsible for adding are really present."""
    for enum_cls, expected_new in EXTENDED_ENUMS_WITH_NEW_MEMBERS:
        actual_values = {member.value for member in enum_cls}
        missing = expected_new - actual_values
        assert not missing, f"{enum_cls.__name__} is missing new Water Intelligence member(s): {missing}"


def test_extended_enums_bind_by_value_via_pg_enum():
    """Same value-binding contract as the standalone enums above, applied to
    the four extended enums — old and new members alike must bind by value."""
    for enum_cls, _ in EXTENDED_ENUMS_WITH_NEW_MEMBERS:
        sa_enum = pg_enum(enum_cls, f"{enum_cls.__name__.lower()}_enum")
        expected_labels = {member.value for member in enum_cls}
        actual_labels = set(sa_enum.enums)
        assert actual_labels == expected_labels, (
            f"{enum_cls.__name__} binds enum labels {actual_labels} via pg_enum(), "
            f"expected values {expected_labels} (bug: bound by .name, not .value)"
        )


# Which real Postgres enum type name each extended Python enum's new values
# actually land in. RiskEntityType maps to observation_entity_type
# specifically, not risk_entity_type/rollup_entity_type: CATCHMENT is only
# ever used via satellite_observation.entity_type (D3) — WaterBalanceResult
# and RechargeStressScore have their own catchment_id column and never use
# the polymorphic entity_type/entity_id pattern RiskScore/RiskRollup do.
EXTENDED_ENUM_TO_POSTGRES_TYPE_NAME = {
    UserRole: "user_role",
    RiskEntityType: "observation_entity_type",
    SatelliteIndexType: "satellite_index_type",
    JobType: "job_type",
}


async def _database_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def db_session():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")
    async with AsyncSessionLocal() as session:
        yield session


async def test_extended_enum_postgres_types_actually_contain_new_values(db_session):
    """The specific regression test for the M0 -> M1 live-verification
    defect: extending the Python enum class is not enough — the real,
    already-created Postgres enum type must also be ALTERed. This queries
    pg_type/pg_enum directly, not the SQLAlchemy model, so it fails if a
    future enum extension forgets the corresponding migration exactly the
    way 0010_extend_existing_enums's predecessor state did."""
    for enum_cls, pg_type_name in EXTENDED_ENUM_TO_POSTGRES_TYPE_NAME.items():
        result = await db_session.execute(
            text(
                "SELECT e.enumlabel FROM pg_type t "
                "JOIN pg_enum e ON t.oid = e.enumtypid "
                "WHERE t.typname = :type_name"
            ),
            {"type_name": pg_type_name},
        )
        actual_labels = {row[0] for row in result}
        expected_labels = {member.value for member in enum_cls}
        missing = expected_labels - actual_labels
        assert not missing, (
            f"Postgres type '{pg_type_name}' is missing value(s) {missing} present in the "
            f"Python enum {enum_cls.__name__} — an ALTER TYPE migration is needed, "
            f"extending the Python enum alone is not sufficient"
        )
