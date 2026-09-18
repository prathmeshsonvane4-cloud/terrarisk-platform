# TerraRisk — Engineering Decision Record

This is the project's architecture decision log, required by the approved
[Engineering Blueprint v1](Engineering_Blueprint_v1.md) as a Phase 0 (M0)
deliverable. Every entry follows the same shape: Decision, Reason,
Alternatives considered, Trade-offs, Future migration path. New decisions
are appended, never rewritten — if a decision changes, a new entry
supersedes the old one and says so explicitly.

---

## Product & platform-level decisions

### Google Earth Engine as the satellite/climate data pipeline

**Decision.** All satellite and climate data (Sentinel-1/2, rainfall, JRC
Global Surface Water) is sourced from Google Earth Engine for the MVP,
free/noncommercial tier, accessed through a dedicated `terrarisk-platform`
GCP project and service account.

**Reason.** Fastest path to a working end-to-end product: GEE provides a
managed compute layer, a large public catalog, and built-in index/time-series
tooling, letting the team validate the full workflow (polygon → satellite
data → risk score → report) without first building satellite data
infrastructure.

**Alternatives considered.** Sentinel Hub / Copernicus Data Space (more
licensing control, less built-in analysis tooling); a self-hosted
rasterio/xarray pipeline (full control, no vendor dependency, but the most
engineering effort before a single report can be produced).

**Trade-offs.** GEE's free tier is noncommercial/research use only —
selling to a bank requires a paid Earth Engine commercial license via Google
Cloud, budgeted for at the paid-pilot stage, not before. Vendor dependency
on Google's infrastructure and quota/rate limits.

**Future migration path.** All access goes through the `SatelliteDataProvider`
interface (`backend/app/services/satellite/provider.py`); the GEE
implementation (`gee_provider.py`) is one interchangeable adapter.
Business logic, the risk engine, and the database schema never depend on
Earth Engine directly — replacing the provider means writing one new
adapter class.

---

### PostgreSQL + PostGIS as the database

**Decision.** PostgreSQL with the PostGIS extension is the single data
store for the platform.

**Reason.** The platform's core objects — farm polygons, administrative
boundaries, risk choropleths — are geometries. PostGIS provides spatial
indexing and queries (point-in-polygon, area, containment) natively instead
of hand-rolling them, and Postgres's JSONB support covers the semi-structured
data (risk factor weights, raw satellite inputs) the schema also needs.

**Alternatives considered.** A generic relational database with geometries
stored as raw coordinate arrays (would require reimplementing spatial
operations in application code); a dedicated geospatial database separate
from the transactional store (unnecessary operational complexity for this
scale).

**Trade-offs.** Requires PostGIS-aware tooling throughout the stack
(GeoAlchemy2 for the ORM layer, PostGIS-aware migrations); geometry columns
cannot be tested against a plain SQLite instance, which shaped the M0
testing strategy (see below).

**Future migration path.** None anticipated — this is a foundational,
low-risk choice unlikely to need revisiting at MVP/pilot scale.

---

### FastAPI (backend) and Next.js (frontend)

**Decision.** FastAPI for the backend API, Next.js (App Router) for the
frontend, as inherited from the initial project scaffold and reaffirmed in
the approved blueprint.

**Reason.** Both are async-native, have strong typing support end to end
(Pydantic on the backend, TypeScript on the frontend), and have mature
ecosystems for the specific needs here (FastAPI's dependency injection maps
cleanly onto role-scoped auth; Next.js's App Router suits a small number of
data-heavy pages rather than a large multi-page site).

**Alternatives considered.** Django REST Framework (heavier, more batteries
included than needed for two services); a plain React SPA without a
framework (would need to hand-build routing/SSR concerns Next.js already
solves).

**Trade-offs.** FastAPI's async ecosystem (SQLAlchemy async, asyncpg) is
less battle-tested than the sync equivalents, though mature enough for this
scale.

**Future migration path.** None anticipated at MVP scale.

---

### Manual polygon drawing (Service 1)

**Decision.** Bank officers manually draw farm boundaries on a map; no
cadastral/parcel data integration in the MVP.

**Reason.** No reliable source of per-farmer parcel boundaries exists yet
for the pilot bank engagement. Manual drawing is a deliberate, human-in-the-loop
MVP approach, not a placeholder for missing functionality.

**Alternatives considered.** Waiting for official cadastral data integration
before building Service 1 at all (would block the entire MVP indefinitely on
a data-access problem outside the team's control).

**Trade-offs.** Report accuracy depends on officer-drawn boundary quality;
mitigated by an explicit area-confirmation step and recording who drew each
polygon (accountability, not just data entry).

**Future migration path.** Official cadastral/parcel integration is a
later-phase enhancement; the `farm_polygon` table's shape (a geometry +
metadata) does not need to change to accommodate it.

---

### Synthetic loan portfolio data

**Decision.** The platform is designed and tested against a realistic
synthetic agricultural loan dataset; no real DCCB portfolio data exists yet.

**Reason.** The pilot bank has not yet provided real portfolio data. Building
against a synthetic dataset now, with a schema designed to be
production-shaped from the start, avoids blocking Service 2 development on
an external data-sharing timeline.

**Alternatives considered.** Waiting for real data before building Service
2 (blocks the MVP on an external dependency); designing a simplified schema
"for now" and rebuilding it later for real data (directly contradicts the
requirement that only the ingestion layer changes when real data arrives).

**Trade-offs.** Synthetic data cannot validate real-world data-quality
problems (inconsistent village name spellings, missing fields) until real
data is actually ingested — the `village_branch_lookup` and CSV validation
design anticipate this class of problem, but the specifics will only be
confirmed against real data.

**Future migration path.** Only the ingestion layer (CSV parsing/validation)
changes when real DCCB data arrives; database schema, APIs, risk engine, and
dashboards are unaffected by design.

---

### Rule-based, configurable Climate Risk Score

**Decision.** The Climate Risk Score is computed by a transparent,
rule-based engine with configurable weights and floor thresholds — not
presented as a scientifically calibrated or AI-predicted score.

**Reason.** No historical loan-performance data exists yet to calibrate a
predictive model, and a bank needs to trust and understand a score before
acting on it. A transparent rules engine with a visible factor breakdown is
both honest about its current basis and immediately usable.

**Alternatives considered.** An ML model trained on synthetic/proxy data
(would produce a false sense of predictive validity with no real basis);
a fixed, hard-coded scoring formula (would require a code change, not a
configuration change, every time domain experts recalibrate it).

**Trade-offs.** Requires ongoing domain-expert involvement (the user, as
water-resources/remote-sensing domain authority) to set and validate
weights and thresholds, rather than "learning" them from data.

**Future migration path.** The engine's public contract —
`compute(observation_bundle, config) -> RiskResult` — is implemented with
zero I/O, so a future ML-backed engine can implement the identical contract
and run in parallel with the rule engine for validation before any cutover.
`risk_score.model_version` and `weights_version_id` make old and new scores
directly comparable.

---

### Async report generation as a durable job

**Decision.** Report generation (Service 1) and portfolio aggregation
(Service 2) run as background jobs tracked in a database table (`job`), not
as synchronous request handling or purely in-process background tasks.

**Reason.** A multi-year, multi-index Earth Engine computation takes longer
than an HTTP request should block on, and job state must survive a server
restart mid-computation — a purely in-memory background task would silently
disappear on redeploy.

**Alternatives considered.** Synchronous request handling (unacceptable
latency for the officer); an in-process-only background task with no
persistence (loses state on restart); a full message-queue system (Celery/
Redis) from day one (more infrastructure than M0's actual job volume
justifies).

**Trade-offs.** Requires clients to poll `/api/v1/jobs/{id}` rather than
receiving results synchronously — an intentional UX trade-off already
reflected in the blueprint's processing-status screens.

**Future migration path.** If job volume grows beyond what polling a
database table comfortably supports, the `job` table's shape doesn't need
to change to add a proper queue (Celery/RQ) behind it — only the execution
mechanism, not the tracking contract.

---

## M0-level implementation decisions

### SQLAlchemy 2.0 (async) + asyncpg + Alembic

**Decision.** SQLAlchemy 2.0's typed declarative style (`Mapped`/
`mapped_column`) with the `asyncpg` driver for the ORM layer, Alembic for
migrations.

**Reason.** Matches FastAPI's async-native design end to end — no sync/async
boundary to manage inside request handlers. SQLAlchemy 2.0's typed style
gives the "proper typing" the engineering standards call for, and Alembic
is the de facto standard migration tool for SQLAlchemy projects.

**Alternatives considered.** A sync SQLAlchemy engine with `psycopg`
(simpler for a small team, but forces a sync/async boundary at every DB
call inside an otherwise-async FastAPI app); a lighter query builder
without a full ORM (loses the typed model layer used throughout the
schema).

**Trade-offs.** Async SQLAlchemy has a smaller body of community examples
than the sync equivalent; a few operations (like the boundary-loading
script) mix sync-style shapely/geoalchemy2 calls with async DB sessions,
requiring `asyncio.run()` wrapping in scripts.

**Future migration path.** None anticipated.

---

### Generic `sqlalchemy.Uuid` over `postgresql.UUID`

**Decision.** Primary keys and foreign keys use SQLAlchemy's generic
`Uuid(as_uuid=True)` type rather than the PostgreSQL-dialect-specific
`postgresql.UUID`.

**Reason.** Compiles to an identical native `UUID` column on PostgreSQL —
verified by offline DDL compilation — while remaining portable enough that
non-geometry tables (like `app_user`) can be exercised against an in-memory
SQLite database in tests, which mattered in an environment with no live
Postgres/PostGIS instance available during M0 development.

**Alternatives considered.** `postgresql.UUID` throughout (equally correct
on Postgres, but makes any non-Postgres testing of even non-geometry tables
impossible); string-typed UUIDs (loses native UUID column benefits on
Postgres for no portability gain, since geometry columns are Postgres-only
regardless).

**Trade-offs.** None identified — this is a strict improvement in
portability with no loss of functionality on the target database.

**Future migration path.** None anticipated.

---

### `bcrypt` + `PyJWT` over `passlib` + `python-jose`

**Decision.** Password hashing uses the `bcrypt` library directly; JWTs use
`PyJWT`.

**Reason.** Both `passlib` and `python-jose` have seen materially slower
maintenance activity, and `passlib`'s bcrypt handler has a known
compatibility issue with bcrypt ≥4.1 (it reads a version attribute that
newer bcrypt releases removed, producing a spurious warning/misdetection).
Using `bcrypt` and `PyJWT` directly avoids both a wrapper library and this
specific friction point, for no loss of functionality at this project's
scale.

**Alternatives considered.** `passlib[bcrypt]` + `python-jose[cryptography]`
(the historically common FastAPI-tutorial pairing, but see reason above).

**Trade-offs.** `passlib` supports pluggable hashing schemes beyond bcrypt;
not needed here, so this is not a real loss for this project.

**Future migration path.** None anticipated.

---

### Hand-written initial Alembic migration (not autogenerated)

**Decision.** The M0 schema migration (`0001_initial_schema.py`) is
hand-written to match the SQLAlchemy models, rather than produced via
`alembic revision --autogenerate`.

**Reason.** Autogeneration requires comparing against a live database
connection; no Postgres/PostGIS instance was reachable in the environment
this milestone was implemented in. The migration was instead validated by
rendering its SQL offline (`alembic upgrade head --sql` / `alembic downgrade
--sql`), which requires no live connection, and by compiling every
SQLAlchemy model to PostgreSQL DDL directly (`backend/tests/test_schema_ddl.py`).

**Alternatives considered.** Deferring the migration until a live database
was available (would have blocked the entire M0 milestone on local
environment setup outside the team's immediate control).

**Trade-offs.** Hand-written migrations are more work to keep in sync with
model changes than autogeneration, and offline SQL rendering — while a
strong correctness signal — is not a substitute for actually running
`alembic upgrade head` against a real PostGIS database, which should be the
first thing done once Docker/Postgres is available locally.

**Future migration path.** All migrations after this one should be
generated normally (`alembic revision --autogenerate`) once a local/CI
Postgres instance is consistently available — this hand-written approach
was specific to M0's environment constraints, not a standing project
convention.

---

### `risk_rollup` as one table with an entity-type discriminator

**Decision.** The blueprint's three conceptual rollup levels (village,
branch, district) are implemented as a single `risk_rollup` table with an
`entity_type` column, rather than three physically separate tables.

**Reason.** All three levels share identical columns (entity reference,
exposure amount, risk band, computed timestamp) — one table is simpler to
query, index, and maintain, and still fully serves the blueprint's intent
(dashboards querying precomputed village/branch/district aggregates).

**Alternatives considered.** Three separate tables as a literal reading of
the blueprint's naming (`risk_rollup_village`, `risk_rollup_branch`,
`risk_rollup_district`) — would triple the schema/migration/query surface
for no behavioral difference.

**Trade-offs.** Queries scoped to one level need a `WHERE entity_type = ...`
clause rather than querying a dedicated table; a minor cost against a
meaningfully simpler schema.

**Future migration path.** If a rollup level's columns ever diverge
meaningfully from the others, it can be split out into its own table without
affecting the other two.

---

### Local PostGIS via `docker/docker-compose.yml`

**Decision.** A single-service Docker Compose file provides a local
PostGIS instance for development and migrations; no other infrastructure is
included.

**Reason.** M0 needs somewhere to run migrations and tests against a real
PostGIS database. Docker Compose is the minimum viable way to provide that
consistently across developer machines, without standing up any
CI/deployment infrastructure (explicitly M5+ scope).

**Alternatives considered.** A natively installed PostgreSQL + PostGIS on
each developer's machine (harder to keep consistent across environments);
a shared cloud development database (unnecessary cost/complexity for a
pre-pilot MVP with no team beyond the founder).

