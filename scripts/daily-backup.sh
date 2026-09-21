#!/usr/bin/env bash
# Daily database backup for the production droplet, run from cron.
#
# Until now every backup was taken by hand before a migration, so between
# migrations there was nothing: on 21 Sep 2026 the newest dump was a week
# old. This keeps 14 daily dumps (~1 MB each today) and verifies each one
# is readable before deleting the old ones — an unverified dump is not a
# backup.
#
# Install on the server (as the deploy user):
#   crontab -e
#   30 21 * * * /opt/terrarisk/scripts/daily-backup.sh >> /opt/terrarisk/backups/backup.log 2>&1
# 21:30 UTC is 03:00 IST — nobody is using the system then.
#
# STILL MISSING: these dumps live on the same droplet as the database
# they protect. If the droplet is lost, so are they. Off-site copies
# (DigitalOcean Spaces, or rclone to cloud storage) need an account and
# credentials the founder has to create.
set -euo pipefail

ROOT="${TERRARISK_ROOT:-/opt/terrarisk}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE="docker compose --env-file ${ROOT}/.env -f ${ROOT}/docker/docker-compose.prod.yml"

cd "$ROOT"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${ROOT}/backups/daily-${stamp}.dump"

echo "[$(date -u +%FT%TZ)] backup starting -> ${target}"
$COMPOSE exec -T postgres sh -c 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc' > "$target"

# Verify before trusting it: pg_restore -l fails on a truncated or empty
# dump, which is exactly the failure a silent cron job would otherwise
# hide until the day it is needed.
if ! $COMPOSE exec -T postgres pg_restore -l < "$target" > /dev/null; then
    echo "[$(date -u +%FT%TZ)] BACKUP UNREADABLE, keeping it for inspection: ${target}" >&2
    exit 1
fi

size="$(du -h "$target" | cut -f1)"
echo "[$(date -u +%FT%TZ)] backup ok (${size}), pruning dumps older than ${KEEP_DAYS} days"
find "${ROOT}/backups" -name 'daily-*.dump' -type f -mtime "+${KEEP_DAYS}" -print -delete
df -h / | tail -1
