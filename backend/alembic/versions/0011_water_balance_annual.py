"""Add per-water-year breakdown to water_balance_result.

The report already stored one set of period totals for its whole 3-year
window, which answers "what happened over this period" but not "is this
catchment getting wetter or drier" — the question a watershed programme
actually acts on. The monthly series needed to answer that was fetched
from Earth Engine on every run and then discarded.

Stored as JSONB rather than a child table: this is a small, fixed-shape
list (one row per water year, at most a handful) that is always read
whole with its parent report and never queried or joined on its own. A
`water_balance_annual` table would add a join to every read for no
query the product makes.

Nullable with no backfill. Existing rows genuinely do not have this — the
monthly data they were computed from no longer exists anywhere, so any
backfilled value would be invented. They read as null until regenerated,
which is honest.

Revision ID: 0011_water_balance_annual
Revises: 0010_extend_existing_enums
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011_water_balance_annual"
down_revision = "0010_extend_existing_enums"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "water_balance_result",
        sa.Column("annual", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("water_balance_result", "annual")
