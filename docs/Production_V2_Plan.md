# TerraRisk Production V2 — Provisioning Plan

**Status:** APPROVED 6 Aug 2026. Not yet executed.
**Founder decisions locked in:** (1) production domain will be purchased before deployment · (2) DigitalOcean Spaces for automated PostgreSQL backups · (3) Docker log rotation approved.
**Companion document:** `DevOps_Workflow.md` — CI/CD, rollback, verification, and scaling.
**Context:** Production V1 (DigitalOcean droplet at `168.144.68.134`) is confirmed unrecoverable. This is a greenfield rebuild.
**Purpose of this environment:** WELL Labs demos · DCC Bank demos · FSID evaluation · first pilot customers.

---

## Part 1 — Review of the existing Deployment Guide

### What should remain unchanged (it was right)

| Element | Why keep it |
|---|---|
| Four-container Docker Compose architecture (postgres/backend/frontend/nginx, one internal network) | Sound, simple, reproducible. No operational reason to change it |
| Only nginx publishes ports | Correct minimal attack surface — Postgres was never internet-exposed |
| Backend runs `alembic upgrade head` on start | Removes a whole class of "forgot to migrate" incidents |
| The GEE key-permissions lesson (`chmod 644` file, `711` parent dir) | Hard-won from a real failed deployment. Keep verbatim — it will bite again otherwise |
| `.env.example` documenting every variable inline | Genuinely good practice; it's why a rebuild is even straightforward |
| `restart: unless-stopped` on all services | Survives reboots without intervention |
| The `pg_dump` command shape in §7 | The command was correct. The problem was that it was a *recommendation*, not an implemented, verified system |

### What must be improved

| Gap in V1 | V2 fix |
|---|---|
| Backups were documented but **never implemented, and would have been on the same host anyway** | Off-host daily backups + weekly whole-droplet snapshots, both mandatory before go-live |
| Backups never restore-tested | Monthly restore drill, scheduled and logged |
| Secrets existed **only on the server** | Encrypted secrets escrow held off-server |
| Droplet's own IP was the public address | **Reserved IP**, survives droplet destruction |
| No monitoring — we discovered the outage by trying to deploy | DO alert policies + external uptime check |
| Root SSH, single key, no hardening documented | Non-root deploy user, key-only, UFW, fail2ban, unattended security upgrades |
| HTTPS treated as optional (§4) | Domain + TLS is now the default, not an upgrade |
| No "rebuild from zero" runbook | Explicit DR runbook with a target recovery time |

### What actually made V1 unrecoverable

Stated precisely, separating verified fact from inference.

**Verified:**
1. **No off-host database backup existed.** I searched the project directory and home directory for `.sql`/`.sql.gz`/`.dump` — nothing. The §7 cron job was never set up.
2. **No off-server copy of production secrets.** No root `.env` locally; `JWT_SECRET`, `POSTGRES_PASSWORD` and the GEE key path existed only on the lost machine.
3. **The public address was the droplet's own IP.** Losing the droplet lost the address permanently.
4. **No monitoring or alerting.** The outage was discovered days later, by accident, while attempting a deploy.

**Not verifiable from here:** the root cause of the droplet's disappearance (billing, accidental deletion, or provider action). This is itself a finding — there was no audit trail or alerting to tell us.

**What survived, and why that matters:** all application code, the deployment process itself, and every reference dataset (864 Raichur village polygons, Latur boundaries) — because they are in git as committed fixtures loadable by `load_admin_boundaries.py`. **The deployment process was never at risk. Only data, secrets, and identity were.** V2's design follows directly from that distinction.

---

## Part 2 — The Plan

### 1. Infrastructure

