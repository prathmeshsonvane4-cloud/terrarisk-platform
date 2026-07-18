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
#
# RC2 finding, reproduced live: the original version of this script retried
# `alembic upgrade head` itself on *any* nonzero exit — which also retried
# (and buried under up to 15 misleading "database likely still starting"
# lines) a genuinely broken config, e.g. a missing required env var. That
# class of failure has nothing to do with database readiness and was never
# going to resolve itself on retry. This version waits for raw DB
# *connectivity* only — using DATABASE_URL directly, before Settings/alembic
# ever load — and lets a real `alembic upgrade head` failure (bad config,
# bad migration SQL, whatever) surface immediately and undiluted, exactly
# once, not interleaved with 15 retry attempts.
#
# The `if cmd; then ... else code=$?; fi` shape (not a bare `code=$(cmd)`)
# is deliberate: under `set -e`, a failing command run directly as a
# statement kills the script before its exit code can even be inspected —
# wrapping it as an `if` test is the one construct `set -e` exempts.
echo "Waiting for the database to accept connections..."
attempt=0
max_attempts=15
while true; do
    if python -c "
import asyncio, os, sys
import asyncpg

async def check():
    url = os.environ.get('DATABASE_URL', '')
    if not url:
        print('DATABASE_URL is not set.', file=sys.stderr)
        return 3
    try:
        conn = await asyncpg.connect(url.replace('postgresql+asyncpg://', 'postgresql://'), timeout=5)
    except (ConnectionRefusedError, TimeoutError, OSError, asyncpg.exceptions.CannotConnectNowError):
        return 2  # database not reachable yet -- worth retrying
    except Exception as exc:
        print(f'Database connection failed: {exc}', file=sys.stderr)
        return 3  # a real, non-transient error -- do not retry
    else:
        await conn.close()
        return 0

sys.exit(asyncio.run(check()))
"; then
        code=0
    else
        code=$?
    fi

    if [ "$code" -eq 0 ]; then
        break
    elif [ "$code" -eq 3 ]; then
        echo "Database connection failed for a reason unrelated to startup timing — not retrying." >&2
        exit 1
    fi

    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$max_attempts" ]; then
        echo "Database did not become reachable after $max_attempts attempts — giving up." >&2
        exit 1
    fi
    echo "Database not reachable yet (attempt $attempt/$max_attempts) — retrying in 2s..."
    sleep 2
done

echo "Database reachable. Running migrations (alembic upgrade head)..."
alembic upgrade head

echo "Starting TerraRisk API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
