# TerraRisk Backend

FastAPI service powering TerraRisk's Farmer Climate Intelligence Report
(built and live-verified). Portfolio-level risk rollups (Service 2) are
reserved in the data model but not yet built. See the repo-root
[README](../README.md) for the product overview and [`docs/`](../docs)
for the full engineering record.

## Architecture

- **FastAPI** (async) + **SQLAlchemy 2.0** (async, typed `Mapped`/
  `mapped_column`) + **asyncpg** + **Alembic** migrations.
- **PostgreSQL + PostGIS** is the single data store — farm polygons,
  administrative boundaries, and risk rollups are geometries, queried with
  PostGIS spatial functions via GeoAlchemy2.
- **Google Earth Engine** is the satellite/climate data source, accessed
  exclusively through the `SatelliteDataProvider` interface
  (`app/services/satellite/provider.py`) — business logic and the risk
  engine never import Earth Engine directly, so the provider is swappable.
- **Risk engine** (`app/services/risk/engine.py`) is a pure, I/O-free
  function: `compute(observation_bundle, config) -> RiskResult`. Rule-based
  and configurable (weights + floor thresholds), not a trained model — see
  [`docs/DECISIONS.md`](../docs/DECISIONS.md) for why.
- **Report generation** (`app/services/reporting/`) renders a PDF via
  ReportLab + Matplotlib, run as a background job.

Every architectural choice above — and every fix found along the way — is
recorded with its reasoning in [`docs/DECISIONS.md`](../docs/DECISIONS.md).
Read that file before changing any of these, not just this summary.

### Directory layout

```
app/
├── api/          # FastAPI routers (one file per resource)
├── core/         # config, logging, security (JWT/bcrypt)
├── database/     # engine/session setup
├── models/       # SQLAlchemy models (source of truth for the schema)
├── schemas/      # Pydantic request/response models
├── services/
│   ├── risk/        # the risk engine (pure, no I/O)
│   ├── satellite/    # SatelliteDataProvider + the Earth Engine adapter
│   └── reporting/    # report generation + PDF rendering
alembic/          # migrations (script_location, versions/)
scripts/          # one-off CLI provisioning scripts (admin boundaries, seed data)
tests/            # pytest suite
```

## API

Routes are versioned from the first endpoint under `/api/v1` (never an
unversioned URL). Interactive OpenAPI docs are served at `/docs` (Swagger
UI) and `/openapi.json` whenever the server is running — that's the
authoritative, always-current API reference; the frontend's typed client is
generated directly from it (`frontend/npm run generate:api`).

| Router | Prefix | Covers |
| --- | --- | --- |
| `auth` | `/api/v1/auth` | Login, session refresh (bearer JWT) |
| `villages` | `/api/v1/villages` | Village/admin-boundary search |
| `farms` | `/api/v1/farms` | Farm polygon creation + retrieval |
| `jobs` | `/api/v1/jobs` | Async job status polling, assessment list |
| `reports` | `/api/v1/reports` | Report trigger + retrieval (PDF, evidence) |

Every response uses one error envelope shape (`{"error": {"code",
"message", ...}}`) regardless of endpoint — see the exception handlers in
`app/main.py`.

Two health endpoints, deliberately different in what they check (M3):

- `GET /health` — cheap liveness probe, no dependencies. Used by the
  Docker image's own `HEALTHCHECK` and Compose's `depends_on` conditions.
- `GET /health/ready` — readiness probe: verifies DB connectivity (`SELECT
  1`) and Earth Engine credential configuration (config/key-file presence,
  not a live `ee.Initialize()` call — see the endpoint's docstring in
  `app/main.py` for why). Returns `503` when a dependency isn't ready.

## Database

PostgreSQL 16 + PostGIS 3.4. Schema is defined by the SQLAlchemy models in
`app/models/`; migrations live in `alembic/versions/` and are applied with
`alembic upgrade head` (the Docker image's entrypoint runs this
automatically on every container start — see
[`docs/Deployment_Guide.md`](../docs/Deployment_Guide.md)). `DATABASE_URL`
is the single source of truth for the connection string — never duplicated
in `alembic.ini` (see `alembic/env.py`).

Local development database: `docker/docker-compose.yml` (PostGIS only,
port 5433 to avoid colliding with a native Postgres on 5432).

## Authentication

Bearer JWT (`PyJWT`), password hashing via `bcrypt` directly (see
[`docs/DECISIONS.md`](../docs/DECISIONS.md) for why not `passlib`/
`python-jose`). No registration/self-signup endpoint exists — TerraRisk's
pilot posture is a small, fixed set of named bank-officer accounts,
provisioned with `scripts/create_admin_user.py` (see
[`docs/Getting_Started.md`](../docs/Getting_Started.md)). Every
resource-scoped endpoint enforces owner-or-same-branch access
(`app/api/deps.py`'s `user_can_access_owned_resource` /
`owned_or_branch_filter`) — an unauthorized resource id returns `404`, not
`403`, so valid ids are never distinguishable from invalid ones.

Roles (`app/models/enums.py::UserRole`): `credit_officer`,
`branch_manager`, `risk_officer`, `ceo`, `chairman`.

## Jobs

Report generation and portfolio aggregation run as in-process FastAPI
`BackgroundTask`s, tracked in a database `job` table (not Celery/RQ — see
[`docs/DECISIONS.md`](../docs/DECISIONS.md) for the reasoning and the
migration path if job volume ever outgrows this). Clients poll `GET
/api/v1/jobs/{id}` until the job reaches a terminal status. Every Earth
Engine SDK call (blocking, no async variant) is wrapped in
`asyncio.to_thread(...)` so it never blocks the event loop.

## Configuration

All configuration is environment-variable-driven via
`app/core/config.py::Settings` — see `.env.example` for the full,
documented list. No secret has a default value; a missing required setting
fails loudly at startup. When `ENVIRONMENT=production`, `Settings` also
refuses to start with a placeholder/weak `JWT_SECRET` or `DEBUG=True`
(M3 production-safety check).

## Development

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env           # then fill in real values
docker compose -f ../docker/docker-compose.yml up -d   # local PostGIS
alembic upgrade head
python scripts/seed_default_config_weight.py
python scripts/create_admin_user.py --email you@example.com --password ... --full-name "Your Name" --role branch_manager
uvicorn app.main:app --reload
```

## Testing

```bash
pytest
```

Tests that need a live PostGIS instance skip cleanly when one isn't
reachable (see `tests/conftest.py`); schema correctness is otherwise
verified offline via DDL compilation (`tests/test_schema_ddl.py`). Test
count changes as the codebase grows — run `pytest -q` for the current
count rather than trusting a number here.

## Deployment

Production runs via Docker — see `Dockerfile` (multi-stage,
`python:3.14-slim-bookworm`, non-root, migrations run automatically by
`docker-entrypoint.sh` before `uvicorn` starts) and
[`docs/Deployment_Guide.md`](../docs/Deployment_Guide.md) for the full
walkthrough.
