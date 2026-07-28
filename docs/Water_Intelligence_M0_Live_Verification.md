# M0 → M1 Infrastructure Verification — Live Database Report

**Date:** 27 July 2026
**Task:** Run the complete M0 migration chain and full backend regression suite against a real PostgreSQL + PostGIS instance — the one recommendation standing between the M0 review's "APPROVED WITH MINOR CHANGES" and an unqualified sign-off.
**Result:** A real defect was found and fixed. Everything else passed. Details below.

---

## 1. Docker Status

Docker Desktop's daemon was not running at the start of this task (confirmed via `docker info` failing to reach `npipe:////./pipe/dockerDesktopLinuxEngine`). Started via `Start-Process "Docker Desktop.exe"`, daemon became responsive within the first readiness check. `docker compose -f docker/docker-compose.yml up -d` brought up the existing `terrarisk-postgis` container (a persistent volume from prior Service 1 development — **2 weeks old, not created this session**) — confirmed healthy via its own healthcheck (`pg_isready`).

## 2. Database Version

**PostgreSQL 16.4** (Debian 16.4-1.pgdg110+2, x86_64-pc-linux-gnu), confirmed via `SELECT version();` against the live container.

## 3. PostGIS Version

**PostGIS 3.4** (`USE_GEOS=1 USE_PROJ=1 USE_STATS=1`), confirmed via `SELECT PostGIS_Version();`.

## 4. Migration Execution Log

**Fresh-database bootstrap** (isolated `terrarisk_m0_verify` database, created specifically so the existing Service 1 dev database — already at migration head `0004` with real data — was never put at risk):