| Item | Recommendation | Justification |
|---|---|---|
| **Droplet** | `s-1vcpu-2gb` (1 vCPU, 2 GB RAM, 50 GB SSD) + 2 GB swap | **Revised down from 4 GB on 6 Aug 2026, because GHCR removes the build from the droplet.** The 4 GB figure existed solely to survive `npm run build` on the server; with CI building images, the droplet only pulls and runs. Measured runtime floor: postgres/postgis ~200–350 MB · backend ~300–450 MB (matplotlib + reportlab + shapely + earthengine-api, with report jobs running in-process via `BackgroundTasks`) · Next.js standalone ~80–150 MB · nginx ~20 MB · Docker + OS ~250 MB → **~0.9–1.2 GB peak**, leaving ~0.8 GB headroom. Swap is insurance against a transient PDF-generation spike, not a substitute for RAM |
| **Region** | `BLR1` (Bangalore) | WELL Labs is Bengaluru-based; FSID (if IISc) is Bengaluru; DCCB Latur is Maharashtra. Lowest latency for every prospect, and Indian data residency is a question institutional buyers *will* ask |
| **OS** | Ubuntu 24.04 LTS | Matches the Deployment Guide's assumption; LTS support to 2029 |
| **Reserved IP** | **Yes — attach one** | Directly fixes a failure we just experienced. Free while attached to a droplet. Survives droplet destroy/rebuild, so a rebuilt server keeps the same address and every shared demo link stays alive |
| **Firewall (DO cloud firewall)** | Inbound: 22, 80, 443 only. Outbound: all | Defence in depth alongside host UFW. Cloud firewall applies even if the host misconfigures |

**Cost note:** roughly **$12/month** for the droplet at current DO pricing — verify before committing, pricing changes. This is the cheaper path referenced in the original draft: GHCR was approved on 6 Aug 2026, so builds moved to CI and the droplet halved in size. **The reliability decision and the cost decision converged** — see `Production_V2_CTO_Review.md`.

### 2. Security

| Control | Setting | Rationale |
|---|---|---|
| SSH keypair | **Generate a new ed25519 pair.** Retire `terrarisk_do_deploy` | The old key's state is unknown — it was rejected by an unknown host. Treat as compromised |
| Root SSH login | `PermitRootLogin no` | Previous deploy used `root@` directly. Standard hardening |
| Password auth | `PasswordAuthentication no` | Key-only |
| Service user | Non-root `deploy` user, in `docker` and `sudo` groups | Least privilege; deploys don't need root |
| UFW | `default deny incoming`; allow 22, 80, 443 | Matches the Deployment Guide §1, kept |
| fail2ban | `sshd` jail enabled | Cheap insurance against credential-stuffing on an internet-facing box |
| Automatic updates | `unattended-upgrades`, **security patches only** | Security fixes without unattended feature upgrades that could break the stack |
| SSH port | **Leave on 22** | Moving it is security theatre against real scanners, and adds friction to every future deploy. UFW + fail2ban + key-only is the real control |

### 3. Domain & HTTPS — **DECIDED: purchase a domain before deployment**

**Founder decision, 6 Aug 2026: approved.** A production domain will be registered before Phase E, with HTTPS via Let's Encrypt. Original reasoning retained below.

Why, in order of importance:

1. **A bank will not take `http://168.x.x.x` seriously.** Chrome displays "Not secure" in the address bar. In a DCCB meeting where you're asking to be trusted with agricultural credit decisions, that is a real, avoidable credibility hit.
2. **You cannot get a TLS certificate for a bare IP.** No domain means no HTTPS, permanently.
3. **A shareable link.** "terrarisk.in" survives in an email thread; an IP address does not.
4. **Combined with the Reserved IP, rebuilds never break shared links.** This is the pair that makes V1's failure mode impossible.
5. **It is the cheapest credibility purchase available to us** — roughly the cost of one coffee per year, against three meetings that matter.

Suggested names (availability unverified — check at registration): `terrarisk.in`, `terrarisk.co.in`, `terrarisk.earth`. A `.in` also signals an India-focused company to Indian institutional buyers.

**Only defensible reason to stay on an IP:** if every demo will be screen-shared by you personally and never accessed independently. Given FSID evaluation and pilot customers are explicit objectives, that assumption fails.

### 4. Deployment

Unchanged architecture — no strong operational reason to deviate:

