# TerraRisk — Deployment Guide

This guide covers running TerraRisk in production: Docker deployment (the
supported path), environment variables, SSL/domain setup, updating an
existing deployment, and backup/recovery. For first-time local setup
(cloning, local dev servers, creating the first account), see
[`Getting_Started.md`](Getting_Started.md). For the reasoning behind any
architectural choice referenced here, see [`DECISIONS.md`](DECISIONS.md).

## Prerequisites

- A server (Ubuntu 22.04/24.04 LTS assumed below; any Docker-capable Linux
  host works the same way).
- Docker Engine + the Docker Compose plugin.
- A domain name pointed at the server, if you want a real HTTPS URL rather
  than plain HTTP on an IP address (recommended for anything beyond a
  closed internal network).
- A Google Earth Engine service-account key file (see `DECISIONS.md`'s GEE
  setup walkthrough) — copied to the server, outside the repo.

## 1. Ubuntu server setup

```bash
sudo apt-get update && sudo apt-get upgrade -y

# Docker Engine + Compose plugin (see https://docs.docker.com/engine/install/ubuntu/
# for the current official steps if this drifts)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# log out/in (or `newgrp docker`) for the group change to take effect

# Open only what's needed: SSH + HTTP/HTTPS. Adjust to your actual SSH port.
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

TerraRisk itself does not need any other inbound port open — PostgreSQL
and the backend/frontend containers are only reachable from nginx, on the
Docker-internal network (see `docker/docker-compose.prod.yml`).

## 2. Docker deployment (primary path)

```bash
git clone <repo-url> terrarisk-platform
cd terrarisk-platform

cp .env.example .env
# Edit .env: real POSTGRES_PASSWORD, JWT_SECRET (32+ random chars — see the
# generation command in .env.example), GEE_PROJECT_ID,
# GEE_SERVICE_ACCOUNT_JSON_HOST_PATH (absolute path to the key file on this
# server), FRONTEND_ORIGIN (your real domain), ENVIRONMENT=production.

# The backend container runs as a non-root user by design (Dockerfile).
# The GEE key file must be readable by that user once bind-mounted — on a
# real Linux host this means the file (and every parent directory in its
# path) needs at least world-execute/read, not just owner access. Found
# during a real deployment: a key file left at the default `chmod 600` a
# `scp`/`cp` typically produces caused every report job to fail
# immediately with a permission error. World-readable is fine here since
# the file is already access-controlled by the host filesystem itself —
# nothing this container exposes lets a caller retrieve it.
chmod 644 /path/to/your/gee-service-account.json
chmod 711 "$(dirname /path/to/your/gee-service-account.json)"

docker compose --env-file .env -f docker/docker-compose.prod.yml up -d --build
```

This builds and starts four containers (`postgres`, `backend`, `frontend`,
`nginx`) on one internal Docker network; only `nginx` publishes ports (80
and 443) to the host. The backend container runs `alembic upgrade head`
automatically before it starts serving (see §4).

Verify:

```bash
docker compose --env-file .env -f docker/docker-compose.prod.yml ps   # all "healthy"/"running"
curl -i http://localhost/health         # proxied by nginx directly to the backend
curl -i http://localhost/health/ready   # DB + Earth Engine config checks
```

Then create the first officer account (see
[`Getting_Started.md`](Getting_Started.md#create-the-first-admin-officer-account)
for the exact command, run inside the `backend` container) and open your
domain (or `http://<server-ip>/` before SSL is configured) in a browser.

## 3. Environment variables

The root `.env` file (from `.env.example`) configures the production
Compose stack. Every variable is documented inline in `.env.example` —
read it before deploying, don't just copy it blind. Summary of what each
group controls:

| Group | Variables | Notes |
| --- | --- | --- |
| Database | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `DATABASE_URL` is derived automatically in `docker-compose.prod.yml` — don't set it separately here. |
| Auth | `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRES_MINUTES` | Startup refuses a placeholder/short `JWT_SECRET` when `ENVIRONMENT=production` (`backend/app/core/config.py`). |
| Earth Engine | `GEE_PROJECT_ID`, `GEE_SERVICE_ACCOUNT_JSON_HOST_PATH` | The host path is bind-mounted read-only into the backend container; see `DECISIONS.md` for the GCP project/service-account setup itself. |
| App | `APP_NAME`, `APP_VERSION`, `ENVIRONMENT`, `DEBUG` | `ENVIRONMENT=production` and `DEBUG=False` for any real deployment. |
| Public origin | `FRONTEND_ORIGIN`, `NEXT_PUBLIC_API_BASE_URL` | Leave `NEXT_PUBLIC_API_BASE_URL` blank (same-origin via nginx) unless you're deploying the frontend without nginx in front of it. |
| TLS | `NGINX_CONF_FILE` | `nginx.conf` (plain HTTP, default) or `nginx.https.conf` (TLS for kshetra.in). See §4 below. |

`backend/.env.example` and `frontend/.env.example` are separate files for
running the services directly on your machine (no Docker) — see
`Getting_Started.md`.

## 4. SSL / domain

The production domain is **kshetra.in** (the product was renamed from
TerraRisk on 19 Sep 2026; code, containers and the database keep the
internal name `terrarisk`). A fresh clone comes up over plain HTTP, so
`docker compose up` never fails on a missing certificate.

How it fits together:

- `docker/nginx/nginx.conf` — plain HTTP. Also answers Let's Encrypt
  challenges, so the first certificate is issued with the site still up.
- `docker/nginx/nginx.https.conf` — TLS for `kshetra.in`; HTTP, `www` and
  the bare IP redirect to `https://kshetra.in`.
- `docker/nginx/snippets/` — everything both share, so they cannot drift.
- The `certbot` service renews in place twice a day; nginx reloads every
  6 hours to pick renewals up. No cron job, no copying files.

### Enabling HTTPS (once)

All commands from `/opt/terrarisk`, with
`C="docker compose --env-file .env -f docker/docker-compose.prod.yml"`.

1. **DNS.** At the registrar, add A records for `@` and `www`, both to the
   server's IP. Wait until both resolve:

   ```bash
   getent hosts kshetra.in www.kshetra.in
   ```

2. **Deploy in HTTP mode** (`NGINX_CONF_FILE=nginx.conf`), so nginx serves
   the challenge path and the `certbot` container exists: `$C up -d`.

3. **Rehearse against Let's Encrypt's staging server** — it does not count
   against the production rate limits:

   ```bash
   $C run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
     --cert-name kshetra.in -d kshetra.in -d www.kshetra.in \
     --agree-tos --register-unsafely-without-email --dry-run
   ```

   `--agree-tos` accepts Let's Encrypt's Subscriber Agreement on the
   domain owner's behalf — confirm with them before running it.
   Let's Encrypt no longer sends expiry emails, so no address is
   registered; renewal is automatic and monitored by the steps below.

4. **Issue the real certificate:** the same command without `--dry-run`.

5. **Switch nginx to TLS.** In `.env` set `NGINX_CONF_FILE=nginx.https.conf`
   and `FRONTEND_ORIGIN=https://kshetra.in`, then check the config before
   swapping it in, and recreate:

   ```bash
   $C run --rm --no-deps --entrypoint nginx nginx -t
   $C up -d nginx backend
   ```

6. **Verify:** `curl -sI http://kshetra.in` (301 to https),
   `curl -s https://kshetra.in/health/ready`, and the certificate's expiry:
   `$C run --rm --entrypoint certbot certbot certificates`.

### Interim: HTTPS on the bare IP (until the domain exists)

Let's Encrypt issues certificates for IP addresses, generally available
since January 2026, only on its six-day `shortlived` profile. Certbot 4.0+
renews a certificate of ten days or less once half its lifetime has
passed; the `certbot` service checks every 12 hours and nginx reloads
every 6, so each certificate gets about six renewal attempts before it
could expire. Browsers ignore HSTS on IP addresses, so this mode sends none.

