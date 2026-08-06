# TerraRisk Startup Readiness Audit — 5 August 2026

**Prepared as:** technical co-founder / CTO.
**Supersedes nothing.** Extends `TerraRisk_Founder_Audit_2026.md` (same date) with an external-customer lens: infrastructure, security, licensing, legal, and business readiness.
**Grounding:** every finding below was verified in this session against the live repo, the GitHub API, and the running infrastructure. Nothing is recalled from memory.

---

## Phase 1 — Startup Readiness Audit

### CRITICAL

| # | Finding | Why it's critical | Verified how |
|---|---|---|---|
| C1 | **IP ownership between TerraRisk and WELL Labs is undocumented.** Service 2 was built during/adjacent to a WELL Labs internship; no IP-assignment terms exist anywhere in this repo. | Gates incorporation, fundraising, AND a WELL Labs pilot simultaneously. A funder's diligence will find this. | Searched all of `docs/`; no internship contract or IP terms present |
| C2 | **Production is unreachable.** | You cannot run a customer demo. Every Phase-2 conversation assumes a live product. | Re-probed live: nginx 404 on all paths incl. `/api/v1/health`; SSH host key rejected |
| C3 | **Zero documented customer conversations, LOIs, or pilots.** | This is the actual difference between "startup" and "advanced side project." It is the first thing any investor asks for. | No such artifact exists in the repo |

### HIGH

| # | Finding | Why it matters |
|---|---|---|
| H1 | **The entire codebase is a PUBLIC GitHub repository** (`prathmeshsonvane4-cloud/terrarisk-platform`, confirmed `visibility: public` via API). Both services' full methodology — water balance, recharge stress, recommendation engine — is world-readable. | Legally protected (LICENSE is All Rights Reserved, no use granted), but strategically this needs a *conscious decision*, not a default. It invites the VC question "what's your moat?" and interacts badly with C1 — if WELL Labs has any claim on Service 2, that work has been published. It may also affect patentability if anything here was ever intended to be patented. Not necessarily wrong — a public portfolio builds credibility for a solo founder — but it must now be a decision, not an inheritance. |
| H2 | **`resolution_flags` hardcoded to `[]`.** Median Raichur village ~715 ha vs ~3,080 ha CHIRPS pixel — most villages are sub-pixel for rainfall and the warning field built to say so has never fired. | Presenting numbers with more apparent certainty than the science supports, to a domain expert (WELL Labs), is the fastest way to lose technical credibility. ~half a day to fix. |
| H3 | **Composite 0–100 stress score has never been field-validated** and has no published equivalent to check against. | This is the core scientific claim. "Uncalibrated" is honestly labelled in-product, which is good — but it caps how strongly the claim can be made until real ground data validates it. |
| H4 | **GEE free tier is noncommercial-only; Esri basemap needs commercial licensing review.** Both already self-flagged in `DECISIONS.md`. | A paid pilot on the free tier is a license violation. Must be closed before money changes hands, not after. |
| H5 | **No incorporated entity.** | Cannot sign a pilot agreement, cannot invoice, no liability shield, no vehicle to receive funding. |

### MEDIUM

| # | Finding | Why it matters |
|---|---|---|
| M1 | No `SECURITY.md`, no documented vulnerability-disclosure process. | Banks ask. Cheap to add when needed. |
| M2 | No formal Dataset & License Register. | The underlying facts exist (DataMeet ODbL, Esri terms, GEE terms) but aren't compiled into one diligence-ready artifact. |
| M3 | No formal backup/restore *rehearsal*. Deployment guide covers DR in writing (11 references), but it has never been executed end-to-end. | Untested DR is a plan, not a capability. Relevant once a customer's data is in the system. |
| M4 | Local database contains mixed test/demo artifacts. | Risk of accidentally demoing wrong data. Trivial to fix. |
| M5 | Single-founder key-person risk; no scientific co-signer. | Affects both funding and scientific credibility. |

### LOW

| # | Finding |
|---|---|
| L1 | No `SLA`/uptime commitments documented — not needed until a paid pilot. |
| L2 | No multi-tenancy hardening beyond current role scoping — not needed until customer #2. |
| L3 | No formal changelog discipline for customer-facing releases — `CHANGELOG.md` exists; process doesn't yet matter. |

### What is genuinely GOOD (and should be said out loud)

Stated because an honest audit reports strengths as evidence, not flattery:

- **No secret has ever been committed** (verified across all git history); `.gitignore` correctly covers `.env`, `*.key`, `*.pem`.
- **CI exists and runs** backend migrations + tests, frontend lint + unit tests + build.
- **Deployment is documented**, including a real operational lesson (GEE key file permissions) learned from an actual failed deployment.
- **Test suites are substantial** — 556 backend, 110+ frontend, all passing.
- **The product caveats itself honestly** — "uncalibrated", confidence %, data-completeness are surfaced in-product and in the PDF. This is rarer than it should be in this sector and is a genuine differentiator with a scientific audience.

