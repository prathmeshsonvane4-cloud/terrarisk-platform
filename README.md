# TerraRisk

Climate risk intelligence for agricultural lending. TerraRisk turns a
farm's location into a transparent, evidence-backed climate risk report a
bank credit officer can act on — and rolls those assessments up into
portfolio-level risk views for branch and district leadership. Built for
the pilot bank as the first pilot customer.

## Overview

Two services, one platform:

1. **Farmer Climate Intelligence Report** — a credit officer draws a farm's
   boundary on a satellite map, TerraRisk pulls multi-year vegetation,
   water, and rainfall data for that exact polygon from Google Earth
   Engine, and a rule-based risk engine produces a Climate Risk Score with
   a visible factor breakdown and a downloadable PDF report.
2. **Portfolio Climate Risk Dashboard** — aggregated risk views across a
   bank's villages, branches, and district (in progress).

The risk score is deliberately **rule-based and configurable**, not an
opaque ML prediction — a bank needs to understand and trust a score before
acting on it. See [`docs/DECISIONS.md`](docs/DECISIONS.md) for the full
reasoning behind every architectural choice in this repository.

## Architecture

```
                    ┌───────────┐
   Browser  ───────▶│   nginx   │  reverse proxy, TLS termination,
                    │ (prod)    │  gzip, security headers, static caching
                    └─────┬─────┘
                 ┌────────┴────────┐
                 ▼                 ▼
         ┌───────────────┐  ┌───────────────┐
         │   frontend     │  │    backend     │
         │  Next.js 15    │  │  FastAPI       │──────▶ Google Earth Engine
         │  (standalone)  │  │  (uvicorn)     │        (satellite/climate data)
         └───────────────┘  └───────┬───────┘
                                    ▼
                            ┌───────────────┐
                            │ PostgreSQL +   │
                            │   PostGIS      │
                            └───────────────┘
```

- **Frontend**: Next.js (App Router) + MapLibre GL/Terra Draw for boundary
  drawing, TanStack Query for server state, a contract-first typed API
  client generated from the backend's OpenAPI schema.
- **Backend**: FastAPI (async), SQLAlchemy 2.0 + PostGIS for spatial data,
  a pure rule-based risk engine, Earth Engine accessed only through a
  swappable provider interface, async report generation as a tracked
  background job (not a message queue — see `docs/DECISIONS.md`).
- **nginx**: single public origin in production — proxies `/api/` to the
  backend and everything else to the frontend, so the browser talks to one
  origin and CORS is a non-issue for real traffic.

Full detail: [`docs/Engineering_Blueprint_v1.md`](docs/Engineering_Blueprint_v1.md)
(original architecture) and [`docs/Product_Design_v2.md`](docs/Product_Design_v2.md)
(production-SaaS UX redesign).

## Features

- Draw a farm boundary on a real satellite basemap; server-authoritative
  area calculation (PostGIS), never trusts the client's live preview.
- Multi-year NDVI/MNDWI/NDMI + rainfall time series from Google Earth
  Engine, composited per farm polygon.
- Transparent, configurable Climate Risk Score with a visible per-factor
  breakdown and a floor-rule for severe individual factors.
- Downloadable PDF report with evidence (time-series charts, map snapshot)
  and methodology tabs.
- Role-scoped access (credit officer / branch manager / risk officer / CEO
  / chairman), owner-or-branch authorization on every resource.
- Async job tracking for long-running Earth Engine computations, with live
  progress polling in the UI.

## Technology stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS v4, shadcn/ui, MapLibre GL, Terra Draw, TanStack Query |
| Backend | FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic |
| Database | PostgreSQL 16 + PostGIS 3.4 |
| Satellite/climate data | Google Earth Engine |
| Reporting | ReportLab, Matplotlib |
| Auth | Bearer JWT (PyJWT), bcrypt |
| Infra | Docker, Docker Compose, nginx |

## Quick start (Docker)

Requires Docker and Docker Compose.

```bash
git clone <repo-url> && cd terrarisk-platform
cp .env.example .env                       # fill in real secrets — see comments in the file
docker compose --env-file .env -f docker/docker-compose.prod.yml up -d --build
docker compose --env-file .env -f docker/docker-compose.prod.yml exec backend \
    python scripts/create_admin_user.py --email you@example.com --password ... --full-name "Your Name" --role branch_manager
```

Open `http://localhost/`. Full walkthrough — including SSL, domain setup,
and creating the first admin account inside the container —
in [`docs/Getting_Started.md`](docs/Getting_Started.md).

## Production deployment

See [`docs/Deployment_Guide.md`](docs/Deployment_Guide.md) for Ubuntu
server setup, Docker deployment, environment variables, SSL/domain
configuration, updating an existing deployment, and backup/recovery.

## Development setup

Backend and frontend can also run directly on your machine (no Docker),
against the local-dev PostGIS container in `docker/docker-compose.yml`.
See [`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md) for service-specific setup, or
the consolidated walkthrough in [`docs/Getting_Started.md`](docs/Getting_Started.md).

## Testing

```bash
# Backend
cd backend && pytest

# Frontend
cd frontend && npm test && npx tsc --noEmit && npm run lint
```

## Project structure

```
terrarisk-platform/
├── backend/            # FastAPI service — see backend/README.md
├── frontend/           # Next.js web application — see frontend/README.md
├── docker/             # Dockerfiles' compose orchestration: local-dev DB (docker-compose.yml),
│                        # production stack (docker-compose.prod.yml), nginx config
├── docs/                # Engineering blueprint, product design, decision log, deployment/setup guides
├── data/                 # Datasets and reference data
├── infrastructure/       # Reserved for future IaC (not yet in use)
└── scripts/              # Repo-level utility scripts
```

## Screenshots

Not yet captured for this README — the pilot workspace covers the
Overview, New Assessment wizard, Assessment Run (progress/trust screen),
Farm detail, and the three-tab Climate Report (see
[`docs/Product_Design_v2.md`](docs/Product_Design_v2.md) §7 for the full
wireframe descriptions). Add real screenshots here once the pilot UI is
stable.

## License

Private — TerraRisk © 2026