**Trade-offs.** Requires Docker Desktop (or equivalent) installed locally;
not usable in a sandboxed environment with no container runtime (as was the
case for the M0 implementation environment — see the M0 summary for what
that did and didn't allow verifying directly).

**Future migration path.** CI-managed ephemeral Postgres instances and a
real deployment target are M5+ concerns per the roadmap; this
docker-compose file is local-development-only by design.

---

### Dedicated GCP project for Earth Engine (not a personal account)

**Decision.** TerraRisk uses its own dedicated Google Cloud project
(`terrarisk-platform`) with Earth Engine enabled and a dedicated service
account — not the founder's personal Earth Engine account.

**Reason.** Keeps billing, quotas, and access scoped to the company from
day one rather than entangled with a personal account, which matters the
moment commercial licensing or team access is added later.

**Alternatives considered.** Using the founder's existing personal GEE
account for MVP development (faster to start, but creates an access/billing
migration problem later that a dedicated project avoids entirely).

**Trade-offs.** Slightly more setup effort upfront (project creation, API
enablement, service account creation) than reusing an existing account.

**Future migration path.** None anticipated — this is the intended
long-term setup, not a placeholder.

---

## M1-level implementation decisions

### `pg_enum()` helper — bind Postgres enum columns by value, not member name

**Decision.** Every enum-typed column uses a shared `pg_enum(enum_cls, name)`
helper (`backend/app/models/mixins.py`) instead of SQLAlchemy's raw `Enum(...)`.

**Reason.** SQLAlchemy's `Enum` type binds and reads using the Python enum's
*member name* ("VILLAGE") by default. Every native Postgres enum type in
this schema was created (migration 0001) with the lowercase *values*
("village") as its only valid labels. Without `values_callable`, inserting
`BoundaryLevel.VILLAGE` failed against real Postgres with "invalid input
value for enum boundary_level: VILLAGE" — a real bug caught during M1
integration testing against a live database, masked throughout M0 because
the only enum-bearing table exercised then (`app_user`) ran against SQLite,
where the mismatch happened to be self-consistent on both write and read.

**Alternatives considered.** Fixing each `Enum(...)` call site individually
with its own `values_callable` lambda (works, but repeats the same fix
twelve times across six files with no single place to catch a regression).

**Trade-offs.** None identified.

**Future migration path.** None anticipated — `pg_enum()` is now the only
way enum columns are declared in this codebase; a permanent regression
test (`test_every_enum_column_binds_by_value_not_by_member_name` in
`backend/tests/test_schema_ddl.py`) checks every table's enum columns
against their Python enum's values, so this class of bug cannot silently
reappear.

---

### `asyncio.to_thread()` around every Earth Engine SDK call

**Decision.** Every call into `SatelliteDataProvider`'s methods from
`report_generator.py` and the report-trigger background task
(`app/api/reports.py`) is wrapped in `asyncio.to_thread(...)`, never called
directly.

**Reason.** The `earthengine-api` Python SDK performs blocking network I/O
with no async variant. `generate_farm_report()` runs as a FastAPI
`BackgroundTask` on the same single event loop as the rest of the API — a
direct (unwrapped) call to a real GEE request would block that event loop,
and therefore every other concurrent request the API is serving, for
however long that call takes. Found during the M1 final Staff Engineer
review, not part of the original implementation — a genuine async-
correctness bug, not a hypothetical one.

**Alternatives considered.** Running the whole background job in a separate
process or thread pool from the start (more infrastructure than warranted
at MVP volume; `asyncio.to_thread()` solves the specific blocking-call
problem without a bigger architectural change).

**Trade-offs.** Each GEE call now costs a thread-pool hop; negligible next
to the GEE network round-trip time itself.

**Future migration path.** None anticipated — this is the correct
long-term pattern for any synchronous SDK call from async code, not an M1-
specific workaround.

---

### Postgres advisory lock for the report-trigger race condition

**Decision.** `trigger_report` (`app/api/reports.py`) acquires a
transaction-scoped advisory lock (`pg_advisory_xact_lock`, keyed on the
farm id) before checking for an in-flight report job.

**Reason.** The "check for an existing job, then insert a new one" sequence
was a genuine TOCTOU race: two concurrent `POST` requests for the same farm
could both pass the "no job in flight" check before either transaction
committed, creating two simultaneous report jobs (and wasting Earth Engine
quota on the duplicate). Found during the M1 final Staff Engineer review.

**Alternatives considered.** A partial unique index on `job (entity_id,
type) WHERE status IN ('pending','running')`, which would prevent this at
the database-constraint level — the more conventional fix, but a schema
change, which the M1 workflow requires stopping to confirm before making.
The advisory lock achieves the same correctness guarantee entirely in
application code, with zero schema impact, so it was applied directly as
part of "fix any issue found" rather than deferred.

**Trade-offs.** A concurrent second request now waits (briefly) for the
lock rather than failing fast; acceptable since the two outcomes converge
to the same correct result (one job created, one 409) either way.
Advisory locks require the same Postgres session to release them, which
`async with AsyncSessionLocal()`'s transaction boundary already guarantees.

**Future migration path.** If report-trigger volume ever grows enough that
lock contention becomes a measurable latency concern, the partial-unique-
index approach above remains available as a schema-level alternative —
revisit then, not preemptively.

---

### `httpx.AsyncClient` + `ASGITransport` for all API tests, session-scoped event loop

**Decision.** Every API integration test uses `httpx.AsyncClient(transport=
ASGITransport(app=app))` rather than FastAPI's `TestClient`, and
`backend/pytest.ini` sets `asyncio_default_fixture_loop_scope = session` /
`asyncio_default_test_loop_scope = session`.

**Reason.** Two related async-testing bugs, both found and fixed during
M1: (1) `app.database.base` creates its async engine — and asyncpg
connection pool — once at import time; asyncpg connections are bound to
the event loop that created them, and pytest-asyncio's default per-
function event loop caused the first DB-touching test in a run to pass and
every subsequent one to silently fail to connect. (2) Starlette's
`TestClient` runs the ASGI app through `anyio`'s `BlockingPortal` in a
separate internal thread/event loop, which corrupts the same connection
pool when a test also opens sessions directly via `AsyncSessionLocal()` in
pytest-asyncio's own loop — surfaced as "Future ... attached to a
different loop". Standardizing on one event loop for the whole test
session, and one HTTP client that shares it, eliminates both classes of
failure at once.

**Alternatives considered.** A fresh engine per test (avoids the loop
mismatch without changing pytest config, but means every test pays full
connection-pool startup cost, and doesn't fix the `TestClient` thread
issue on its own — both changes were needed together).

**Trade-offs.** None identified — this is a strict fix, not a compromise.

**Future migration path.** None anticipated. M0's `test_auth.py` and
`test_health.py` were migrated to the same pattern during the M1 final
review for consistency and to remove Starlette's `TestClient` deprecation
warning, not because they had the bug themselves (they didn't mix
`TestClient` with direct shared-engine sessions).

---

### Redundant unique index on `app_user.email` (migration 0002)

**Decision.** A new migration (`0002_drop_dup_email_idx.py`) drops the
`app_user_email_key` unique constraint, keeping `ix_app_user_email`.

**Reason.** The M0 migration declared uniqueness on `app_user.email` twice
— once via column-level `unique=True` (Postgres auto-named it
`app_user_email_key`, backing a formal `UNIQUE CONSTRAINT`) and again via
an explicit `op.create_index(..., unique=True)` immediately after (a
separate plain unique index, `ix_app_user_email`). Both physically
enforced the same rule — confirmed via `alembic check`, which flagged the
mismatch against the current model, and via direct inspection of
`pg_indexes` — but it was pure redundancy: two indexes maintained on every
`app_user` write for no benefit. Found during the M1 final verification
pass.

**Alternatives considered.** Editing migration 0001 directly — explicitly
rejected; migration 0001 is frozen (M0's approved deliverable) and already
applied, so the only correct fix is an additive migration.

**Trade-offs.** None — this is a pure cleanup with no functional change
(re-verified: duplicate-email inserts are still rejected, now via
`ix_app_user_email` alone).

**Future migration path.** None anticipated. `ix_app_user_email` matches
this codebase's naming convention for every other index
(`ix_admin_boundary_*`, `ix_farm_polygon_*`, etc.) and is what the current
`AppUser` model actually represents, so no further drift is expected here.

---

### GEE service account IAM roles — `Service Usage Consumer` + `Earth Engine Resource Viewer`, nothing more

**Decision.** The `terrarisk-gee-adapter@terrarisk-platform.iam.gserviceaccount.com`
service account is granted exactly two IAM roles on the `terrarisk-platform`
GCP project: **Service Usage Consumer** (`roles/serviceusage.serviceUsageConsumer`)
and **Earth Engine Resource Viewer** (`roles/earthengine.viewer`, pre-existing
from M0). No write-capable Earth Engine role (`roles/earthengine.writer`) is
granted.

**Reason.** The live GEE integration tests (`tests/services/test_gee_provider.py`)
failed at M1 verification time with a `403 PERMISSION_DENIED` /
`USER_PROJECT_DENIED` error from `ee.Initialize()`:

```
Caller does not have required permission to use project terrarisk-platform.
Grant the caller the roles/serviceusage.serviceUsageConsumer role...
```

This is reproducible and diagnosable directly from the error text — Earth
Engine's Cloud API backend requires `serviceusage.services.use` permission
on whichever project is passed to `ee.Initialize(credentials, project=...)`,
separately from any Earth Engine-specific role, so that API calls can be
quota/billing-attributed to that project. The pre-existing `earthengine.viewer`
role (granted during M0) authenticates the service account and authorizes
reading Earth Engine assets, but does not itself grant permission to *use*
the project for that purpose — hence the separate 403 despite EE access
already being nominally configured.

Granting only `serviceusage.serviceUsageConsumer` (least privilege — the
adapter's M1 workload is entirely `get_index_time_series` /
`get_rainfall_series` / `get_rainfall_climatology` / `get_water_history`,
all reads, no `ee.batch.Export.*` or asset-writing calls anywhere in
`gee_provider.py`) was sufficient: all 9 tests in `test_gee_provider.py`,
including the three live-network ones, pass with no further permission
errors. `earthengine.writer` was deliberately *not* granted pre-emptively.

**Alternatives considered.** Granting `earthengine.writer` alongside
`serviceusage.serviceUsageConsumer` up front, on the theory that a future
milestone (SAR export tasks, per the reserved-but-unimplemented
`get_sar_backscatter_series` seam) will eventually need write access —
rejected under least-privilege: grant it when a concrete write-capable
method is actually implemented and a real 403 names it as missing, not
speculatively.

**Trade-offs.** None identified for M1's read-only scope. The moment a
future milestone adds an Earth Engine write operation (e.g. exporting a
composite image, per the SAR seam), expect a new `403` naming
`earthengine.writer` (or a narrower resource-specific role) explicitly —
diagnose and grant only that role then, following the same
reproduce-first methodology used here rather than assuming.

**Future migration path.** Reproduce this exact setup for any new
environment (staging, a second developer's local `.env`) by: (1)
registering the GCP project for Earth Engine at
`https://code.earthengine.google.com/register`, (2) creating the service
account and granting it `roles/earthengine.viewer`, (3) granting it
`roles/serviceusage.serviceUsageConsumer` on the same project, (4) waiting
a few minutes for IAM propagation. Steps 1-2 were already done in M0;
step 3 is the fix this entry documents.

---

### Removal of pre-Blueprint stub endpoints (`climate_engine`, portfolio CSV upload)

**Decision.** `app/api/location.py`, `app/api/district.py`,
`app/services/climate_engine/` (both files), and `app/api/upload.py` are
deleted, along with their router registrations in `app/main.py` and one
obsolete regression test in `tests/test_health.py`
(`test_locations_endpoint_no_longer_crashes_on_import`, which only
asserted the now-removed `/locations/states` route didn't crash on
import).

**Reason.** These four routes (`/api/v1/locations/states`,
`/api/v1/locations/districts`, `/api/v1/district/report`,
`/api/v1/upload/csv`) predate `docs/Engineering_Blueprint_v1.md` — they
are leftover scaffold from the original `initialize TerraRisk MVP
architecture` commit — and were never brought in line with it. Found
during M1 final production-readiness verification: exercising the live
server showed `GET /api/v1/locations/states` returning `200 OK` with body
`null` (the backing `LocationService.get_states()` is a bare `pass`),
and `POST /api/v1/upload/csv` unconditionally returns
`{"success": true, ...}` regardless of file content, with no parsing or
validation. None of the four appear in the Blueprint's §03 API surface
for M1 or M3 (Service 2's real district/village-lookup endpoints are
specified there as reading `risk_rollup` / `village_branch_lookup`, which
this scaffold never touched), and none were covered by any test other
than the one asserting the import itself didn't crash.

Leaving live routes that return fabricated success/empty responses in the
API surface is a real integration hazard the moment a real client (the
M2/M4 frontend, or a bank's own integration) calls one expecting real
data — worse than a `404`, which at least fails loudly.

**Alternatives considered.** Disabling the router registrations only
(routes 404, code stays) — rejected in favor of full removal: the code
had zero real implementation to preserve, and keeping unreferenced dead
files invites someone re-wiring them by habit later under the mistaken
impression they're a starting point.

**Trade-offs.** None — this is a pure deletion of code with no working
behavior to lose. Service 2's real portfolio-upload and district/village
lookup endpoints are M3 scope per the roadmap and will be built fresh
against `village_branch_lookup` / `risk_rollup`, per the Blueprint.

**Future migration path.** M3 ("Service 2: backend core") implements the
real CSV upload + validation workflow and the real
`/risk/districts · /branches · /villages` rollup-query endpoints per
Blueprint §03/§10 — from scratch, not by resurrecting this scaffold.

---

### IDOR fix — `GET /farms/{farm_id}` missing owner-or-branch authorization

**Decision.** `get_farm` (`app/api/farms.py`) now calls the same
`user_can_access_owned_resource(db, current_user, farm.drawn_by)` check
already used by `get_job` and `get_report`, returning `404` (not `403`)
on failure — identical pattern, identical not-found-vs-forbidden
rationale.

**Reason.** Found during the M1 final security review: `get_farm`
depended only on `get_current_user` (any authenticated, active user of
any role) with no ownership or branch scoping, while its sibling
endpoints (`get_job`, `get_report`) both enforce owner-or-same-branch
access via the shared `deps.py` helper. Any authenticated user who
learned a `farm_id` belonging to a different officer/branch — e.g. from a
shared link, browser history, or a former colleague's session — could
read that farm's village, area, drawing officer's user id, and creation
date with no authorization check at all. Verified directly by reading
the endpoint (not just inferred from the review) before fixing it, and a
new regression test
(`test_get_farm_rejects_user_outside_owner_or_branch` in
`tests/test_farms.py`) proves the fix, mirroring the existing
`test_get_report_rejects_user_outside_owner_or_branch` /
`test_unrelated_user_gets_404_not_403` tests for the other two endpoints.

**Alternatives considered.** None — this is a straightforward application
of the exact pattern already established and tested for the two sibling
endpoints in this same milestone; no design choice to weigh.

**Trade-offs.** None identified — strict correctness fix, no behavior
change for legitimate same-owner/same-branch access.

**Future migration path.** None anticipated. This closes the gap; any
future new resource-scoped `GET` endpoint should use
`user_can_access_owned_resource` from the start, per the pattern all
three of `farms.py`/`jobs.py`/`reports.py` now share consistently.

---

## M2A-level implementation decisions

### Contract-first frontend API client — `openapi-typescript` + `openapi-fetch`, generated types committed

**Decision.** The frontend never hand-writes a request/response shape for
the backend API. `npm run generate:api` runs `openapi-typescript` against
the backend's live `/openapi.json` and writes `frontend/src/lib/api/
schema.d.ts`; `frontend/src/lib/api/client.ts` wraps `openapi-fetch`'s
generated client with bearer-token injection and a 401 → clear-session
interceptor. The generated file is committed (not gitignored) so a fresh
checkout typechecks without a running backend.

**Reason.** Extends the project's end-to-end typing discipline (Pydantic
on the backend, TypeScript on the frontend — see the FastAPI/Next.js
entry above) across the network boundary. Without this, every response
shape is hand-typed twice — once by the backend's Pydantic schema, once
by a frontend developer reading the response — and the two drift
silently the moment either side changes. With it, a backend schema
change that isn't matched on the frontend fails the frontend *build*,
not a runtime bug discovered in the demo.

**Alternatives considered.** Hand-written TypeScript interfaces per
endpoint (the common default, but exactly the drift risk above); a full
codegen client (e.g. `openapi-generator`'s TypeScript-axios target,
heavier generated surface, class-based client that fits this project's
functional/hooks style less naturally than `openapi-fetch`'s thin
fetch-shaped wrapper).

**Trade-offs.** The generated schema must be regenerated by hand
(`npm run generate:api` against a running backend) whenever the backend's
OpenAPI shape changes — no watch-mode automation in M2A. Acceptable at
this team size; worth automating (a pre-commit hook or CI check) if a
second frontend developer joins.

**Future migration path.** None anticipated — this is the intended
long-term pattern for every new endpoint, not an M2A-specific choice.

---

### Bearer token in `localStorage`, not an httpOnly cookie

**Decision.** The frontend stores the session (JWT + role + officer name)
in `localStorage` (`frontend/src/features/auth/session.ts`), attached to
every request via an `Authorization: Bearer` header.

**Reason.** The backend already issues a bearer JWT (M0/M1); a
`localStorage`-based SPA client is the natural, lowest-effort consumer of
that exact contract, and matches the M2A specification's explicit pilot
posture: a controlled, small-scale demo/pilot for a handful of named
the pilot bank's officer accounts, not a public-internet deployment.

**Alternatives considered.** An httpOnly-cookie-based BFF (backend-for-
frontend) session, which closes the XSS-exfiltration exposure a
`localStorage` token has by construction — the objectively more secure
long-term answer, deliberately not built now because it requires a
backend session/cookie-issuing change out of M2A's scope (a
Next.js-only frontend milestone), not just frontend work.

**Trade-offs.** A successful XSS against this frontend can exfiltrate an
officer's active session token. Mitigated in the near term by the
pilot's small, controlled user base and the absence of any user-supplied
HTML rendering path in M2A's screens (search results and report data are
all structured/typed, never raw HTML injection points). This is
accepted, named technical debt, not an oversight.

**Future migration path.** Before any deployment beyond the controlled
pilot (a public demo URL, additional banks, etc.), replace with a
cookie-based BFF session: the backend issues an httpOnly, `SameSite`
cookie instead of a bearer token in the login response body, and the
Next.js server (via Route Handlers or middleware) forwards it to the API
server-side. Tracked explicitly here so it is a scheduled successor, not
a forgotten gap.

---

### CORS — single explicit frontend origin, no wildcard

**Decision.** `backend/app/main.py` adds `CORSMiddleware` allowing
exactly one origin, read from the new `FRONTEND_ORIGIN` setting
(`backend/app/core/config.py`, defaulting to `http://localhost:3000` for
local dev) — never `allow_origins=["*"]`.

**Reason.** M2A's Next.js frontend is a separate origin from the FastAPI
backend, so the browser refuses every cross-origin request without a
CORS policy. A wildcard origin is the common shortcut, but this API
authenticates via a bearer token in the `Authorization` header — while a
wildcard's practical risk is lower without cookie-based credentials, an
explicit single origin costs nothing extra and removes the question
entirely rather than reasoning about it later.

**Alternatives considered.** `allow_origins=["*"]` (rejected per above);
a hardcoded origin string instead of a setting (rejected — would need a
code change, not a config change, to run the frontend on a different
port or a deployed URL later).

**Trade-offs.** None identified.

**Future migration path.** When a deployed (non-localhost) frontend URL
exists, `FRONTEND_ORIGIN` is one environment variable to update — no
code change.

---

### Real Latur village dataset sourced from OpenStreetMap, not Bhuvan/LGD

**Decision.** The M0 placeholder fixture (4 invented "Sample Village N"
rows) is replaced with 872 real admin boundaries — 1 state, 1 district,
10 talukas, 860 villages — for Latur district, built by
`backend/scripts/fetch_latur_villages_osm.py` from OpenStreetMap data and
loaded via the existing `load_admin_boundaries.py`. State, district, and
taluka are real OSM administrative *polygons* (cross-checked against the
`ref:LGD:*` codes embedded in their OSM tags, which trace to India's
official Local Government Directory). Villages are real OSM place
*names and point locations* (`place=village`/`town`/`city` nodes,
point-in-polygon assigned to their real containing taluka) — each
wrapped in a small synthetic ~150m square, since `admin_boundary.geometry`
is a `NOT NULL MULTIPOLYGON` column and no schema change was in scope for
this milestone. The square is a standard GIS placeholder-extent
technique; it is not a claim about the village's true cadastral shape.

**Reason.** Verified directly, not assumed: OpenStreetMap has real
polygon boundaries for Latur district and its 10 talukas, but **zero**
village-level administrative polygons anywhere in the district (confirmed
with a district-wide Overpass count query, not a spot check). India's
authoritative village boundaries live in Bhuvan/ISRO's government GIS
portal, which has no scriptable bulk-download API reachable from this
environment — acquiring it is a manual, out-of-session task. Rather than
ship the M2A demo against 4 fake village names (which fails the demo's
actual purpose — an officer searching for a village they recognize) or
block P1 entirely on external data delivery, this is the deliberate
middle ground: every name, taluka/district assignment, and approximate
location is real and independently checkable (e.g. Killari — the 1993
Latur earthquake epicenter — correctly resolves to Ausa taluka at its
real coordinates); only the polygon *shape* for villages is synthetic.

**Alternatives considered.** Waiting for a real Bhuvan/LGD export before
starting P1 (blocks the milestone on an external, manual data-acquisition
task with no committed timeline); keeping the M0 sample fixture's 4
invented villages (fails the demo's own purpose); a bare `Point` geometry
for villages (rejected — would require changing `admin_boundary.geometry`
off `NOT NULL MULTIPOLYGON`, a schema change out of P1's scope, for a
data-quality improvement the map/search flow doesn't actually need yet,
since Blueprint §05 only requires a *centroid* for search/map-recenter,
not a rendered boundary — the boundary-overlay layer is already deferred
to M2B in the approved M2A spec).

**Trade-offs.** Village *boundary shapes* are not real — acceptable
because M2A never renders them (search returns only a centroid; the
overlay layer is M2B+). Coverage depends on OSM's community-contributed
place-node data for rural Marathwada, which is broad (860 villages
across all 10 talukas) but not guaranteed complete against LGD's full
official village count — a village an officer searches for during the
pilot could, in principle, be missing. This is named, tracked debt, not
a silent gap.

**Future migration path.** Full official coverage and real village
polygons: source a real Bhuvan/LGD export and point
`load_admin_boundaries.py --file` at it — zero code change, per the
loader's existing source-agnostic design. Tracked as pre-pilot data
debt, to close before the actual pilot bank engagement (M6), not before the
M2A demo.

---

### `load_admin_boundaries.py` existence check now scoped to the full `(level, name, parent_id)` tuple

**Decision.** The loader's already-loaded check
(`backend/scripts/load_admin_boundaries.py`) now matches on
`level == X AND name == Y AND parent_id == Z`, not `level == X AND name
== Y` alone.

**Reason.** Real bug, found running the loader against real data for the
first time: 51+ real Latur village names repeat across different talukas
(e.g. more than one village named "Wadgaon" — a genuinely common pattern
in Indian administrative data, exactly what the Blueprint's `village_branch_lookup`
design already anticipated: "duplicate village names across talukas...
requiring the fuller tuple, not fuzzy string guessing"). The loader's
own existence check didn't follow that same rule — checking level+name
only caused it to treat a real, distinct village in a second taluka as
an already-loaded duplicate of the first and silently skip inserting it.
59 real villages were dropped on the first load attempt before this fix;
zero were dropped after. The table's own unique constraint
(`uq_admin_boundary_level_name_parent`) already covers `(level, name,
parent_id)` — the loader's check simply hadn't matched it. Never
triggered before because the M0 sample fixture had no repeated names at
any level.

**Alternatives considered.** None — this is a straightforward correctness
fix matching the loader's check to the table's own constraint and the
Blueprint's own stated business rule; no design choice to weigh.

**Trade-offs.** None identified.

**Future migration path.** None anticipated.

---

### Mapping stack implementation — MapLibre GL JS + Terra Draw + Esri World Imagery (M2A P2)

**Decision.** The interactive farm map (`components/map/base-map.tsx`,
`features/farm-drawing/farm-map.tsx`) is built on MapLibre GL JS with
Terra Draw (`terra-draw` + `terra-draw-maplibre-gl-adapter`) for polygon
drawing/editing, over Esri World Imagery raster tiles. The tile URL is
env-swappable (`NEXT_PUBLIC_MAP_TILE_URL`, `src/config.ts`); Esri's
required attribution is always rendered. Drawing enforces a
single-polygon rule (leaving draw mode the moment the first boundary
closes), rejects self-intersections at finish/commit via Terra Draw's
`ValidateNotSelfIntersecting`, and allows vertex-level editing only —
whole-feature dragging is disabled, since sliding an entire boundary off
its field is a data hazard with no legitimate use.

**Reason.** Stack chosen in the approved M2A specification (GPU-rendered
modern cartography; Terra Draw is the actively maintained drawing layer;
MapLibre's vector data-driven styling is also what M4's choropleths
need, so this choice is made once). Officers must recognize their actual
field, so a real satellite basemap is non-negotiable; Esri World Imagery
is free with attribution for dev/demo use.

**Alternatives considered.** Leaflet (+leaflet-draw): simplest, but
raster-first with effectively unmaintained drawing plugins, and reads
dated for a product whose first impression is the map. OpenLayers: the
most capable and least approachable — its power (projections, WMS,
topology editing) is exactly what this MVP doesn't need, paid for in
learning curve and bundle weight.

**Trade-offs.** (1) `/farms/new` first-load JS grew to ~460kB — that is
MapLibre's GL engine; accepted because the map *is* the page, and a
dynamic import would only defer the cost, not remove it. (2) Esri World
Imagery's terms require review before commercial deployment — a named
line item on the commercial checklist next to the GEE license; the URL
being one env variable makes a provider swap a config change. (3) GL
canvas contents are not directly assertable by E2E tooling; `BaseMap`
therefore sets `data-map-loaded` / `data-map-idle` attributes from
MapLibre's own lifecycle events ("idle" = all in-view tiles fetched and
rendered) as a permanent testability hook — this is how map health was
actually verified in P2, and what the M2B Playwright suite will assert.
(4) Found during live verification: throttling draw-event state reports
with `requestAnimationFrame` silently freezes in hidden/backgrounded
tabs (browsers stop delivering frames entirely); replaced with a 50ms
timer throttle, which keeps firing (clamped) in hidden tabs.

**Future migration path.** Provider swap = one env variable. The
boundary-overlay layer (village polygons on the map) is deferred M2B
scope per the approved spec, and slots into `BaseMap` as an additional
source/layer without structural change.

---

### Client-side polygon area is a preview from `@turf/area` — never the recorded value

**Decision.** The live area shown while drawing (`lib/geo.ts`
`ringAreaHectares`, displayed as "X ha (Y acres)") is computed
client-side with `@turf/area` (geodesic). The value recorded on the farm
row remains exclusively the server's PostGIS `ST_Area` computation
(`app/api/farms.py`), exactly as M1 built it.

**Reason.** Blueprint §05: the client's number is a preview for the
officer's confirmation decision, "never trusted as the record of truth."
Officers need immediate feedback while tracing; the server needs to stay
the sole authority. `@turf/area` implements the same class of geodesic
algorithm PostGIS uses on geography types, so preview and record agree
closely — but if they ever disagree, the server's number is the record,
and the UI copy says so explicitly.

**Alternatives considered.** Round-tripping each draw change to the
server for authoritative live area (correct number, but a network call
per vertex drag — unacceptable latency for a drawing interaction, and
pointless load); planar shoelace area computed by hand (wrong by ~2-3%
at field scale in WGS84 degrees without projection handling — a
misleading preview is worse than none).

**Trade-offs.** One small, well-scoped dependency (`@turf/area`).

**Future migration path.** None anticipated.

---

### Vitest as the frontend unit-test runner

**Decision.** `vitest` (node environment, no DOM) runs the frontend's
pure-logic tests (`src/**/*.test.ts` — geometry construction, geodesic
area sanity, formatting), via `npm test`.

**Reason.** P2 introduced the first frontend logic that can be silently
wrong (ring closing, backend-contract geometry shape, m²→ha conversion,
ha→acres display). The approved M2A testing strategy already named
Vitest for exactly this class of test; P2 is simply the phase where the
need materialized.

**Alternatives considered.** Jest (heavier setup with Next/ESM, slower,
no advantage here); deferring all testing to manual E2E (leaves unit
conversions — the classic silent-failure class — unguarded).

**Trade-offs.** None significant — node-environment-only keeps it fast;
jsdom/component testing is deliberately excluded until something needs
it (manual E2E covers browser behavior per the M2A spec).

**Future migration path.** The M2B Playwright E2E suite complements
(not replaces) these tests.

*(Superseded in part by the M2A P3 entry below: one jsdom-based
integration test now exists, for the specific reason documented there.
The node-environment default for pure-logic tests stands.)*

---

### Real-stack integration test for the farm-creation flow, with the GL map as the only mocked seam (M2A P3)

**Decision.** `page.integration.test.ts` (jsdom, opt-in via pragma)
renders the real `/farms/new` page component and drives the real local
stack end to end: real login, real `GET /villages` (through the real
300ms debounce), a real `POST /farms` over HTTP, asserting the saved
panel displays the *server's* recorded area, that the map locks after
saving, and that the workflow restarts. Exactly one seam is mocked:
`FarmMap`, whose mock fires the same `onPolygonChange(ring, complete)`
callback with a real Killari-area ring that the real map fires on
drawing completion. The test skips cleanly (like the backend suite's
PostGIS-gated tests) when the local stack or the seeded test officer
isn't available.

**Reason.** A WebGL map cannot initialize without rendered animation
frames — jsdom has none, the embedded preview pane delivers none (P2
finding), and a real browser delivers none while its window is hidden
or minimized. During P3 verification this made human-in-the-loop
confirmation unreliable in practice: three user-reported successful
save runs produced zero database rows (ground truth checked after each),
while the API path proven directly via curl worked perfectly. Rather
than continue a flaky manual loop, the click-through gap was closed
with a repeatable machine-run test of everything downstream of the
canvas. The canvas-drawing seam itself was verified in a real visible
browser during P2 (map load + all-tiles-rendered via the data-map-idle
hook; draw/edit flow confirmed hands-on).

**Alternatives considered.** Continuing user-driven verification
(demonstrated unreliable here, and unrepeatable); Playwright now
(planned for M2B — heavier install, and it would face the same
GL-in-headless constraints without extra flags/GPU setup); mocking the
HTTP layer instead of the map (tests far less — the point is proving
the real request/response/persistence path).

**Trade-offs.** (1) The test depends on the local stack (backend +
PostGIS + a seeded `p3-e2e@example.com` officer) and silently skips
without it — CI (M5) must provision that stack for the test to count
there. (2) Each run persists one farm row for the test officer in the
dev database. (3) Written with `React.createElement` instead of JSX:
Next.js pins tsconfig `"jsx": "preserve"`, and this Vitest runs on
rolldown-vite, where the fix is the `oxc.jsx` config override (added)
— but `@vitejs/plugin-react` itself is blocked by a Babel 7-vs-8 peer
conflict via the shadcn CLI package, so the test file avoids JSX
syntax to stay dependency-free.

**Future migration path.** M2B's Playwright suite adds true
click-the-canvas coverage in a real headed browser (using the
`data-map-loaded`/`data-map-idle` hooks from P2); this integration test
remains as the fast, stack-level regression check.

---

### Empty-month guard in the GEE adapter — `ee.Algorithms.If(contains)` instead of a bare `Dictionary.get` (M2A P4)

**Decision.** Every per-period `reduceRegion(...).get(band)` lookup in
`gee_provider.py` (index series, rainfall series, rainfall climatology)
is wrapped in `ee.Algorithms.If(stats.contains(band), stats.get(band),
None)`, yielding null — which flows into the existing skip-this-month
path (`_parse_monthly_features`) — whenever a compositing month contains
zero source images.

**Reason.** REAL production bug, found by M2A P4's live end-to-end run
(the first-ever full report generated through the UI pipeline): the
report window ends at the previous calendar-month boundary, but CHIRPS
rainfall publishes with a multi-week lag, so the window's most recent
month had zero published images. An empty collection's `sum()` is a
band-less image, `reduceRegion` then returns an *empty dictionary* (not
a null-valued key), and the server-side `Dictionary.get` threw
"Dictionary does not contain key: 'precipitation'", failing the entire
job. M1's live tests never caught it because they all queried
fully-published past windows — the job pipeline was the first caller to
touch a current-boundary window. The same latent crash existed in
`get_index_time_series` for any scene-less month and is fixed
identically.

Two implementation notes worth recording: (1) the obvious fix —
`stats.get(band, None)` — does NOT work: the Earth Engine Python client
prunes a `None` default from the serialized call, silently reproducing
the bare `.get`; verified by running the regression test against live
GEE, which still failed. (2) Any non-null default (0, a sentinel) would
fabricate a rainfall/index reading for an unpublished month — exactly
the "no data must never become measured zero" rule the parser already
enforces — so the `If(contains)` null-yield is the only correct shape.

**Alternatives considered.** Shortening the lookback window to end one
extra month earlier (hides rather than fixes — CHIRPS lag is variable,
and Sentinel-2 gaps can produce empty months anywhere in the window);
padding empty months with a zero-band image (fabricates data).

**Trade-offs.** None — a month with no published data is now treated
identically to a fully cloud-masked month, the sparse-data path the
engine's confidence score was designed around from M1 (the live-verified
report shows confidence 94.4%: exactly one skipped month out of 36).

**Future migration path.** A live regression test
(`test_rainfall_series_over_a_current_window_skips_unpublished_months`)
uses the report generator's exact window arithmetic, so this class of
bug fails the suite rather than a demo.

---

### Report dashboard — recharts for time series; all prose from fixed templates over engine outputs (M2A P5)

**Decision.** The report page renders from a single `GET
/reports/{id}` whose payload was extended to carry the farm context
(geometry, village/taluka/district, officer, area) and the monthly
observation series alongside the existing score/factor data. Charts
use recharts (NDVI line, rainfall bar; one validated hue per
single-series chart, risk-band status colors never used for data
series). Every sentence of prose — the overall narrative
(`narrative.ts`) and the per-factor driver lines (`drivers.ts`) — is a
fixed template composed ONLY from the engine's persisted outputs and
`raw_inputs`: highest/lowest factor is stated as an arithmetic fact,
never a causal claim, and a missing raw input shortens the sentence
instead of guessing. The farm map (`report-map.tsx`) is read-only:
saved boundary on satellite imagery, fitted with padding, no drawing
controls. The lineage footer names the three source datasets, the
model version, generation time, and confidence.

**Reason.** Blueprint §08 — the report is decision support for a
credit officer, so it must never assert a cause the backend didn't
compute; template-only prose makes "no invented causes" testable
(`report-text.test.ts` pins the exact sentences). One payload keeps
the dashboard renderable from a single fetch with no client-side
joins. recharts is React-native and SVG-based, so chart output is
assertable in jsdom without a canvas.

**Alternatives considered.** Hand-rolled SVG charts (more code to
maintain for two chart types); LLM-generated narrative (unverifiable,
can invent causes — rejected outright for a lending document);
separate endpoints for series/farm context (extra round trips, shared
loading states for no benefit).

**Trade-offs.** recharts adds a dependency (~100KB gz) for two chart
types; fixed templates read plainly and are English-only until the
localization pass. Live verification of this phase (score 42/100
moderate, confidence 97%, 35-month series, Killari farm) matched the
API payload field-for-field; the one defect found was a hardcoded
"th" ordinal suffix ("31th percentile"), fixed with a regression
test.

---

### PDF export — server-side reportlab render from the shared payload; prose templates mirrored and pinned by twin tests (M2A P6)

**Decision.** `GET /reports/{id}/pdf` (Blueprint §API) renders the PDF
server-side with reportlab + matplotlib from the same
`_load_report_response()` the JSON endpoint uses — one loader, one
owner-or-branch guard, so the two views can't diverge on data or
access. The map panel stitches the SAME Esri World Imagery tiles the
dashboard renders (config.ts MAP_TILE_URL) and draws the boundary in
the same style; on tile-fetch failure it degrades to the real boundary
on a neutral panel with an explicit "imagery unavailable" note — never
fabricated content. All prose comes from `report_text.py`, a
deliberate Python mirror of `narrative.ts`/`drivers.ts` (including a
`js_round` matching JS `Math.round` half-away-from-zero, so PDF and
dashboard can't disagree on x.5 values); `test_report_text.py` asserts
the IDENTICAL strings `report-text.test.ts` asserts, so a template
change on one side fails the other side's copy of the test. Rendered
PDFs are cached to disk keyed `{risk_score_id}-v{PDF_LAYOUT_VERSION}`
— a risk score row is immutable once computed, so the cache never
expires; layout changes bump the version constant instead of
invalidating files. Content assertions in `test_report_pdf.py` go
through pypdf text extraction — what a reader of the document sees.

**Reason.** Blueprint §08: the PDF is what actually enters the loan
file, rendered from the same payload as the dashboard ("two views of
one artifact"). Server-side rendering keeps the artifact reproducible
and cacheable per report id, independent of any officer's browser.

**Alternatives considered.** Headless-Chromium printing of the actual
report page (pixel-perfect parity and no template mirroring, but adds
a browser runtime + auth plumbing to the server, and P2/P3 already
established WebGL maps don't initialize headless — the map would need
a static fallback anyway); WeasyPrint (HTML→PDF, but requires GTK
native libraries on Windows dev machines); client-side jsPDF (ties
the loan-file artifact to the officer's browser and can't be cached
or later fetched by auditors server-side).

**Trade-offs.** (1) The prose templates exist in two languages,
mirror-pinned by twin test files — accepted cost of Python-side
rendering; the M4 portfolio report engine reuses this renderer, so
the mirror pays for itself. (2) First render fetches ~15–24 imagery
tiles (observed ~13 s live, incl. matplotlib's first import); every
subsequent request is a disk read. (3) +4 backend deps (reportlab,
matplotlib, pillow, tzdata — the last because report timestamps
render in IST, the bank's timezone, and Windows has no system tz
database). Live-verified end to end: browser download of the Killari
report (2.7 MB, 2 pages) matches the dashboard field-for-field.

---

## M2B-level implementation decisions

M2B is the Product Design v2 redesign (`docs/Product_Design_v2.md`,
approved 12 Jul 2026): TerraRisk from a one-shot assessment funnel to a
workspace-first commercial SaaS product, phased P7 (Workspace) → P8
(Honest Progress) → P9 (Evidence & Explainability) → P10 (Workflow
Hardening) → P11 (Final UX Polish). The M1 backend architecture, GEE
pipeline, Risk Engine, and PDF renderer are the approved foundation and
are not redesigned — M2B additions are strictly additive reads over
already-persisted tables, no new writes, no schema migration.

### Workspace list endpoints — batch queries over existing tables, SQL-expression twin of the existing owner-or-branch rule (M2B P7)

**Decision.** Four new read-only endpoints back the workspace screens
(Product Design v2 §7): `GET /farms` (every farm the caller owns or
shares a branch with, each carrying its latest completed assessment and
current in-flight job if any), `GET /farms/{id}/assessments` (a farm's
full append-only score history plus its active job — the Farm detail
timeline), `GET /jobs` (every farm-report run with farm context
resolved, doubling as the Assessments index), and `GET /reports` (every
issued report — the auditor/manager entry point, one row per
`risk_score`, deliberately not collapsed to latest-per-farm the way the
Farms index is). All four are scoped by a new `owned_or_branch_filter()`
helper in `app/api/deps.py` — the SQL-expression twin of the existing
`user_can_access_owned_resource()` used by the single-resource GET
endpoints, so both code paths enforce the identical branch-scoped
visibility rule (Product Design v2 §5) rather than two independently
maintained ones. `GET /jobs` and `GET /farms` resolve the
`Job.entity_id` polymorphism the P4 background-task design already
established — while a job is in flight or failed, `entity_id` is the
farm_id; once DONE it's overwritten with the resulting `risk_score_id`
— by batch-fetching both shapes and merging in Python, matching this
codebase's existing no-window-functions style at pilot data volume
(dozens to low hundreds of rows, not millions).

**Reason.** Product Design v2 principle P1 ("the workspace is the
product; the wizard is a feature") and the M2A review finding that
follows from it: today's app has no way back to any prior work once the
report page is left, which reads as a scripted demo regardless of how
real the underlying pipeline is. These four endpoints are the entire
backend surface the workspace needs — no new tables, no new write paths,
purely read-models over data every prior phase already persists.

**Alternatives considered.** A single combined `/workspace` endpoint
returning everything at once (rejected — couples four independently
cacheable, independently paginatable screens into one brittle response
shape, and none of the four lists share a natural join key cleanly
enough to justify it); pushing the farm/score merge into a single SQL
query with window functions (rejected for now — adds a query pattern
this codebase doesn't otherwise use, for a saving that only matters
past pilot scale; revisit if a branch's farm count grows beyond a page).

**Trade-offs.** No pagination yet on any of the four lists (matches
every other endpoint in this codebase — none paginate) — acceptable at
DCCB-pilot branch scale, must be added before a multi-branch rollout
with hundreds of farms. `GET /reports` is O(all issued reports in
scope) with no date/band filtering yet; filtering is UI-only until a
query-param contract is worth adding (P9/P10 territory once the Reports
screen has real filter UI to drive it).

---

### 409-conflict payload carries the in-flight job id (M2B P7 · B5)

**Decision.** `trigger_report`'s existing 409 (a report already running
for this farm — the `pg_advisory_xact_lock` TOCTOU fix from M2A) now
raises `HTTPException(409, detail={"message": ..., "job_id": ...})`
instead of a bare string. The global exception handler
(`app/main.py`) was extended to accept either a string or a dict
`detail`: a dict's `"message"` key becomes the envelope's `message`
field as before, and any other keys are merged into the same `error`
object — so every existing caller that only ever reads `error.message`
is unaffected, while this one call site gains a structured `job_id` the
frontend can route to directly instead of just displaying failure text.

**Reason.** Product Design v2 §7.2: hitting the 409 must not be a dead
end. The advisory lock already knows exactly which job is in flight —
surfacing its id turns "you can't start a new one" into "here's the one
already running," matching the honest-progress principle (P2) that a
conflict on real concurrent work should route to that work, not just
report failure.

**Trade-offs.** None — purely additive to the error envelope; verified
by both the existing `test_trigger_report_rejects_duplicate_in_flight_request`
(still 409, unchanged shape assertions) and a new test asserting the
`job_id` round-trips, live-verified with two genuinely concurrent
triggers over real HTTP (not just the ASGI test transport) against the
live dev database, producing a real 202/409 pair with the 409 carrying
the exact id the 202 returned.

**Bug found and fixed during implementation.** The first cut of
`owned_or_branch_filter()` called `current_user.branch_id.is_not(None)`
— but `current_user` is an already-loaded ORM *instance* here, not a
mapped class or alias, so `.branch_id` is a concrete Python value
(`UUID | None`), and calling a SQLAlchemy column method on it raised
`AttributeError` on every branch-scoped list request. Fixed by
resolving the branchless case in Python (`if current_user.branch_id is
None: return owner.id == current_user.id`) and only building a SQL
clause from a real branch id — caught by the new test suite before any
live traffic, not after.

---

### Workspace shell and route restructure — the wizard becomes one action among several (M2B P7 frontend)

**Decision.** The one-shot funnel (`/farms/new` → `/reports/status/{id}`
→ `/reports/{id}`, with `/` doing nothing but redirecting) is replaced
by a persistent workspace shell (`components/workspace/app-shell.tsx`):
a left rail on desktop, a Sheet-based drawer behind a menu button on
mobile, both showing the same four destinations (Overview, Assessments,
Farms, Reports), a persistent "+ New assessment" action, a live
activity chip (count of pending/running assessments, polled only while
something is actually in flight — `useAssessments()`'s existing
adaptive `refetchInterval`), and a user chip with role + sign-out.
Routes move to match: `/farms/new` → `/assessments/new`,
`/reports/status/{jobId}` → `/assessments/{jobId}` (both `git mv`'d,
preserving history and the P3 integration test unchanged except for
its new location), and four new index/detail routes — `/` (Overview),
`/assessments`, `/farms` + `/farms/{id}`, `/reports` — read entirely
from the M2B P7 backend list endpoints. `(app)/layout.tsx` gains a real
loading state (previously `return null` while `!isInitialized`) and
deep-link preservation: an unauthenticated visit to any route now
redirects to `/login?next={path}` and returns there after sign-in
(`login-form.tsx`, plain `URLSearchParams` rather than
`useSearchParams()` — avoids a Suspense-boundary requirement on a page
that would otherwise need one purely for this). The `next` value is
validated to be a same-origin path (`startsWith("/")`,
`!startsWith("//")`) before use, closing the open-redirect a raw query
value would otherwise permit.

Farm detail's re-assess action reuses `useTriggerReport()`; a genuine
409 (another tab/officer already re-assessing this farm) is caught via
a new `ReportTriggerConflictError` carrying the backend's `job_id`
(B5) and routed straight to `/assessments/{that job}` instead of
surfacing raw failure text — the actual UI expression of the backend
decision two entries above.

**Reason.** Product Design v2 principle P1 ("the workspace is the
product; the wizard is a feature") and the review finding it was
written to fix: the funnel read as a scripted demo — leaving the report
page stranded the officer with no way back to any prior work — despite
every number in it being real and live-verified since P4. This phase
makes nothing new computationally; it makes what already exists
reachable and resumable.

**Alternatives considered.** Keeping `/farms/new` as the canonical path
and aliasing `/assessments/new` to it (rejected — a redirect alias is
exactly the kind of leftover seam the redesign is meant to remove, and
`git mv` costs nothing); a notification-center/toast system for the
activity signal instead of a persistent header chip (deferred — Product
Design v2 §10 explicitly reserves this for M5, once there are enough
event types to justify one); `useSearchParams()` for the `next` param
(rejected — would require wrapping `/login` in a Suspense boundary for
a single query read that a browser API answers just as well).

**Trade-offs.** Farm detail's wireframe (Product Design v2 §7.4) shows
a read-only boundary map; neither `GET /farms` nor `GET /farms/{id}`
carries geometry (only a completed report's payload does — the M2A P5
enrichment lives on `ReportResponse`, not `FarmResponse`). Rather than
reopen the just-verified-and-committed backend mid-frontend-pass for a
field the design doc's own §8 backend-additions list (B1–B9) never
actually calls out, or show placeholder map chrome for data that
doesn't exist (explicitly forbidden — "no placeholder content, ever"),
this phase ships Farm detail without that section. Flagged as an open
gap for P8/P9 to close (`GET /farms/{id}` gaining `geometry` is a
one-line additive schema change when picked up).

**Bugs found and fixed during live verification.** (1) A `Button
render={<Link href="/reports" />}` on the Overview page rendered a
Base UI button primitive as an anchor element, which Base UI flags at
runtime (`nativeButton` mismatch) since the component can no longer
guarantee native button semantics — fixed by styling the `Link`
directly with `buttonVariants()`, the pattern already used everywhere
else in this codebase (`app-shell.tsx`'s own nav links), rather than
wrapping it in `Button`. (2) A Tailwind `capitalize` class applied to
an entire sentence ("running · started 1m ago") capitalized every
word's first letter, not just the status word — Overview's in-progress
card read "Started 1m Ago"; fixed by scoping `capitalize` to a nested
span around just `{item.status}`.

**Live verification.** Full workspace walkthrough against the real dev
stack: deep-link preservation (unauthenticated visit to a real report
URL → `/login?next=...` → back on that exact report after sign-in,
confirmed via `window.location.pathname`); Overview/Farms/Assessments/
Reports all rendering real persisted data (including farms/reports
accumulated across every prior phase's live verification); the mobile
drawer opening and auto-closing on navigation. The 409-conflict routing
was verified with a genuine race, not a simulation: two separate
browser tabs firing "Re-assess" on the same farm within the same
second — one received the 202 and created the job, the other hit the
409, extracted its `job_id`, and both tabs converged on the identical
resulting report URL; the farm's history afterward showed exactly one
new entry, confirming the M1 advisory lock prevented a duplicate score
even under real concurrent UI action, not just concurrent curl
requests. A console-error investigation during this pass (repeated
`nativeButton` warnings that persisted across reloads and even a full
dev-server restart) turned out to be the browser tool's console-message
buffer never clearing within a long-lived tab — confirmed via a
genuinely fresh tab showing zero errors after the real fix landed; a
false lead worth recording so a future session doesn't chase the same
ghost.

**Tests.** Frontend: 32/32 (26 existing + a new `errors.test.ts`
covering `extractApiErrorMessage` and the new `extractConflictingJobId`
against both well-formed and malformed error envelopes). ESLint clean,
`tsc --noEmit` clean, production build clean (10 routes, no route
conflicts from the restructure). Backend untouched in this phase —
still 117/117 from the prior commit.

---

### Honest per-stage execution timeline — job.progress JSONB, one entry per real pipeline checkpoint (M2B P8, backend addition B2)

**Decision.** `Job` gains a nullable `progress` JSONB column
(`0003_job_progress` migration), written exclusively by a new
`ProgressTracker` (`app/services/reporting/progress.py`) that
`report_generator.py`'s pipeline calls at eleven points —
`start()`/`complete()` bracketing each real operation, `fail_current()`
in the existing top-level `except`. The eleven stages, in the exact
order the pipeline executes them: `preparing`, `loading_geometry`,
`vegetation_observations` (NDVI), `surface_water_observations`
(MNDWI), `crop_moisture_observations` (NDMI), `rainfall_observations`
(CHIRPS), `rainfall_climatology`, `water_history` (JRC), `scoring`
(the single `RiskEngine.compute()` call), `saving`, `completed`. Each
stage row carries `{id, title, status, started_at, completed_at,
metadata}`; the four observation-fetch stages additionally carry
`{source: "cache"|"fetched", months: N}` from the exact same
cache-check branch the pipeline already had (B7 — cache provenance was
free once the branch existed, just previously invisible outside a log
line). `JobStatusResponse` exposes this as a typed `JobProgress`
(`app/schemas/job.py`) via Pydantic's `from_attributes` coercion of the
raw dict — confirmed working end to end through the real HTTP response,
not just the ORM layer, in `test_reports.py`.

Frontend: the Assessment Run page (`/assessments/{jobId}`) replaces its
flat `STATUS_COPY`-driven card with `AssessmentTimeline`
(`features/assessment/`), a pure renderer of `job.progress.stages` —
check/spinner/X/dashed-circle markers per status, a live-ticking
elapsed counter for the running stage (computed from its real
`started_at`, re-rendered on a 1s interval — the ONLY client-side
"clock," never a percentage or ETA), and either a cache/fetch label or
a real duration for completed stages. `STATUS_COPY` itself is now dead
(nothing else referenced it) and was deleted rather than left as
unused cruft; `isTerminalStatus` — still used by the polling hook —
was kept. Retry (on a `failed` job) reuses `useTriggerReport()` with
the failed job's `entity_id` (guaranteed to still be the farm_id — P4's
polymorphism only overwrites `entity_id` on DONE) and the existing
`ReportTriggerConflictError` 409-routing from P7's Farm detail —
one code path, two callers, never duplicated.

**Reason.** Product Design v2 P2 ("show the machine working, never a
spinner") and B2/B7 from the backend-additions table. The prior status
page showed one hardcoded sentence for the entire 2–4 minute run
regardless of what was actually happening — exactly the "scripted
demo" tell the whole redesign exists to remove, despite the pipeline
underneath being completely real since M1.

**Deliberate deviation from the founder's illustrative 12-stage
example** (documented here per that message's own instruction: "every
visible stage must correspond to an actual checkpoint"). The example
listed "Computing vegetation indicators," "Computing moisture
indicators," "Computing rainfall anomaly," "Calculating factor
scores," and "Running TerraRisk engine" as five separate stages. In
the real code there is exactly ONE synchronous call —
`RiskEngine.compute(bundle, config)` — that computes all four factor
scores and the composite score together, atomically, from data already
fetched. Inventing four additional stages around fragments of one
function call would have been precisely the fabricated-checkpoint
problem this phase forbids, so they collapse into the single `scoring`
stage. Conversely, NDVI/MNDWI/NDMI — which the example bundled toward
"vegetation" and "moisture" — are kept as three fully separate stages,
because each is an independently cached-or-fetched Earth Engine call
with its own real cache outcome; merging them would have hidden honest
information (a partial cache hit on just one of the three) rather than
inventing anything. Net: 11 real stages, not 12 illustrative ones —
fewer where the example implied a granularity that doesn't exist in
the code, one more granular where collapsing would have lost a real
signal.

**Retry semantics.** No "resume the same job" concept exists anywhere
in this codebase — jobs are immutable once terminal. Retry triggers a
genuinely new job via the existing `POST /farms/{farm_id}/reports`,
which — exactly as Journey C describes — benefits from the SAME
per-farm cache the pipeline already had: stages already cached from
the failed attempt complete near-instantly and say so, while only the
stage that actually failed (and anything after it) does real work
again. No new backend endpoint needed.

**Alternatives considered.** WebSockets/SSE for stage push updates
(rejected per Product Design v2 §8 — polling with backoff already
holds at pilot volume and survives hostile bank network proxies
better; the existing `useJobStatus` poll needed zero changes to carry
the richer payload). A separate `job_stage` table instead of JSONB on
`job` (rejected — the entire timeline for one job is always read and
written as a single unit, never queried stage-by-stage across jobs;
JSONB matches the access pattern and needed no join). Mutating
`job.progress` in place via the ORM attribute (considered and
rejected — SQLAlchemy does not detect nested JSONB mutation without
`MutableDict`; every write in `ProgressTracker` instead reassigns a
brand-new dict object, mirroring the exact fetch-mutate-commit pattern
`_set_job_status` already used, so the two writers stay consistent).

**Trade-offs.** None found. Additive migration (nullable column, no
backfill — pre-existing job rows and non-report job types simply have
`progress = null`, handled gracefully by both the API contract and the
frontend's fallback message). Eleven small commits per pipeline run
instead of the prior two (`RUNNING`, then `DONE`/`FAILED`) — negligible
at pilot volume, and each commit is immediately visible to any session
polling `GET /jobs/{id}`, which is the entire point.

**Live verification.** A newly created, guaranteed-uncached farm's
report was triggered via real HTTP and watched live, both via repeated
`GET /jobs/{id}` polling (captured real per-stage durations: 3.70s/
4.47s/3.45s for the three Sentinel-2 fetches, 0.80s rainfall, 1.27s
climatology, 0.70s JRC — genuine Earth Engine round trips, not
simulated) and directly in the browser, catching the live timeline
mid-run on two separate real triggers (once at the `scoring` stage,
once at `rainfall_climatology`) with the ticking elapsed counter
visibly advancing and real "retrieved (N months)" labels rendering.
A second trigger for the same farm showed every observation stage at
`source: cache` with ~25–31ms durations (vs 3–4.5s fetched) — an
honest, dramatic, truthful speedup — while the two stages with no
cache path (`rainfall_climatology`, `water_history`) still took real
time, exactly as designed. The raw `job.progress` JSONB was inspected
directly in Postgres via `jsonb_pretty` and matched the API response
exactly. The failure + Retry path was verified against a realistic
synthetic failure (a real farm, a hand-inserted `job` row shaped
exactly like the automated
`test_progress_preserves_earlier_completed_stages_when_a_later_stage_fails`
scenario — deliberately not a live-forced GEE quota exhaustion, which
would be reckless to engineer on purpose): the failed stage rendered
distinctly, all four completed stages before it remained visible with
their real cache/fetch data intact, the generic error message and a
job-id support reference displayed, and clicking Retry triggered a
genuinely new real pipeline run for the same farm that this time
completed successfully end to end. Refresh-mid-run reconstruction was
verified by repeated reload attempts at the earliest possible moment
after navigation; the pipeline in this environment consistently
completes in 10–20 seconds — faster than this tool's own round-trip
latency budget for a manual reload-during-a-still-running-job capture
— so the strongest evidence combines two genuine mid-flight
fresh-navigation captures (proving the timeline renders live, accurate,
non-frozen state) with the architectural fact that a reload and a
fresh navigation are the identical code path in this SPA (no
client-only progress state exists anywhere in the Run page — confirmed
by review — so nothing distinguishes the two cases). Every reload
attempt, regardless of timing, landed on the true current backend
state, never a stale one.

**Tests.** Backend: 125/125 (117 prior + 4 pure-unit stage-definition
tests + 4 full-pipeline integration tests — fresh run with fetch
labels, second run with cache labels, missing-farm failure at
`loading_geometry`, and a simulated rainfall-stage failure proving
earlier completed stages stay untouched — plus the existing end-to-end
workflow test extended to assert the HTTP-level `progress` payload
shape). Frontend: 42/42 (32 prior + 4 `duration.test.ts` boundary
cases + 6 `AssessmentTimeline` component tests covering ordering,
cache vs. fetched labeling, plain duration, the pending-stage "nothing
shown" case, the live-ticking counter under fake timers, and the
failed-stage styling). ESLint clean, `tsc --noEmit` clean, production
build clean (`/assessments/[jobId]` grew 1.4 kB → 4.1 kB, no route
changes). `@testing-library/jest-dom` is not a dependency of this
project — component test assertions use plain DOM properties
(`.textContent`, `.className`), matching the one prior integration
test's existing convention, rather than adding a new dependency for
this phase alone.

---

### Evidence & Method tabs, deterministic Recommendation — a genuine bug found and fixed along the way (M2B P9, backend addition B3)

**Decision.** The report page gains two new tabs alongside the existing
dashboard (now "Report"): **Evidence** (observation window, per-index
monthly coverage strips, real Sentinel-2 scene acquisition dates, and
the confidence calculation spelled out arithmetically) and **Method**
(score anatomy — weight × value → contribution → composite, honest
about the floor rule when it fired — band thresholds, factor
definitions, and assumptions & limitations). A new **Recommendation**
block (Assessment Summary / Primary Drivers / Recommended Action) sits
under the verdict on the Report tab, deterministic and keyed only on
`overall_band` + `confidence` + factor scores already in the payload
(`features/report/recommendation.ts`).

Three additive, genuinely-required backend fields make this possible
without any recomputation at read time (Blueprint §03):
`risk_score.observation_window_start/end` (the exact window
`_run_pipeline` queried Earth Engine with, persisted once at compute
time) and `risk_score.weighted_average_score` (the plain weighted
average `RiskEngine.compute()` already calculates internally as a local
variable, now returned on `RiskResult` and persisted — not
re-derived). `ReportResponse` gained `evidence` (window +
`expected_months`, computed by reusing `gee_provider._monthly_periods`
against the persisted window — the identical function the pipeline
itself used, not a reimplementation) and `method` (weights + effective
date, read back from `config_weight` via the already-existing
`weights_version_id` foreign key, plus `floor_threshold` and
`weighted_average_score`). Migration `0004_report_evidence_fields`,
nullable throughout — pre-existing reports simply show less Evidence/
Method detail, never an error.

**A real bug found and fixed, not just a new field.** Product Design
v2 §7.5 promised "the real Sentinel-2 acquisition dates that fed the
composite" from `satellite_observation.source_dates` — a column that
has existed since M1. Investigating what the Evidence tab would
actually show revealed it was **always an empty list**: `GeeProvider.
get_index_time_series`'s `_compute_period` never computed per-image
dates, and `_parse_monthly_features` never read a `source_scene_dates`
field into `IndexObservation` from anywhere. The M1 "data lineage"
promise for scene dates had never been wired up in the real adapter —
only the column existed, not the query filling it. Fixed by having
`_compute_period` aggregate each month's Sentinel-2 images'
`system:time_start` server-side (`aggregate_array` + `ee.Date.format`,
returned in the same `getInfo()` call — no extra round trip) and
`_parse_monthly_features` parse those into `IndexObservation.
source_scene_dates`. `FakeSatelliteDataProvider` updated to populate
deterministic fake dates for the three optical indices, left honestly
empty for rainfall (CHIRPS is a daily gridded product with no discrete
"scene," never fabricated). Rather than ship an Evidence tab with a
silently-broken feature or invent placeholder dates — both explicitly
forbidden by this phase's brief — the actual gap was closed.
Live-verified against real Earth Engine (see below): real dates with
the genuine ~5-day Sentinel-2 revisit cadence.

**Confidence arithmetic, shown honestly, not simplified.**
`RiskEngine._compute_confidence` averages completeness across NDVI,
MNDWI, and NDMI only — rainfall is deliberately excluded (CHIRPS isn't
cloud-limited the same way). The Evidence tab reproduces this exact
formula from the payload's own series lengths and `expected_months`
— `(NDVI u/e + MNDWI u/e + NDMI u/e) / 3` — rather than showing a
simplified "35/36" for one series that would misrepresent how the
number is actually computed. Live-verified to match the persisted
`confidence` value exactly (92% both ways on the same report).

**Score anatomy is honest about the floor rule.** `RiskEngine.compute()`
can raise `overall_score` above the plain weighted average when any
factor reaches the severe floor threshold (existing M1 logic,
unchanged). Showing four contribution bars that visually imply "these
sum to the composite" would misrepresent the score on any report where
the floor rule fired. The Method tab compares the persisted
`weighted_average_score` to `overall_score`: when they differ, it shows
the pre-floor weighted average plus an explicit "floor rule applied"
explanation before the composite; when they're equal (the floor rule
never fired), it shows only the composite — never a spurious diagram
implying arithmetic that didn't happen. Covered by a dedicated
component test (`method-tab.test.tsx`) exercising both branches, since
the one real report live-verified against did not happen to trigger
the floor rule.

**A judgment call, documented for review.** The Recommendation's
"indicative only" qualifier fires below `RECOMMENDATION_CONFIDENCE_
THRESHOLD = 70`. Product Design v2 specifies the qualifier's existence
but not its exact cutoff. 70% was chosen as a conservative line —
below it, on average more than 10 of 36 expected optical months were
unusable. This is a fixed product-level constant (like
`BAND_THRESHOLDS`), not part of the versioned risk-engine config
surface, and is called out explicitly here for founder review; it is
trivially adjustable without touching any other logic.

**Scope deferral, not silent omission.** Product Design v2 §7.5 also
specifies a PDF "Evidence & Method appendix" (`PDF_LAYOUT_VERSION`
bump). This message's own verification checklist covers Evidence tab,
Method tab, Recommendation, Refresh, and Navigation — it does not
mention the PDF. Rather than either silently expand scope into
un-requested, unverified PDF/reportlab work, or silently drop an
approved design-doc requirement, this phase ships the complete web
experience and explicitly flags the PDF appendix as the next piece of
already-approved scope, unchanged from the design doc. `PDF_LAYOUT_
VERSION` is untouched this phase; `test_report_pdf.py`'s 11 tests
still pass unmodified against the extended `ReportResponse` shape,
confirming no regression.

**Alternatives considered.** Recomputing `expected_months` via a fresh
`date` calculation instead of reusing `_monthly_periods` (rejected —
reusing the exact function the pipeline called eliminates any
possibility of drift, and it was already imported cross-module by
`report_generator.py`, so this isn't a new coupling). Persisting a
`floor_rule_applied` boolean instead of `weighted_average_score`
(rejected — the two raw numbers let the UI show the actual pre-floor
value, not just a flag, at no extra cost). Making the Evidence/Method
tabs URL-synced routes or query params (rejected for this phase — adds
`useSearchParams()` Suspense-boundary complexity for a same-page tab
switch with no deep-linking requirement in the brief; local component
state is simpler and a hard refresh reconstructing to the Report tab
is reasonable, not a regression).

**Live verification.** A newly created, guaranteed-uncached farm's
report was generated against real Earth Engine and inspected at every
layer: the raw `risk_score` row in Postgres (`observation_window_start
= 2023-07-01`, `_end = 2026-07-01`, `weighted_average_score` equal to
`overall_score` — this farm's factors never reached the floor
threshold); the raw `satellite_observation.source_dates` JSONB
(`["2023-08-04", "2023-08-09", ...]` — a genuine ~5-day Sentinel-2
revisit pattern, confirming the GeeProvider fix works against live
data, not just the deterministic fake); the full HTTP response
(confidence arithmetic `(NDVI 33/36 + MNDWI 33/36 + NDMI 33/36) / 3 =
92%` matching the persisted `confidence` field exactly); and the same
report rendered in a real browser tab — Recommendation block with real
primary drivers (the three factors that actually scored High), Evidence
tab with real coverage strips and an expandable scene-date disclosure
showing the same real dates from Postgres, Method tab with real
per-factor contribution bars summing correctly to the composite. A
second independent fresh browser tab confirmed zero console errors.
Refresh-mid-tab was verified by switching to the Evidence tab, hard-
reloading, and confirming the page reconstructed entirely from a fresh
`GET /reports/{id}` (defaulting to the Report tab, as designed — no
crash, no stale state). Navigation was verified round-trip: report →
Farm detail (via "View farm") → back into the same report from its
history entry, plus the in-page "How was this score calculated?" link
correctly switching to the Method tab without a route change. The PDF
download was also re-verified live (200 OK) against the extended
payload shape to confirm no regression.

**Tests.** Backend: 128/128 (125 prior + 3 new: `RiskEngine.
weighted_average_score` transparency for both the floor-triggered and
never-triggered cases; `satellite_observation.source_dates` populated
for the three optical indices and honestly empty for rainfall;
`risk_score.observation_window_start/end` and `weighted_average_score`
persisted end to end through a fresh pipeline run) plus extensions to
two existing tests (the full HTTP workflow test now asserts `evidence`/
`method`/`source_dates` in the live response; the PDF/report-text
fixture builders updated for the two new required payload fields, no
new failures). Frontend: 51/51 (48 prior + 3 new `MethodTab` tests
covering the floor-rule branch, the no-floor-rule branch, and the
mirrored band-threshold table — plus the 6 `recommendation.test.ts`
tests already covered above). ESLint clean, `tsc --noEmit` clean,
production build clean (`/reports/[id]` grew 110 kB → 121 kB, all 10
routes unchanged).

---

### Wizard & session hardening — sliding-session refresh, per-officer draft persistence, Resume/Discard, navigation guard, error-state taxonomy; two real bugs found live (M2B P10, backend addition B6)

**Decision.** Four independent hardening pieces, all additive over the
existing architecture (owner-or-branch auth, `ReportResponse`, async
jobs, the wizard's existing farm/report endpoints — none redesigned):

1. **Sliding session (B6).** `POST /auth/refresh` (`app/api/auth.py`) —
   a caller holding a still-valid bearer token exchanges it for a fresh
   one via the same `create_access_token` used by login, identical
   response shape. `get_current_user` already re-validates the token and
   re-checks the user is active, so the endpoint adds nothing beyond
   issuing a new token for the same identity. Frontend: `session.ts`
   gained client-side (display-only, unverified) JWT payload decoding —
   `getSessionExpiresAt()` / `getSessionUserId()` — and a new
   `SessionExpiryProvider` (mounted inside the authenticated app shell)
   that arms a warning modal 2 minutes before the real `exp`, offers
   "Stay signed in" (calls `/auth/refresh`, re-arms the timers against
   the new expiry — the actual "sliding" behavior) or "Sign out." The
   design doc named two acceptable shapes for B6 — "token refresh
   endpoint (or sliding expiry)" — this implements both halves cheaply
   rather than choosing one, since the warning UX needs client-side exp
   visibility regardless of whether refresh exists.

2. **Persistent assessment drafts + Resume/Discard.**
   `features/assessment-wizard/draft-storage.ts` — a per-officer
   (keyed by JWT `sub`) localStorage draft `{step, village, ring,
   savedFarmId, savedFarmAreaHa, triggeredJobId, interruptedBySessionExpiry}`,
   patched on every meaningful wizard state change. `/assessments/new`
   (`page.tsx`) now gates on mount: a draft with `triggeredJobId` routes
   straight to the existing `/assessments/{jobId}` Run page (job
   recovery — never re-create a running assessment); a resumable draft
   with no in-flight job shows `ResumeDraftPrompt` (Resume / Discard,
   never silent overwrite); a draft flagged `interruptedBySessionExpiry`
   auto-restores with no prompt, since that interruption wasn't the
   officer's choice.

3. **Four-step stepper wizard.** `/assessments/new` is rewritten from
   the old single-page conditional-panel flow (`ConfirmPanel` →
   `FarmSavedPanel`, two separate UI moments for farm-creation and
   report-trigger) into `AssessmentWizard` — Village → Boundary → Verify
   → Submit (`features/assessment-wizard/stepper.tsx`,
   `assessment-wizard.tsx`), matching Product Design v2 §7.2 exactly.
   The map remains the persistent dominant region across all four steps
   (only the side panel changes); farm-creation and report-trigger are
   now genuinely one combined action on the Verify step's confirm click
   (closing the exact gap §7.2 called out: "today: two separate UI
   moments"). `FarmSavedPanel` is deleted (superseded, no remaining
   callers). `FarmMap` gained a `restoreRing` prop — a previously-drawn
   ring loads onto the map as an already-complete, editable boundary via
   `TerraDraw.addFeatures([...{properties: {mode: "polygon"}}])` +
   `setMode("select")`, applied exactly once via a ref guard the first
   time the map becomes ready — live-verified end to end (see below).

4. **Navigation guard + error-state taxonomy.**
   `features/navigation-guard/` — a ref-backed (not state-backed, so
   arming it while actively drawing never re-renders the app shell)
   context; `useUnsavedWorkGuard(active)` arms both a native
   `beforeunload` listener (refresh/tab-close/external nav) and the
   context's `confirmNavigation()` gate, which every in-app navigation
   trigger in `AppShell` now checks before acting (rail links, mobile
   drawer, the "+New assessment" buttons, sign-out) — a Next.js
   client-side `<Link>` transition never fires `beforeunload` itself,
   since the page never unloads, so the in-app half is a separate
   mechanism, not a duplicate of the browser one. Armed only when a
   completed polygon exists and the assessment hasn't been submitted yet
   (Product Design v2 §7's "warn only when there's real unsaved work").
   Separately, `components/ui/error-state.tsx` + `empty-state.tsx` +
   `skeleton.tsx` + `offline-banner.tsx` replace every index/detail
   page's single hand-rolled generic error card with the four-family
   taxonomy (network / auth / not-found / server-with-reference-id) the
   design doc's §7.6 calls for — family is derived from a real HTTP
   status via a new `ApiError` class (`lib/api/errors.ts`) the affected
   query hooks now throw, not guessed from message text.

**Two real bugs found and fixed during this phase, not just new
surface.**

- **Infinite re-render risk in the wizard's resume-gate effect.** The
  first cut of `/assessments/new/page.tsx` had
  `useEffect(() => {...}, [router])`. `useRouter()` is stable in real
  Next.js, so this never manifests in production — but it is not
  actually idempotent: a live-browser test (see below) reproduced the
  bug directly, and independently the frontend test suite's real-backend
  integration test reliably hit a 200–300 second V8 heap-exhaustion crash
  that turned out to be React StrictMode's development-only double
  effect invocation combined with a *second*, related bug (next item)
  spinning in a tight loop. Fixed by moving `router`/`pathname` into refs
  (`routerRef`, `pathnameRef` — same pattern applied to
  `SessionExpiryProvider`'s `handleExpired` for consistency) so the
  effect's own identity never depends on router/pathname reference
  stability, only on its real trigger (`session` changing).
- **`takeInterruptedFlag` consumed under React StrictMode's double
  effect invocation.** `takeInterruptedFlag(draft)` is a read-and-clear
  side effect, not a pure read. A naive `useEffect(() => {...}, [])`
  runs twice in development (StrictMode's intentional diagnostic
  behavior) — the first invocation correctly consumed the flag and
  requested the auto-restore gate, but the second invocation re-read the
  now-already-cleared flag and fell back to showing the Resume/Discard
  prompt instead, with the *second* call's `setGate` winning. Caught
  live, not by code review: a real short-TTL session was allowed to
  expire mid-wizard (backend restarted locally with
  `JWT_EXPIRES_MINUTES=2` for the duration of this test only, restored
  to 720 immediately after), and after logging back in the Resume prompt
  appeared where the design requires silent auto-restore. Fixed with a
  `hasCheckedDraftRef` mount-guard, the standard remedy for this exact
  StrictMode class of bug — re-verified live afterward: the same
  short-TTL expiry → re-login round trip landed directly on the restored
  Boundary step with the polygon reloaded, no prompt, and the frontend
  test suite (previously reproducibly OOM-crashing on the real-backend
  integration test at the ~250–300s mark, worker-fork heap exhaustion)
  went back to a clean ~15s pass. This would not have affected the
  compiled production build (StrictMode's double-invocation is dev-only),
  but the underlying non-idempotence was real and worth fixing on its
  own terms, not just to unblock the test run.

**Alternatives considered.** A full `useRouter`/`usePathname`-based
`useBlocker` (React Router has one; Next.js App Router does not) for
in-app navigation protection — rejected as unavailable in this stack;
the ref-backed context + explicit per-link `confirmNavigation()` checks
achieves the same effect with what's actually available, at the cost of
needing each new navigation trigger to remember to call it (documented,
not hidden). A `job_stage`-style separate table for the assessment draft
instead of localStorage — rejected: the M2A `session.ts` localStorage
trade-off already accepted for the session itself applies identically
here, and a draft is explicitly *client-scoped, pre-persistence* state
by design (Product Design v2 §7.2: "village + drawn ring held
client-side"), not a server record. Recomputing `isDraftResumable`
inline everywhere instead of a shared per-officer-keyed module — rejected
for the same reason every other shared concern in this codebase gets one
home, not several ad hoc copies.

**Trade-offs.** The many small new UI primitives this phase introduces
(`ErrorState`, `EmptyState`, `Skeleton`, `OfflineBanner`, `Stepper`,
`ResumeDraftPrompt`, `Dialog`) ship without dedicated new unit test
files — verified instead via `tsc`/`ESLint`/production build (all
clean) and the live browser walkthrough below, which is a real trade-off
against this codebase's usual per-module unit-test discipline, made
under this phase's time budget; flagged here explicitly as a gap worth
closing with focused component tests, not silently accepted as
equivalent coverage. `handleDiscardAndRestart` calls `clearDraft()`, but
the wizard's own state-persistence effect immediately re-saves a blank
(all-null, `isDraftResumable() === false`) draft object right after —
functionally inert (a reload correctly shows no Resume prompt, verified
live) but leaves a harmless empty key in localStorage rather than a
fully absent one; noted rather than fixed under time pressure, since
fixing it risks more churn than the cosmetic debt it costs.

**Live verification.** Full walkthrough against the real local stack
(backend + PostGIS + a real seeded officer): village search → select →
boundary step transition, confirmed via the accessibility tree (the
Browser pane's screenshot/zoom capture was independently found to be
non-functional for this entire session — reproduced on a plain
WebGL-free page too, so a session-level tooling issue, not a P10 defect;
all verification below therefore used the accessibility tree, console/
network inspection, and read-only `javascript_tool` DOM/localStorage
reads instead of pixel screenshots). Draft persistence: village
selection and a directly-injected completed ring (a real ~15.87 ha
Killari-area polygon) were confirmed round-tripping through real
`localStorage`, correctly keyed per officer id. **The `restoreRing` →
`TerraDraw.addFeatures` path was proven live, not just by code
review**: after a hard reload + Resume click, the boundary step rendered
"Edit boundary" / "Delete" (the post-draw `select`-mode UI) and the
correct 15.87 ha preview area — meaning the restore actually invoked
`onPolygonChange(ring, true)` through real TerraDraw/MapLibre logic, not
a stub. Navigation guard: hooking `window.confirm` before triggering an
in-app nav click while a polygon was present captured the exact real
call — `"You have an unsaved farm boundary. Leave without saving?"` —
proving `confirmNavigation()` genuinely fires, not just that navigation
happens to succeed (headless browsers auto-accept native dialogs, so a
successful navigation alone would have been weak evidence). Session
expiry: the backend was restarted locally with a 2-minute JWT TTL for
the duration of this test only; the warning dialog appeared
automatically, "Stay signed in" round-tripped through a real
`POST /auth/refresh` (confirmed via decoding the new token's `exp`,
strictly later than the old one), "Sign out" cleared the real session
and redirected, and a passive (un-acted-on) expiry correctly redirected
to `/login?next=%2Fassessments%2Fnew` with the draft's
`interruptedBySessionExpiry` flag set beforehand — followed by a real
re-login that landed silently back on the restored Boundary step (the
StrictMode bug fix, re-verified after the fix). Offline banner:
dispatching real `offline`/`online` window events showed and cleared
the banner exactly as designed. Backend restored to the real 720-minute
TTL and confirmed via a fresh login's `expires_in: 43200` before this
phase's tests were declared final. The full real create-farm →
trigger-report → route-to-Run-page chain (the one piece not
independently re-driven through the live browser in this pass, since
the map's `data-map-loaded` attribute never set on this session's
Browser pane — WebGL unavailable, consistent with the pane's broader
screenshot/render issue) is proven instead by the rewritten
`page.integration.test.ts`, which drives the real wizard end to end
(real login, real debounced village search, real `POST /farms`, real
`POST /farms/{id}/reports`) and asserts the resulting navigation target
matches a real job id — this is strictly the same evidentiary chain the
live browser would have provided, just exercised via the automated
suite instead.

**Tests.** Backend: 131/131 (128 prior + 3 new `/auth/refresh` tests —
valid-token round trip including that the *new* token is itself usable,
missing-token 401, garbage-token 401). Frontend: 51/51 (50 prior +
the real-backend integration test rewritten for the combined
create-farm-and-trigger-report flow, same count since it replaces
rather than adds — the rewrite's own reasoning, and the two live bugs
its repeated OOM crashes led to, are documented above). ESLint clean,
`tsc --noEmit` clean, production build clean (`/assessments/new` grew
43.7 kB → 43.8 kB; all 10 routes unchanged).

---

### UX polish & production readiness — shared RiskBandChip, error-taxonomy coverage completed, print styles, responsive fix (M2B P11)

**Decision.** A QA/polish pass over the already-complete P0–P10 product,
entirely additive — no new endpoints, no schema change, no
`ReportResponse`/authorization change. Five pieces:

1. **`components/ui/risk-band-chip.tsx`.** The risk-band pill
   (`rounded-full px-2 py-0.5 ...` + `RISK_BANDS[band]`) had been
   hand-duplicated at 8 independent call sites (Overview, Farms index,
   Farm detail, Assessments index, Reports index, `FactorCard`,
   `MethodTab`) since M2A/M2B — each a faithful copy, but 8 places to
   keep visually identical by hand. Consolidated into one component,
   `score?: number` optional for the "{label} · {score}" vs. band-only
   forms already both in use, and a `title` tooltip stating the band's
   real score range (read from the same `BAND_THRESHOLDS` mirror the
   Method tab's own table already renders — one source of the cutoff
   numbers, `bandRange()` computes the label, never restated by hand).
   This is this phase's answer to Product Design v2's P11-scoped item
   14 ("contextual methodology links... everywhere a score appears"):
   extending the exact `title=` pattern the P9 confidence badge already
   established, rather than introducing a new tooltip primitive or
   deep-linking into nested `<Link>` rows (every list row *is* a
   `<Link>` to the report already — a second interactive element inside
   it would be an invalid nested-anchor DOM, not just an inconsistency).

2. **Error-taxonomy coverage completed.** P10 shipped `ApiError` +
   `ErrorState`/`InlineErrorState` but only wired the six query hooks
   that existed at the time; the survey for this phase found
   `useVillageSearch`, `useCreateFarm`, and `useTriggerReport` still
   throwing plain `Error` (no status), and four call sites
   (`village-search.tsx`, farm detail's re-assess, the Run page's retry,
   the wizard's submit-step failure) still rendering a raw
   `error.message` string with no family classification. All three hooks
   now throw `ApiError` with the real HTTP status (identical pattern to
   P10's fix), and all four call sites now render through
   `InlineErrorState`/`ErrorState` — except **`login-form.tsx`,
   deliberately left alone**: its raw `{loginMutation.error.message}` is
   correct as-is, not a defect. The backend's login 401 already returns
   the intentional generic "Invalid email or password" (Blueprint §03,
   M0 decision — no user enumeration), and `ErrorState`'s "auth" family
   copy ("Session no longer valid... sign in again") describes an
   *existing session expiring*, not a *login attempt failing* — routing
   login failures through that family would show semantically wrong
   text. Distinguishing "this raw message happens to already be right"
   from "this raw message is a defect" was the actual judgment call
   this item required, not a mechanical find-and-replace.

3. **Dead prop cleanup.** `ConfirmPanel`'s `isPending`/`errorMessage`
   props were always called with `false`/`null` after P10's wizard
   rewrite (the panel's own click immediately advances the wizard past
   it, into the "submit" step, which owns its own pending/error
   display) — genuinely dead, not just unused-by-convention. Removed
   from the component's interface entirely rather than left as
   permanently-`null` plumbing.

4. **Print styles for the live Report page.** Zero `@media print`
   existed anywhere in the app before this phase (verified by grep).
   Added scoped `print:` utility classes (not a new global stylesheet
   file) to `reports/[id]/page.tsx` and `AppShell`: navigation chrome,
   the tab list, and every interactive-only control (View farm/New
   assessment/Download PDF, the "How was this score calculated?" link)
   hide on print; the live `ReportMap` — a WebGL canvas a browser's
   print pipeline cannot reliably capture — also hides in print rather
   than risking blank or clipped output, with the verdict panel taking
   the freed width; `print:break-inside-avoid`/`print:break-before-page`
   keep factor cards, charts, and the lineage footer from splitting
   mid-block across a page boundary. Deliberately scoped to the Report
   page only, not every index page — printing a raw farms/reports list
   table isn't a real bank workflow, and the authoritative printed
   artifact for a report is already the server-rendered reportlab PDF
   (M2A P6, untouched this phase); this is a quick-reference browser
   print of the live dashboard, not a second PDF pipeline.

5. **Responsive fix, `MethodTab` score-anatomy row.** Flagged by static
   review, then confirmed live: the row's fixed-width columns (`w-36` +
   `w-20` + `w-12` label/weight/contribution cells) left too little
   room for the contribution bar under ~640px, and "Vegetation
   stability"/"Water availability" sat right at the wrap boundary of
   their `w-36` cell. Changed to `flex-col` (two stacked lines:
   label+weight/value, then bar+contribution) below Tailwind's `sm`
   breakpoint, `sm:contents` restoring the original single-row layout
   at `sm:` and up — live-verified at exactly 375px
   (`getComputedStyle().flexDirection === "column"`, zero
   viewport-width overflow) and 768px (`"row"`, matching the original
   desktop layout pixel-for-pixel).

**A genuine environment incident, not a code defect, worth recording.**
Mid-phase, the Next.js dev server started failing with
`ENOSPC: no space left on device` and Turbopack `TurbopackInternalError`
panics — the machine's C: drive was at 238GB/238GB used, 0 bytes free.
This also explains this session's earlier (P10) intermittent Vitest
worker heap-exhaustion crashes: Windows' page file cannot grow on a full
disk, so what looked like a memory ceiling was actually disk exhaustion
wearing a memory-error costume. This machine-level problem was flagged
to the founder rather than guessed at — deleting arbitrary files to free
space on a shared dev machine without knowing what 238GB belonged to
would have been exactly the kind of unilateral destructive action these
sessions' own operating rules exist to prevent. The founder freed space
directly; the stale `.next` build cache (built partway through the
disk-full window, at risk of corrupted partial writes) was cleared and
rebuilt clean before verification resumed. No source change resulted
from this incident — it's recorded here purely so a future session
seeing a "memory" crash on this machine checks disk space first.

**Alternatives considered.** A generic `<Tooltip>` primitive (Radix/
base-ui style, hover-card positioning, etc.) for the band-range hint —
rejected as introducing a new UI dependency/pattern for one line of
static text when the native `title=` attribute, already established
and accepted for this exact purpose in P9, does the job with zero new
code. Deep-linking report tabs via `?tab=method` so index-page rows
could link straight to the Method tab — rejected for this phase: every
row that shows a score is already a whole-row `<Link>` to the report
(Overview, Farms, Farm detail, Assessments, Reports), so a second
nested link/button for "explain" would be an invalid nested-interactive
DOM structure, not just a design choice; the tooltip achieves the
"how was this calculated" requirement without restructuring five list
components' click targets for marginal gain over what's already one
click away (open the report, the Method tab is right there).

**Trade-offs.** None identified for the shipped changes — all five
items are strictly additive or corrective (dead-prop removal, a
consolidated component with byte-identical rendered output at existing
call sites, print CSS scoped to `print:` variants that have zero effect
on-screen, a responsive fix verified not to change desktop/tablet
layout). The disk-space incident cost real session time but produced no
code trade-off — the fix was operational (free disk, clear stale
cache), not a design compromise.

**Live verification.** Full walkthrough against the real stack (backend
+ PostGIS + the same seeded officer used throughout M2B): Overview,
Farms index, Farm detail, Assessments index, and a real Report page
(all three tabs) all confirmed rendering the new `RiskBandChip` with
correct text and a real, accurate `title` tooltip (e.g.
`"Moderate risk = 25.01–50 / 100"`, read directly off the live DOM, not
asserted from source). The compiled production CSS was inspected
directly (`grep -c "@media print"` on the built chunk) after the
in-browser `document.styleSheets` check gave an unreliable negative —
6 real `@media print` blocks confirmed present. `MethodTab`'s
responsive fix was verified at both 375px and 768px via
`getComputedStyle` on the live DOM, not inferred from the Tailwind
classes alone. The wizard's village search was exercised live
end-to-end (real debounced `GET /villages`, three real results
returned) with zero console errors across the entire session. A farm
with real assessment history correctly showed "Re-assess" (not
"Assess") in the header, confirming the wording fix's conditional logic
against real data.

**Tests.** Backend: 131/131 (unchanged — this phase touched no backend
code). Frontend: 51/51 (unchanged count — no tests added or removed;
existing `method-tab.test.tsx` and the full suite re-verified passing
against every change in this phase, including the `ConfirmPanel` prop
removal and the `RiskBandChip` swap-in, since both existing test suites
assert on visible text/behavior, not implementation markup). ESLint
clean, `tsc --noEmit` clean, production build clean (`/reports/[id]`
123 kB → 123 kB, `/assessments/new` 43.8 kB → 45.1 kB from the
responsive/print class additions, all 10 routes unchanged).

---

### RC1 audit — missing authorization check on report trigger (real IDOR), unbounded polygon rings

**Decision.** Two fixes from a Staff Engineer RC1 readiness audit, both
release-blocking, both closed the same day they were found.

1. `POST /farms/{farm_id}/reports` (`trigger_report`, `app/api/
   reports.py`) loaded the target farm by id and checked only that it
   existed — `user_can_access_owned_resource`, the owner-or-branch check
   every other resource-scoped endpoint in this codebase depends on, was
   never called here. Any authenticated `CREDIT_OFFICER`/`BRANCH_MANAGER`
   who learned or guessed a `farm_id` outside their own branch could
   trigger a real, billed Earth Engine compute job against it. This is
   the identical bug class the M1 IDOR fix closed for `GET /farms/
   {farm_id}` (see that entry above) — the fix was applied to every
   sibling read endpoint at the time but never to this one write
   endpoint, which is the single most expensive operation in the system
   to leave unguarded. Fixed with the same established pattern: 404 (not
   403) on a farm outside the caller's scope, indistinguishable from one
   that doesn't exist.

2. Chained consequence: `GET /jobs` (`list_assessments`, `app/api/
   jobs.py`)'s farm-enrichment query (resolving `village_name`/`area_ha`
   for each listed job's farm) had no ownership filter of its own — it
   inherited its correctness entirely from the assumption that every job
   in scope was created against a farm the creator already had access
   to, an assumption fix (1) restores but which the query didn't itself
   enforce. This contradicted `workspace.py`'s own module docstring,
   which claims every list endpoint is owner-or-branch scoped with no
   exceptions. Fixed as defense in depth — filtered the same way
   `list_farms`/`list_reports` already filter their own farm joins —
   even though it should be unreachable once (1) is fixed, matching this
   codebase's existing layered-defense precedent (the advisory lock
   *and* the in-flight-job check both guard the same race, for the same
   reason: correctness shouldn't depend on exactly one line staying
   correct forever).

3. Separately, the same audit found `GeoJSONPolygon`'s ring validation
   (`app/schemas/farm.py`) enforced a minimum point count but no
   maximum — an unbounded ring lets a client submit an arbitrarily large
   coordinate array that Shapely and PostGIS's `ST_Area` then process
   synchronously in the request path (not the background job), a cheap
   denial-of-service vector with no legitimate hand-drawn-boundary use
   case. Capped at 2000 points — generous headroom over any real field
   trace. While in the same validator, made the NaN/Infinity rejection
   explicit (`math.isfinite`) rather than relying on it happening to
   fail the chained range comparison, which worked but wasn't a
   documented guarantee.

**Reason.** Found during a full RC1 skeptical audit (architecture,
backend, frontend, security, database, performance, reliability, API
design, testing, deployment, documentation) commissioned before any
real bank pilot go-live decision. Four parallel deep-dive investigations
(database/schema, security/auth, reliability/deployment, API/docs/
testing) each independently cross-referenced this file first, so as not
to re-flag already-accepted, documented trade-offs as new bugs — these
two items were the only ones that met the bar of "matches an already-
established, already-once-fixed security pattern in this exact
codebase, but wasn't actually applied here."

**Alternatives considered.** None for the IDOR fix — this is a
straightforward application of the exact pattern every sibling endpoint
already uses; there was no design choice to weigh, the same as the
original M1 `get_farm` fix. For the vertex cap, a stricter limit (e.g.
500) was considered and rejected as unnecessarily tight for a
legitimately hand-traced irregular field boundary with many vertices;
2000 was chosen as generous-but-bounded rather than tuned to a measured
real-world maximum, since no such measurement exists yet.

**Trade-offs.** None identified. Both fixes are strictly corrective —
no legitimate request is rejected by either change (proven live: the
farm's actual owner still receives a real `202` and a real job; the
existing `test_full_service_1_workflow_end_to_end` and all `test_workspace.py`
branch-scoping tests still pass unmodified with the new filter in
place).

**Live verification.** Backend restarted with the fix; a real farm was
created and its owner's own trigger-report request confirmed `202`
against the live server (not just the test suite). The outsider-
rejection case is proven by a new automated regression test
(`test_trigger_report_rejects_user_outside_owner_or_branch`,
mirroring `test_get_farm_rejects_user_outside_owner_or_branch`
exactly) rather than repeated by hand against the shared pilot
database, since creating a throwaway unauthorized account against
real data has no advantage over the isolated test-fixture version and
the test suite already exercises exactly this path end to end.

**Tests.** Backend: 134/134 (132 prior + 2 new: the IDOR regression
test above, and `test_rejects_ring_over_max_points` /
`test_rejects_non_finite_coordinates` in `test_farm_schema.py`).

---

## M3-level implementation decisions

### Missing user-provisioning path — `scripts/create_admin_user.py`

**Decision.** A new CLI script, `backend/scripts/create_admin_user.py`,
creates an `app_user` row (hashed password via the existing
`hash_password()`, any `UserRole`, optional `branch_id`), following the
exact async-script pattern `seed_default_config_weight.py` already
established (`sys.path` bootstrap, `AsyncSessionLocal`, `asyncio.run`).

**Reason.** Found while implementing M3 ("a new engineer should be able to
clone the repository and launch TerraRisk using documented steps"):
`app/api/auth.py` has only `/login` and `/refresh` — no registration
endpoint, no admin-creation endpoint, and no seed script for `app_user`
existed anywhere. A fresh deployment would have a fully working API and an
empty `app_user` table with no way to authenticate at all. This is a
release blocker for "clone and launch," not a nice-to-have — filled the
same way every other one-off provisioning need in this codebase already is
(a script, not a new API surface), consistent with the pilot's fixed,
named-officer-account posture (no self-service signup — see the M2A
"Bearer token in localStorage" entry above for that posture's origin).

**Alternatives considered.** An admin-only `POST /users` API endpoint —
rejected as unnecessary API surface for what is, at pilot scale, a handful
of manually-provisioned accounts; a script matches the actual operational
need without adding a new authenticated write path to audit. A raw SQL
`INSERT` documented in the deployment guide — rejected because it would
either hardcode a bcrypt hash (awkward, easy to get wrong) or require the
operator to hash a password by hand outside the app's own `hash_password()`,
duplicating logic that already exists.

**Trade-offs.** None identified — purely additive; no existing behavior
changes.

**Future migration path.** If TerraRisk ever needs self-service account
creation (a second bank, a larger officer roster), this script is the
natural reference for a future `POST /users` endpoint's business logic —
not a placeholder to be deleted, since manual/CLI provisioning by an
administrator remains a reasonable path even alongside a future API.

---

### Production deployment architecture — single-origin nginx, migrate-on-boot, config-presence GEE readiness

**Decision.** Three infrastructure choices made together for M3 ("Production
Deployment & Pilot Infrastructure"):

1. **nginx as the single public origin.** `docker/nginx/nginx.conf`
   reverse-proxies `/api/` to the backend and everything else to the
   frontend, both under one public origin. The frontend's production
   Docker build sets `NEXT_PUBLIC_API_BASE_URL` to an empty (relative)
   string by default, so browser API calls resolve to `/api/v1/...`
   same-origin — CORS is a non-issue for real traffic in this topology.
   `FRONTEND_ORIGIN`-scoped CORS (M2A) remains in the backend as
   defense-in-depth for any caller that bypasses nginx, not removed.

2. **Migrations run automatically on backend container start.**
   `backend/docker-entrypoint.sh` runs `alembic upgrade head` then execs
   `uvicorn` — idempotent, so this is the same code path for a first
   deployment and every subsequent redeploy. Rollback
   (`alembic downgrade -1`) stays a deliberate, manual, documented step
   (`docs/Deployment_Guide.md`) — never automatic.

3. **`GET /health/ready`'s Earth Engine check is credential/config
   presence, not a live `ee.Initialize()` call.** `GET /health` (unchanged
   since M0, asserted verbatim by `tests/test_health.py`) stays the cheap
   liveness probe with zero dependencies. The new `/health/ready` checks DB
   connectivity (`SELECT 1`) and whether `GEE_PROJECT_ID` +
   `GEE_SERVICE_ACCOUNT_JSON_PATH` are set and the key file exists on disk.

**Reason.** (1) reuses the backend's existing `/api/v1` route prefix with
zero backend routing changes, and removes an entire class of CORS
misconfiguration from the deployed system rather than just documenting
around it. (2) is the standard pattern at this project's scale — a
separate one-off "migrate" service/step would be more moving parts for no
real benefit at current job/deploy volume, matching this codebase's
existing "add infrastructure when the current approach actually strains,
not preemptively" pattern (see the async-job-as-DB-table decision above).
(3) is a deliberate reading of the M3 requirement's own "(where
practical)" qualifier: actually calling `ee.Initialize()` on every
orchestrator health-check hit would mean a real network round-trip (and,
per the existing `asyncio.to_thread()` decision above, a thread-pool hop)
on a health-check cadence — not merely undesirable but the wrong shape of
check for a readiness probe an orchestrator may call every few seconds.

**Alternatives considered.** A separate one-shot "migrate" Compose service
run before `backend` starts (rejected — more infrastructure than this
project's deploy cadence justifies; the idempotent-entrypoint approach
gives the same guarantee with less to maintain, and remains easy to split
out later if migrations ever need to run before multiple backend replicas
start concurrently). A live `ee.Initialize()` health check, possibly
cached/rate-limited (rejected as unnecessary complexity for what a
config/file-presence check already answers correctly: "will the next real
report-generation attempt find its credentials?" — a stale-but-valid cached
"OK" from an earlier successful live check would be actively misleading if
the credentials were revoked since).

**Trade-offs.** The `/health/ready` Earth Engine check cannot catch every
possible failure mode (e.g. valid-looking credentials that Google has since
revoked, or an IAM role removed after initial setup — see the M1 "GEE
service account IAM roles" entry above for the kind of failure this
wouldn't catch) — it only catches "credentials aren't configured at all,"
which is the actual failure mode a fresh/misconfigured deployment hits.
Real IAM/credential-validity problems still surface as errors on the first
real report-generation attempt, exactly as they do today.

**Future migration path.** If the platform ever runs multiple backend
replicas, the migrate-on-boot pattern needs revisiting (concurrent
`alembic upgrade head` calls from multiple containers racing on startup) —
a dedicated migrate-then-deploy step at that point, not before. None
anticipated for `/health/ready`'s design or the nginx topology at pilot
scale.

**Tests.** Backend: 135/135 (134 prior + 1 new:
`test_health_ready_endpoint_reports_component_checks`; the existing
`test_routes_are_versioned_under_api_v1` was updated, not newly added, to
exclude the new top-level `/health/ready` path the same way it already
excluded `/health`).

---

## RC2-level implementation decisions

### Job reaper — startup + periodic sweep for orphaned/stuck jobs

**Decision.** New `app/services/jobs/reaper.py`, wired into `app/main.py`
via a FastAPI `lifespan` handler: on process startup, any `job` row still
`PENDING`/`RUNNING` is immediately marked `FAILED` (nothing about a new
process's startup could be continuing it); for the process's lifetime, a
background task also fails any `PENDING`/`RUNNING` job whose `updated_at`
is older than 20 minutes, independent of any restart.

**Reason.** RC2 production-readiness audit, reliability review: found —
and reproduced live — that a job killed mid-flight by a routine
`docker compose up -d --build` redeploy (a normal pilot operation) stayed
`RUNNING` forever. `trigger_report`'s own in-flight-job check (`reports.py`)
then permanently refused any future report for that farm, with no operator
recovery path short of a manual database `UPDATE`. `generate_farm_report`'s
own try/except (`report_generator.py`) only guarantees a terminal status
for exceptions raised *within* that process — it cannot catch the process
being killed. `Job.updated_at` is bumped by every `ProgressTracker` stage
transition (`progress.py`), not just job creation, so the periodic sweep's
age check measures "time since last observed sign of life," not "time
since the job started" — a legitimately long-running job that's still
actively progressing is never killed just because its total runtime
crosses the threshold.

**Alternatives considered.** A reaper triggered only on startup (rejected
— doesn't catch a job whose background task is still alive but hung, e.g.
a network call that never times out, since the process never restarts to
trigger a fresh sweep). Adding a real timeout to every individual Earth
Engine call instead (a complementary, not alternative, fix — deferred as
a Medium-priority recommendation in the RC2 report, not implemented this
pass, since the age-based reaper already bounds the failure mode's
duration without needing to instrument every call site).

**Trade-offs.** A job that is genuinely still running at the 20-minute
mark (never observed in practice — typical runtime is 2-4 minutes) would
be failed and require a manual retry. Judged acceptable: 20 minutes is
generous headroom, and a false failure is strictly better than the
previous behavior (permanently stuck, unrecoverable without database
access).

**Future migration path.** None anticipated at this job volume/architecture.
If Earth Engine call-level timeouts are added later, the periodic sweep's
threshold remains a correct backstop regardless.

---

### `pool_pre_ping=True` + `pool_recycle=1800` on the async engine

**Decision.** `app/database/base.py`'s `create_async_engine` call now sets
`pool_pre_ping=True` and `pool_recycle=1800`.

**Reason.** RC2 reliability review, reproduced live: `postgres` runs as
its own independently restartable container. Stopping and restarting it
while `backend` stayed up left every pooled connection stale; without
pre-ping, the *next* API request to check one out failed with a raw
connection error (a 500) instead of transparently getting a fresh
connection. Verified the fix directly: stopped and restarted the
`postgres` container without touching `backend`, and confirmed API calls
succeeded immediately afterward with zero manual intervention.

**Alternatives considered.** Relying on `restart: unless-stopped` to
eventually recover (rejected — that only fires if the *backend* container
itself crashes, which a stale-connection 500 does not cause; the backend
process stays up and stays broken until either an operator restarts it or
enough requests happen to cycle every stale connection out of the pool
naturally).

**Trade-offs.** `pool_pre_ping` adds one cheap round-trip on connection
checkout — negligible next to any real query latency.

**Future migration path.** None anticipated.

---

### nginx rate limiting on login, plus a general API backstop

**Decision.** `docker/nginx/nginx.conf` adds `limit_req_zone`s: `login_limit`
(5 requests/minute, per client IP, `burst=3 nodelay`) applied only to
`POST /api/v1/auth/login`, and a looser `api_limit` (60 requests/minute)
applied to `/api/` generally. `limit_req_status 429`.

**Reason.** RC2 security audit: nothing anywhere — application or proxy
layer — throttled login attempts. bcrypt's cost factor slows one guess but
does nothing against parallel/distributed guessing against a small, fixed
set of named bank-officer accounts (the only account-provisioning path is
`create_admin_user.py`). Verified live: 8 rapid login POSTs from one
client returned `401 401 401 401 429 429 429 429` — the limiter engages
exactly as configured.

**Alternatives considered.** An application-level, per-account failed-
attempt lockout (rejected as the *sole* mechanism — an account-keyed
lockout is itself a denial-of-service vector, since an attacker who knows
a real officer's email could deliberately lock them out; per-IP at the
proxy layer doesn't have that failure mode). Rate-limiting `/api/`
generally without a tighter login-specific rule (rejected — 60r/m is
reasonable for normal API usage patterns but far too loose to meaningfully
slow credential guessing).

**Trade-offs.** A per-IP limiter can't distinguish multiple legitimate
users behind one NAT/proxy from an attacker — acceptable at pilot scale (a
handful of named officers, not a large shared-NAT deployment); revisit if
that changes.

**Future migration path.** None anticipated at pilot scale.

---

### `/health/ready` no longer returns raw exception text

**Decision.** The database-check failure path in `GET /health/ready`
(`app/main.py`) now logs the exception server-side and returns
`{"status": "error"}` with no `detail` field, instead of `str(exc)`.

**Reason.** RC2 security audit: this route has no auth dependency (an
orchestrator/LB probe can't carry one), and asyncpg connection exceptions
can include hostnames, ports, or database/user names. Every other failure
path in this codebase already keeps exception detail server-log-only (the
generic exception handler in the same file); this one hadn't matched that
convention. Low exploitability as shipped (`nginx.conf` only proxied
`/api/` and `/` to the public origin at the time this was found — see the
next entry), but the fix is free and closes the gap regardless of future
proxy config changes.

**Alternatives considered.** None — straightforward application of the
existing "exception detail is server-log-only" convention.

**Trade-offs.** None.

**Future migration path.** None anticipated.

---

### `/health` and `/health/ready` now proxied through the public nginx origin

**Decision.** `docker/nginx/nginx.conf` adds `location = /health` and
`location = /health/ready`, both proxying to the backend.

**Reason.** RC2 documentation-accuracy audit found `docs/Deployment_Guide.md`
told operators to `curl http://localhost/health` as a post-deploy
verification step — but neither endpoint was actually reachable through
the public origin; only `/api/` and `/` were proxied, so that curl hit the
frontend's catch-all and got a 404. Beyond fixing the doc, the more
complete fix is making the claim true: an external uptime monitor or load
balancer pointed at the public domain now has a real, unauthenticated (by
design) health surface to hit, not just an internal-Docker-network one.

**Alternatives considered.** Just fixing the documentation to stop
claiming this works (rejected — the underlying capability is genuinely
useful for a real deployment's external monitoring, and adding it is two
cheap `location` blocks).

**Trade-offs.** None — both endpoints are already designed to be
safely unauthenticated (see the M3 `/health/ready` entry above).

**Future migration path.** None anticipated.

---

### `create_admin_user.py --reset-password`, and a minimum password length

**Decision.** The account-provisioning script gains a `--reset-password`
mode (rotates `password_hash` for an existing `--email`, mirroring
`create_user()`'s pattern exactly) and a 12-character minimum enforced on
every password, create or reset.

**Reason.** RC2 security audit: there was no supported way to rotate a
compromised, forgotten, or routinely-due-for-rotation officer credential
short of direct database surgery, and no minimum length was enforced on
the only account-provisioning path in the system.

**Alternatives considered.** Composition rules (uppercase/digit/symbol
requirements) instead of a length minimum — rejected in favor of current
NIST guidance that length is the stronger predictor of guess-resistance,
and composition rules mostly push users toward predictable substitutions.

**Trade-offs.** None identified.

**Future migration path.** If self-service password reset is ever needed
(not currently in scope — the pilot's fixed, named-officer-account posture
per the M2A entry above), this script's `reset_password()` is the natural
reference for that endpoint's business logic, the same relationship
`create_user()` has to a hypothetical future `POST /users`.

---

### `docker-entrypoint.sh` — distinguish "database not ready" from "genuinely broken config"

**Decision.** The migration-retry logic added in M3 (bounded retry around
`alembic upgrade head`) is replaced with a two-phase script: first wait
for raw database *connectivity* (a direct `asyncpg.connect()` against
`DATABASE_URL`, before Settings/Alembic load), retrying only on
connection-level errors; once connected, run `alembic upgrade head`
exactly once, letting any real failure (bad config, bad migration SQL)
surface immediately.

**Reason.** RC2 error-recovery testing reproduced a real diagnostic gap
live: starting a container with `JWT_SECRET` unset (a config error,
nothing to do with database readiness) produced 15 repeated "database
likely still starting — retrying in 2s" log lines over ~30 seconds before
finally showing the real `pydantic.ValidationError` at the bottom — because
the old script retried on *any* nonzero exit from `alembic upgrade head`,
which itself imports and validates `Settings` as a side effect. An
operator debugging a failed production deploy would have to scroll past
misleading noise to find the actual cause. Verified the fix both ways: the
same missing-`JWT_SECRET` case now fails in ~10 seconds with the real
error immediately visible and no retry noise; a genuine fresh-volume
database-startup race (the scenario M3's original fix targeted) still
retries correctly (`Database not reachable yet (attempt 1/15)...`) and
proceeds once Postgres is actually ready.

**Alternatives considered.** Keeping the M3 version as-is (rejected — the
diagnostic-quality gap is real and was reproduced, not hypothetical).
Parsing `DATABASE_URL` to run a lighter-weight raw TCP check instead of a
real `asyncpg.connect()` (rejected as unnecessary complexity — a real
connection attempt is barely more expensive and directly exercises the
actual thing that needs to succeed).

**Trade-offs.** None identified — this is a strict diagnostic-quality
improvement; both the legitimate-race and genuine-failure paths were
re-verified live after the change.

**Future migration path.** None anticipated.

---

### RC2 audit scope note — what was reviewed but deliberately not changed

**Decision.** Several findings from the RC2 audit are recorded as known,
accepted limitations rather than fixed in this pass: (1) the sliding
refresh token (`POST /auth/refresh`) has no absolute session-length
ceiling independent of repeated refresh, and no revocation mechanism
beyond deactivating the account (`is_active`, already enforced on every
request) — this compounds the already-documented localStorage-token
trade-off (see the M2A entry above) but closing it properly needs a
session-epoch or similar mechanism, which is a real design decision, not
a quick fix; (2) no retry-with-backoff around individual Earth Engine
calls for transient network failures (partially mitigated already: cached
per-stage observations mean a manual retry only re-fetches what failed,
not the whole pipeline); (3) no container resource limits, log-rotation
config, or Linux-capability hardening in `docker-compose.prod.yml`; (4) no
metrics/APM endpoint; (5) backups remain a documented manual `pg_dump`
cron recipe, not automated or verified by anything in this repository.

**Reason.** The RC2 audit's own brief: "Only implement fixes if they are
genuine release blockers... Do NOT invent work." None of these prevent a
correctly-operated pilot from functioning; each either has a partial
mitigation already, requires a real design decision this audit pass
shouldn't rush, or depends on production load/scale data that doesn't
exist yet to size correctly (resource limits sized blind risk causing the
OOM-kills they're meant to prevent).

**Trade-offs.** Documented explicitly here, and in `docs/RC2_Final_Signoff.md`'s
Known Limitations section, specifically so they are a tracked, visible
backlog — not a silently-dropped audit finding.

**Future migration path.** Revisit session revocation before any
deployment beyond a controlled pilot (same trigger condition already
named in the M2A entry). Revisit resource limits and monitoring once real
pilot load data exists to size them against. Revisit GEE retry if transient
failures are observed in practice to be more than a rare inconvenience.

---

### Evidence-aware roadmap, Phase A — physical validation harness (Sep 2026)

**Decision.** Add `app/services/validation/`: a product registry, ingestion-time
unit/scale assertions, zone-relative water balance plausibility checks, and a
cross-product agreement check. Run it on every water report and return the
findings with the result. Fix the three product-read defects the audit
confirmed (JRC occurrence reducer, JRC coverage date, MOD16A2 valid range).
Full findings and measurements: `docs/GEE_Product_Audit_2026.md`.

**Reason.** Six specification defects, including MOD16A2 ET wrong by ~4x,
passed the whole suite green: the tests verified execution, not physics.
Blueprint v2 Part 11 specified this layer in July ("does the water balance
close within a plausible residual range?") and it was never built. Work order
for the full roadmap: 1 → 5 → 3 → 2 → 4 → 6 → 8 → 7, with items 1 and 7 split
so zone groundwork happens first.

**Trade-offs.**
- **No closure test against the engine.** ΔS is defined as P − ET − Q, so
  `P − ET − Q − ΔS` is identically zero and any tolerance test on it is
  vacuous. The identity is asserted only as a labelled refactor guard;
  plausibility envelopes stand in until an independent ET estimate is wired.
- **Findings are returned and logged, not raised, and results are still
  persisted on failure.** A suppressed report cannot be diagnosed; the field
  is non-optional so no caller can render a headline without the verdict.
  Persisting findings is Phase B (item 5).
- **Zone envelopes are uncalibrated and unreviewed**, and classification uses
  rainfall rather than the aridity index. Every finding says so.
- **The cross-product tolerance has no default.** MOD16A2 and PML_V2 disagree
  by 48% on a Maski-area polygon; picking a tolerance is a scientific
  decision, not a default.
- **CHIRPS no-data asymmetry left unfixed:** probed over 1,096 days with no
  such pixels present. Latent, guarded by the ingestion range check.

**Future migration path.** Persist findings with provenance (item 5). Wire
PML_V22a for ET cross-checks and PET for aridity-index zoning once a tolerance
is agreed. Derive `high_relief_terrain` from a DEM. Recompute the Service 1
assessments carrying inflated JRC flood factors.

**Correction (13 Sep 2026).** This entry's first version, and commit
`f17c514`, said the stored production Maski balance showed ET at 20% of
rainfall and had never been regenerated. False: the figures came from the
project brief and match no stored balance. Validating all 135 stored
balances in production found none with the ET defect; 121 pass. Thirteen
show the opposite problem — ET at 95-109% of rainfall, consistent with
unmodelled canal irrigation. See `docs/GEE_Product_Audit_2026.md`.

---

### Evidence-aware roadmap, Phase B — evidence provenance and lineage (Sep 2026)

**Decision.** Persist, in the same transaction as every result in both
services, one `evidence_record` per input the result depended on (each
remote-sensing series and each assumed parameter), plus a `validation_run`
and its `validation_finding`s. Expose them read-only at
`GET /reports/{id}/lineage` and `GET /catchments/{id}/water-reports/lineage`.
Backfill validation findings — not lineage — for stored water balances.
Schema and rules: `docs/Climate_Intelligence_Data_Model.md`.

**Founder decisions taken at the start of this phase.**
1. Recompute Service 1 assessments with an inflated JRC flood factor —
   after Phase B, so recomputed rows carry lineage; only rows with a
   non-zero JRC value, appended, old rows kept.
2. ET cross-product tolerance: 25%, warning only, never a block, and not
   wired live. The 48% MOD16A2/PML_V2 disagreement at Maski is measured
   uncertainty for item 8, not a defect to gate on.
3. Identity-guard tolerance for values read back from `NUMERIC(10,2)`:
   0.02 mm, derived from storage precision. In-memory stays 0.01 mm.
4. The 13 catchments with ET at 95-109% of rainfall are flagged in the
   database via backfill; canal command-area verification is a separate
   data task. The envelope is not widened to pass them.
5. Semi-arid ET/P envelope kept at 0.55-0.95, labelled uncalibrated.

**Reason.** Item 5 requires every number to be traceable to source,
version, dates, resolution, resampling, limitations and validation status,
persisted with the result rather than only rendered.

**Trade-offs.**
- **No "plausibility checked" validation level.** A value inside a
  literature envelope has not been validated. Every input today is
  `unvalidated`; plausibility lives in the validation tables.
- **String vocabularies behind CHECK constraints, not native enums** — the
  one deliberate break from house convention. The evidence vocabulary will
  grow through the roadmap, and every native enum value needs an ALTER TYPE
  migration that fails silently if forgotten. Constraints are generated
  from the Python enums; a test pins model and migration to them.
- **Polymorphic `(result_table, result_id)`, no foreign key**, mirroring
  `risk_score`. No cascade on result deletion. Application code never
  deletes results; the test suite sweeps orphans at session end.
- **No reconstructed provenance** for results pre-dating migration 0012.
  Their parameters, including a Curve Number changed during the hydrology
  audit, are unrecoverable. The API states "provenance not recorded".
- **Lineage describes the Earth Engine providers only.** Values are
  imported from the provider and engine modules, not restated. Any other
  provider gets a record saying its lineage is not described.
- **Not rendered in the report yet.** Report output is redesigned in
  Phases C-D; rendering lineage now would be built twice.
- **Hydrology provider returns no scene dates**, so ET and SAR lineage
  record `acquisition_dates` as null ("not recorded") with a stated
  limitation. Fixing it needs a provider contract change.

**Defects found while building this.**
- **Findings inserted before their run.** With no ORM relationship, the
  unit of work had no dependency between `validation_finding` and
  `validation_run` and inserted findings first; Postgres rejected the
  foreign key. Found on the first live-database run of the water report.
  Service 1's tests had passed only because clean fake data produced no
  findings. Fixed with a declared relationship; a regression test forces
  an ERROR finding through the real database.
- **Cached Service 1 observations lost their scene dates.**
  `_read_cached_observations` rebuilt observations without
  `source_dates`, so any re-assessment silently lost acquisition lineage.
- **Sentinel-2 registry caveat mis-scoped.** B11's 20 m native resolution
  was a product-wide limitation, so NDVI (B8/B4) inherited it. Now
  attached per index.
- **Three scale literals in `gee_provider.py`** — the monthly and
  climatology rainfall paths hardcoded 5000 instead of the existing
  `_CHIRPS_SCALE_METERS`. Named; no behaviour change.
- **Committed frontend API types had drifted** from the backend before
  this phase. Regenerated; type-check clean.

**Future migration path.** Item 3 adds model confidence and decision
sufficiency as distinct persisted fields, reading from these tables. The
hydrology provider contract should return composite and pass dates. Wire
PML_V22a so ET can reach `cross_checked`. Recompute the affected Service 1
assessments (decision 1).

---

### Evidence-aware roadmap, Phase C — model confidence separated from decision sufficiency (Sep 2026)

**Decision.** Three fields where there was one. `risk_score.confidence` keeps
its name and is documented as what it always measured — optical data
completeness. `model_confidence` is a statistical property of the estimate.
`decision_sufficiency` evaluates the evidence per stakes tier against a
versioned policy (`decision_policy`, seeded with uncalibrated
`sufficiency-v1`) and states every shortfall. No factor or composite score is
ever invented again. Data model: `docs/Climate_Intelligence_Data_Model.md` §6a.

**What production showed.** The only Service 1 assessment in production (the
0.25 ha Shera plot, 26 Aug 2026) was reported as Moderate, 37.5, at "83%
confidence". Three of its four factors were a neutral 50 and the fourth was JRC
occurrence 0.0. That was not bad luck; two structural defects produced it:

1. **The seasonal baseline was never fetched.** The report window was cached
   first; the eight-year baseline request found those rows, treated any row in
   range as a complete hit, and skipped the other years. Every calendar month
   had at most three baseline samples against a minimum of five, so vegetation
   stability, MNDWI, NDMI and VCI were uncomputable on every farm's first
   assessment.
2. **Small farms got no rainfall.** CHIRPS `reduceRegion` at ~5 km returned
   null for any polygon too small to contain a sample point of the grid.
   Probed live: 0.25 ha and 1.25 ha null, 10 ha and above fine. Indian
   smallholdings are typically 0.5-2 ha.

**Fixes.**
- CHIRPS: polygon mean, falling back to the containing cell's value only when
  the mean is null. Verified live that the 233 ha Maski polygon is
  byte-identical to the old code, so no catchment number moves.
- Cache: `observation_fetch` records the ranges actually fetched; a range is a
  hit only if a recorded fetch covers it. Refetching skips months already
  stored, so legacy caches are neither trusted nor duplicated.
- Engine (`rule-engine-v2`): uncomputed factors are null and excluded; a
  composite requires two computed factors carrying at least half the weight;
  otherwise there is no overall score. Re-averaging what survived would have
  turned the production assessment into Low from one number.
- Recharge stress (`recharge-stress-engine-v2`) and the water balance: no
  neutral score or "Normal" band. Nothing computable raises
  `InsufficientEvidenceError`, and the job fails with that reason, not
  "please retry".

**Trade-offs.**
- **The `confidence` field is not renamed.** Renaming would touch ~25 files
  across API, database, PDF and UI for no behaviour change. It is documented as
  a legacy name everywhere it appears, and every user-facing label now reads
  "Data completeness".
- **Only baseline-sampling uncertainty is quantified** — Wilson intervals at
  90% on the percentile signals, combined under a perfect-correlation bound.
  Every interval is a lower bound, and says so. The rest is item 8.
- **Sufficiency is reported for all three tiers.** Loan amount and
  reversibility become inputs in item 2; inventing a rupee-to-tier mapping now
  would be policy taken by default.
- **High stakes can never be sufficient today**, because no input is validated.
  Intended: nothing here has been back-tested against loan outcomes.
- **Water Intelligence gets the fixes, not a sufficiency verdict.** Its
  decision is programme targeting, not a loan, and that context has not been
  defined.
- **Migration 0013's downgrade refuses** when honestly-null scores exist,
  rather than inventing values to restore NOT NULL.

**Other defects found on the way.**
- The report's chart series read every cached month for the farm, unbounded.
  With the baseline now fetched it would have charted 132 months as though the
  report covered them. Now bounded to the report's own window.
- A migration command chain continued after a failed upgrade and stepped the
  local database back a revision. Local only; each migration step is now run
  and checked separately.
- `report_findings.py` used `FACTOR_LABELS` without importing it — would have
  crashed any PDF with an uncomputed factor. Caught by the new PDF test.

**Future migration path.** Item 2 maps loan amount and reversibility to a tier
and adds action thresholds to `decision_policy`. Item 8 widens the intervals to
include measurement error and propagates them. The production Shera assessment
is recomputed under `rule-engine-v2`, appended; the v1 row is kept.

---

### Every account may use both services (17 Sep 2026)

**Decision.** `REPORTING_ROLES` (`backend/app/api/deps.py`) lists every role,
and gates farm creation, farm reports and every catchment endpoint. Until now
Service 1 was `credit_officer`/`branch_manager` only and Water Intelligence
`programme_officer`/`programme_admin` only, so of the four real accounts the
Chairman could generate nothing at all, the two programme accounts could not
assess a farm, and the credit officer could not open a catchment. The UI rail
now shows both products to every role.

**What did not change.** Data scoping. Farms stay owner-or-same-branch,
catchments stay creator-only, and both still return 404 — never 403 — for
someone else's row. Widening the roles moved the "which product is yours"
boundary only; it did not widen anyone's view of anyone else's data. The old
cross-product 403 tests now assert exactly that: a bank role reaching another
user's catchment gets 404, and its own catchments list shows only its own.

**Trade-offs.**
- **The role split was a product statement, not a security control**, and it is
  now gone. When a bank pilot needs "a Chairman may read but not commission
  assessments", that is a new, narrower list — not a revert.
- **Listed explicitly, not `tuple(UserRole)`.** A role added later is excluded
  until someone decides otherwise, and `test_auth.py` fails to force that
  decision.
- **An external collaborator's account (`vivek.srinivasan@ifmr.ac.in`,
  programme officer) gains Service 1 access** as part of "all accounts". It
  sees only farms it draws itself. Revoke by narrowing the list or
  deactivating the account.
- **Metered Earth Engine compute is now reachable by every account**, on a
  non-commercial GCP project.

---

### Product renamed to Kshetra; HTTPS prepared for kshetra.in (19 Sep 2026)

**Decision.** Everything a user sees — app header, login, page titles, both
PDF reports, the API's title — now says **Kshetra** (क्षेत्र: field, region).
The domain is `kshetra.in`, bought by the founder. `PDF_LAYOUT_VERSION` went
to 4 so no cached PDF keeps the old name.

**What deliberately keeps the old name.** The repository, Python and npm
package names, Docker project and database, docs file names, and the
browser-storage keys `terrarisk.session` and `terrarisk.assessment-draft.*`.
Renaming the storage keys would sign every user out and delete unsaved
assessment drafts; renaming the rest is churn nobody sees.

**HTTPS.** Until now production served plain HTTP on a bare IP, so login
passwords crossed the network unencrypted. The nginx config is now split
into `nginx.conf` (HTTP, default) and `nginx.https.conf` (TLS for
kshetra.in), with everything shared in `docker/nginx/snippets/` — the old
commented-out HTTPS block had already drifted from the live one. A `certbot`
service renews in place and nginx reloads every 6 hours.

**Trade-offs.**
- **The first certificate is issued by hand**, because it accepts Let's
  Encrypt's Subscriber Agreement on the domain owner's behalf; renewals
  are automatic.
- **HSTS starts at one day**, not two years, so a bad first rollout cannot
  lock visitors out for long. Raise it after a clean week.
- **The domain is hardcoded** in `nginx.https.conf` and `snippets/tls.conf`.
  Templating it would serve a hypothetical second deployment.
- **Others own kshetra.com, kshetra.co.in and kshetra.ai.** No agritech or
  geospatial company of that name turned up in a quick search. A formal
  trademark search is needed before incorporating under the name.
