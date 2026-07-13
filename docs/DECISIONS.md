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
