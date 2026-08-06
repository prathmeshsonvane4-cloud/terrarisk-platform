# Production V2 — Final CTO Design Review

**Date:** 6 August 2026 · **Status:** Review complete. Architecture FROZEN. Nothing executed.
**Reviews:** `Production_V2_Plan.md` + `DevOps_Workflow.md` as one system.
**Constraint applied throughout:** pre-revenue. *Spend money only when customer demand requires it.*

---

## 1. Would this architecture survive 10 pilot customers tomorrow?

**Mostly yes — and the parts that wouldn't are cheap to add later, except two disciplines that are painful to retrofit.**

Holds fine at 10 customers: the four-container topology, nginx-only exposure, GHCR image deploys, off-host backups, Reserved IP, the DR runbook. None of that is throwaway work.

Would need adding **at** 10 customers (all deferrable, all cheap when the time comes):

| Need | When it triggers | Cost |
|---|---|---|
| Managed Postgres (automated backups, PITR, failover) | DB competes with app for RAM | +$15/mo |
| Staging environment | A customer would notice a 5-minute outage | +$12/mo |
| Vertical resize (2 → 4 GB) | Sustained memory >70% | +$12/mo |
| Dedicated worker container | GEE jobs queue behind web requests | $0 |

### The two things I'd change NOW, because retrofitting them hurts

**1. Backward-compatible migration discipline.** Already specified in `DevOps_Workflow.md` §3.3 — adopt it from the first migration, not the fiftieth. Once real customer data exists, a destructive migration you can't roll back means restoring from a dump and losing hours of their data. Free to adopt today; expensive to introduce after the fact.

**2. Tenant isolation verification.** Org scoping exists in the code (`created_by` / organization scoping), but it has never been *proved* with a test that customer A cannot read customer B's catchments. Right now that's theoretical. With one customer it's harmless; the day customer #2 onboards it becomes the single highest-severity bug class in the product. Write the test before it matters — this is a test, not a feature.

Everything else on the "10 customers" list is a config change or a bigger box. Those two are behavioural.

---

## 2. Is GHCR correct versus building on the droplet? — engineering trade-offs only

**Yes.** And the decision compounds favourably, which is rare.

**What GHCR gives us**

- **Rollback becomes an artifact swap, not a rebuild.** `IMAGE_TAG=<prev-sha> docker compose up -d` — seconds, byte-identical to what was tested. Rebuilding an old commit only *approximates* the previous state: base images drift, transitive dependencies move.
- **The artifact tested is the artifact deployed.** CI builds it once; that exact image is what runs.
- **A failed build can never half-deploy production.** Build failure stops the pipeline before the deploy job exists. V1's failure mode of "deploy left the stack in a broken intermediate state" becomes structurally impossible.
- **It removes the build from the server**, which is what let the droplet drop from 4 GB to 2 GB.

**What GHCR costs us**

- Two more moving parts: registry auth on the droplet, image tags in compose.
- Deploy now requires pulling ~500 MB–1 GB over the network. Slower than an incremental local rebuild would be, though bandwidth is free.
- **A new external dependency in the deploy path.** If GHCR is unavailable, we cannot deploy. Running production is unaffected — images are already on disk — so this degrades deployment, not availability.
- Disk hygiene becomes mandatory: accumulated images will fill a 50 GB disk if never pruned. Mitigated by keeping the last 5 and pruning the rest.
- `latest` must never be used in production compose. Tags must be immutable SHAs, or rollback silently breaks.

**Net:** the only real new risk is a deploy-time dependency on GHCR availability, which does not affect a running system. Against that, we gain genuine rollback, build/deploy isolation, and a 50% smaller server. Clear win.

---

## 3. Is anything unnecessarily complicated for our stage?

Yes — four things, and I'm cutting them.

| Over-engineered | Verdict | Reasoning |
|---|---|---|
| **DO weekly droplet snapshots** ($2.40/mo) | **Cut** | Duplicates a documented ~1.5 h rebuild where every input is already off-host. Buys back 1.5 hours of downtime that no one is currently waiting on. Reinstate at first pilot |
| **DO Spaces** ($5/mo, $5 minimum) | **Reconsider — see §6** | Our gzipped dumps are tens of megabytes. Free-tier S3-compatible storage covers this ~100× over |
| **Quarterly full DR rehearsal** | **Reduce** | Do it **once** before the first customer conversation, then quarterly *after* the first pilot. A solo founder rehearsing DR quarterly with zero customers is ceremony |
| **GitHub Environment approval gates** | **Cut the approval, keep the Environment** | Self-approving your own PR is friction theatre. Keep the Environment for secret scoping and audit trail; require no reviewer |

**Deliberately keeping**, despite looking like ceremony:

