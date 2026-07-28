# TerraRisk Water Intelligence — Implementation Plan & Engineering Backlog (Rev. 2)

**Status:** Architecture frozen (Blueprint v2, TDR-resolved, APPROVED MINOR CHANGES). This document does not revisit any design decision — it converts the approved blueprint into tickets a new engineer can pick up cold.
**Rev. 2 (27 July 2026):** renumbered to match what the codebase actually contains, after implementation diverged from Rev. 1's ticket labels. **No milestone was redesigned, no feature was added or removed — this revision only corrects sequencing and labels.** Full rationale for every change is in the **Changelog** at the end of this document; read that first if you only read one new section. `[R2]` tags mark every changed line inline.
**Verified against repository state as of 27 July 2026** — migration numbering, ticket completion status, and file contents below are read from the actual codebase and from `docs/Water_Intelligence_M0_Review.md` / `docs/Water_Intelligence_M0_Live_Verification.md`, not recalled or assumed.
**Source documents:** `docs/Water_Intelligence_Service_Blueprint.md` (v2), `docs/Water_Intelligence_TDR.md`, `docs/Water_Intelligence_M0_Review.md`, `docs/Water_Intelligence_M0_Live_Verification.md`

---

## `[R2]` Completed

| Ticket | What | Status |
|---|---|---|
| M0-001 | Enum extensions (`app/models/enums.py`) | ✅ Done, merged |
| M0-002 | `Organization` model + migration `0005` | ✅ Done, merged |
| M0-003 | `Catchment` model + migration `0006` | ✅ Done, merged |
| M0-004 | `WaterBalanceResult` model + migration `0007` | ✅ Done, merged |
| M0-005 | `RechargeStressScore` model + migration `0008` | ✅ Done, merged |
| M0-006 | `CgwbGroundwaterObservation` model + migration `0009` | ✅ Done, merged |
| M0-007 `[R2]` | **Extend pre-existing Postgres enum types** (`user_role`, `observation_entity_type`, `satellite_index_type`, `job_type`) + migration `0010` | ✅ Done — a real defect found and fixed during live-database verification, not part of Rev. 1's plan; see Changelog |
| — | M0 Principal Engineer review | ✅ APPROVED WITH MINOR CHANGES (`docs/Water_Intelligence_M0_Review.md`) |
| — | M0 live-database verification (fresh bootstrap, full up/down/up cycle, full regression suite) | ✅ Complete — 208 passed, 0 skipped, 0 failed after the M0-007 fix (`docs/Water_Intelligence_M0_Live_Verification.md`) |
| M2-001 | `WaterBalanceBundle`/`WaterBalanceConfig`/`WaterBalanceEngineResult` dataclasses | ✅ Done, merged |
| M2-002a `[R2]` | **`WaterBalanceEngine` skeleton** — class, `compute()` signature, input validation, logging, documented `NotImplementedError` stub | ✅ Done, merged — built under the mislabeled name "M1-001"; see Changelog |

**Everything else in this document is not started.** Tag `v0.3.0-m0-final` marks the state after M0-001 through M0-007; work since then (M2-001, M2-002a) is unreleased.

## `[R2]` Remaining work

Every ticket below M0 and the two M2 items above, in dependency order: `M1-001` through `M1-007` (GEE provider, zero tickets started), `M2-002b` through `M2-005` (engine arithmetic onward — **M2-002b is the immediate next ticket**), `M3-001` through `M3-004`, `M4-001` through `M4-007`, `M5-001` through `M5-005`, `M6-001` through `M6-007`. 30 tickets remain out of 43 total (13 done).

---

## Repository facts this plan depends on (verified, not assumed)