```bash
$C run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot   --preferred-profile shortlived --ip-address 174.138.122.238   --cert-name 174.138.122.238   --agree-tos --register-unsafely-without-email --dry-run   # then without --dry-run
```

Then set `NGINX_CONF_FILE=nginx.https-ip.conf` and
`FRONTEND_ORIGIN=https://174.138.122.238`, run `nginx -t` as in step 5, and
`$C up -d nginx backend`. When the domain works, follow steps 1–6 and
switch to `nginx.https.conf`; the IP certificate can then be deleted with
`certbot delete --cert-name 174.138.122.238`.

After a week without problems, raise `Strict-Transport-Security` in
`nginx.https.conf` from one day to two years.

**Rolling back:** set `NGINX_CONF_FILE=nginx.conf` and `$C up -d nginx`.
Browsers that already received HSTS keep insisting on HTTPS until its
max-age runs out — why it starts at one day.

**Alternative**: if TLS is already terminated upstream (a cloud load
balancer, a bank-managed WAF/reverse proxy in front of this server), leave
nginx on plain HTTP and point that upstream at port 80.

## 5. Reverse proxy design

nginx (`docker/nginx/nginx.conf`) is the only container with a published
port. It proxies `/api/` to the backend and everything else to the
frontend, both on the same public origin — this is why
`NEXT_PUBLIC_API_BASE_URL` can be a relative empty string in production
(browser requests to `/api/v1/...` are same-origin, so CORS never enters
the picture for real traffic; the backend's `FRONTEND_ORIGIN`-scoped CORS
policy stays in place as defense-in-depth for any direct, non-proxied
access). It also handles gzip, baseline security headers, and long-lived
immutable caching for Next.js's content-hashed static assets. See the
comments in `nginx.conf` for what's deliberately left disabled by default
(HSTS, a Content-Security-Policy) and why.

## 6. Updating an existing deployment

```bash
cd terrarisk-platform
git pull
docker compose --env-file .env -f docker/docker-compose.prod.yml up -d --build
```

The backend container re-runs `alembic upgrade head` on every start — this
is a no-op if the schema is already current, and applies any new
migrations otherwise. **Take a database backup before updating** (§7) —
this is a standing recommendation, not optional for anything beyond a demo
environment.

## 7. Backup recommendations

Daily `pg_dump`, kept off the same host if possible:

```bash
# Add to root's crontab (crontab -e), adjust paths/retention as needed:
0 2 * * * docker compose -f /path/to/terrarisk-platform/docker/docker-compose.prod.yml \
    exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
    | gzip > /var/backups/terrarisk/terrarisk-$(date +\%Y\%m\%d).sql.gz
```

Also back up (separately, not part of the database dump):

- The `.env` file (contains secrets — store it somewhere access-controlled, not in the backup directory above verbatim).
- The GEE service-account key file.
- The `pdf_cache` and `uploads` named Docker volumes, if report re-generation cost matters to you — both are regenerable from the database, so this is optional, not critical.

## 8. Recovery

```bash
# Stop the backend so nothing writes during restore:
docker compose -f docker/docker-compose.prod.yml stop backend

gunzip -c /var/backups/terrarisk/terrarisk-YYYYMMDD.sql.gz | \
    docker compose -f docker/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" "$POSTGRES_DB"

# Re-verify schema state (should be a no-op if the dump was already current):
docker compose -f docker/docker-compose.prod.yml up -d backend
docker compose -f docker/docker-compose.prod.yml exec backend alembic upgrade head
```

## Rollback (migrations)

Alembic downgrades are a deliberate manual step, never automatic:

```bash
docker compose -f docker/docker-compose.prod.yml exec backend alembic downgrade -1
```

Alembic downgrades are not a substitute for a real backup — some
migrations (e.g. ones that drop a column) lose data a downgrade cannot
recreate. Restoring from the most recent `pg_dump` (§8) is the reliable
rollback path for anything beyond a purely additive migration.
