#!/bin/sh
# Runs on every container start (fresh deploy and every redeploy alike).
# `alembic upgrade head` is idempotent — a no-op when the schema is already
# current — so this is the same code path for "first deployment" and
# "upgrade deployment" (docs/Deployment_Guide.md). Rollback is a deliberate
# manual step (`alembic downgrade -1`), never automatic here.
set -e

# Real race found during M3 verification: on a fresh `postgres_data` volume,
# the postgres container's own `pg_isready` healthcheck (docker-compose.prod.yml)
# can report healthy — and Compose's `depends_on: condition: service_healthy`
# proceed to start this container — moments before Postgres's *second*
# internal startup (the official postgres image runs initdb, a temporary
# internal-only instance to execute init scripts, shuts that down, then
# starts the real listener) is actually accepting external connections.
# Without this retry, alembic hit a bare ConnectionRefusedError on first
# boot every time, crashing this container; `restart: unless-stopped` then
# papered over it a few seconds later on retry — but `docker compose up`
# itself had already reported the dependency chain failed and exited
# non-zero, aborting frontend/nginx startup along with it. Retrying here
# (bounded, not open-ended) means a fresh deployment succeeds on the first
# `docker compose up`, not "the second time you run it."
echo "Waiting for the database to accept connections..."
attempt=0
max_attempts=15
until alembic upgrade head; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$max_attempts" ]; then
        echo "Database did not become ready after $max_attempts attempts — giving up." >&2
        exit 1
    fi
    echo "Migration attempt $attempt failed (database likely still starting) — retrying in 2s..."
    sleep 2
done

echo "Starting TerraRisk API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
