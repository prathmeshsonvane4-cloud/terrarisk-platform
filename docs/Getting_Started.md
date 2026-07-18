# TerraRisk — Getting Started

Get a fresh clone of TerraRisk running locally. For running it on a real
server, see [`Deployment_Guide.md`](Deployment_Guide.md) instead — this
guide is the fastest path to a working local instance, whether via Docker
or by running each service directly.

## 1. Clone

```bash
git clone <repo-url> terrarisk-platform
cd terrarisk-platform
```

## 2. Choose a path

- **Docker (recommended — fewer moving parts, matches production)**: §3.
- **Bare-metal local dev (hot-reload on both services, for active
  development)**: §4.

Both need a Google Earth Engine service-account key file to generate real
reports — see [`DECISIONS.md`](DECISIONS.md) for the one-time GCP
project/service-account setup. Without it, everything except report
generation still works (login, farm drawing, village search).

## 3. Docker path

```bash
cp .env.example .env
```

Edit `.env`:

- `POSTGRES_PASSWORD`, `JWT_SECRET` — generate real values (commands are in
  the file's comments); never use the placeholders.
- `GEE_PROJECT_ID`, `GEE_SERVICE_ACCOUNT_JSON_HOST_PATH` — point at your
  service-account key file's absolute path on this machine.
- `FRONTEND_ORIGIN` — `http://localhost` is fine for local use.
- `ENVIRONMENT` — leave as `production` even locally; it's what enables the
  startup safety checks, and there's no meaningful "local Docker" mode
  distinct from it.

```bash
docker compose --env-file .env -f docker/docker-compose.prod.yml up -d --build
```

Wait for all four containers to report healthy:

```bash
docker compose -f docker/docker-compose.prod.yml ps
```

Migrations run automatically (the backend container's entrypoint runs
`alembic upgrade head` before starting). Seed the risk engine's initial
config weights (required before any report can be generated) and create
your first account:

```bash
docker compose -f docker/docker-compose.prod.yml exec backend \
    python scripts/seed_default_config_weight.py

docker compose -f docker/docker-compose.prod.yml exec backend \
    python scripts/create_admin_user.py \
    --email you@example.com \
    --password "a-real-password" \
    --full-name "Your Name" \
    --role branch_manager
```

`--role` must be one of: `credit_officer`, `branch_manager`,
`risk_officer`, `ceo`, `chairman` (run the script with `--list-roles` to
see this from the source of truth). Open `http://localhost/` and log in.

## 4. Bare-metal local dev path

Local PostGIS (shared by both services):

```bash
docker compose -f docker/docker-compose.yml up -d
```

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows; `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env             # fill in JWT_SECRET, GEE_* — DATABASE_URL's
                                   # default already matches docker-compose.yml
alembic upgrade head
python scripts/load_admin_boundaries.py --file scripts/fixtures/latur_villages_osm.geojson
python scripts/seed_default_config_weight.py
```

### Create the first admin/officer account

```bash
python scripts/create_admin_user.py \
    --email you@example.com \
    --password "a-real-password" \
    --full-name "Your Name" \
    --role branch_manager
```

This is the only way to create an account — there is no self-service
registration endpoint (a deliberate choice for a small, fixed set of named
bank-officer accounts; see `backend/README.md`'s Authentication section).
Run it again with a different `--email`/`--role` for each additional
account you need (e.g. a `credit_officer` to test branch-scoped access
alongside a `branch_manager`).

Start the backend:

```bash
uvicorn app.main:app --reload
```

Verify: `http://127.0.0.1:8000/health` should return `{"status":
"healthy"}`, and `http://127.0.0.1:8000/docs` should show the interactive
API docs.

Frontend (separate terminal):

```bash
cd frontend
npm install
cp .env.example .env.local   # default already points at the local backend above
npm run dev
```

Open `http://localhost:3000` and log in with the account created above.

## What's next

- [`backend/README.md`](../backend/README.md) / [`frontend/README.md`](../frontend/README.md) — architecture and structure of each service.
- [`Deployment_Guide.md`](Deployment_Guide.md) — running this on a real server.
- [`DECISIONS.md`](DECISIONS.md) — why the codebase is built the way it is; read before changing any established pattern.
