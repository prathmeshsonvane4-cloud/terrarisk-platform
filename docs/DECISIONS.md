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
for the DCCB Latur pilot. Manual drawing is a deliberate, human-in-the-loop
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

**Reason.** DCCB Latur has not yet provided real portfolio data. Building
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