```
Internet → DO Cloud Firewall → UFW → nginx (:80/:443, only published ports)
                                       ├── /api/*  → backend  (FastAPI, alembic on start)
                                       └── /*      → frontend (Next.js standalone)
                                                     backend → postgres (postgis/postgis:16-3.4)
                                    internal network: terrarisk_net
                                    volumes: postgres_data (critical), pdf_cache, uploads (regenerable)
```

Deployment follows Deployment Guide §2, with two additions: it runs as the `deploy` user (not root), and the reference-data load (`load_admin_boundaries.py` against the committed Raichur/Latur fixtures) becomes an explicit post-deploy step rather than an afterthought.

**Docker log rotation — DECIDED: approved 6 Aug 2026.** To be added to `docker-compose.prod.yml` on every service during Phase E. Unbounded `json-file` logs filling the disk is one of the most common causes of a small droplet dying quietly.

```yaml
logging:
  driver: json-file
  options: { max-size: "10m", max-file: "3" }
```

### 5. Secrets

**Rule: no secret ever enters git.** Already structurally true — `.gitignore` covers `.env`, `.env.*`, `*.key`, `*.pem`, and I verified no secret has ever been committed in the repo's entire history.

| Secret | Generation | Storage on server | Escrow (the V1 gap) |
|---|---|---|---|
| `JWT_SECRET` | `openssl rand -base64 48` | `/opt/terrarisk/.env`, `chmod 600`, owned by `deploy` | Encrypted escrow |
| `POSTGRES_PASSWORD` | `openssl rand -base64 32` | same | Encrypted escrow |
| GEE service-account JSON | Downloaded from GCP | `/opt/terrarisk/secrets/gee.json`, `chmod 644`, parent dir `711` (per the guide's hard-won lesson) | Encrypted escrow + still downloadable from GCP |
| All other env vars | Per `.env.example` | same `.env` | Encrypted escrow |

**Secrets escrow — the fix for V1's actual failure:** encrypt `.env` + the GEE key into a single archive (`age` or `gpg`), and store it in **two places off the server** — your password manager, plus one offline copy. Refresh whenever a secret rotates.

Without this, losing the droplet means losing the ability to reconstitute the environment even *with* a database backup. That is precisely what happened.

### 6. Backups — mandatory before go-live

Two independent layers, because they fail differently:

**Layer 1 — DO Droplet Backups (weekly whole-machine snapshots).** ~20% of droplet cost (≈$4.80/mo). Recovers the entire machine including config. Coarse-grained but zero-effort.

**Layer 2 — Daily `pg_dump`, shipped OFF-HOST to DigitalOcean Spaces.** **DECIDED: approved 6 Aug 2026** — Spaces, not the laptop-pull alternative. This is the layer whose absence caused V1's data loss.

```
02:00 daily → pg_dump → gzip → upload to DO Spaces (s3-compatible, ≈$5/mo)
```

**Retention:** 7 daily · 4 weekly · 3 monthly. Older pruned automatically.

**Restore procedure** (extends Deployment Guide §8): stop backend → download dump from Spaces → `gunzip | psql` → `alembic upgrade head` → start backend → verify row counts on `app_user`, `catchment`, `admin_boundary`.

**Verification schedule — non-negotiable, monthly:** restore the latest dump into a throwaway Postgres container and assert non-zero row counts on those three tables. Log the result in the Founder Dashboard. **An untested backup is a belief, not a backup** — and this is the discipline that would have made V1 a nuisance instead of a loss.

*(The laptop-pull alternative was considered and rejected: it only works when your machine is on. Spaces is the reliable option.)*

### 7. Monitoring — deliberately minimal

Enterprise observability is the wrong tool at this stage. Three things, ~15 minutes to set up, ~$0:

1. **DO Monitoring + alert policies** (free, built in): alert on CPU >80% for 5 min, memory >80%, **disk >80%** (disk is what actually kills small droplets).
2. **UptimeRobot free tier**: HTTPS check on `/health` every 5 minutes → email alert. *This alone would have told us V1 was down within five minutes instead of days.*
3. **Existing Docker healthchecks** — already in `docker-compose.prod.yml`, keep them.

Explicitly NOT doing: Prometheus, Grafana, ELK, Datadog, Sentry. Revisit when there is a paying customer with an SLA.

### 8. Disaster Recovery

**Target: full rebuild from zero in under 2 hours, losing at most 24 hours of data.**

The V2 DR position rests on four things surviving any single server loss:

| Asset | Where it survives | Recovery |
|---|---|---|
| Application code | git (GitHub) | `git clone` |
| Deployment process | `Deployment_Guide.md` in git | Follow it |
| Reference data (864 villages, Latur) | Committed fixtures | `load_admin_boundaries.py` |
| **Customer data** | **Off-host daily dumps (Spaces)** | Restore procedure §6 |
| **Secrets** | **Encrypted escrow, off-server** | Decrypt, place, `chmod` |
| **Public address** | **Reserved IP** | Re-attach to new droplet |

**Rebuild runbook:** provision droplet → attach Reserved IP → harden (§2) → clone repo → restore secrets from escrow → `docker compose up -d --build` → restore latest DB dump → verify → re-point nothing (Reserved IP + domain already correct).

The Deployment Guide will be updated with this runbook and an explicit statement that **§6 and §7 are go-live blockers, not recommendations** — the exact framing failure that caused V1.

---

## Part 3 — Execution Checklist

Nothing below is executed until approved. **[F]** = founder (DO console / registrar / GCP), **[C]** = Claude (once SSH works).

### Phase A — Provision *(founder, ~30 min)*
- [ ] A1 **[F]** Confirm DO account is in good standing (rules out billing as V1's cause)
- [ ] A2 **[C]** Generate new ed25519 keypair; give founder the public key
- [ ] A3 **[F]** Add the new public key to the DO account
- [ ] A4 **[F]** Create droplet: `s-2vcpu-4gb`, Ubuntu 24.04 LTS, region `BLR1`, new SSH key, name `terrarisk-prod-v2`
- [ ] A5 **[F]** Create and attach a **Reserved IP**
- [ ] A6 **[F]** Create DO cloud firewall: inbound 22/80/443 only; attach to droplet
- [ ] A7 **[F]** Enable DO weekly backups on the droplet
- [ ] A8 **[F]** Share the Reserved IP with Claude

### Phase B — Domain *(founder, ~20 min — parallel with A)*
- [x] B1 **[F]** ~~Decide: domain or IP-only~~ — **DECIDED: domain**
- [ ] B2 **[F]** Register domain
- [ ] B3 **[F]** Point an `A` record at the **Reserved IP**
- [ ] B4 **[F]** Confirm DNS resolves before Phase E

### Phase C — Harden *(Claude, ~30 min)*
- [ ] C1 **[C]** SSH in, `apt update && upgrade`
- [ ] C2 **[C]** Create `deploy` user (sudo + docker groups), install the SSH key
- [ ] C3 **[C]** `PermitRootLogin no`, `PasswordAuthentication no`, reload sshd — **verify `deploy` login works before closing the root session**
- [ ] C4 **[C]** UFW: default deny incoming; allow 22/80/443; enable
- [ ] C5 **[C]** Install + enable fail2ban (sshd jail)
- [ ] C6 **[C]** Configure `unattended-upgrades` (security only)
- [ ] C7 **[C]** Install Docker Engine + Compose plugin

### Phase D — Secrets *(both, ~20 min)*
- [ ] D1 **[C]** Generate `JWT_SECRET` and `POSTGRES_PASSWORD`
- [ ] D2 **[F]** Provide the GEE service-account JSON (or confirm reuse of the existing GCP service account)
- [ ] D3 **[C]** Place key at `/opt/terrarisk/secrets/gee.json`; `chmod 644` file, `711` parent
- [ ] D4 **[C]** Write `/opt/terrarisk/.env` from `.env.example`; `chmod 600`
- [ ] D5 **[C]** Produce encrypted escrow archive (`.env` + GEE key)
- [ ] D6 **[F]** Store escrow in password manager **and** one offline copy

### Phase E — Deploy *(Claude, ~45 min)*
- [ ] E1 **[C]** Clone repo to `/opt/terrarisk`
- [ ] E2 **[C]** Add Docker log rotation to prod compose *(approved)*
- [ ] E3 **[C]** `docker compose up -d --build`; confirm all four containers healthy
- [ ] E4 **[C]** Verify `/health` and `/health/ready`
- [ ] E5 **[C]** Load reference data (Raichur + Latur fixtures)
- [ ] E6 **[C]** Create the first admin account
- [ ] E7 **[C]** TLS: certbot, install cert, enable the nginx 443 block *(requires B4)*
- [ ] E8 **[C]** Confirm HTTP→HTTPS redirect and a valid certificate

### Phase F — Backups *(Claude, ~30 min) — GO-LIVE BLOCKER*
- [ ] F1 **[F]** Create a DO Space + access keys *(approved — Spaces)*
- [ ] F2 **[C]** Install and configure the upload client
- [ ] F3 **[C]** Install the daily 02:00 backup cron with retention pruning
- [ ] F4 **[C]** **Run one backup manually and confirm the object exists in Spaces**
- [ ] F5 **[C]** **Perform one full restore drill into a throwaway container; verify row counts**
- [ ] F6 **[C]** Document the drill result

### Phase G — Monitoring *(both, ~15 min)*
- [ ] G1 **[F]** DO alert policies: CPU >80%, memory >80%, disk >80%
- [ ] G2 **[F]** UptimeRobot check on `/health`, 5-minute interval, email alert
- [ ] G3 **[C]** Verify an alert actually fires (trigger a test)

### Phase H — Verify & Document *(Claude, ~45 min)*
- [ ] H1 **[C]** End-to-end smoke test: log in → create catchment (Select Area) → generate real GEE report → dashboard → PDF
- [ ] H2 **[C]** Confirm zero console errors on every page
- [ ] H3 **[C]** Update `Deployment_Guide.md`: DR runbook, backups as go-live blockers, hardening steps, escrow procedure
- [ ] H4 **[C]** Record the V2 environment facts (IP, domain, droplet name, region) in `DECISIONS.md`
- [ ] H5 **[F]** Confirm demo-readiness: clean data, no test artifacts

---

## Estimated cost

**Revised 6 Aug 2026 for minimum pre-revenue burn.** See `Production_V2_CTO_Review.md` §6 for the full option comparison and reasoning.

| Item | Approx / month | Verdict |
|---|---|---|
| Droplet `s-1vcpu-2gb` | $12 | **Spend** — demo reliability |
| Domain (≈$12/yr) | ~$1 | **Spend** — credibility + TLS is impossible without it |
| Reserved IP (attached) | $0 | **Spend** — free, and fixes a V1 failure |
| Off-host DB backups (free-tier object storage) | $0 | **Spend** — the V1 failure that cost us everything |
| Monitoring (DO alerts + UptimeRobot free) | $0 | **Spend** — would have caught V1 in 5 min |
| GHCR image registry | $0 | **Spend** — free for this repo |
| Swap (2 GB, on disk) | $0 | **Spend** — OOM insurance |
| ~~DO weekly droplet snapshots~~ | ~~$2.40~~ | **Defer** — rebuild is ~1.5 h and everything irreplaceable is already off-host |
| ~~Staging droplet~~ | ~~$12~~ | **Defer** — no customer would notice an outage yet |
| ~~Managed Postgres~~ | ~~$15~~ | **Defer** — until the DB competes for RAM |
| **Total** | **≈$13/month** | |

Verify current DO pricing before committing — these are approximate.

**Down from ≈$35/month in the original draft**, without giving up a single reliability control that V1's failure actually demanded. The savings came from moving builds to CI (halving the droplet), using free-tier object storage instead of paid Spaces, and deferring whole-machine snapshots that duplicate a fast, documented rebuild path.

---

*Approved 6 Aug 2026. No step above has been executed yet — execution begins on explicit instruction.*