- Existing migrations at Rev. 1 time: `0001_initial_schema.py` through `0004_report_evidence_fields.py` → next migration was `0005`. `[R2]` **As of Rev. 2, migrations `0005`–`0010` all exist and are merged** — `0005_organization.py`, `0006_catchment.py`, `0007_water_balance_result.py`, `0008_recharge_stress_score.py`, `0009_cgwb_observation.py`, `0010_extend_existing_enums.py` (the M0-007 fix). Next migration is `0011`.
- `[R2]` Rev. 1 assumed no live Postgres/PostGIS instance was available in this dev sandbox and planned for offline-only verification. **That assumption no longer holds** — Docker was brought up and the full migration chain, schema, and regression suite were verified against a real PostgreSQL 16.4 + PostGIS 3.4 instance (`docs/Water_Intelligence_M0_Live_Verification.md`). Offline DDL compilation (`test_schema_ddl.py`'s pattern) remains the fast day-to-day check; live verification is no longer blocked and should be run again at least once per remaining milestone, not treated as a one-time M0 exercise.
- Backend dependencies (`backend/requirements.txt` or equivalent): `shapely==2.1.2` is already present (parses GeoJSON-shaped geometry natively) — **KML and Shapefile parsing have no existing dependency and need one added** (see M4 ticket notes; this plan recommends `pyshp` + stdlib `xml.etree.ElementTree` over `fiona`/`geopandas` specifically to avoid a GDAL binary dependency in the container).
- No task queue or scheduler exists in the codebase today (`docs/DECISIONS.md`: "FastAPI BackgroundTask, no message queue, at MVP volume"). The CGWB periodic-ingestion job (M3) needs *some* trigger mechanism that doesn't exist yet — resolved below as an authenticated internal endpoint triggered by external cron, not new in-process infrastructure.
- Frontend mapping stack: MapLibre GL JS + Terra Draw + Esri World Imagery (`docs/DECISIONS.md`), contract-first API client via `openapi-typescript`/`openapi-fetch` with committed generated types, Vitest as the unit-test runner.
- Existing enums live in `app/models/enums.py`; the `pg_enum()` gotcha (values, not member names) is a proven historical bug in this codebase and every new enum ticket must avoid re-triggering it.

---

# 1. IMPLEMENTATION_PLAN.md

## Milestones (unchanged scope from Blueprint v2, converted to execution units — `[R2]` ticket counts/status revised, milestone scope itself untouched)

| Milestone | Scope (from Blueprint v2) | Ticket count | Done | Critical path? |
|---|---|---|---|---|
| M0 — Foundations | Enums, 5 new tables, migrations, pre-existing-enum fix `[R2]` | 7 | **7/7** ✅ | **Yes — gates everything** |
| M1 — GEE hydrology provider | Provider ABC `[R2 — moved in from old M0-007]`, ET/SAR/MNDWI series, scale/maxPixels policy, cost measurement | 7 `[R2: +1]` | 0/7 | **Yes** |
| M2 — Water balance engine | Dataclasses, engine skeleton `[R2 — done]` + arithmetic `[R2 — split, remaining]`, storage-change band, resolution flags, golden-dataset test | 6 `[R2: +1]` | **2/6** ✅ | No — parallel to M1 |
| M3 — Recharge-stress + CGWB ingestion | Percentile scoring vs. 30yr climatology, CGWB staging + ingest job | 4 | 0/4 | No — parallel to M1/M2 |
| M4 — API + jobs + boundary upload | Router, boundary parser, job wiring | 7 | 0/7 | **Yes — needs M1+M2+M3 merged** |
| M5 — Reporting pipeline | Orchestrator, methodology text, PDF, resilience test | 5 | 0/5 | **Yes** |
| M6 — Frontend | Polygon-drawing generalization, catchment UI, dashboard | 7 | 0/7 | **Yes for integration; M6-001/002 start Day 1** |

**Total: 43 tickets `[R2: was 41]`. 13 done.**

## Sprint plan (assuming a 2-person backend + 1-person frontend team; adjust divisor for solo execution)

| Sprint (1 week each) | Focus | Parallel tracks |
|---|---|---|
| Sprint 1 | M0 complete (all 7 tickets — this is the one place sequencing is tight, since every later ticket reads the schema M0 writes) | Frontend: M6-001/M6-002 (polygon-drawing generalization) starts immediately — zero backend dependency |
| Sprint 2 | M1 (GEE provider) **and** M2 (pure engine) **and** M3 (recharge-stress/CGWB) run **concurrently** — none of the three depends on either of the other two, only on M0 | Frontend continues M6-001/002, starts M6-003 (catchment-drawing draw path) against a mocked API contract |
| Sprint 3 | M4 (API) — the integration point where M1+M2+M3's outputs get wired together for the first time | Frontend: M6-004 (upload path), begins wiring against real M4 endpoints as they land |
| Sprint 4 | M5 (reporting pipeline) | Frontend: M6-005/006 (dashboard, PDF download) |
| Sprint 5 | M6-007 (contract regen + real-stack integration test, both draw and upload paths), hardening, staging GEE cost measurement (M1's deferred exit criterion), buffer | — |

**This is a 5-sprint (5-week) plan for a small team, matching the Blueprint's "2–3 week scope" once the true parallelism in Sprint 2 is accounted for** — the v2 blueprint's milestone list reads sequentially but Sprint 2 above shows three of its seven milestones running side by side.

## Dependency graph (summary — full detail in Section 3)

```
M0 (schema) ─┬─→ M1 (GEE provider) ──┐
             ├─→ M2 (pure engine)  ──┼─→ M4 (API) ─→ M5 (reporting) ─→ M6 integration
             └─→ M3 (stress+CGWB) ──┘
                                        M6-001/002 (frontend polygon refactor) — independent from Day 1
```

## Estimated effort

| Milestone | Backend effort | Frontend effort |
|---|---|---|
| M0 | 3–4 person-days | 0 |
| M1 | 3–4 person-days | 0 |
| M2 | 2–3 person-days | 0 |
| M3 | 2 person-days | 0 |
| M4 | 4–5 person-days | 0 (contract only) |
| M5 | 3–4 person-days | 0 |
| M6 | 0 | 8–10 person-days |
| **Total** | **~17–22 person-days backend** | **~8–10 person-days frontend** |

## Acceptance criteria (milestone-level — ticket-level ACs are in Section 2)

A milestone is done when: every ticket in it is merged to `main`, every ticket's own tests pass in CI, and the milestone's own "Independently testable via" claim from Blueprint v2 Part 8 is demonstrably true (i.e., someone who wasn't in the room can run the named test file and see it exercise real, non-trivial behavior — not a stub that asserts `True`).

## Testing strategy (milestone-to-test-type mapping — full detail in Section 8)

Mirrors the existing Service 1 test taxonomy exactly: pure-engine tests (zero I/O), provider tests (real GEE against a test project), fakes (deterministic stand-ins for integration tests), schema/DDL tests (offline compile, given no live Postgres in this environment), report twin-tests (pinned text), one real-stack integration test at the very end. **New in this plan, not in Service 1's original taxonomy:** golden-dataset scientific regression tests (M2), and boundary-parser fixture tests (M4) — both directly required by the TDR.

## Merge strategy

- **One ticket = one PR = one reviewable diff.** No ticket in Section 2 below touches more than one logical concern; several explicitly note "do not combine with ticket X" where the temptation to batch exists.
- **Every PR must be green against the full existing Service 1 suite, not just its own new tests** — the riskiest failure mode in this entire plan is silent regression of Service 1 while building alongside it (enum extension, `farm-drawing` → `polygon-drawing` refactor, and shared `GEEProvider` helper extraction are the three places this is most likely).
- **M0's migrations merge in numeric order, each its own PR** — never squashed into one migration, so a future `alembic downgrade` has real, individually-reversible steps.
- **Feature flag, not branch-by-abstraction:** since Water Intelligence is entirely new routes/tables with no Service 1 code path change (except the three shared-helper extractions), no feature flag is needed for backend work — new routes simply don't exist until their ticket merges. Frontend is the one place a flag is worth considering (Part 6, below) if `catchment-drawing` needs to ship incrementally without a half-built nav entry visible to users.

---

# 2. ENGINEERING BACKLOG

**Ticket ID convention:** `M{milestone}-{sequence}`. **Complexity** is T-shirt sized (S/M/L) against this codebase's existing patterns, not absolute difficulty. **Time** assumes one engineer already familiar with the reused Service 1 patterns (i.e., has read the relevant existing file first — each ticket names which one).

Every ticket implicitly carries the general **Definition of Ready / Definition of Done / Review Checklist** from Section 9 — only ticket-specific additions to that template are called out below.

## M0 — Foundations `[R2: 7/7 done]`

### Ticket M0-001 ✅ DONE
**Title:** Extend shared enums for Water Intelligence
**Description:** Add every new enum value/type the v2 blueprint's schema requires: `SatelliteIndexType.ET/SURFACE_WATER_SAR/SURFACE_WATER_MNDWI`; `RiskEntityType.CATCHMENT`; `JobType.CATCHMENT_WATER_REPORT/CATCHMENT_BOUNDARY_UPLOAD`; `UserRole.PROGRAMME_OFFICER/PROGRAMME_ADMIN`; new standalone enums `DelineationMethod` (`manual`/`upload`/`auto_dem`), `CalibrationStatus` (`uncalibrated`/`partially_calibrated`/`field_calibrated`), `StressBand`, `StorageChangeBand` (5-band), `BaselineWindow` (`climatology_30yr`/`trailing_3yr`), `OrganizationType`.
**Files to modify:** `backend/app/models/enums.py`
**Files to create:** none
**Dependencies:** none — first ticket in the whole plan
**Acceptance Criteria:** every new enum uses `pg_enum()` exactly as existing enums do (values, not member names); every extended enum (`SatelliteIndexType`, `RiskEntityType`, `JobType`, `UserRole`) has its existing members untouched — a diff review should show only additions, zero modified lines on existing members.
**Tests:** a unit test asserting `pg_enum()`'s `values_callable` produces the expected lowercase value list for each new/extended enum — this is the exact class of bug (`pg_enum()` member-vs-value mismatch) the codebase already hit once; this ticket's test exists specifically to prove it can't happen again for these enums.
**Estimated complexity:** S
**Estimated time:** 2–3 hours

### Ticket M0-002 ✅ DONE
**Title:** `Organization` model + migration 0005
**Description:** Create the `Organization` model (`id`, `name`, `org_type`, `created_at`) per Blueprint v2 Part 5, and its migration.
**Files to create:** `backend/app/models/organization.py`, `backend/alembic/versions/0005_organization.py`
**Files to modify:** `backend/app/models/__init__.py` (register the new model for Alembic autogenerate-diffing, even though this migration itself is hand-written)
**Dependencies:** M0-001 (needs `OrganizationType` enum)
**Acceptance Criteria:** table created with `UUIDPrimaryKeyMixin`/`CreatedAtMixin`, matching every other model's mixin usage; migration has a working `downgrade()`, not just `upgrade()`.
**Tests:** offline DDL compilation test asserting the table and enum type compile without error (mirrors `test_schema_ddl.py`'s existing pattern for tables this environment can't test against live Postgres).
**Estimated complexity:** S
**Estimated time:** 1–2 hours

### Ticket M0-003 ✅ DONE
**Title:** `Catchment` model (MULTIPOLYGON, bounds, resolution flags) + migration 0006
**Description:** Create `Catchment` exactly per Blueprint v2 Part 5 — `GEOMETRY(MULTIPOLYGON, 4326)` (not `POLYGON`), `organization_id` (nullable FK), `delineation_method`, `pour_point` (nullable), `admin_boundary_id` (nullable FK), `resolution_flags` (JSONB, default `[]`), the two `CHECK` constraints (`chk_catchment_area`: 0.5–50,000 ha; `chk_catchment_vertex_count`: `ST_NPoints(geometry) <= 2000`), and all three indexes (GIST on geometry, btree on `organization_id`, btree on `admin_boundary_id`).
**Files to create:** `backend/app/models/catchment.py`, `backend/alembic/versions/0006_catchment.py`
**Dependencies:** M0-001, M0-002 (FK to `organization`)
**Acceptance Criteria:** `CHECK` constraints are part of the `CREATE TABLE` DDL in the migration, not added in a follow-up — this was an explicit TDR finding (constraints as an afterthought vs. day-one). A geometry typed anything other than `MULTIPOLYGON` fails review outright.
**Tests:** offline DDL compile test; **a second test inserting a fixture geometry that violates each `CHECK` constraint in turn (oversized area, >2000 vertices) and asserting Postgres rejects it** — this is the specific test the TDR called out as missing in v1 and required in v2's Part 14 ticket. (This test needs a real Postgres connection to actually exercise a `CHECK` constraint — mark it to skip cleanly in this sandbox per the existing `db_session` fixture pattern, and run for real in CI.)
**Estimated complexity:** M
**Estimated time:** 4–5 hours

### Ticket M0-004 ✅ DONE
**Title:** `WaterBalanceResult` model + migration 0007
**Description:** Create `WaterBalanceResult` per Blueprint v2 Part 5 — **no `weights_version_id`** (this was the TDR's specific schema-bug finding; do not add it back), `storage_change_band` (required, the new headline field), `closed_catchment_assumed` (boolean, default `true`), `resolution_flags` (JSONB), `calibration_status` (default `uncalibrated`).
**Files to create:** `backend/app/models/water_balance.py` (this ticket populates only `WaterBalanceResult`; `RechargeStressScore` is M0-005), `backend/alembic/versions/0007_water_balance_result.py`
**Dependencies:** M0-001, M0-003 (FK to `catchment`)
**Acceptance Criteria:** a code reviewer explicitly checks for the *absence* of `weights_version_id` on this table — call this out in the PR description so it isn't silently reintroduced by someone pattern-matching off `RiskScore`.
**Tests:** offline DDL compile test.
**Estimated complexity:** S
**Estimated time:** 2 hours

### Ticket M0-005 ✅ DONE
**Title:** `RechargeStressScore` model (with `weights_version_id`) + migration 0008
**Description:** Create `RechargeStressScore` in the same `water_balance.py` file — `baseline_window` (default `climatology_30yr`), `weights_version_id` FK to `config_weight` (correctly placed here, per the v2 fix), `cgwb_category`/`cgwb_category_as_of` (context fields).
**Files to modify:** `backend/app/models/water_balance.py`
**Files to create:** `backend/alembic/versions/0008_recharge_stress_score.py`
**Dependencies:** M0-001, M0-003, M0-004 (same file as `WaterBalanceResult`)
**Acceptance Criteria:** `weights_version_id` present and FK'd to `config_weight` — the mirror image of M0-004's check.
**Tests:** offline DDL compile test; index existence check for `idx_recharge_stress_catchment_period` (the index the TDR noted was missing in v1).
**Estimated complexity:** S
**Estimated time:** 2 hours

### Ticket M0-006 ✅ DONE
**Title:** `CgwbGroundwaterObservation` staging model + migration 0009
**Description:** Create the ingestion staging table per Blueprint v2 Part 5 — `block_code`, `block_geometry` (nullable `MULTIPOLYGON`), `category`, `assessment_period`, `source_url`, unique constraint on `(block_code, assessment_period)`.
**Files to create:** `backend/app/models/cgwb.py`, `backend/alembic/versions/0009_cgwb_observation.py`
**Dependencies:** M0-001
**Acceptance Criteria:** the uniqueness constraint is present and named (`uq_cgwb_block_period`) — this is the exact mechanism M3's ingestion job relies on to be idempotent on re-run.
**Tests:** offline DDL compile test; a test inserting a duplicate `(block_code, assessment_period)` pair and asserting rejection.
**Estimated complexity:** S
**Estimated time:** 2 hours

### Ticket M0-007 ✅ DONE `[R2 — this slot's content changed; see Changelog]`
**Title:** Extend pre-existing Postgres enum types with Water Intelligence values + migration 0010
**Description:** `user_role`, `observation_entity_type`, `satellite_index_type`, and `job_type` are all Postgres enum types created back in `0001_initial_schema.py`. M0-001 correctly extended the corresponding **Python** enum classes, but no migration ever ran `ALTER TYPE ... ADD VALUE` on the real, already-created Postgres types — a gap no offline test could catch, since `test_schema_ddl.py`'s enum-binding test only checks a SQLAlchemy model's declared type against itself. Discovered live: inserting `AppUser(role=UserRole.PROGRAMME_OFFICER)` against a real database failed with `invalid input value for enum user_role: "programme_officer"`. Fixed with eight `ALTER TYPE ... ADD VALUE IF NOT EXISTS` statements, nothing else.
**Files to create:** `backend/alembic/versions/0010_extend_existing_enums.py`
**Files to modify:** `backend/tests/test_enums.py` (new live-DB regression test querying `pg_type`/`pg_enum` directly, so this class of defect — Python enum extended, real Postgres type forgotten — cannot silently recur)
**Dependencies:** M0-001 (the Python enum values this migration adds must already exist), M0-003/004/005 implicitly (their live verification is what surfaced the gap)
**Acceptance Criteria:** all four Postgres types contain their full expected value sets, confirmed by direct query against a real database, not just by re-reading the migration source. `downgrade()` raises `NotImplementedError` rather than silently no-opping — Postgres has no `ALTER TYPE ... DROP VALUE`, and pretending to reverse it would be dishonest about what actually happened.
**Tests:** `test_enums.py::test_extended_enum_postgres_types_actually_contain_new_values` (live-DB, skips cleanly without one) — new, this ticket.
**Estimated complexity:** S
**Estimated time:** ~1 hour (fix) + verification time already spent finding it

**M0 exit gate — met:** all 7 tickets merged, full existing Service 1 suite green, and — beyond what Rev. 1 required — **the full chain verified live against real PostgreSQL 16.4 + PostGIS 3.4** (`docs/Water_Intelligence_M0_Live_Verification.md`): fresh bootstrap, full downgrade-to-base, clean re-upgrade, 208 passed / 0 skipped / 0 failed. M0 is closed.

---

## M1 — GEE Hydrology Provider `[R2: 0/7 done, +1 ticket — see Changelog]`

### Ticket M1-001 `[R2 — relocated here from old M0-007; not yet started]`
**Title:** `HydrologyDataProvider` ABC (contract only, no implementation)
**Description:** Define the abstract interface per Blueprint v2 D1 — `get_et_series`, `get_surface_water_extent_series` (parameterized by method: SAR/MNDWI/combined), returning the same style of frozen dataclasses `SatelliteDataProvider` already uses. Document, in each method's docstring, the `scale` value D9 specifies for that index (10 m surface water, 500 m ET) even though no implementation calls Earth Engine yet.
**Files to create:** `backend/app/services/hydrology/provider.py` (note: `backend/app/services/hydrology/__init__.py`, `models.py`, and `engine.py` already exist as of M2-001/M2-002a — this ticket adds `provider.py` to the same package, it does not create the package)
**Dependencies:** none beyond M0-001 (uses the new enums for method signatures)
**Acceptance Criteria:** zero `ee.*` imports anywhere in this file — it's a pure interface, exactly mirroring `app/services/satellite/provider.py`'s existing discipline. An engineer reading this file alone (without `gee_provider.py` open) should understand exactly what data Water Intelligence needs, in domain vocabulary.
**Tests:** a contract test asserting every abstract method raises `NotImplementedError`/`TypeError` when the ABC is instantiated directly (mirrors how `SatelliteDataProvider`'s contract is exercised).
**Estimated complexity:** S
**Estimated time:** 2–3 hours

### Ticket M1-002 `[R2: was M1-001]`
**Title:** Extract shared GEE helpers for reuse without circular imports
**Description:** `_monthly_periods()` and the cloud-masking constant currently live as module-private helpers in `app/services/satellite/gee_provider.py`. Before `gee_hydrology_provider.py` can share them (per D1's explicit "shares the existing module's internal helpers" requirement), decide and implement the reuse mechanism — most likely promoting them to a small shared module (e.g. `app/services/satellite/_gee_common.py`) both `gee_provider.py` and the new `gee_hydrology_provider.py` import from, rather than either duplicating them or creating an import dependency from `satellite/` on `hydrology/` (wrong direction — `hydrology/` is the newer, dependent module).
**Files to modify:** `backend/app/services/satellite/gee_provider.py` (extract, re-export for backward compatibility so nothing else breaks)
**Files to create:** `backend/app/services/satellite/_gee_common.py`
**Dependencies:** M1-001 `[R2: was M0-007, same ticket, new number]`
**Acceptance Criteria:** every existing Service 1 test that touches `gee_provider.py` still passes unmodified — this is a pure refactor, zero behavior change, and the PR description should say so explicitly so a reviewer knows not to look for new functionality.
**Tests:** existing `test_gee_provider.py` suite, unchanged, must stay green — that **is** the test for this ticket.
**Estimated complexity:** S
**Estimated time:** 2–3 hours

### Ticket M1-003 `[R2: was M1-002]`
**Title:** `GEEHydrologyProvider.get_et_series()` — MODIS MOD16A2, scale=500m
**Description:** Implement the ET series method per D9's explicit scale policy. Follow `gee_provider.py`'s exact discipline: one `getInfo()` per series (not per month), `asyncio.to_thread()` wrapping at the call site (not inside this method — matches the existing convention where wrapping happens at the orchestrator boundary), dataclasses only crossing back out.
**Files to create:** `backend/app/services/hydrology/gee_hydrology_provider.py`
**Dependencies:** M1-002, M1-001 `[R2: was M1-001, M0-007]`
**Acceptance Criteria:** `scale=500` is a named constant at module level (mirroring how `_CLOUD_PROBABILITY_THRESHOLD` is a named constant in `gee_provider.py`), not a magic number inline — a future reviewer changing the scale policy should be able to find and change one line.
**Tests:** `test_gee_hydrology_provider.py::test_get_et_series` against the real GEE test project (mirrors `test_gee_provider.py`'s existing live-GEE test pattern) — **this test requires real GEE credentials and will skip cleanly, not fail, in this sandbox**, exactly as the existing GEE tests already do.
**Estimated complexity:** M
**Estimated time:** 4–5 hours

### Ticket M1-004 `[R2: was M1-003]`
**Title:** `GEEHydrologyProvider.get_surface_water_extent_series()` — Sentinel-1 SAR, scale=10m
**Description:** Implement SAR-based water extent per D9 — fixed VV backscatter threshold (documented as a named limitation per Blueprint v2 Part 4's terrain caveat, not silently presented as precise), `scale=10`.
**Files to modify:** `backend/app/services/hydrology/gee_hydrology_provider.py`
**Dependencies:** M1-003 `[R2: was M1-002]` (same file, sequenced to avoid merge conflicts rather than a real logical dependency)
**Acceptance Criteria:** the threshold constant is named and comment-linked to Blueprint v2 Part 4's terrain-limitation note, not a bare number.
**Tests:** `test_gee_hydrology_provider.py::test_get_surface_water_extent_series_sar`, real-GEE, same skip-cleanly-in-sandbox behavior.
**Estimated complexity:** M
**Estimated time:** 4–5 hours

### Ticket M1-005 `[R2: was M1-004]`
**Title:** `GEEHydrologyProvider` MNDWI cross-check confirmation
**Description:** Add the Sentinel-2 MNDWI secondary confirmation layer to the same surface-water method, per Part 4's "SAR primary, MNDWI secondary confirmation" methodology.
**Files to modify:** `backend/app/services/hydrology/gee_hydrology_provider.py`
**Dependencies:** M1-004 `[R2: was M1-003]`
**Acceptance Criteria:** cloud-masking reuses the shared helper from M1-002 `[R2: was M1-001]`, not a re-implementation.
**Tests:** `test_gee_hydrology_provider.py::test_mndwi_confirmation_agrees_with_sar` — a real-GEE test asserting the two methods agree directionally on a known water body, with the disagreement rate logged (not asserted to be zero — some disagreement is expected and informative, not a bug).
**Estimated complexity:** M
**Estimated time:** 3–4 hours

### Ticket M1-006 `[R2: was M1-005]`
**Title:** `maxPixels`/scale enforcement at the provider call boundary
**Description:** Per D9, defense-in-depth alongside M0-003's database `CHECK` constraints: the provider layer itself sets an explicit `maxPixels` value (sized against the 500 km² MVP ceiling) and **never** sets `bestEffort: true`. If a caller somehow reaches this code with an out-of-bounds geometry (shouldn't happen given M0-003, but this is the belt to that suspenders), the provider raises a clear, typed exception rather than letting Earth Engine silently degrade precision.
**Files to modify:** `backend/app/services/hydrology/gee_hydrology_provider.py`
**Dependencies:** M1-003, M1-004, M1-005 `[R2: was M1-002/003/004]`
**Acceptance Criteria:** grep the whole new module for `bestEffort` — it should not appear anywhere.
**Tests:** a unit test (no real GEE needed) asserting the exception path triggers on a mock oversized geometry.
**Estimated complexity:** S
**Estimated time:** 2 hours

### Ticket M1-007 `[R2: was M1-006]`
**Title:** Staging GEE compute-cost measurement (M1's exit criterion per Blueprint v2)
**Description:** Not a code ticket in the usual sense — run the full M1 provider against 3–5 representative catchment sizes in the staging environment, record actual GEE compute-unit/latency consumption per report, and **update Blueprint v2's D9 section** (replacing the "~50% more calls than Service 1" estimate with the measured figure), per the blueprint's own explicit commitment to do so.
**Files to modify:** `docs/Water_Intelligence_Service_Blueprint.md` (D9 section, with the measured numbers)
**Dependencies:** M1-003, M1-004, M1-005, M1-006 `[R2: was M1-002/003/004/005]`, and a staging environment with real GEE access
**Acceptance Criteria:** the blueprint document itself is updated with real numbers — this ticket isn't done until the *document* changes, not just until a number exists in a Slack message.
**Tests:** none in the code sense — the "test" is the measurement itself.
**Estimated complexity:** S (execution), but **blocked on environment access**, not code complexity
**Estimated time:** 1 day (mostly waiting on GEE calls to run across several catchment sizes)

**M1 exit gate:** all provider methods implemented and passing against real GEE in CI/staging; D9's cost estimate replaced with a measured figure. **New dependency, discovered post-Rev.-1 `[R2]`:** M4-006 and M5-001 (not M1 itself — the provider stays zero-DB-I/O) need M0-007's enum fix to persist `Job`/`SatelliteObservation` rows using M1's new enum values; already satisfied, since M0-007 is done.

---

## M2 — Water Balance Engine `[R2: 2/6 done, M2-002 split into M2-002a/M2-002b — see Changelog]`

*(Runs in parallel with M1 — this entire milestone depends only on M0, never on M1, because every test here uses synthetic bundles.)*

### Ticket M2-001 ✅ DONE
**Title:** `WaterBalanceBundle`/`WaterBalanceConfig`/`WaterBalanceEngineResult` dataclasses
**Description:** Define the input/output shapes for the engine, mirroring `app/services/risk/models.py`'s exact structure (frozen dataclasses, `MonthlyValue`-style time series types reused where the shape matches).
**Files to create:** `backend/app/services/hydrology/models.py`
**Dependencies:** M0-001 (enums)
**Acceptance Criteria:** `WaterBalanceBundle` has no dependency on `ee.*` or any provider type — it's pure data, constructible entirely from primitives in a test.
**Tests:** none beyond type-checking — this ticket is data-shape only; behavior is tested in M2-002b.
**Estimated complexity:** S
**Estimated time:** 2 hours
**As-built note `[R2]`:** matches this ticket's spec exactly — `MonthlyValue` reused from `risk/models.py`, not redefined, per the ticket's own instruction. `WaterBalanceBundle` deliberately excludes a `runoff_monthly` field (runoff is derived, not fetched — documented in the dataclass docstring as an M2-002b design decision, not an omission).

### Ticket M2-002a ✅ DONE `[R2 — split from the original M2-002; see Changelog]`
**Title:** `WaterBalanceEngine` skeleton — class, `compute()` signature, validation, stub
**Description:** The structural half of the original M2-002: the `WaterBalanceEngine` class itself, `compute(bundle, config)`'s public signature, full input validation (bundle/config well-formedness), module-level logging on every call, and a documented `NotImplementedError` in place of the arithmetic. Zero I/O (D4) — no repository, session, or provider ever injected; that wiring belongs to a future orchestrator (M5-001), exactly how `report_generator.py` already wires `RiskEngine` today.
**Files to create:** `backend/app/services/hydrology/engine.py`
**Dependencies:** M2-001
**Acceptance Criteria:** a well-formed call reaches (and only reaches) the documented `NotImplementedError` — never a silent wrong answer, never an unrelated crash. Malformed input is rejected with a specific `ValueError`/`TypeError` before validation ever reaches the stub.
**Tests:** `test_water_balance_engine.py` (13 tests: construction, valid-input-reaches-the-stub, bundle validation, config validation) — built and passing.
**Estimated complexity:** S (was scoped inside the original M2-002's M estimate; this half alone is smaller)
**Estimated time:** ~3 hours (actual)

### Ticket M2-002b `[R2 — split from the original M2-002; NOT STARTED, the immediate next ticket]`
**Title:** `WaterBalanceEngine.compute()` — core P−ET−Q=ΔS arithmetic
**Description:** Replace M2-002a's `NotImplementedError` with the real, deterministic arithmetic per D4 — zero I/O, `MODEL_VERSION`-stamped. **The docstring must state, explicitly, both the closed-catchment assumption (no lateral flow term) and the gross-`Q` assumption (no recharge-structure netting)** — a specific, named TDR requirement, not a nice-to-have comment. `WaterBalanceEngineResult`'s fields (already defined, M2-001) must all be populated with real values, not left `None`.
**Files to modify:** `backend/app/services/hydrology/engine.py`
**Dependencies:** M2-002a
**Acceptance Criteria:** a code reviewer can find both stated assumptions in the docstring without reading Blueprint v2 — the document and the code must say the same thing. The 13 existing skeleton tests in `test_water_balance_engine.py` still pass unmodified (their assertions were about validation and the stub, not the arithmetic) once the `NotImplementedError` cases in them are updated to assert real results instead.
**Tests:** extend `test_water_balance_engine.py` — synthetic bundles, zero GEE, mirrors `test_risk_engine.py`'s existing philosophy exactly. Cases: normal-data path, missing-month gaps, all-null edge case (should not crash, should return a documented low-confidence result).
**Estimated complexity:** M
**Estimated time:** 4–5 hours (reduced from the original M2-002's 5–6h estimate, since M2-002a already absorbed the scaffolding work)

### Ticket M2-003
**Title:** `storage_change_band` derivation (5-band qualitative headline)
**Description:** Implement the climatology-relative banding logic per D5's v2 revision — the mm residual is computed (M2-002b) but the *headline* output is this qualitative band. Band thresholds should be named constants, versioned the same way `RiskEngine`'s `_BAND_THRESHOLDS` are.
**Files to modify:** `backend/app/services/hydrology/engine.py`
**Dependencies:** M2-002b `[R2: was M2-002]`
**Acceptance Criteria:** the band derivation function is separately unit-testable from the mm computation — a reviewer should be able to test "does -80mm anomaly map to 'much below normal'" without re-deriving the whole water balance.
**Tests:** `test_water_balance_engine.py::test_storage_change_band_thresholds` — table-driven test over the band boundaries.
**Estimated complexity:** S
**Estimated time:** 2–3 hours

### Ticket M2-004
**Title:** `resolution_flags` derivation (sub-pixel rainfall/ET, terrain)
**Description:** Given a catchment's `area_ha` (and, for the terrain flag, a DEM-derived relief metric — this ticket accepts relief as a pre-computed input parameter rather than computing it itself, keeping the engine free of any new GEE dependency), derive the `resolution_flags` list per Part 4's `[v2]` additions: `rainfall_sub_pixel` below ~3,000 ha, `et_sub_pixel` below ~25 ha, `high_relief_terrain` above a stated relief threshold.
**Files to modify:** `backend/app/services/hydrology/engine.py` (or a small sibling module if the function count grows — reviewer's call at PR time)
**Dependencies:** M2-002a `[R2: was M2-002 — corrected to the skeleton half specifically, since this derivation needs the class to exist but never needed the arithmetic]`
**Acceptance Criteria:** flags are additive and independently triggerable — a tiny, flat catchment should get both `rainfall_sub_pixel` and `et_sub_pixel` but not `high_relief_terrain`, and the test suite proves each in isolation.
**Tests:** `test_water_balance_engine.py::test_resolution_flags` — boundary-value tests at exactly 3,000 ha and 25 ha.
**Estimated complexity:** S
**Estimated time:** 2–3 hours

### Ticket M2-005
**Title:** Golden-dataset scientific regression test
**Description:** The TDR's specific testing-strategy requirement: construct a synthetic `WaterBalanceBundle` from the inputs of the Western Maharashtra Curve Number validation study already cited in Blueprint v2's Sources, run it through the real engine, and assert computed runoff falls within that study's published range. This is the one test in the whole plan whose job is to catch the *science* being wrong, not just the code.
**Files to create:** `backend/tests/services/test_water_balance_golden_dataset.py`
**Dependencies:** M2-002b, M2-003 `[R2: was M2-002, M2-003]`
**Acceptance Criteria:** the test's fixture data cites the specific paper and figure/table it was derived from, in a code comment — a future engineer must be able to trace the expected values back to the literature, not trust a magic number.
**Tests:** this ticket *is* a test.
**Estimated complexity:** M
**Estimated time:** 4–5 hours (mostly literature-to-fixture translation, not engine code)

**M2 exit gate:** engine complete, golden-dataset test passing, zero GEE dependency anywhere in this milestone's code. **2/6 done (M2-001, M2-002a); M2-002b is the next actionable ticket in the entire plan.**

---

## M3 — Recharge-Stress Scoring + CGWB Ingestion

*(Also parallel to M1 — depends only on M0. `recharge_stress.py`'s scoring logic needs a bundle of time series, which for testing purposes is synthetic; CGWB ingestion is fully independent of GEE entirely.)*

### Ticket M3-001
**Title:** `recharge_stress.py` — percentile-based scoring vs. 30-year climatology
**Description:** Port `RiskEngine`'s `_percentile_rank()` pattern, but **benchmarked against the 30-year CHIRPS climatology baseline, not a trailing 3-year window** — this is the specific v2 fix (Part 4/D6's baseline revision) and the whole point of this ticket. Combine rainfall anomaly + VCI + surface-water trend into `stress_score`/`stress_band`.
**Files to create:** `backend/app/services/hydrology/recharge_stress.py`
**Dependencies:** M2-001 (reuses the same bundle/dataclass shapes)
**Acceptance Criteria:** the function signature makes the baseline window an explicit, required parameter — not an implicit default that could silently regress to the 3-year window a future refactor might reach for out of habit.
**Tests:** `test_recharge_stress.py` — synthetic bundles, includes a specific regression case: a catchment whose trailing 3 years are all drought years should score differently under the 30-year baseline than it would under the old 3-year one (this test is the direct proof the TDR's finding is actually fixed, not just documented as fixed).
**Estimated complexity:** M
**Estimated time:** 4–5 hours

### Ticket M3-002
**Title:** CGWB source verification (research spike, not implementation)
**Description:** **Before writing the ingestion job, confirm the exact, current, programmatically-accessible CGWB/India-WRIS data source** — the blueprint's research confirmed CGWB data is publicly accessible via India-WRIS/data.gov.in in principle, but did not pin an exact API endpoint, file format, or download cadence mechanism, because that wasn't the blueprint's job. This ticket is a time-boxed spike to confirm: (a) is there a stable API, or is it a periodic bulk CSV/shapefile download; (b) what does a real response actually look like; (c) does it require an API key/registration.
**Files to create:** a short findings note, either inline as a code comment header in M3-003's ingestion module or as a `docs/` addendum — reviewer's call
**Dependencies:** none (pure research)
**Acceptance Criteria:** M3-003 cannot start until this ticket produces a concrete, verified data-access mechanism — **do not let M3-003 begin against an assumed/guessed API shape**, which is exactly the kind of thing that silently breaks in production against a real government data source.
**Tests:** N/A — this is a research ticket.
**Estimated complexity:** S, but genuinely uncertain time — **flagged as a risk in Section 10**
**Estimated time:** 0.5–1 day

### Ticket M3-003
**Title:** `cgwb_ingest.py` — periodic batch ingestion job
**Description:** Implement the ingestion job per whatever M3-002 confirms is the real data source, writing into `cgwb_groundwater_observation` (M0-006), relying on the `(block_code, assessment_period)` uniqueness constraint for idempotent re-runs.
**Files to create:** `backend/app/services/ingestion/cgwb_ingest.py`, `backend/app/services/ingestion/__init__.py`
**Dependencies:** M0-006, M3-002
**Acceptance Criteria:** re-running the job against the same source data is a no-op (no duplicate rows, no error) — this is the concrete behavior the uniqueness constraint exists to guarantee, and this ticket's test proves it.
**Tests:** an ingestion test against a fixture/recorded CGWB response (not a live call in CI — record a fixture during M3-002's spike, replay it in tests) asserting correct row creation and idempotent re-run.
**Estimated complexity:** M
**Estimated time:** 5–6 hours

### Ticket M3-004
**Title:** Ingestion trigger — authenticated internal endpoint + external cron
**Description:** Since no scheduler exists in this codebase yet (verified — no APScheduler/Celery-beat dependency), expose a minimal authenticated internal endpoint (e.g., `POST /admin/ingest/cgwb`, admin-role-gated) that runs `cgwb_ingest.py`, triggered externally by OS/CI-scheduled cron matching CGWB's quarterly publication cadence — no new in-process infrastructure, consistent with D7/D9's established "don't add infrastructure MVP doesn't need" pattern.
**Files to modify:** `backend/app/api/` (a small new admin router, or an addition to an existing one if one already exists — verify at implementation time)
**Dependencies:** M3-003
**Acceptance Criteria:** the endpoint is unreachable by any role except an admin-equivalent; calling it twice in a row doesn't duplicate data (relies on M3-003's idempotency).
**Tests:** an API-level test asserting non-admin roles get 403, and asserting a double-call doesn't duplicate rows.
**Estimated complexity:** S
**Estimated time:** 3 hours

**M3 exit gate:** stress scoring passes its regression test against the corrected baseline; CGWB ingestion is idempotent and triggerable; **CGWB source access is verified against a real endpoint, not assumed.**

---

## M4 — API + Jobs + Boundary Upload

*(This is where M1, M2, and M3's independent work streams converge for the first time — nothing before this milestone required them to know about each other.)*

### Ticket M4-001
**Title:** `schemas/catchment.py` — request/response Pydantic models
**Description:** `CatchmentCreateRequest` (manual polygon), `CatchmentUploadRequest` (file upload metadata), `CatchmentResponse`, mirroring `schemas/farm.py`'s validation-at-the-boundary discipline (geometry validity, closedness, coordinate range checked here, before a request ever reaches the router).
**Files to create:** `backend/app/schemas/catchment.py`
**Dependencies:** M0-003
**Acceptance Criteria:** area/vertex bounds are checked in both the schema layer (fast-fail, good error message) *and* the database `CHECK` constraint (M0-003) — the schema check is a UX improvement, not a substitute for the DB-level guarantee, and the PR description should say why both exist rather than looking like redundant validation.
**Tests:** `tests/schemas/test_catchment_schema.py` — mirrors `test_farm_schema.py`'s structure.
**Estimated complexity:** M
**Estimated time:** 4 hours

### Ticket M4-002
**Title:** `boundary_parser.py` — GeoJSON/KML/Shapefile parsing
**Description:** Parse an uploaded boundary file into the same validated geometry shape manual drawing produces. GeoJSON uses the existing `shapely` dependency directly. **KML and zipped Shapefile have no existing dependency — this ticket adds `pyshp` (pure Python, no GDAL) for Shapefile and uses stdlib `xml.etree.ElementTree` for KML** (a deliberate DevOps-informed choice over `fiona`/`geopandas` to avoid a GDAL binary dependency in the container image).
**Files to create:** `backend/app/services/hydrology/boundary_parser.py`
**Files to modify:** `backend/requirements.txt` (add `pyshp`)
**Dependencies:** M4-001
**Acceptance Criteria:** all three formats converge on the identical internal representation and pass through the identical validation function M4-003's manual-draw path also uses — one validation boundary, proven by a test that feeds equivalent geometry through both entry points and asserts identical results.
**Tests:** `test_boundary_parser.py` — valid fixtures for all three formats, plus malformed fixtures per format (corrupt zip, invalid KML XML, self-intersecting GeoJSON polygon) asserting clean rejection with a useful error, never a raw stack trace to the client.
**Estimated complexity:** L (three file formats, several failure modes each)
**Estimated time:** 1–1.5 days

### Ticket M4-003
**Title:** `POST /catchments` — manual polygon creation
**Description:** Mirrors `POST /farms`'s exact pattern (`api/farms.py`): role-gated (`PROGRAMME_OFFICER`/`PROGRAMME_ADMIN`, not the bank roles), server-side `ST_Area` recompute on a `Geography` cast (never trusts client-supplied area), rejects out-of-bounds geometry with a 422.
**Files to create:** `backend/app/api/catchments.py`
**Dependencies:** M4-001, M0-003
**Acceptance Criteria:** identical defensive posture to `farms.py` — the officer/creator identity always comes from the JWT, never the request body; a fat-fingered huge polygon gets a 422 with a clear message, never a 500 from a downstream GEE call that should never have been reached.
**Tests:** `test_catchments.py` — happy path, oversized-area rejection, excessive-vertex rejection, wrong-role rejection (mirrors `test_farms.py`'s structure directly).
**Estimated complexity:** M
**Estimated time:** 5–6 hours

### Ticket M4-004
**Title:** `POST /catchments/upload`
**Description:** Accepts a multipart file upload, runs it through M4-002's parser, then the **identical** persistence path M4-003 uses (same function, different entry point — not a parallel implementation).
**Files to modify:** `backend/app/api/catchments.py`
**Dependencies:** M4-002, M4-003
**Acceptance Criteria:** code-review check: the persistence call in this endpoint should be a direct call to the same internal function `POST /catchments` calls, not a copy-pasted variant — this is the concrete proof of D2's "one validation boundary, two ways in" design intent.
**Tests:** `test_catchments.py::test_upload_*` — one test per supported format, one malformed-file-per-format rejection test.
**Estimated complexity:** M
**Estimated time:** 4 hours

### Ticket M4-005
**Title:** `GET /catchments`, `GET /catchments/{id}`
**Description:** List and detail endpoints, owner-or-branch-scoped exactly like `GET /farms`/`GET /farms/{id}` (including the IDOR fix already documented in `docs/DECISIONS.md` for the equivalent Service 1 endpoint — this ticket must not reintroduce that class of bug).
**Files to modify:** `backend/app/api/catchments.py`
**Dependencies:** M4-003
**Acceptance Criteria:** an authorization test explicitly proves a user cannot fetch another org's/branch's catchment by ID — this exact bug class was found and fixed once already in Service 1; this ticket's tests exist specifically so it isn't rediscovered here.
**Tests:** `test_catchments.py::test_get_catchment_owner_scoping`, `test_get_catchment_idor_rejected`.
**Estimated complexity:** S
**Estimated time:** 3 hours

### Ticket M4-006
**Title:** `POST /catchments/{id}/water-reports` — job creation
**Description:** Mirrors `POST /farms/{id}/reports` — reuses the existing `Job` model and advisory-lock pattern for the report-trigger race condition (already solved and documented for Service 1; reuse, don't re-solve).
**Files to modify:** `backend/app/api/catchments.py`
**Dependencies:** M4-005, M1 (provider), M2 (engine), M3 (stress scoring) — **this is the first ticket that actually needs all three parallel milestones merged**
**Acceptance Criteria:** two concurrent requests for the same catchment/period produce one job, not two — the exact race condition Service 1's advisory lock already prevents, proven the same way Service 1's equivalent test proves it.
**Tests:** `test_water_reports.py::test_concurrent_trigger_race` — real two-request concurrency test, mirroring whatever test proves this for Service 1 today.
**Estimated complexity:** M
**Estimated time:** 5 hours

### Ticket M4-007
**Title:** `GET .../water-reports/{id}`, `GET .../water-balance`, `GET .../recharge-stress`
**Description:** Read endpoints over the persisted results.
**Files to modify:** `backend/app/api/catchments.py`
**Dependencies:** M4-006
**Acceptance Criteria:** response shape correctly separates the headline `storage_change_band` from the technical-view mm values (D5's presentation decision) — this should be visible in the response schema itself, not just in how the frontend chooses to render it.
**Tests:** `test_water_reports.py` — response shape assertions.
**Estimated complexity:** S
**Estimated time:** 3 hours

**M4 exit gate:** full API surface live, all real-stack integration paths exercised, `GET /jobs/{id}` (reused unchanged from Service 1) correctly reports status for the new `JobType` values.

---

## M5 — Reporting Pipeline

### Ticket M5-001
**Title:** `water_report_generator.py` — orchestrator with verified incremental persistence
**Description:** Mirrors `report_generator.py`'s shape (farm → bundle → engine → persisted result → job completion), run as a `BackgroundTask` per D7/D9. **Explicitly re-verify, not just inherit, the incremental-persistence-per-series property** — Water Intelligence fetches more series per report (rainfall, ET, SAR, MNDWI) than Service 1 does, so a mid-pipeline failure has more surface area, and the TDR specifically flagged that v1 asserted this property without re-checking it held under the added series count.
**Files to create:** `backend/app/services/reporting/water_report_generator.py`
**Dependencies:** M4-006 (needs the job/trigger path to exist), M1, M2, M3
**Acceptance Criteria:** each fetched series is persisted to `satellite_observation` (extended cache table) immediately after fetch, not batched at the end — a code reviewer should be able to point at the exact line after each `await` where persistence happens.
**Tests:** see M5-005 (the resilience test is the real proof of this ticket's core requirement).
**Estimated complexity:** L
**Estimated time:** 1–1.5 days

### Ticket M5-002
**Title:** `water_methodology_text.py` — the ✓/⚠ language, verbatim
**Description:** Render Blueprint v2 Part 4's methodology language into report prose, including every `[v2]` addition (closed-catchment assumption, terrain caveat, sub-pixel resolution flags, structure/runoff interaction note) — not just the v1 baseline language.
**Files to create:** `backend/app/services/reporting/water_methodology_text.py`
**Dependencies:** M2 (needs the engine's output shape, including `resolution_flags` and `closed_catchment_assumed`)
**Acceptance Criteria:** every `[v2]`-tagged limitation from the blueprint has a corresponding, findable string in this module — a reviewer should be able to checklist Blueprint v2 Part 10's numbered limitations against this file's test fixtures one by one.
**Tests:** `test_water_methodology_text.py` — twin test, pinned exactly as `test_methodology_text.py` already pins Service 1's report language; any wording drift fails CI, forcing a conscious decision to update the pinned text rather than silent drift.
**Estimated complexity:** M
**Estimated time:** 5–6 hours

### Ticket M5-003
**Title:** PDF export wiring
**Description:** Reuse `pdf_renderer.py` directly — no new rendering logic, just a new payload shape being fed into the existing renderer, per Blueprint v2's "reuse the reporting pipeline shape" decision.
**Files to modify:** `backend/app/services/reporting/pdf_renderer.py` (extend, don't fork — add a water-report payload variant alongside the existing farm-report one)
**Dependencies:** M5-001, M5-002
**Acceptance Criteria:** the farm-report PDF path is completely unaffected — a regression test on the existing PDF output is part of this PR's CI run.
**Tests:** `test_water_report_pdf.py`, twin-tested like `test_report_pdf.py`; existing `test_report_pdf.py` must stay green, unmodified.
**Estimated complexity:** M
**Estimated time:** 5 hours

### Ticket M5-004
**Title:** Dashboard JSON payload contract
**Description:** Define the exact response shape the frontend dashboard (M6) will consume — band-first headline, technical view nested separately, `resolution_flags` and `calibration_status` surfaced as first-class fields, not buried in a generic metadata blob.
**Files to modify:** `backend/app/schemas/water_report.py`
**Dependencies:** M5-001
**Acceptance Criteria:** this schema is what `openapi-typescript` (M6-007) generates frontend types from — get this right once, here, rather than discovering shape problems during frontend integration.
**Tests:** schema-level test asserting the response serializes with headline/technical-view separation intact.
**Estimated complexity:** S
**Estimated time:** 3 hours

### Ticket M5-005
**Title:** Forced mid-pipeline-failure resilience test
**Description:** The concrete proof for M5-001's core requirement — simulate the ET call succeeding and the SAR call failing mid-report, and assert the ET observation already persisted survives the failure and isn't re-fetched on retry.
**Files to create:** `backend/tests/services/test_water_report_generator_resilience.py`
**Dependencies:** M5-001
**Acceptance Criteria:** this test must actually fail if M5-001's incremental-persistence claim is false — i.e., write the test first against a deliberately-broken "batch everything at the end" implementation to confirm it catches the bug, then confirm it passes against the real implementation. (This "test the test" step is cheap insurance and worth the extra half hour.)
**Tests:** this ticket is a test.
**Estimated complexity:** M
**Estimated time:** 4 hours

**M5 exit gate:** full report pipeline live end-to-end (still backend-only — no frontend needed to verify this milestone, exactly as Service 1's own M1/M2 split allowed).

---

## M6 — Frontend

### Ticket M6-001
**Title:** Generalize `farm-drawing` into `polygon-drawing`
**Description:** Extract the reusable MapLibre + Terra Draw polygon-drawing primitive from `features/farm-drawing/` into `features/polygon-drawing/`, with `farm-drawing` becoming a thin wrapper supplying farm-specific chrome (labels, validation copy) around it.
**Files to create:** `frontend/src/features/polygon-drawing/*`
**Files to modify:** `frontend/src/features/farm-drawing/*` (reduced to a thin wrapper)
**Dependencies:** none — **can start Day 1, in parallel with M0**, since this is a pure frontend refactor with no backend dependency
**Acceptance Criteria:** every existing farm-drawing Vitest test and the existing real-stack farm-creation-flow integration test **must still pass, unmodified in assertions** (implementation details may change, but observable behavior must not) — this is the single highest-regression-risk ticket in the whole plan for exactly the reason the TDR would flag: refactoring a component underneath a shipped, working feature.
**Tests:** existing farm-drawing test suite (must stay green), plus new `polygon-drawing` unit tests exercising the primitive in isolation from any farm-specific chrome.
**Estimated complexity:** L
**Estimated time:** 1–1.5 days

### Ticket M6-002
**Title:** Verify `farm-drawing` regression, formally
**Description:** A dedicated verification pass — run the full existing Service 1 frontend suite plus a manual smoke test of the real farm-creation flow in a browser, specifically because M6-001 touches shipped, working code. This is deliberately its own ticket (not folded into M6-001) so it gets independent review attention rather than being assumed clean because the refactor "should" be behavior-preserving.
**Files to modify:** none (verification only)
**Dependencies:** M6-001
**Acceptance Criteria:** a named person (not the M6-001 author) signs off having exercised the real farm-drawing flow in a running dev environment, not just read the diff.
**Tests:** N/A — this ticket's output is a verification record, not new code.
**Estimated complexity:** S
**Estimated time:** 2–3 hours

### Ticket M6-003
**Title:** `catchment-drawing` — manual draw path
**Description:** Thin wrapper around `polygon-drawing` supplying catchment-specific chrome, area bounds messaging (0.5–50,000 ha, materially different range from farm's), and the vertex-count warning as the user draws (client-side pre-check, server is still authoritative).
**Files to create:** `frontend/src/features/catchment-drawing/*`
**Dependencies:** M6-001; can develop against a mocked API contract before M4 lands, per the sprint plan
**Acceptance Criteria:** drawing a polygon exceeding either bound shows an inline warning **before** submission, not just a server error after.
**Tests:** Vitest unit tests against the mocked contract.
**Estimated complexity:** M
**Estimated time:** 5–6 hours

### Ticket M6-004
**Title:** `catchment-drawing` — upload path
**Description:** File-input UI for GeoJSON/KML/zipped-Shapefile, client-side file-type/size pre-check, server confirms via M4-004.
**Files to modify:** `frontend/src/features/catchment-drawing/*`
**Dependencies:** M6-003, M4-004 (real endpoint, once available — can stub earlier)
**Acceptance Criteria:** both entry points (draw, upload) visibly converge on the same review/confirm step before final submission — the UI should make D2's "one validation boundary, two ways in" visible to the user, not just true in the backend.
**Tests:** Vitest unit tests covering valid and invalid file selection.
**Estimated complexity:** M
**Estimated time:** 5–6 hours

### Ticket M6-005
**Title:** `water-intelligence` dashboard — band-first headline
**Description:** Dashboard view consuming M5-004's payload shape — the qualitative `storage_change_band` prominent, mm values and confidence interval in a clearly secondary "technical view" (collapsed/tabbed, not deleted), charts via `recharts` (matching Service 1's existing chart library choice), map via MapLibre.
**Files to create:** `frontend/src/features/water-intelligence/*`
**Dependencies:** M5-004 (contract), M6-007's generated types (can start against a hand-written interim type, reconciled once M6-007 lands)
**Acceptance Criteria:** the primary view genuinely cannot be mistaken for showing the mm figure as the headline — this is a design-intent requirement (D5), not just a data-plumbing one, and should be checked visually, not just by asserting the right field is bound.
**Tests:** Vitest unit tests; a visual/manual check against D5's intent.
**Estimated complexity:** L
**Estimated time:** 1–1.5 days

### Ticket M6-006
**Title:** PDF download wiring
**Description:** Wire the dashboard's "download report" action to M5-003's PDF endpoint, matching Service 1's existing download UX pattern.
**Files to modify:** `frontend/src/features/water-intelligence/*`
**Dependencies:** M6-005, M5-003
**Acceptance Criteria:** matches existing farm-report download UX exactly — no new interaction pattern invented for this one feature.
**Tests:** Vitest test asserting the download action calls the correct endpoint with the correct report ID.
**Estimated complexity:** S
**Estimated time:** 2 hours

### Ticket M6-007
**Title:** Contract regeneration + real-stack integration test (both paths)
**Description:** Regenerate `openapi-typescript` types against the final M4/M5 API surface, commit them per the existing convention, then write **one** real-stack integration test exercising the full catchment-creation-to-report flow **twice** — once via manual drawing, once via upload — both converging on the same downstream assertions, with the GL map as the only mocked seam (mirrors the existing farm-creation-flow integration test's exact mocking boundary).
**Files to modify:** generated API client types (committed, per existing convention)
**Files to create:** `frontend/` integration test file for the catchment flow
**Dependencies:** everything else in M4, M5, M6 — **this is the final ticket in the plan**
**Acceptance Criteria:** both the draw-path and upload-path integration tests pass; the generated types compile with zero manual `any` escape hatches introduced to paper over a contract mismatch (a mismatch here means M4/M5's actual response shape drifted from M5-004's contract ticket, and should be fixed at the source, not typed around).
**Tests:** this ticket is itself the top-level test.
**Estimated complexity:** L
**Estimated time:** 1 day

**M6 exit gate — and the whole plan's exit gate:** both integration tests green, full existing Service 1 suite (backend and frontend) still green, staging deploy smoke-tested end to end.

---

# 3. DEPENDENCY GRAPH `[R2 — updated for the new ticket numbering; see Changelog]`

## Full ticket-level graph (critical path in **bold**)

```
                              ┌─ M6-001 ─→ M6-002 ─┐ (independent from Day 1)
                              │                      │
M0-001 ─┬─→ M0-002 ─┬─→ M0-003 ─┬─→ M0-004 ─→ M0-005 │
         │           │           │                   │
         │           └───────────┴─→ M0-006          │
         └─→ M0-007 [R2: enum-fix ticket, done]          │
              │                                          │
    ┌─────────┼──────────────────────┬───────────────────┼──────────┐
    ▼         ▼                      ▼                    ▼          │
 [M1: M1-001→M1-002→M1-003→M1-004→M1-005→M1-006→M1-007]  [R2: +1 ticket]
                                                                       │
 [M2: M2-001→M2-002a→M2-002b→M2-003, M2-002a→M2-004, M2-002b/M2-003→M2-005]  (parallel to M1) [R2: M2-002 split]
                                                                       │
 [M3: M3-001, M3-002→M3-003→M3-004]                (parallel to M1,M2)│
    │         │             │                                        │
    └─────────┴─────────────┴──────────┬─────────────────────────────┘
                                        ▼
                     M4-001→M4-002→M4-003→M4-004
                              M4-003→M4-005
                     M4-003,M1,M2,M3 → M4-006 → M4-007   ← convergence point
                                        │
                                        ▼
                     M5-001 → M5-002 → M5-003
                     M5-001 → M5-005
                     M2 → M5-004
                                        │
                                        ▼
              M6-003 (after M6-001) ── M6-004 (needs M4-004)
                              │
                              ▼
              M6-005 (needs M5-004) → M6-006 (needs M5-003)
                              │
                              ▼
                          M6-007  ← final ticket, needs everything above
```

## Critical path (the chain that actually gates final delivery)

**M0-001 → M0-002/003 → M0-007 → M1-001 → M1 (all seven tickets, sequential within M1) → M4-006 → M4-007 → M5-001 → M5-005 → M6-005 → M6-007** `[R2: was "M0-007 → M1 (all six tickets...)" — M1 now starts at M1-001 (the relocated provider ABC) and runs seven tickets, not six]`

M1 is on the critical path (not M2 or M3) specifically because M1's tickets are internally sequential (each GEE method builds on the shared-helper extraction and the prior method's scaffolding) and because M4-006 is the first point that needs *real* provider output, not synthetic — M2 and M3 finish comfortably inside M1's runtime if resourced in parallel, per the sprint plan.

## Parallel work streams (can proceed simultaneously without coordination)

- **Stream A (backend core):** M1 (GEE provider)
- **Stream B (backend logic):** M2 (pure engine) — zero dependency on Stream A
- **Stream C (backend logic):** M3 (stress scoring + CGWB) — zero dependency on Stream A or B
- **Stream D (frontend):** M6-001/M6-002 — zero dependency on any backend stream, can start the same day as M0-001

## Independent work (no other ticket depends on these; can be dropped or delayed with the smallest blast radius)

- M1-007 (cost measurement) `[R2: was M1-006]` — blocks nothing except updating a document with a real number
- M3-002 (CGWB research spike) — blocks only M3-003/004, nothing outside M3
- M6-002 (regression verification) — a checkpoint, not a code dependency for anything downstream

---

# 4. FILE-BY-FILE PLAN

## `backend/app/models/`
- **New:** `organization.py`, `catchment.py`, `water_balance.py`, `cgwb.py`
- **Modify:** `enums.py` (additive only — see M0-001's acceptance criteria), `__init__.py` (register new models)
- **Untouched:** `farm.py`, `job.py`, `risk.py`, `satellite.py`, `user.py`, `admin.py`, `loan.py`, `mixins.py`

## `backend/app/services/`
- **New directory:** `hydrology/` (`provider.py`, `gee_hydrology_provider.py`, `engine.py`, `recharge_stress.py`, `boundary_parser.py`, `models.py`, `__init__.py`) — `[R2]` **`__init__.py`, `models.py`, and `engine.py` already exist and are merged** (built under M2-001/M2-002a); `provider.py`, `gee_hydrology_provider.py`, `recharge_stress.py`, and `boundary_parser.py` do not yet exist
- **New directory:** `ingestion/` (`cgwb_ingest.py`, `__init__.py`)
- **Modify:** `satellite/gee_provider.py` (extraction only, re-exports for compatibility), `reporting/pdf_renderer.py` (extend with a water-report payload variant)
- **New in `reporting/`:** `water_report_generator.py`, `water_methodology_text.py`
- **Untouched:** `risk/engine.py`, `risk/models.py`, `reporting/map_snapshot.py`, `reporting/progress.py`, `reporting/recommendation.py`, `reporting/report_findings.py`, `reporting/report_generator.py`, `reporting/report_statistics.py`, `reporting/report_text.py`, `jobs/reaper.py` (already generic across `JobType`, needs no change)

## `backend/app/api/`
- **New:** `catchments.py`
- **Modify:** possibly one new small admin router file for the CGWB ingestion trigger (M3-004) — exact placement decided at implementation time depending on whether an admin router already exists by then
- **Untouched:** `auth.py`, `deps.py`, `farms.py`, `jobs.py`, `reports.py`, `villages.py`

## `backend/app/schemas/`
- **New:** `catchment.py`, `water_report.py`
- **Untouched:** `auth.py`, `errors.py`, `farm.py`, `job.py`, `report.py`, `village.py`, `workspace.py`

## `backend/alembic/versions/`
- **New:** `0005_organization.py`, `0006_catchment.py`, `0007_water_balance_result.py`, `0008_recharge_stress_score.py`, `0009_cgwb_observation.py`, `0010_extend_existing_enums.py` `[R2 — the M0-007 enum fix, not in Rev. 1's plan]`
- **Untouched:** `0001`–`0004` (never edit a merged migration — new schema needs are always a new migration, per the project's own established norm)

## `backend/tests/`
- **New:** `fakes/fake_hydrology_provider.py`; `services/test_water_balance_engine.py`, `test_water_balance_golden_dataset.py`, `test_recharge_stress.py`, `test_boundary_parser.py`, `test_gee_hydrology_provider.py`, `test_water_report_generator_resilience.py`; `test_catchments.py`, `test_water_reports.py`, `test_water_methodology_text.py`, `test_water_report_pdf.py`; `schemas/test_catchment_schema.py`
- **Untouched:** every existing `test_*.py` file — and every one of them **must stay green** throughout this entire plan; that's not a file to modify, it's a file to keep passing

## `frontend/src/features/`
- **New:** `polygon-drawing/`, `catchment-drawing/`, `water-intelligence/`
- **Modify (reduced, not rewritten):** `farm-drawing/`
- **Untouched:** `assessment/`, `assessment-wizard/`, `auth/`, `navigation-guard/`, `report/` (reused, its chart/PDF *patterns* are followed, its files are not edited), `workspace/`

## `backend/requirements.txt` (or `pyproject.toml`)
- **Modify:** add `pyshp` (Shapefile parsing, M4-002) — this is the **only** new backend dependency this entire plan introduces. No new dependency for KML (stdlib `xml.etree.ElementTree`), none for GeoJSON (`shapely` already present), none for scheduling (external cron, not a new library).

---

# 5. DATABASE PLAN

| Migration | Changes | Reversible? | Depends on |
|---|---|---|---|
| **0005** — `organization` | New enum `organization_type_enum`; new table `organization` | Yes — `DROP TABLE`, `DROP TYPE` | 0004 (existing head) |
| **0006** — `catchment` | New enums `delineation_method_enum`, extends `SatelliteIndexType`/`RiskEntityType`/`JobType`/`UserRole` pg enums with new values; new table `catchment` with `MULTIPOLYGON` geometry, GIST + 2 btree indexes, 2 `CHECK` constraints | Partially — table drop is trivial; **`ALTER TYPE ... ADD VALUE` cannot be cleanly reversed** (Postgres has no `DROP VALUE`) — downgrade path documented as "requires a new enum type + data migration if ever needed," not a silent no-op | 0005 |
| **0007** — `water_balance_result` | New enums `calibration_status_enum`, `storage_change_band_enum`; new table, FK to `catchment` | Yes | 0006 |
| **0008** — `recharge_stress_score` | New enums `stress_band_enum`, `baseline_window_enum`; new table, FK to `catchment` and `config_weight` | Yes | 0007 |
| **0009** — `cgwb_groundwater_observation` | New table, unique constraint on `(block_code, assessment_period)`, GIST index | Yes | 0008 (sequential numbering; no real dependency on 0007/0008's content) |
| **0010** — `extend_existing_enums` `[R2 — not in Rev. 1's plan; ticket M0-007]` | Eight `ALTER TYPE ... ADD VALUE IF NOT EXISTS` statements against the four **pre-existing** Postgres enum types (`user_role`, `observation_entity_type`, `satellite_index_type`, `job_type`) created back in `0001_initial_schema.py` — fixes a real defect found during live verification, where M0-001's Python enum extensions were never mirrored onto the actual Postgres types | No — Postgres has no `ALTER TYPE ... DROP VALUE`; `downgrade()` raises `NotImplementedError` rather than pretending to reverse it | 0005–0009 (must run after every migration that could plausibly need these values) |

**Known migration-writing risk, flagged explicitly for whoever implements 0006:** extending an existing native Postgres enum type with `ALTER TYPE ... ADD VALUE` **cannot be used in the same transaction as inserting a row that uses the new value** on older Postgres behavior, and some drivers/ORM patterns still hit "unsafe use of new value" errors even on newer Postgres if the same migration both adds the value and seeds data with it. **Mitigation: 0006 only adds enum values and creates tables — it seeds no data using the new enum values.** If a future migration needs to seed data using a newly-added enum value, split that into its own subsequent migration.

**Phase 2 note (not in this plan's scope, named so it isn't forgotten):** `recharge_structure` table creation is explicitly deferred — Blueprint v2's M0.1 ticket says its schema "can wait for Phase 2," and this plan takes that literally: **no migration for it exists in 0005–0009.** Phase 2 will add its own migration (0010+) when that work is scoped.

---

# 6. API IMPLEMENTATION ORDER

1. **`POST /catchments` first** (M4-003) — every other endpoint needs a catchment to exist; this is the natural root of the dependency tree, exactly as `POST /farms` was for Service 1.
2. **`GET /catchments`, `GET /catchments/{id}` second** (M4-005) — needed to write any meaningful test for what comes after, and low-risk (read-only, well-understood pattern reused directly from `farms.py`).
3. **`POST /catchments/upload` third** (M4-004) — deliberately *after* the manual-create path is solid, because it reuses that path's persistence internals; building upload first would mean building the shared validation core without a working reference implementation to validate it against.
4. **`POST /catchments/{id}/water-reports` fourth** (M4-006) — the highest-complexity endpoint (job orchestration, advisory locking, the first point needing M1/M2/M3 merged), deliberately sequenced after the simpler CRUD is proven so any integration surprises are isolated to this one endpoint rather than compounding with unproven CRUD underneath it.
5. **The `GET` report/result endpoints last** (M4-007) — trivial once the job and persistence model from step 4 exists; sequencing them last is purely about not building read endpoints for data that can't be created yet.

**Each endpoint's required tests**, restated compactly:
- `POST /catchments`: happy path, role-gate rejection, area-bound rejection, vertex-bound rejection, malformed-geometry rejection.
- `GET /catchments`, `GET /catchments/{id}`: owner-or-branch scoping, explicit IDOR rejection test.
- `POST /catchments/upload`: one happy-path test per file format, one malformed-file test per format.
- `POST /catchments/{id}/water-reports`: happy path, concurrent-trigger race condition (must produce exactly one job).
- `GET` report endpoints: response-shape assertions confirming headline/technical-view separation.

---

# 7. GEE IMPLEMENTATION ORDER

**Order: Rainfall → ET → Surface Water (SAR, then MNDWI) → Recharge Stress → Water Balance.**

1. **Rainfall first — because it requires zero new implementation.** `SatelliteDataProvider.get_rainfall_series()`/`get_rainfall_climatology()` already exist, already work, and Water Intelligence reuses them unchanged. Sequencing it "first" really means: **confirm reuse works before building anything new** — a cheap, fast sanity check that the shared-helper extraction (M1-002 `[R2: was M1-001]`) didn't break anything, before any real new engineering starts.
2. **ET second — the simplest genuinely new implementation.** One well-documented public dataset (MODIS MOD16A2), one `scale` value, no threshold-tuning judgment calls, no terrain sensitivity. Building this first among the *new* work establishes the `GEEHydrologyProvider` pattern (scale constants, series-not-monthly `getInfo()` calls, dataclass boundary) on the lowest-risk case, so mistakes in the pattern itself are caught here, not in something harder.
3. **Surface water (SAR) third — meaningfully harder, tackled once the pattern is proven.** SAR introduces the threshold-tuning judgment call and the terrain-sensitivity caveat (Part 4's `[v2]` addition) — real scientific nuance that ET didn't have. Doing this third means the *engineering* pattern is already de-risked by ET, so effort here goes entirely into the genuinely hard part (the threshold and its documented limitation), not into re-debugging the provider scaffolding at the same time.
4. **Surface water (MNDWI) fourth — a confirmation layer, not a new capability.** Explicitly sequenced right after SAR because it's evaluated *against* SAR's output (the cross-check test in M1-005 `[R2: was M1-004]`), so SAR has to exist first for MNDWI's own test to have something to compare against.
5. **Recharge stress fifth — a pure composition of rainfall + ET + surface-water outputs, no new GEE calls at all.** This is why M3 doesn't need M1 done: `recharge_stress.py` operates on already-fetched series (real or synthetic), so its correct position in *engineering* sequencing (not milestone sequencing) is "after the inputs it composes exist," which for testing purposes is Day 1 (synthetic), and for real-data purposes is whenever M1 actually lands — both are fine because the logic itself has zero direct GEE dependency.
6. **Water balance last — because it's the composition of every other module, and composing before the parts exist would mean testing against mocks of mocks.** This mirrors exactly why `WaterBalanceEngine` (M2) is architected as pure/synthetic-testable in the first place: the engine's *correctness* doesn't need real GEE data to prove, but its *real-world output* is only as good as every upstream series feeding it, so it is correctly the last GEE-adjacent thing to be exercised end-to-end (in M4-006/M5-001), even though the engine's own code (M2) was built and tested much earlier.

**Why this order minimizes engineering risk, restated as one sentence:** each new step adds exactly one new kind of difficulty (a new dataset, then a threshold/terrain judgment call, then a cross-validation, then a composition, then a full end-to-end wiring) instead of stacking several unproven things at once — if something breaks, the step that broke it is small and recent, not buried under three simultaneous unknowns.

---

# 8. TESTING ROADMAP `[R2 — ticket references updated, see Changelog]`

| Milestone | Unit Tests | Integration Tests | Database Tests | GEE Tests | Scientific Validation Tests | Regression Tests |
|---|---|---|---|---|---|---|
| **M0** | `pg_enum()` value-list assertions | — | Offline DDL compile (all 5 tables); `CHECK` constraint rejection (needs real Postgres, skips cleanly in sandbox); `[R2]` **live-DB regression test asserting the four pre-existing Postgres enum types actually contain their new values** (`test_enums.py::test_extended_enum_postgres_types_actually_contain_new_values`, ticket M0-007) — this is the permanent guard against the exact defect M0-007 fixed | — | — | Full existing Service 1 suite must stay green |
| **M1** | `maxPixels`/`bestEffort` guard unit test | — | — | `test_gee_hydrology_provider.py` (ET, SAR, MNDWI cross-check) against real GEE test project — skips cleanly without credentials | — | Existing `test_gee_provider.py` must stay green post-extraction (M1-002 `[R2: was M1-001]`) |
| **M2** | `WaterBalanceEngine.compute()` core cases, band-threshold table test, resolution-flag boundary tests | — | — | — | **`test_water_balance_golden_dataset.py`** — the one test proving the science, not just the code | `test_risk_engine.py` untouched, must stay green (proves M2's file additions didn't leak into `risk/`) |
| **M3** | Percentile-scoring unit tests, 30yr-vs-3yr baseline regression case | Ingestion job against a recorded CGWB fixture, idempotent-rerun test | Uniqueness-constraint rejection test | — | Baseline-window regression case (a drought-sequence catchment scoring differently under the corrected baseline) | — |
| **M4** | Schema validation unit tests | `test_catchments.py`, `test_water_reports.py`, `test_boundary_parser.py` (real stack, mirrors existing `test_farms.py`) | IDOR rejection test, owner/branch scoping | — | — | Full `farms.py`/`reports.py` suites must stay green |
| **M5** | Methodology-text unit assembly | `test_water_report_pdf.py` twin test | — | — | — | **Existing `test_report_pdf.py`, `test_report_text.py` must stay green unmodified** — the resilience test (M5-005) is written against a deliberately-broken implementation first, to prove the test itself catches the bug |
| **M6** | Vitest unit tests per feature folder | Real-stack integration test, both draw and upload paths, GL map as the only mock | — | — | — | **Full existing farm-drawing Vitest suite + real-stack farm-creation-flow integration test must stay green (M6-002's explicit verification gate)** |

---

# 9. DEFINITION OF DONE

## Definition of Ready (every ticket, before work starts)
- The ticket's **Dependencies** are merged to `main`, not just "in review."
- The engineer has read the one existing file each ticket names as its pattern-to-mirror (e.g., M4-003's engineer has actually opened `api/farms.py`, not just this document's summary of it).
- Any ambiguity the ticket doesn't resolve (there shouldn't be any — flag it back to this document if there is) is raised **before** coding starts, not discovered mid-PR.

## Definition of Done (every ticket, before requesting review)
- All tests named in the ticket exist and pass locally.
- The **full existing Service 1 test suite** (backend and, where relevant, frontend) still passes — not just the new ticket's own tests.
- No `bestEffort: true` anywhere touched by this ticket (GEE tickets only).
- No new dependency added without being named in Section 4's file-by-file plan (currently: `pyshp` only, nothing else).
- Every new enum value uses `pg_enum()` correctly (verified by the M0-001-style test pattern, for any ticket touching enums).
- Docstrings/comments state assumptions the code makes that aren't obvious from reading it — specifically, any ticket touching `WaterBalanceEngine` must carry the closed-catchment and gross-`Q` statements verbatim.
- The PR description names which ticket this is, which Blueprint v2 section it implements, and explicitly calls out anything a reviewer might mistake for scope creep so it doesn't need to be discovered.

## Review Checklist (every PR)
1. Does this PR do **only** what its ticket describes — no incidental refactors bundled in?
2. Does it touch any file marked "Untouched" in Section 4? If yes, stop and explain why in the PR description before requesting review.
3. Are the ticket's named tests present, and do they fail if the implementation is reverted (not just pass trivially)?
4. For schema tickets: is the migration's `downgrade()` real, not a `pass`?
5. For GEE tickets: is the `scale` value a named constant, and does it match D9's table exactly?
6. For anything touching `farm-drawing`, `gee_provider.py`, or shared enums: has the reviewer actually run the existing Service 1 suite locally, not just trusted CI?

---

# 10. RISK REGISTER

| Milestone | Technical Risk | Scientific Risk | Product Risk | Mitigation | Rollback Strategy |
|---|---|---|---|---|---|
| **M0** | `ALTER TYPE ADD VALUE` transaction semantics bite during migration 0006 | None — pure schema | Delays every downstream milestone if schema is wrong, since everything reads it | Migration 0006 adds enum values and creates tables in the same migration but seeds no data using new values (see Section 5) | `DROP TABLE`/`DROP TYPE` for new tables/enums; enum-value removal is not cleanly reversible — documented, not solved |
| **M1** | GEE quota/latency behavior under real load is unverified until M1-007 `[R2: was M1-006]` actually runs | SAR threshold accuracy in real Indian terrain is unverified until real catchments are tested — the fixed threshold is a stated approximation, not a proven one | If M1-007's measured cost is far worse than the ~50% estimate, M4's cost assumptions need revisiting | M1-007 `[R2: was M1-006]` is explicitly scheduled, not optional; D9's reject-at-creation bound limits worst-case blast radius regardless of the actual multiplier | Feature-flag the water-report trigger endpoint if cost proves unsustainable post-launch; the read/create catchment endpoints have no GEE cost and are unaffected |
| **M2** | None significant — pure functions, fully unit-testable | Golden-dataset test only validates against **one** regional CN study — a second location could reveal the citation doesn't generalize as far as even the region-qualified claim assumes | Low — engine correctness is provably testable; scientific *generalizability* is the open question, already flagged in Blueprint v2's Remaining Open Questions | Golden-dataset test is a floor, not a ceiling — Blueprint v2 already names a second ET-validation golden case as a should-have | Engine is versioned (`MODEL_VERSION`) — a future correction ships as a new version, old results remain queryable and distinguishable |
| **M3** | CGWB source access mechanism is **genuinely unverified** until M3-002's spike completes — real risk the assumed access pattern (API vs. bulk download) is wrong | Block-level CGWB categories may not align well with catchment-scale results in practice — this is a named, accepted limitation, not a defect | Ingestion job could silently go stale if the real cadence differs from "quarterly" assumption | M3-002 is explicitly time-boxed and gates M3-003 — no ingestion code is written against an assumed API shape | If the confirmed source changes format later, only `cgwb_ingest.py` needs updating — the staging table schema is source-agnostic |
| **M4** | Boundary-file parsing (3 formats × several failure modes) is the single largest-scope ticket (M4-002) in the plan and the most likely to run over its estimate | None directly — this is a parsing/validation concern, not a hydrology one | A confusing upload error message is a real first-demo risk, per the TDR's UX finding that motivated building this at all | M4-002 is scoped generously (1–1.5 days, largest single-ticket estimate in the plan) and explicitly tested against malformed fixtures per format, not just happy paths | Upload path can be feature-flagged off independently of manual drawing if it proves unstable post-launch — the two paths share validation internals but are separate endpoints |
| **M5** | Incremental-persistence-under-more-series-than-Service-1 is a real, not hypothetical, regression risk given more sequential GEE calls | None directly | A user staring at a "generating report" spinner that silently fails partway with no partial data saved is a real trust-eroding product risk | M5-005's resilience test is explicitly validated against a deliberately-broken implementation first, to prove it actually catches the failure mode it exists to catch | `Job` model already carries `error_message` and `progress` fields (reused unchanged) — a failed report is diagnosable from persisted state, not a silent black box |
| **M6** | Refactoring `farm-drawing` (a shipped, working Service 1 feature) underneath itself is the highest-blast-radius frontend risk in the entire plan | None | A regression in farm creation — TerraRisk's actual existing production feature — while building an unrelated new service would be a severe, avoidable product failure | M6-002 exists as its own ticket specifically to force independent verification of this one risk, not bundled into M6-001's own self-assessment | If M6-001's refactor proves unstable, `farm-drawing` can retain its pre-refactor implementation (revert M6-001 alone) without touching any Water Intelligence code, since `polygon-drawing` was designed as an extraction, not a rewrite |

---

## Closing note for whoever picks up M2-002b `[R2: was "whoever picks up M0-001" — M0 is done and M1/M2 are underway]`

This plan converts an approved, frozen architecture into 43 tickets `[R2: was 41]` across 7 milestones. As of this revision, 13 tickets are done (all 7 of M0, plus M2-001 and M2-002a) and **M2-002b — the real P−ET−Q=ΔS arithmetic — is the next actionable ticket in the entire plan.** Nothing here should require re-opening `docs/Water_Intelligence_Service_Blueprint.md` or `docs/Water_Intelligence_TDR.md` to understand *what* to build — those documents remain the record of *why*. If a ticket's acceptance criteria and the blueprint ever seem to disagree, the blueprint wins, and that's a signal this document has a bug worth fixing, not a signal to improvise. If this document's ticket numbering and the actual repository ever seem to disagree, treat the repository as the source of truth and fix this document — exactly the situation this Rev. 2 revision itself resolved (see Changelog below).

---

# CHANGELOG — Rev. 1 → Rev. 2 (27 July 2026)

**Why this revision exists:** implementation proceeded, correctly, ahead of Rev. 1's exact ticket labels — a real defect was found and fixed during live-database verification (never anticipated by Rev. 1, since Rev. 1 assumed no live Postgres was available), and the WaterBalanceEngine skeleton was built under the working label "M1-001" because at the time it was implemented, no ticket in the frozen backlog matched what was actually being asked for under that name. Rather than leave the plan silently wrong, this revision reconciles ticket numbering with what the repository actually contains. **No milestone was redesigned. No feature was added or removed. No architectural decision was revisited.** Every change below is a renumbering, a relabeling, or a status update.

1. **New ticket M0-007 — extend pre-existing Postgres enum types (migration `0010`).** Not in Rev. 1's plan at all. Discovered during the M0 live-database verification pass (`docs/Water_Intelligence_M0_Live_Verification.md`): M0-001 extended the **Python** enum classes (`UserRole`, `RiskEntityType`, `SatelliteIndexType`, `JobType`) but no migration ever ran `ALTER TYPE ... ADD VALUE` on the corresponding **Postgres** enum types, which were created back in `0001_initial_schema.py`. This is structurally undetectable by any offline test (`test_schema_ddl.py`'s enum-binding tests only check a SQLAlchemy model's declared type against itself, never against a real Postgres catalog) and was only found because this project's M0 sign-off included, for the first time, an actual live-database verification pass rather than offline DDL compilation alone. Fixed with migration `0010_extend_existing_enums.py` (eight `ALTER TYPE ... ADD VALUE IF NOT EXISTS` statements) plus a permanent regression test (`test_enums.py::test_extended_enum_postgres_types_actually_contain_new_values`). Filled the vacant `M0-007` slot (see item 2) since it is, in every structural sense, a seventh M0 foundations ticket — schema-only, gates every downstream milestone the same way M0-001 through M0-006 do.

2. **Old `M0-007` (`HydrologyDataProvider` ABC) relocated to new `M1-001`.** Rev. 1's Section 2 actually specified an `M0-007` ticket for the provider ABC's contract-only interface — a fact this document's own "Completed"/"Remaining work" tracking had drifted away from before this revision, since work proceeded past M0-006 without that ticket ever being picked up. On inspection, this ticket was never built, and it structurally belongs at the *start* of M1 (it's the provider contract every other M1 ticket implements against), not inside M0 (it has no schema, no migration, and every other M0 ticket is schema-only). Relocated to `M1-001`, content unchanged, only its number and milestone changed.

3. **M1's old tickets 001–006 shifted to 002–007.** A direct consequence of item 2 — with the provider ABC now occupying `M1-001`, the six tickets that were `M1-001` through `M1-006` in Rev. 1 (shared-helper extraction, `get_et_series`, SAR, MNDWI, `maxPixels` enforcement, cost measurement) shift down one slot each to `M1-002` through `M1-007`. Every internal dependency reference within M1 (e.g., old M1-006's "depends on M1-002/003/004" becomes new M1-007's "depends on M1-003/004/005") and every cross-reference from Sections 3, 7, 8, and 10 was updated to match. **M1 is now 7 tickets, not 6** — the milestone's scope is identical; it just now has one more numbered unit of work than Rev. 1 counted, because Rev. 1 undercounted by placing the provider ABC in M0 without giving M1 credit for depending on it as its own first step.

4. **Old `M2-002` split into `M2-002a` (done) and `M2-002b` (not started).** This is the one place actual *work already performed* didn't cleanly match any single Rev. 1 ticket. Under the session-time working label "M1-001" (a label chosen at the time because no ticket in the then-current backlog matched "build the WaterBalanceEngine skeleton, structure only, no arithmetic" — see item 5), the team built exactly the *structural* half of what Rev. 1's `M2-002` described: the `WaterBalanceEngine` class, `compute()`'s public signature, full input validation, logging, and a documented `NotImplementedError` in place of the arithmetic — deliberately excluding the P−ET−Q=ΔS calculation itself, per the explicit instruction that scoped that work ("no scientific calculations yet"). Rev. 1's single `M2-002` bundled both the skeleton and the arithmetic into one ticket. Splitting it in two lets the "Completed" section credit the skeleton work that is actually merged, without falsely claiming the arithmetic (the scientifically load-bearing half, per the TDR's closed-catchment/gross-Q requirement) is done when it is not. `M2-002a` is marked done; `M2-002b` inherits the closed-catchment/gross-Q docstring requirement and is now **the single next actionable ticket in the entire plan**. Downstream dependents were re-pointed individually, not uniformly, based on which half they actually need: `M2-003` (band derivation, needs the real mm values) and `M2-005` (golden-dataset test, needs real output) now depend on `M2-002b`; `M2-004` (resolution-flags derivation, only needs the class/method to exist, never touches the arithmetic) now depends on `M2-002a`.

5. **The work done under the session-time label "M1-001" is correctly attributed to `M2-001` + `M2-002a`, not to any M1 ticket.** At the time that work was requested, its label ("M1-001 — WaterBalanceEngine skeleton") did not match Rev. 1's actual M1-001 (which, per item 2/3 above, was always the GEE provider ABC or the shared-helper extraction, never the engine). The discrepancy was flagged explicitly before implementation rather than silently built under the wrong ticket identity or silently substituted; the interpretation used at the time — that the request meant the structural portion of the engine work — is confirmed correct by this revision and is now formally recorded as `M2-001` (dataclasses, already independently correct and complete) plus the new `M2-002a` (the skeleton itself).

6. **Total ticket count: 41 → 43.** Net effect of items 1–4: +1 for the new M0-007 (enum fix), +1 for M1 gaining a ticket it was always structurally owed (net zero from the M0→M1 relocation, since M0-007's old content moved out but new content moved in — see item 1 vs. item 2), +1 for the M2-002 split (M2-002a + M2-002b replacing one M2-002). Milestone *scope* — what capabilities each milestone delivers — is byte-for-byte identical to Rev. 1; only the number of discrete, independently-mergeable units of work changed.

**What did not change:** every milestone's boundaries and responsibilities (Section 1's table), the dependency *shape* between milestones (M1/M2/M3 still run in parallel off M0, still converge at M4-006), every architectural decision (D1–D9), every acceptance criterion's substance (only ticket-number references within them were updated), and Sections 6 (API Implementation Order) and 9 (Definition of Done) — neither contained a stale ticket-number reference, so neither required a Rev. 2 edit.
