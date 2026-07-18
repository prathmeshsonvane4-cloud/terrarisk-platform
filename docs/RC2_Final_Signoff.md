# TerraRisk — RC2 Final Production Readiness & Pilot Sign-off

**Audit date:** 18 Jul 2026
**Scope:** Full production-readiness audit ahead of the first external pilot
(District Central Cooperative Banks, NABARD, commercial banks, government
agencies). Architecture frozen — this audit does not redesign anything; it
verifies, and where a genuine release blocker was found, fixes it.

## Architecture summary

Unchanged from M3: FastAPI (async, Python 3.14) backend + Next.js 15
(standalone) frontend + PostgreSQL/PostGIS, deployed as four Docker Compose
services (`postgres`, `backend`, `frontend`, `nginx`) on one internal
network, with nginx as the single public origin (proxies `/api/` and now
`/health`/`/health/ready` to the backend, everything else to the frontend).
Report generation runs as an in-process, database-tracked background job
(no message queue), Earth Engine is accessed only through the
`SatelliteDataProvider` interface, and the risk engine is a pure,
rule-based, configurable function. See `docs/DECISIONS.md` for the full
reasoning behind every choice, including this audit's own entries.

## Verification summary

This audit did not review code in isolation — every claim below was
exercised against a real, fresh Docker deployment:

- **Fresh install, from a completely empty Postgres volume**, following
  only the documentation: `docker compose up` succeeded in one shot, all
  four containers reached healthy, migrations 0001-0004 applied
  automatically, `create_admin_user.py` and `seed_default_config_weight.py`
  ran successfully inside the container.
- **Full user journey, real data, no mocks**: logged in through nginx,
  created a real farm near Killari via the API (server-computed area
  1.17 ha), triggered a real report, watched it progress through all 11
  pipeline stages against **live Google Earth Engine** (NDVI/MNDWI/NDMI,
  rainfall, climatology, water history — 34 months of real satellite data
  fetched), reached a real computed risk score (38/100, moderate,
  94% confidence) with a full factor breakdown, downloaded a real 2.7MB
  PDF report, viewed it in the browser (Report/Evidence/Method tabs, all
  rendering real data), and logged out — confirmed the session was
  actually cleared, not just the UI.
- **Error recovery, tested live, not assumed**: stopped Postgres mid-session
  → API degraded gracefully (`503`, no leaked exception detail) →
  restarted Postgres → backend recovered automatically with **zero manual
  intervention** (the `pool_pre_ping` fix, directly verified). Restarted
  backend and frontend containers independently — both recovered cleanly.
  Tested invalid, malformed, missing, and expired JWTs — all correctly
  rejected with `401`, no information leakage. Tested a container started
  with `JWT_SECRET` completely unset — fails in ~10 seconds with the real
  error immediately visible (verified both before and after the
  entrypoint diagnostic fix below).
- **Rate limiting, tested live**: 8 rapid login attempts from one client
  returned `401 401 401 401 429 429 429 429` — the new limiter engages
  exactly as configured.
- **Backend test suite: 139/139 passing** (135 prior + 4 new job-reaper
  tests), including against a real PostGIS instance. `pip-audit`: **no
  known vulnerabilities** in any pinned dependency.

## Deployment summary

No changes to the deployment topology from M3. Docker image sizes,
Compose health-check ordering, and the nginx reverse-proxy design are
unchanged except: `/health` and `/health/ready` are now proxied through
the public origin (previously only reachable on the internal Docker
network), and `docker-entrypoint.sh`'s startup logic now distinguishes a
genuine database-connectivity race (retries, as before) from a broken
configuration (fails immediately, with the real error — previously
buried under misleading retry noise).

## Security summary

Fixed and verified this pass: no rate limiting anywhere on login (now
nginx-enforced, per-IP); `/health/ready` leaked raw exception text on a DB
failure (now generic); the only account-provisioning script had no way to
rotate an existing password and no minimum length (both added). `pip-audit`
clean. Every resource-scoped endpoint re-verified to enforce owner-or-branch
authorization; no SQL injection, SSRF, path traversal, mass-assignment, or
algorithm-confusion vectors found. **Known, accepted limitation, not fixed
this pass:** the sliding refresh token has no absolute session-length
ceiling or revocation mechanism beyond account deactivation — this
compounds the already-documented localStorage-token trade-off from M2A and
requires a real design decision (a session-epoch mechanism) rather than a
quick fix; tracked explicitly, see Known Limitations below.

## Known limitations

Recorded here so they are a visible, tracked backlog — not a silently
dropped audit finding (full reasoning for each in `docs/DECISIONS.md`'s
RC2 entries):

1. **No absolute session ceiling / token revocation** beyond deactivating
   an account. A stolen token can be kept alive indefinitely via
   `/auth/refresh` until an admin notices and deactivates the account.
   Revisit before any deployment beyond a controlled pilot (same trigger
   condition M2A's localStorage-token entry already named).
2. **No retry-with-backoff for individual Earth Engine calls.** A
   transient network blip fails the whole report; partially mitigated
   already (a manual retry only re-fetches the stage that failed, not the
   whole pipeline, since successful stages are cached).
3. **No container resource limits, log-rotation config, or Linux-capability
   hardening** in `docker-compose.prod.yml`. Not sized this pass —
   guessing limits without real pilot load data risks causing the
   OOM-kills they're meant to prevent.
4. **No metrics/APM endpoint.** Structured JSON logs exist; no Prometheus
   or equivalent.
5. **Backups are a documented manual `pg_dump` cron recipe**
   (`docs/Deployment_Guide.md`), not automated or verified by anything in
   this repository.
6. **Two Low-priority code-quality items**, not release-blocking: an
   untracked `TerraRisk-Report.pdf` sitting in the repo root (a
   test-verification artifact from earlier manual testing — left
   untouched since it wasn't created by this audit and isn't this audit's
   file to delete unilaterally; recommend the founder remove it before any
   external repo review).

## Version recommendation

**`v1.0.0-rc1`** — see Pilot Readiness Decision below.

---

*(Executive summary, scores, and the full findings list for this audit are
in the assistant's final report for this session, not duplicated here —
this file is the durable artifact; the chat response is the presentation
of it.)*
