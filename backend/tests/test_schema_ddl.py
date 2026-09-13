"""Validates every model compiles to correct PostgreSQL DDL without needing
a live database connection — the closest thing to a migration smoke test
available in an environment with no reachable Postgres/PostGIS instance
(see the M0 milestone summary). Running `alembic upgrade head` against a
real PostGIS database is still the authoritative check and should be done
wherever this suite runs with Docker available.
"""

import enum

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.database.base import Base
from app.models import (  # noqa: F401 — import registers every table on Base.metadata
    AdminBoundary,
    AppUser,
    Branch,
    Catchment,
    CgwbGroundwaterObservation,
    ConfigWeight,
    FarmerIdentity,
    FarmPolygon,
    Job,
    Loan,
    Organization,
    RechargeStressScore,
    RiskFactorScore,
    RiskRollup,
    RiskScore,
    SatelliteObservation,
    VillageBranchLookup,
    WaterBalanceResult,
)

EXPECTED_TABLES = {
    "admin_boundary",
    "branch",
    "village_branch_lookup",
    "app_user",
    "catchment",
    "farm_polygon",
    "farmer_identity",
    "loan",
    "satellite_observation",
    "organization",
    "config_weight",
    "cgwb_groundwater_observation",
    "evidence_record",
    "recharge_stress_score",
    "risk_score",
    "risk_factor_score",
    "risk_rollup",
    "job",
    "validation_finding",
    "validation_run",
    "water_balance_result",
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
    catchment = Base.metadata.tables["catchment"]

    assert admin_boundary.c.geometry.type.srid == 4326
    assert admin_boundary.c.geometry_simplified.type.srid == 4326
    assert farm_polygon.c.geometry.type.srid == 4326
    assert catchment.c.geometry.type.srid == 4326
    assert catchment.c.pour_point.type.srid == 4326


def test_catchment_geometry_is_multipolygon_not_polygon():
    """Regression test for the specific TDR §4 finding: v1 typed
    catchment.geometry as POLYGON by copying FarmPolygon's shape without
    checking a real watershed is guaranteed simply connected. It isn't."""
    catchment = Base.metadata.tables["catchment"]
    assert catchment.c.geometry.type.geometry_type == "MULTIPOLYGON"


def test_catchment_check_constraints_are_present():
    """Offline-verifiable half of the CHECK-constraint requirement — proves
    the constraints exist and compile with the expected names/conditions.
    Whether Postgres actually *enforces* them on insert is proven by the
    live-database tests in tests/test_catchment_model.py, which this
    sandbox cannot run without a reachable PostGIS instance."""
    catchment = Base.metadata.tables["catchment"]
    check_constraints = {c.name: str(c.sqltext) for c in catchment.constraints if isinstance(c, CheckConstraint)}

    assert "chk_catchment_area" in check_constraints
    assert "BETWEEN 0.5 AND 50000" in check_constraints["chk_catchment_area"]
    assert "chk_catchment_vertex_count" in check_constraints
    assert "ST_NPoints(geometry) <= 2000" in check_constraints["chk_catchment_vertex_count"]


def test_every_enum_column_binds_by_value_not_by_member_name():
    """Regression test for a real M1 bug: SQLAlchemy's Enum type binds
    using the Python member name ("VILLAGE") by default, but every native
    Postgres enum type here was created (Alembic migration 0001) with the
    lowercase *values* ("village") as its only valid labels. Without
    values_callable (see app.models.mixins.pg_enum), an insert of
    BoundaryLevel.VILLAGE fails against real Postgres with "invalid input
    value for enum boundary_level: VILLAGE" — DDL compilation alone never
    catches this, because it only validates that CREATE TABLE renders, not
    that bound parameter values match the column's accepted labels.
    """
    for table_name, table in Base.metadata.tables.items():
        for column in table.columns:
            if not isinstance(column.type, SAEnum) or column.type.enum_class is None:
                continue
            enum_cls: type[enum.Enum] = column.type.enum_class
            expected_labels = {member.value for member in enum_cls}
            actual_labels = set(column.type.enums)
            assert actual_labels == expected_labels, (
                f"{table_name}.{column.name} binds enum labels {actual_labels}, "
                f"expected values {expected_labels} (bug: bound by .name, not .value)"
            )


def test_water_balance_result_has_no_weights_version_id():
    """Regression test for a real TDR finding (§6): v1 of the Water
    Intelligence blueprint copied weights_version_id onto
    water_balance_result by pattern-matching off risk_score's shape,
    without checking whether it applied. It doesn't — a P-ET-Q=dS mass
    balance is an arithmetic sum of physical terms, not a weighted
    composite. Weights genuinely belong only on recharge_stress_score
    (M0-005). This test exists so the field can't be silently
    reintroduced by a future engineer pattern-matching the same way v1 did.
    """
    water_balance_result = Base.metadata.tables["water_balance_result"]
    assert "weights_version_id" not in water_balance_result.columns


def test_recharge_stress_score_has_weights_version_id():
    """The mirror image of the test above (M0-005's own acceptance
    criteria): recharge_stress_score genuinely is a weighted composite
    (rainfall anomaly + VCI + surface-water trend), the same shape as
    risk_score's four-factor weighting — so weights_version_id belongs
    here, FK'd to config_weight, exactly where it was moved to in
    Blueprint v2 (TDR §6)."""
    recharge_stress_score = Base.metadata.tables["recharge_stress_score"]
    assert "weights_version_id" in recharge_stress_score.columns
    fk_targets = {fk.target_fullname for fk in recharge_stress_score.c.weights_version_id.foreign_keys}
    assert fk_targets == {"config_weight.id"}


def test_recharge_stress_score_catchment_computed_at_index_exists():
    """Regression test for the TDR finding: v1 was missing an index on
    recharge_stress_score(catchment_id, computed_at) — this is the query
    shape "latest + historical stress scores for a catchment" (Blueprint v2
    Part 6's GET /catchments/{id}/recharge-stress) will always use."""
    recharge_stress_score = Base.metadata.tables["recharge_stress_score"]
    index_columns = {tuple(c.name for c in idx.columns) for idx in recharge_stress_score.indexes}
    assert ("catchment_id", "computed_at") in index_columns


def test_cgwb_block_period_uniqueness_constraint_is_present():
    """Offline-verifiable half of the M0-006 requirement — proves
    uq_cgwb_block_period exists with the expected columns. Whether Postgres
    actually *enforces* it on a duplicate insert is proven by the
    live-database test in tests/test_cgwb_model.py, which this sandbox
    cannot run without a reachable PostGIS instance."""
    cgwb = Base.metadata.tables["cgwb_groundwater_observation"]
    unique_constraints = {c.name: {col.name for col in c.columns} for c in cgwb.constraints if isinstance(c, UniqueConstraint)}
    assert unique_constraints.get("uq_cgwb_block_period") == {"block_code", "assessment_period"}


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


def test_evidence_vocabulary_constraints_admit_exactly_the_python_enum_values():
    """The evidence tables store vocabulary as strings behind CHECK
    constraints (see app/models/evidence.py for why). This pins that the
    constraints are generated from the enums, so adding a value in Python
    without the database learning it — the silent failure 0010 exists to
    fix for native enums — cannot happen here."""
    import re

    from app.models.enums import EvidenceKind, EvidenceResultTable, EvidenceValidation, FindingSeverity

    expected = {
        ("evidence_record", "ck_evidence_record_kind"): EvidenceKind,
        ("evidence_record", "ck_evidence_record_validation"): EvidenceValidation,
        ("evidence_record", "ck_evidence_record_result_table"): EvidenceResultTable,
        ("validation_run", "ck_validation_run_result_table"): EvidenceResultTable,
        ("validation_finding", "ck_validation_finding_severity"): FindingSeverity,
    }
    for (table_name, constraint_name), enum_cls in expected.items():
        table = Base.metadata.tables[table_name]
        constraint = next(c for c in table.constraints if isinstance(c, CheckConstraint) and c.name == constraint_name)
        admitted = set(re.findall(r"'([^']+)'", str(constraint.sqltext)))
        assert admitted == {m.value for m in enum_cls}, f"{constraint_name} drifted from {enum_cls.__name__}"


def test_there_is_no_plausibility_level_of_validation():
    """Passing a plausibility envelope is not validation. A label saying
    otherwise would put 'validated' next to numbers that merely failed to
    look broken."""
    from app.models.enums import EvidenceValidation

    assert not any("plausib" in m.value for m in EvidenceValidation)


def test_the_migration_constraints_match_the_model_constraints():
    """The migration writes its CHECK expressions out literally; the
    model generates them. Both must admit the same values, or a fresh
    database and the ORM disagree about what is legal."""
    import re
    from pathlib import Path

    migration = (Path(__file__).parents[1] / "alembic" / "versions" / "0012_evidence_provenance.py").read_text(encoding="utf-8")
    for table_name in ("evidence_record", "validation_run", "validation_finding"):
        for constraint in Base.metadata.tables[table_name].constraints:
            if not isinstance(constraint, CheckConstraint) or " IN (" not in str(constraint.sqltext):
                continue
            model_values = set(re.findall(r"'([^']+)'", str(constraint.sqltext)))
            for value in model_values:
                assert f"'{value}'" in migration, f"{constraint.name}: '{value}' missing from migration 0012"