- `alembic upgrade head` from a genuinely empty database (only PostGIS's own `spatial_ref_sys` table present): ran `0001` → `0009` in one pass, zero errors.
- `alembic downgrade base`: reversed all 9 migrations, confirmed the database returned to containing only `alembic_version` and `spatial_ref_sys` — genuinely empty, not just "no errors reported."
- `alembic upgrade head` a second time: ran cleanly again from empty, confirming the cycle is repeatable, not a one-shot fluke.
- **A real defect was found at this point** (detailed in Section 8) and fixed with a new migration, `0010_extend_existing_enums`.
- `alembic upgrade head` (now to `0010`) re-run against both the verification database and the real standing `terrarisk` dev database: clean, zero errors, purely additive to the latter (confirmed existing Service 1 rows — 9 `app_user`, 30 `farm_polygon` — untouched before and after).
- Verification database (`terrarisk_m0_verify`) dropped after use — it was a disposable artifact created for this task, not a resource to leave behind.

## 5. Schema Verification (against the live database, not offline compilation)

| Check | Result |
|---|---|
| All 20 tables present (13 Service 1 + 5 Water Intelligence + `spatial_ref_sys`) | ✓ `\dt public.*` confirmed |
| All 6 new enum types created with exact expected values | ✓ `organization_type`, `delineation_method`, `storage_change_band`, `calibration_status`, `stress_band`, `baseline_window` — queried directly from `pg_type`/`pg_enum` |
| `alembic_version` at correct head | ✓ `0009_cgwb_observation` before the fix, `0010_extend_existing_enums` after |
| Indexes on all 5 new tables | ✓ 13 indexes confirmed via `pg_indexes` — including both auto-created GIST indexes on `catchment` (`geometry` **and** `pour_point` — the latter never explicitly stated in any prior ticket, confirmed live here) and the GIST index on `cgwb_groundwater_observation.block_geometry` |
| `CHECK` constraints on `catchment` | ✓ `chk_catchment_area`, `chk_catchment_vertex_count` — confirmed present via `pg_get_constraintdef`, and confirmed **enforced** (see Section 6) |
| `UNIQUE` constraint on `cgwb_groundwater_observation` | ✓ `uq_cgwb_block_period` confirmed present and enforced |
| Foreign keys | ✓ All 6 expected FKs confirmed via `pg_constraint`: `catchment→organization`, `catchment→admin_boundary`, `catchment→app_user`, `water_balance_result→catchment`, `recharge_stress_score→catchment`, `recharge_stress_score→config_weight`. `cgwb_groundwater_observation` correctly has zero FKs (by design) |
| Geometry column SRIDs and types | ✓ `catchment.geometry` (MULTIPOLYGON, 4326), `catchment.pour_point` (POINT, 4326), `cgwb_groundwater_observation.block_geometry` (MULTIPOLYGON, 4326) — confirmed via the `geometry_columns` system view |

## 6. Executed Live-Database Tests

All previously-skipping tests now executed for real, against a real database, for the first time in this project's history:

- `tests/test_catchment_model.py` (4 tests) — including the two `CHECK`-constraint rejection tests, which **actually triggered a live Postgres rejection** for oversized area and excessive vertex count, not just an offline assertion that the constraint exists.
- `tests/test_cgwb_model.py` (3 tests) — including the `UNIQUE`-constraint rejection test, which actually triggered a live `uq_cgwb_block_period` violation.
- `tests/test_enums.py` — 1 new test added during this task (Section 9), also executed live.

## 7. Regression Summary

| Run | Result |
|---|---|
| First live run (before the fix) | **203 passed, 4 errors** — all 4 errors in `tests/test_catchment_model.py`, all the same root cause |
| After the fix, live-DB tests only | 7/7 passed (`test_catchment_model.py` + `test_cgwb_model.py`) |
| After the fix, full suite | 207 passed, 0 skipped, 0 failed |
| **Final, complete run**, including the new regression test added in response to the defect | **208 passed, 0 skipped, 0 failed, 1 pre-existing cosmetic warning** |

This is the first time in this project's history the full suite has run with **zero skips** — every environment-gated test that previously could only assert "correctly written, never executed" now has an actual, live, passing execution behind it.

## 8. Migration Issues Discovered

**One real defect, found by this exercise doing exactly what it was designed to do.**

`user_role`, `observation_entity_type`, `satellite_index_type`, and `job_type` are all **pre-existing** Postgres enum types, created in `0001_initial_schema.py`, long before Water Intelligence existed. Ticket M0-001 correctly extended the corresponding **Python** enum classes in `app/models/enums.py` (per D3's decision to reuse existing enums rather than create parallel ones) — but no migration was ever written to actually `ALTER TYPE ... ADD VALUE` on the real, already-created Postgres types. The Python side and the database side silently diverged, and **no offline test could have caught this**: `test_schema_ddl.py`'s enum-binding test only checks a SQLAlchemy model's declared type against itself — both sides are derived from the same Python source, so they trivially always agree, regardless of what a real, previously-created database type actually contains.

**First symptom:** `tests/test_catchment_model.py`'s `user` fixture — the one place across the entire M0 milestone that actually inserts a row using one of the new enum values (`UserRole.PROGRAMME_OFFICER`) — failed against the real database with:

```
sqlalchemy.exc.DBAPIError: invalid input value for enum user_role: "programme_officer"
```

**Confirmed scope, by direct query against the live database, before assuming anything:** all four extended enum types were frozen at their pre-M0 values —

```
job_type                | {farm_report,portfolio_aggregation}
observation_entity_type | {farm,village,branch,district}
satellite_index_type    | {ndvi,mndwi,ndmi,rainfall,jrc_water_occurrence}
user_role                | {credit_officer,branch_manager,risk_officer,ceo,chairman}
```

The other three (`observation_entity_type`, `satellite_index_type`, `job_type`) carried the identical latent defect but had not yet been triggered by any M0 test, since M0 deliberately excludes any code path (API, service, engine, job) that would insert a row using one of those specific new values — this would have surfaced the moment M1/M4 wrote real code that did.

## 9. Fix Applied

**`backend/alembic/versions/0010_extend_existing_enums.py`** — a new, purely additive migration:

```sql
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'programme_officer';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'programme_admin';
ALTER TYPE observation_entity_type ADD VALUE IF NOT EXISTS 'catchment';
ALTER TYPE satellite_index_type ADD VALUE IF NOT EXISTS 'et';
ALTER TYPE satellite_index_type ADD VALUE IF NOT EXISTS 'surface_water_sar';
ALTER TYPE satellite_index_type ADD VALUE IF NOT EXISTS 'surface_water_mndwi';
ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'catchment_water_report';
ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'catchment_boundary_upload';
```

**Why `observation_entity_type` and not also `risk_entity_type`/`rollup_entity_type`:** `RiskEntityType.CATCHMENT` is only ever intended to flow through `satellite_observation.entity_type` (bound to `observation_entity_type`) per D3's stated design — `WaterBalanceResult` and `RechargeStressScore` have their own dedicated `catchment_id` foreign key columns and never use the polymorphic `entity_type`/`entity_id` pattern `RiskScore`/`RiskRollup` do. Altering those two would be scope creep for values that can never occur there.

**Downgrade:** raises `NotImplementedError` with a clear explanation, rather than a silent no-op. PostgreSQL has no `ALTER TYPE ... DROP VALUE` — reversing this cleanly requires rebuilding each enum type from scratch (rename, recreate with only the original values, re-point every dependent column, drop the old type), which is only safe if no row anywhere already uses an added value. That is a materially riskier, data-dependent operation out of proportion to this fix, and pretending to reverse it with a no-op would be dishonest about what actually happened.

**Regression test added** — `tests/test_enums.py::test_extended_enum_postgres_types_actually_contain_new_values` — queries `pg_type`/`pg_enum` directly against the live database for all four extended types and asserts every Python-side value is actually present. This is the test that should have existed from M0-001 and didn't; it now exists specifically so this class of defect (Python enum extended, real Postgres type forgotten) cannot silently recur for any future service that reuses this same D3 pattern.

**Verified fixed:** all four types confirmed live to now contain their full expected value sets; the previously-failing test and the full suite both re-run clean (Section 7).

## 10. Recommended Fixes

None outstanding. The one discovered defect has a merged fix, a passing re-verification, and a permanent regression test guarding against recurrence.

---

## Quality Gate

✓ Fresh database migrated successfully (`0001`→`0009`, then `0010` after the fix, from genuinely empty)
✓ Downgrade succeeded (full reversal to empty, confirmed by table count, not just exit code)
✓ Upgrade succeeded again (second clean bootstrap from empty, proving repeatability)
✓ Live DB tests executed (all 8 previously-skipping tests, plus 1 new one, all against a real instance)
✓ No outstanding migration defects — the one found is fixed, verified, and permanently regression-tested
✓ Ready to begin M1

---

# M1 INFRASTRUCTURE VERIFIED

The M0 review's one open recommendation is closed. This exercise did not just confirm M0 works — it found something offline verification structurally could not have found, fixed it with the smallest correct change, and left a permanent test so it can't happen again. M0 is now verified against a real PostgreSQL 16.4 + PostGIS 3.4 instance, in both directions, twice, with the full regression suite at **208 passed, 0 skipped, 0 failed**. M1 can begin.
