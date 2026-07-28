"""Extend four existing Postgres enum types with their Water Intelligence
values.

user_role, observation_entity_type, satellite_index_type, and job_type
were all extended in Python (app/models/enums.py, ticket M0-001) per D3's
decision to reuse existing enums rather than create parallel ones — but
the actual Postgres enum types, created back in 0001_initial_schema, were
never altered to match. No offline test could catch this: the offline
DDL-compile suite only checks a SQLAlchemy model's declared enum against
itself (both sides come from the same Python source), never against what
an already-created Postgres type actually contains at the database level.

Discovered live, not hypothesized: running the full backend regression
suite against a real PostgreSQL 16.4 + PostGIS 3.4 instance (the M0 -> M1
infrastructure-verification ticket) failed with

    sqlalchemy.exc.DBAPIError: invalid input value for enum user_role:
    "programme_officer"

in tests/test_catchment_model.py's `user` fixture — the one place in all
of M0 that actually inserts a row using one of the new UserRole values.
observation_entity_type, satellite_index_type, and job_type carry the
identical latent defect (confirmed by direct inspection of the live
enum's current labels) but were not yet triggered by any M0 test, since
M0 deliberately excludes any code that would insert a
satellite_observation or job row using a Water Intelligence value.

Revision ID: 0010_extend_existing_enums
Revises: 0009_cgwb_observation
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_extend_existing_enums"
down_revision: str | None = "0009_cgwb_observation"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot be used to insert/select the new
    # value within the same transaction it was added in (a PostgreSQL
    # restriction) — this migration only adds values and nothing in it
    # ever uses one, so that restriction never applies here.
    # IF NOT EXISTS makes each statement safe to re-run.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'programme_officer'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'programme_admin'")
    op.execute("ALTER TYPE observation_entity_type ADD VALUE IF NOT EXISTS 'catchment'")
    op.execute("ALTER TYPE satellite_index_type ADD VALUE IF NOT EXISTS 'et'")
    op.execute("ALTER TYPE satellite_index_type ADD VALUE IF NOT EXISTS 'surface_water_sar'")
    op.execute("ALTER TYPE satellite_index_type ADD VALUE IF NOT EXISTS 'surface_water_mndwi'")
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'catchment_water_report'")
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'catchment_boundary_upload'")


def downgrade() -> None:
    # PostgreSQL has no ALTER TYPE ... DROP VALUE. Reversing this cleanly
    # requires rebuilding each enum type from scratch (rename the old
    # type, create a new type with only the original values, ALTER every
    # dependent column to the new type, drop the old type) — safe only if
    # no row anywhere already uses one of the added values. That is a
    # data-dependent, materially riskier operation than anything else in
    # this migration set, and out of proportion to this fix. Raising here,
    # rather than a silent no-op, so a downgrade attempt fails loudly
    # instead of quietly claiming success while leaving the added enum
    # values in place.
    raise NotImplementedError(
        "Cannot cleanly downgrade: PostgreSQL has no ALTER TYPE ... DROP VALUE. "
        "Rebuilding user_role/observation_entity_type/satellite_index_type/job_type "
        "from scratch would be required, and is only safe if no existing row uses "
        "an added value — verify that manually before attempting it."
    )
