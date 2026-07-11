"""Drop redundant unique index on app_user.email.

The initial migration (0001) declared uniqueness on app_user.email twice:
once via the column-level `unique=True` in op.create_table (which Postgres
auto-named `app_user_email_key`, backing a formal UNIQUE CONSTRAINT), and
again via an explicit `op.create_index("ix_app_user_email", ...,
unique=True)` immediately after (a separate, plain unique index). Both
physically enforce the same constraint — no functional gap — but it's
pure redundancy: two indexes maintained on every INSERT/UPDATE to
app_user, wasted disk space, and schema drift against the current
SQLAlchemy model. app.models.user.AppUser declares `unique=True,
index=True` together on the email column, which resolves to exactly one
unique index (confirmed via `alembic check`, which flags `app_user_email_key`
as unexpected drift against that model) — matching `ix_app_user_email`,
not two separate index objects.

`ix_app_user_email` is kept: it matches this codebase's naming convention
for every other index (ix_admin_boundary_*, ix_farm_polygon_*, etc.) and
is what the current model actually represents. `app_user_email_key` is
dropped — as a CONSTRAINT, not a bare index (Postgres refuses a direct
DROP INDEX on an index backing a constraint; confirmed by actually running
this against the live database, not assumed — see docs/DECISIONS.md).
No data is affected — this only removes a redundant index/constraint
structure, not a column or any row.

Revision id kept short (<=32 chars): Alembic's own alembic_version table
uses VARCHAR(32) for version_num by default, and a longer, more
descriptive first attempt at this revision id
("0002_drop_redundant_app_user_email_index", 40 chars) failed with
StringDataRightTruncationError — confirmed by actually running it, not
assumed.

Revision ID: 0002_drop_dup_email_idx
Revises: 0001_initial_schema
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_drop_dup_email_idx"
down_revision: str | None = "0001_initial_schema"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("app_user_email_key", "app_user", type_="unique")


def downgrade() -> None:
    # Restores the exact original (redundant) state for a clean round-trip
    # — not a recommendation to keep both in practice.
    op.create_unique_constraint("app_user_email_key", "app_user", ["email"])