- **Automated monthly backup verification.** This is the exact discipline whose absence destroyed V1. It is ~20 lines and it shouts when it breaks.
- **Auto-rollback on health-check failure.** ~15 lines of bash; converts a bad deploy from an outage into a blip.
- **Six deployment health checks.** All cheap. `/health/ready` alone justifies the set — it checks DB *and* Earth Engine config, which is the class of silent failure that ran unnoticed for months in V1.

---

## 4. What's missing that could realistically cause production failure?

Seven real operational risks not yet covered. Ordered by likelihood × impact.

| # | Risk | Why it's real | Fix |
|---|---|---|---|
| **1** | **TLS certificate expiry** | Let's Encrypt expires every 90 days. Our only cert check runs *at deploy time* — if we don't deploy for 90 days, nothing notices until the site goes HTTPS-dead, likely mid-demo | certbot renewal timer **plus** UptimeRobot SSL-expiry monitoring (free, independent of our own cron) |
| **2** | **SSH lockout** | Root login disabled + one key. Lose that key and we are locked out of our own production server | Second recovery key held separately, and confirm DO console recovery access works **before** disabling root |
| **3** | **Disk exhaustion from Docker images** | Every deploy pulls new images. 50 GB fills quietly; symptoms look like random failures | `docker image prune` in the deploy job, keep last 5. Disk >80% alert already planned |
| **4** | **Domain expiry** | A lapsed domain kills the site and can be re-registered by anyone | Auto-renew ON at registration, plus registrar contact email that is actually monitored |
| **5** | **Unencrypted backups in object storage** | Dumps contain user accounts and, later, customer data. Object storage is access-controlled, not encrypted by us | `gpg`/`age` encrypt before upload; key goes into the same escrow as `.env` |
| **6** | **GEE quota or project disablement** | `/health/ready` verifies *configuration*, not *quota*. A quota trip means reports fail while everything looks healthy | Accept as a known limitation; surface job-failure reasons in the UI (already honest). Watch during demos |
| **7** | **No swap on a small droplet** | A transient matplotlib/PDF spike triggers the OOM killer mid-demo | 2 GB swap file. Free, uses disk |

Items 1, 2, 3 and 5 are added to the checklists. Item 4 is a registration-time setting. Item 6 is accepted and documented. Item 7 is in the droplet spec.

---

## 5. Architecture freeze

**The Production V2 architecture is FROZEN as of 6 August 2026.**

Frozen: droplet topology · four-container Compose stack · GHCR image deployment · GitHub Actions CI/CD · secrets model · backup strategy · monitoring set · DR runbook.

Changes permitted **only** when triggered by one of:
1. **Customer feedback** — a named customer requirement that the architecture cannot meet
2. **A production incident** — a real failure, with a postmortem
3. **Scaling beyond 10 customers** — measured, not anticipated

Not valid reasons: a more interesting technology · a cleaner abstraction · a blog post · anticipated future scale.

---

## 6. Cost-optimised redesign

### Droplet options compared

Runtime floor, measured from actual dependencies (`matplotlib`, `reportlab`, `shapely`, `earthengine-api`; report jobs run **in-process** via FastAPI `BackgroundTasks`):

> postgres/postgis ~200–350 MB · backend ~300–450 MB · Next.js standalone ~80–150 MB · nginx ~20 MB · Docker + OS ~250 MB → **~0.9–1.2 GB steady, higher during PDF generation**

| Option | ~Cost/mo | Expected limitations | Deployment risk | Sufficient? |
|---|---|---|---|---|
| **1 vCPU / 1 GB** | **$6** | Below the measured floor before any spike. Postgres and the Python geo stack alone approach 1 GB | **High.** OOM killer terminates a container mid-demo. Swap thrashing makes the app visibly slow exactly when someone is watching | **No.** Saves $6/mo and risks the meeting the server exists for |
| **1 vCPU / 2 GB** | **$12** | Single core — concurrent GEE report + page load will feel slower. Irrelevant at our concurrency (≈1 user) | **Low**, once builds are in CI. ~0.8 GB headroom + swap | **Yes — recommended** |
| **2 vCPU / 4 GB** | **$24** | None | Very low | Yes, but **we would be paying $12/mo for headroom no current workload needs** |

**Recommendation: `s-1vcpu-2gb` + 2 GB swap.**

The $6 delta over the 1 GB box is not general-purpose headroom — it is specifically insurance against an OOM kill during a WELL Labs or DCC Bank demo. That is the one failure this environment exists to prevent, so it is exactly where the money belongs. The $12 delta up to 4 GB buys capacity for load we do not have.

### Did CI remove the memory bottleneck?

**Yes — completely, and it was the *only* reason 4 GB was ever proposed.** `frontend/Dockerfile:23` runs `npm run build`; Next builds routinely exceed 2 GB. With GHCR, that happens on GitHub's runners. The droplet only pulls and runs. **The reliability decision and the cost decision pointed the same way** — that convergence is the strongest signal in this review that GHCR was right.