**Engineering is not the bottleneck.** Every CRITICAL item is legal, commercial, or infrastructural.

---

## Phase 2 — Customer-Readiness Checklists

*(Checklists only — documents deliberately not created yet.)*

### Meeting 1 — WELL Labs

**Assumption I am challenging before anything else:** this meeting should NOT be framed as a sales pitch. It should be framed as (a) showing them what their feedback produced, and (b) getting IP clarity collaboratively. Pitching a commercial pilot *before* resolving C1 puts you in a weaker position if they later assert a claim.

- [ ] **C1 resolved, or explicitly on the agenda** — know your own internship terms before the meeting
- [ ] Production live and reachable
- [ ] Demo account with clean, real Raichur data (no test artifacts)
- [ ] `resolution_flags` wired (H2) — you are presenting to hydrologists
- [ ] Known-limitations sheet, stated unprompted (uncalibrated, ±500 m boundaries, village≠watershed, no groundwater measurement)
- [ ] The one-sentence answer to "how is this different from Jaltol?" — already drafted in `WELL_Labs_Demo_Guide.md`
- [ ] A specific, concrete ask (pilot? data-sharing for calibration? advisory?) — do not leave without one
- [ ] Written follow-up within 24h capturing what they actually said

### Meeting 2 — Latur DCC Bank

- [ ] Production live
- [ ] **Service 1 demo path rehearsed** (this is a Service 1 conversation, not Service 2 — do not demo water intelligence to a lender)
- [ ] Sample farmer report PDF using realistic (non-identifying) data
- [ ] GEE commercial licensing path understood and costed (H4) — they will ask "what does this cost at scale"
- [ ] A clear statement of what TerraRisk does NOT do: it is decision support, not automated loan approval
- [ ] Data-protection posture: where does farmer data live, who can see it
- [ ] Pricing hypothesis (per-report? per-branch? annual?) — a hypothesis to test, not a fixed price
- [ ] Understanding of who actually signs: DCCB decisions typically involve a board/CEO, not a single officer

### Meeting 3 — FSID

**I need to flag an information gap honestly:** I believe FSID here is IISc's Foundation for Science Innovation and Development, given your IISc M.Tech background — but I am not certain, and its specific requirements, deadlines, and funding structure are outside what I can reliably assert. **Please confirm what FSID is and share its actual application requirements** — the checklist below is therefore generic-accelerator shaped and should be corrected once you tell me.

- [ ] Incorporation status decided (H5) — many programs require or strongly prefer a registered entity
- [ ] C1 resolved — an unresolved IP question is disqualifying for most funders
- [ ] Executive summary (1 page)
- [ ] Pitch deck (10–12 slides)
- [ ] Technical architecture diagram
- [ ] Evidence of customer validation — even one documented conversation beats zero
- [ ] Clear articulation of the moat, given H1 (public code)
- [ ] Financial ask with use-of-funds
- [ ] Founder background / why-you narrative (IISc water resources M.Tech is genuinely strong here)

---

## Phase 3 — Company Document Index

Priority: **P0** = before next customer meeting · **P1** = before funding application · **P2** = before/at incorporation · **P3** = later.
Owner: **F** = founder (you) · **CTO** = me · **EXT** = external (lawyer/CA/advisor).

### Engineering
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| Technical Architecture Diagram | Explain the system in one page to non-engineers | P1 | CTO | Before FSID |
| API Documentation | Integration readiness for bank IT teams | P2 | CTO | Before bank pilot |
| Engineering Blueprint *(exists)* | Internal design record | — | CTO | Maintained |
| DECISIONS.md *(exists)* | Architecture decision log — genuinely strong diligence artifact | — | CTO | Maintained |

### Scientific
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| Methodology White Paper | Defend the science to hydrologists/funders | P1 | F + CTO | Before FSID |
| Validation Report | Field calibration evidence | P1 | F | After first data partnership |
| Known Limitations Register | Honest constraint list, stated unprompted | **P0** | CTO | Before WELL Labs |
| Alignment Report *(exists)* | Positioning vs WELL Labs methodology | — | CTO | Maintained |

### Business
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| Executive Summary (1p) | Opening artifact for every conversation | P1 | F | Before FSID |
| Pitch Deck | Funding narrative | P1 | F | Before FSID |
| Business Model & Pricing | How money is made | P1 | F | After customer discovery |
| Go-To-Market Plan | Route to first 10 customers | P1 | F | After customer discovery |
| Competitor Analysis | Market awareness (SatSure, Cropin, Jaltol, ICEYE) | P1 | F + CTO | Before FSID |
| Customer Discovery Log | **Evidence** that beliefs are validated | **P0** | F | Starting now |

