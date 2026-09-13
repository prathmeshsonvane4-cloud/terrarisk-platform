"""One-off CLI: run the physical validation harness over stored water
balances that pre-date it, and persist the findings (evidence-aware
roadmap, Phase B).

WHAT THIS DOES AND DOES NOT BACKFILL
------------------------------------
It backfills VALIDATION FINDINGS, marked `source='backfill'`, because those
can be derived honestly from stored values: the harness only needs P, ET,
Q and dS.

It does NOT backfill EVIDENCE LINEAGE. A stored result cannot tell us which
Curve Number, masking rule or provider version produced it — several of
those changed during the hydrology audit — and a reconstructed lineage
would be invented. Those results keep no evidence rows, and the lineage
API reports "provenance not recorded" for them.

HOW IT DIFFERS FROM THE LIVE PIPELINE, STATED IN EVERY RUN IT WRITES
--------------------------------------------------------------------
- Agro-climatic zone: the live pipeline uses the catchment's 30-year CHIRPS
  climatology, which old rows never stored. Here the zone comes from the
  result's own annualised observed rainfall. A window containing a failed
  monsoon could therefore be classed drier than its climate. Each run gets
  an INFO finding recording this.
- Identity guard: values come back from NUMERIC(10,2) columns, so the
  stored-value rounding allowance applies (`values_from_storage=True`).

Idempotent: a result that already has any validation run is skipped.
Dry run by default — nothing is written without --apply.

Usage (inside the backend container):
    python scripts/backfill_validation.py            # dry run: report only
    python scripts/backfill_validation.py --apply    # write findings
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

# Running this file directly only puts scripts/ on sys.path; the backend
# root is needed for `app.*` imports (same fix as the other scripts here).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database.base import AsyncSessionLocal  # noqa: E402
from app.models.enums import EvidenceResultTable  # noqa: E402
from app.models.evidence import ValidationRun  # noqa: E402
from app.models.water_balance import WaterBalanceResult  # noqa: E402
from app.services.hydrology.models import AnnualWaterBalance, WaterBalanceEngineResult  # noqa: E402
from app.services.provenance import add_validation_run  # noqa: E402
from app.services.validation import (  # noqa: E402
    AgroClimaticZone,
    Severity,
    ValidationFinding,
    ValidationReport,
    classify_zone_by_rainfall,
    validate_water_balance,
)

_DAYS_PER_YEAR = 365.25


def _as_float(value) -> float | None:
    return None if value is None else float(value)


def validate_stored_balance(row: WaterBalanceResult) -> tuple[AgroClimaticZone, ValidationReport]:
    """Pure: rebuild a stored balance, validate it, and attach the finding
    that records how this differs from a pipeline run. No I/O."""
    result = WaterBalanceEngineResult(
        storage_change_band=row.storage_change_band,
        storage_change_mm=_as_float(row.storage_change_mm),
        rainfall_mm=_as_float(row.rainfall_mm),
        et_mm=_as_float(row.et_mm),
        runoff_mm=_as_float(row.runoff_mm),
        data_completeness=_as_float(row.data_completeness) or 0.0,
        calibration_status=row.calibration_status,
        closed_catchment_assumed=row.closed_catchment_assumed,
        resolution_flags=list(row.resolution_flags or []),
        model_version=row.model_version,
        annual=[AnnualWaterBalance(**year) for year in (row.annual or [])],
    )

    years = (row.period_end - row.period_start).days / _DAYS_PER_YEAR
    annual_rainfall = result.rainfall_mm / years if result.rainfall_mm is not None and years > 0 else None
    zone = classify_zone_by_rainfall(annual_rainfall)

    report = validate_water_balance(
        result, zone=zone, subject=f"water_balance_result:{row.id}", values_from_storage=True
    )
    basis = ValidationFinding(
        check="backfill_zone_basis",
        severity=Severity.INFO,
        subject="agro_climatic_zone",
        observed=annual_rainfall,
        message=(
            "Backfilled after the fact from stored values. The zone was derived from this result's own "
            f"annualised observed rainfall ({annual_rainfall:.0f} mm/yr), not the 30-year climatology a "
            "pipeline run uses, because none was stored — a window containing a failed monsoon could be "
            "classed drier than its climate. No evidence lineage exists for this result and none was "
            "reconstructed."
            if annual_rainfall is not None
            else "Backfilled after the fact from stored values. Rainfall was not stored, so no zone could be "
            "derived and plausibility checks were skipped. No evidence lineage was reconstructed."
        ),
        expected="zone from the 30-year CHIRPS climatology, as in a pipeline run",
    )
    return zone, ValidationReport(
        subject=report.subject,
        findings=[basis, *report.findings],
        checks_run=report.checks_run,
        checks_skipped=report.checks_skipped,
    )


async def main(apply: bool) -> int:
    async with AsyncSessionLocal() as db:
        already = set(
            (
                await db.execute(
                    select(ValidationRun.result_id).where(
                        ValidationRun.result_table == EvidenceResultTable.WATER_BALANCE_RESULT.value
                    )
                )
            ).scalars().all()
        )
        rows = (await db.execute(select(WaterBalanceResult))).scalars().all()
        pending = [row for row in rows if row.id not in already]

        failed = 0
        checks: Counter[str] = Counter()
        zones: Counter[str] = Counter()
        for row in pending:
            zone, report = validate_stored_balance(row)
            zones[zone.value] += 1
            if report.failed:
                failed += 1
                checks.update(f.check for f in report.findings if f.is_failure)
            if apply:
                add_validation_run(
                    db, EvidenceResultTable.WATER_BALANCE_RESULT, row.id, report, zone=zone.value, source="backfill"
                )

        print(f"water balances: {len(rows)} total, {len(already)} already validated, {len(pending)} to backfill")
        print(f"zones: {dict(zones)}")
        print(f"failing validation: {failed} of {len(pending)}")
        print(f"failing checks: {dict(checks)}")
        if apply:
            await db.commit()
            print(f"WROTE {len(pending)} validation runs (source='backfill').")
        else:
            print("DRY RUN — nothing written. Re-run with --apply to persist.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Write validation runs. Without this, report only.")
    sys.exit(asyncio.run(main(parser.parse_args().apply)))