### Where to spend, and where not to

**Spend now (~$13/month total):**

| Item | Cost | Why this one |
|---|---|---|
| Droplet 1 vCPU / 2 GB | $12 | The demo must not fall over |
| Domain (~$12/yr) | ~$1 | A bank will not trust `http://<ip>`; TLS is impossible without it |
| Reserved IP | $0 | Free, and directly fixes a V1 failure |
| Off-host encrypted backups | $0 | The V1 failure that cost us everything |
| Monitoring (DO alerts + UptimeRobot) | $0 | Would have caught V1 within 5 minutes |
| GHCR | $0 | Free for this repository |
| Swap | $0 | OOM insurance |

**Deliberately NOT spending yet:** droplet snapshots ($2.40) · staging droplet ($12) · Managed Postgres ($15) · paid monitoring/APM ($0–50) · CDN · load balancer · second region · paid uptime tiers. **Combined deferral: ~$30–80/month held back until a customer requires it.**

### One change I recommend to your approved decision

You approved **DO Spaces** for backups. I'd flag one thing, since you also asked me to minimise recurring cost in the same instruction:

- **Spaces has a $5/month floor** regardless of usage. Our gzipped dumps are tens of megabytes.
- **Backblaze B2 or Cloudflare R2 free tiers** (~10 GB free) cover us roughly 100× over, at **$0**, with the **same S3-compatible API** — the backup script is identical either way.
- **The trade-off is real but small:** one more vendor account, one more credential in escrow. Spaces keeps everything on one bill and one console.

**My recommendation: free-tier B2 or R2** — $60/year saved, zero reliability difference, identical tooling. But **if you prefer single-vendor simplicity, Spaces at $5/mo is entirely defensible** and I'll implement it without further debate. Your call; it's the last open decision.

### Minimum realistic monthly cost until first pilot

**≈$13/month** (~₹1,100), assuming free-tier object storage. **≈$18/month** with DO Spaces.

For context: that is the cost of keeping a credible, backed-up, monitored production environment alive for the WELL Labs, DCC Bank and FSID conversations. Down from the ~$35/month first draft, with no reliability control removed.

---

## 7. Production Readiness Score — **73 / 100**

| Dimension | Score | Deductions |
|---|---|---|
| **Infrastructure** | 85 | −10 not yet provisioned; −5 DO account standing unverified (if billing killed V1, V2 dies the same way in ~30 days) |
| **Deployment** | 80 | −10 CI/CD workflows designed but not written; −10 compose not yet migrated from `build:` to `image:` |
| **Security** | 80 | −10 SSH lockout has no second key or verified console-recovery path; −10 backup encryption specified in this review but not yet in the plan |
| **Operations** | 78 | −12 TLS expiry unmonitored between deploys; −5 image pruning unspecified; −5 no DR rehearsal has ever been executed |
| **Business Readiness** | 40 | −60 zero customers, zero LOIs, zero documented discovery conversations; **IP ownership unresolved** |
| **Scientific Readiness** | 72 | −18 `resolution_flags` still hardcoded `[]`, so sub-pixel villages report false precision; −10 composite stress score never field-calibrated |

**Overall: 73/100** (equal weighting).

### What the score actually says

Read it in two halves, because the average hides the finding:

- **Technical readiness (infra, deployment, security, ops): ~81/100** — sound design, well above the line to start executing. Every deduction is a small, named, closeable gap.
- **Company readiness (business, scientific): ~56/100** — this is what drags the number down, and **not one point of it is fixed by deploying a server.**

### Recommendation: **execute Production V2 now**

The sub-90 score does *not* mean "don't deploy." It means the company is less ready than the infrastructure, and deploying is precisely what unblocks the business half — you cannot run the customer conversations that fix a 40/100 business score without a live product.

**Minimum work before execution** (all small, all in the checklists):

1. **[F]** Verify DO account standing — 5 min. Non-negotiable; if billing killed V1, V2 repeats it
2. **[F]** Decide backup storage: free-tier B2/R2 or DO Spaces — 2 min
3. **[C]** Add to the plan: backup encryption, TLS-expiry monitoring, image pruning, swap, second SSH key — plan amendments, ~15 min
4. **[C]** Migrate compose `build:` → `image:` with a local build overlay — part of Phase E

Items 1 and 2 are yours and take under 10 minutes. Item 3 I'll fold in before Phase A. Item 4 is already scheduled work.

**Not blockers for deployment, but the real priorities afterwards:** the IP question (R1), wiring `resolution_flags` (R4), and the first customer conversations. Those move the 40 and the 72 — and a server, however well built, will not.

---

*Review complete. Architecture frozen. Awaiting one decision (backup storage) and instruction to begin Phase A.*