### Legal
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| IP Ownership Clarification | Resolve C1 | **P0** | F + EXT | Immediately |
| Incorporation Documents | Legal entity | P2 | EXT | When pilot/funding requires |
| Founder Agreement | If a co-founder joins | P2 | EXT | At incorporation |
| Pilot Agreement Template | Contract for first pilot | P2 | EXT | After pilot interest confirmed |
| Data Processing Agreement | Bank/government data handling | P2 | EXT | Before handling customer data |

### Operations
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| Deployment Guide *(exists)* | Reproducible deployment | — | CTO | Maintained |
| Disaster Recovery Runbook | **Tested** restore procedure | P2 | CTO | Before customer data |
| Incident Response Plan | What happens when it breaks | P2 | CTO | Before paid pilot |
| Onboarding Runbook | Adding a new customer org | P2 | CTO | Before pilot #2 |

### Investor
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| Due Diligence Folder | Single organized location | P1 | F | Before FSID |
| Financial Plan | Runway, costs, projections | P1 | F | Before FSID |
| Cap Table | Ownership record | P2 | F | At incorporation |

### Customer Success
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| Demo Guide *(exists)* | Repeatable demo script | — | CTO | Maintained |
| FAQ / Objection Handling | Consistent answers | P1 | F + CTO | Before bank meeting |
| Pilot Success Criteria | What "working" means, agreed upfront | P2 | F | At pilot start |

### Product
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| Product Roadmap | Sequenced, customer-driven | P1 | F + CTO | After discovery |
| Feature Request Log | Where customer asks go | **P0** | CTO | Starting now |

### Deployment / Risk
| Doc | Purpose | Priority | Owner | When |
|---|---|---|---|---|
| Dataset & License Register | Every dataset, its license, commercial status | P1 | CTO | Before FSID |
| Risk Register *(exists)* | Ranked company risks | — | CTO | Reviewed per mission |
| Security Overview | Auth, data handling, access control | P2 | CTO | Before bank pilot |

---

## Phase 4 — Operating Cadence

**Daily** — only if actively in a build or pilot sprint. Check production health. Log any customer contact the same day it happens.

**Weekly (~60 min)**
- Customer pipeline: who was contacted, who replied, what did they actually say
- Feature Request Log review: did any real customer ask for anything?
- Production health + deployment status
- One-line answer to: "did this week increase pilot/funding/customer probability?"

**Monthly (~2 hrs)**
- Risk Register review — update, don't rewrite
- Scientific validation status: what's still uncalibrated, what evidence arrived
- Document Index gaps: what's P0/P1 and still missing
- Runway/cost review (GEE spend, hosting)
- Roadmap: reprioritized *only* by customer evidence gathered this month

**Quarterly (~half day)**
- Full startup readiness re-audit (this document)
- Funding readiness: what changed, what's still missing
- Pilot status: real progress or stalled
- Strategic decisions: incorporate? hire? public-repo policy? licensing?

---

## Phase 5 — Next 30 Days

Deliberately light. Four weeks, one theme each. Everything here maps to pilot / funding / incorporation.

### Week 1 — Unblock
| Task | Why | Objective served |
|---|---|---|
| Check internship contract for IP terms (C1) | Highest-severity unknown; costs an hour | Incorporation, pilot, funding |
| Diagnose + restore production (C2) | Cannot demo without it | Pilot |
| Decide public-vs-private repo (H1) | Must be a decision, not a default | Funding |

### Week 2 — Credibility
| Task | Why | Objective served |
|---|---|---|
| Wire `resolution_flags` (H2) | Honest uncertainty before a hydrologist sees it | Pilot |
| Clean demo data; rehearse both demo paths | Avoid an avoidable failure | Pilot |
| Compile Dataset & License Register (M2) | Diligence-ready; also closes H4 questions | Funding |

### Week 3 — Talk to people
| Task | Why | Objective served |
|---|---|---|
| WELL Labs follow-up meeting | The only real customer signal you have | Pilot, partnership |
| Reach out to Latur DCC Bank | Service 1's actual target buyer | Customer |
| Start Customer Discovery Log | Evidence, not memory | Funding |

### Week 4 — Consolidate
| Task | Why | Objective served |
|---|---|---|
| Write up both conversations honestly | Input to everything in Phase 4 | Funding |
| Decide incorporation timing based on what you learned | Evidence-driven, not calendar-driven | Incorporation |
| Draft Executive Summary using real quotes | First investor artifact grounded in evidence | FSID |

**Explicitly NOT in the next 30 days:** new features, UI work, raster/tile serving, canal/LULC layers, pitch-deck design polish, any further map iteration.

---

## Appendix — VC Perspective

See chat response of the same date. Three hesitations: (1) no customer evidence, (2) IP ambiguity compounded by a public codebase, (3) unvalidated core science + single founder.
