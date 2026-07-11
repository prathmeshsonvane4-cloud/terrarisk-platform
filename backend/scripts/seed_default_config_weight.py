"""One-off seed: inserts the initial risk-engine ConfigWeight row.

Required before any report can be generated — RiskScore.weights_version_id
is a non-nullable foreign key, so the risk engine has nothing to run
against until at least one ConfigWeight row exists (see
app/services/reporting/report_generator.py's _get_active_config_weight).

The weights here are an EQUAL, PROVISIONAL starting point — consistent
with the approved decision that v1 is transparent and rule-based, not
scientifically calibrated (docs/DECISIONS.md). They are not a domain
claim about relative factor importance; recalibration is a matter of
inserting a new ConfigWeight row (never editing this one in place), once
real loan-performance data and domain-expert input are available.

Usage:
    python scripts/seed_default_config_weight.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Running this file directly (`python scripts/seed_default_config_weight.py`)
# only puts scripts/ on sys.path, not the backend/ root — without this,
# `from app...` below fails with ModuleNotFoundError. Must run before any
# app.* import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database.base import AsyncSessionLocal
from app.models.enums import RiskFactor
from app.models.risk import ConfigWeight

# A single shared severe-threshold cutoff across all four factors (approved
# methodology: docs/DECISIONS.md "Floor Rule"). A factor scoring at or
# above this value forces the overall Climate Risk Score to at least the
# High band, regardless of the weighted average.
_DEFAULT_FLOOR_THRESHOLD = 80.0


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(ConfigWeight).limit(1))).scalar_one_or_none()
        if existing is not None:
            print(f"A ConfigWeight row already exists ({existing.id}) — not inserting a duplicate.")
            return

        config = ConfigWeight(
            weights={factor.value: 0.25 for factor in RiskFactor},
            floor_thresholds={"threshold": _DEFAULT_FLOOR_THRESHOLD},
            effective_from=datetime.now(timezone.utc),
            created_by=None,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
        print(f"Seeded default ConfigWeight: {config.id}")


if __name__ == "__main__":
    asyncio.run(seed())
