#!/usr/bin/env bash
# Pre-demo readiness check. Run it on the production server before any
# meeting where the platform will be shown:
#
#   ssh -i ~/.ssh/terrarisk_v2_admin deploy@174.138.122.238 /opt/terrarisk/scripts/preflight.sh
#
# Every line prints OK or a specific problem. It only reads — nothing here
# changes the system, so it is safe to run minutes before a demo.
set -uo pipefail

ROOT="${TERRARISK_ROOT:-/opt/terrarisk}"
COMPOSE="docker compose --env-file ${ROOT}/.env -f ${ROOT}/docker/docker-compose.prod.yml"
ORIGIN="${ORIGIN:-https://174.138.122.238}"
fail=0

say()  { printf '%-34s %s\n' "$1" "$2"; }
bad()  { printf '%-34s PROBLEM: %s\n' "$1" "$2"; fail=1; }

cd "$ROOT" || exit 1

# Containers: every service up, and the ones with health checks healthy.
down="$($COMPOSE ps --format '{{.Service}} {{.Status}}' | grep -v 'Up' | cut -d' ' -f1 | tr '\n' ' ')"
[ -z "$down" ] && say "containers" "OK (all up)" || bad "containers" "not up: $down"

# The app, end to end through nginx and TLS, exactly as a browser sees it.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$ORIGIN/health/ready")"
[ "$code" = "200" ] && say "app health" "OK" || bad "app health" "HTTP $code from $ORIGIN/health/ready"

body="$(curl -s --max-time 20 "$ORIGIN/health/ready")"
case "$body" in
    *'"database":{"status":"ok"}'*) say "database" "OK" ;;
    *) bad "database" "$body" ;;
esac
case "$body" in
    *'earth_engine":{"status":"configured"'*) say "earth engine credentials" "OK" ;;
    *) bad "earth engine credentials" "not configured" ;;
esac

# Certificate: days left. The IP certificate lasts six days and renews
# itself, so anything under two days means renewal has been failing.
end="$(echo | openssl s_client -connect "${ORIGIN#https://}:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"
if [ -n "$end" ]; then
    left=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
    [ "$left" -ge 2 ] && say "TLS certificate" "OK ($left days left)" || bad "TLS certificate" "only $left day(s) left — check the certbot container"
else
    bad "TLS certificate" "could not read it from $ORIGIN"
fi

# Disk and memory: a full disk stops Postgres writing.
disk="$(df --output=pcent / | tail -1 | tr -dc '0-9')"
[ "$disk" -lt 85 ] && say "disk" "OK (${disk}% used)" || bad "disk" "${disk}% used"
avail="$(free -m | awk '/^Mem:/ {print $7}')"
[ "$avail" -gt 200 ] && say "memory" "OK (${avail} MB available)" || bad "memory" "only ${avail} MB available"

# A stuck job is what a demo actually trips over: the UI shows a report
# that never finishes.
stuck="$($COMPOSE exec -T postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -Atc "select count(*) from job where status in ('"'"'pending'"'"','"'"'running'"'"') and created_at < now() - interval '"'"'30 minutes'"'"'"' 2>/dev/null | tr -dc '0-9')"
[ "${stuck:-0}" = "0" ] && say "stuck jobs" "OK (none)" || bad "stuck jobs" "$stuck job(s) running over 30 minutes"

# Last night's backup should exist.
newest="$(find "${ROOT}/backups" -name 'daily-*.dump' -mtime -2 2>/dev/null | wc -l)"
[ "$newest" -gt 0 ] && say "backup (last 48h)" "OK" || bad "backup (last 48h)" "no recent daily dump — check cron"

# Errors the backend logged today.
errs="$($COMPOSE logs --since 24h backend 2>&1 | grep -icE 'traceback|exception|error' )"
[ "${errs:-0}" -eq 0 ] && say "backend errors (24h)" "OK (none)" || say "backend errors (24h)" "$errs line(s) — read them: docker compose logs --since 24h backend"

echo
[ "$fail" -eq 0 ] && echo "READY — nothing blocking." || echo "NOT READY — fix the lines marked PROBLEM above."
exit "$fail"
