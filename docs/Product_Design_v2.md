# TerraRisk Product Design v2 — From Working Engine to Commercial SaaS

*Status: **APPROVED** by founder, 12 Jul 2026, with amendments (three
additional product principles §1.1; Methodology page removed from top-level
IA in favor of contextual entry points). Implementation proceeds P7 → P11.*
*Scope: product and UX redesign only. The M1 backend architecture, satellite
pipeline, Risk Engine, and PDF renderer are approved foundations and are not
redesigned here. Backend changes proposed in §8 are strictly additive.*
*Prepared: 12 Jul 2026, on top of M2A P0–P6 (commit 6e37c2d).*

---

## 1 · Product philosophy

**TerraRisk is evidence infrastructure for agricultural credit decisions.**

The buyer (a bank, NBFC, insurer, or government department) is not buying
screens. They are buying three things:

1. **A defensible number.** A risk score that an officer can act on, a manager
   can supervise, and an auditor can reconstruct three years later.
2. **Evidence they could not otherwise obtain.** Banks cannot see cultivation
   history; satellites can. The product's job is to make that evidence legible
   to a non-GIS professional.
3. **A workflow that fits their institution.** Files, approvals, branch
   hierarchies, audit trails — not a data-science notebook.

From these, five design principles that govern every screen:

- **P1 — The workspace is the product; the wizard is a feature.** Today the
  app *is* the one-shot assessment funnel. In v2 the officer lives in a
  workspace of farms, assessments, and reports; creating a new assessment is
  one action among several. Nothing is disposable; everything is resumable.
- **P2 — Show the machine working, never a spinner.** Real computation is a
  selling point. Progress UI renders only actual pipeline state, with real
  timestamps, real parameters (which collections, which window, which farm),
  and honest cache behavior. No fake progress bars, no artificial delays, no
  invented stages.
- **P3 — Every number carries its provenance.** Score → factors → raw inputs
  → observations → scene dates → data sources. The chain must be walkable in
  the UI, not asserted in a footer. Confidence is shown as arithmetic
  ("35 of 36 months usable"), not as a mystery percentage.
- **P4 — State what the product does not know.** Assumptions, limitations,
  unobservable months, imagery gaps. Institutional users trust products that
  volunteer their limits; they distrust products that only ever say "done."
- **P5 — One visual language.** The dashboard, the report page, and the PDF
  are three views of one artifact (Blueprint §08). Risk-band colors, factor
  ordering, and prose are identical everywhere; nothing may drift.

**Anti-goals** (explicitly not this product): a consumer app for farmers; a
GIS analysis tool for specialists; a lending decision engine (the disclaimer
is a design principle — the credit decision remains with the bank).

### 1.1 Founder-added principles (approved 12 Jul 2026)

- **P6 — Decision Transparency.** Every important number must answer
  "where did this number come from?" with evidence visible in the UI, not
  available-on-request. This elevates P3 from a design preference to a
  product requirement: any score, area, confidence, or factor value that
  cannot show its provenance is a defect.
- **P7 — Decision Support.** TerraRisk is a Decision Support System, not a
  reporting tool. Every completed report carries a concise
  **recommendation** for the Credit Officer. Recommendations are
  deterministic fixed templates keyed ONLY on backend outputs (overall
  band, with a confidence qualifier when confidence is low) — the same
  pinned-template discipline as the narrative (`report_text` twin tests).
  Recommended postures by band: low → standard appraisal, no
  climate-driven escalation; moderate → standard appraisal, note the
  leading factor in the loan file; high → escalate to branch-manager
  review, consider risk-adjusted terms; very high → refer to branch
  manager, independent field verification before sanction. Below a
  confidence threshold, the recommendation carries an "indicative only"
  qualifier. Never advice beyond the evidence; the sanction decision
  remains the bank's. (Implements Blueprint §08 "Recommendation" row;
  ships in P9 with the report redesign, mirrored into the PDF.)
- **P8 — Portfolio Intelligence (reserved).** The architecture must let
  branch managers eventually understand portfolio exposure, district
  trends, and assessment history without rework: branch-scoped list
  endpoints and assessment history (P7) are designed as the portfolio
  layer's data spine; the `risk_rollup` table exists in the schema since
  M0; the IA reserves the Portfolio slot. **No portfolio features are
  implemented until M4.**

---

## 2 · Enterprise workflow

### Personas (in adoption order)

| Persona | Institution role | Uses TerraRisk to… | Cadence |
|---|---|---|---|
| **Credit Officer** | Branch, field-facing | Map a farm during/after a site visit, run the assessment, attach the PDF to the loan file | Daily, 2–10 farms |
| **Branch Manager** | Branch supervisor | Review officers' assessments, re-open reports in committee, sanity-check scores before sanction | Weekly |
| **Risk / Portfolio Manager** | HQ | Portfolio exposure by band/geography (Service 2, M4 — designed for, not built now) | Weekly/monthly |
| **Auditor / Regulator** | External or internal | Reconstruct: who assessed what, when, from which data, under which model version | Rare but decisive for procurement |
| **IT Administrator** | Bank IT | Users, branches, access control, logs (M5 — designed for, not built now) | Setup + exceptions |

### The core loop (Credit Officer)

```
   ┌────────────────────────────────────────────────────────────┐
   │  WORKSPACE  (home)                                         │
   │  resume running assessments · open recent reports ·        │
   │  find any farm · start new assessment                      │
   └──────┬─────────────────────────────────────▲───────────────┘
          │ "New assessment"                    │ report ready
          ▼                                     │ (notification)
   NEW ASSESSMENT (wizard)               ASSESSMENT RUN (live)
   village → map → draw →        ──►     staged pipeline view,
   validate → area verify →              real telemetry, leave-
   submit                                and-return safe
                                                │
                                                ▼
                                         CLIMATE REPORT
                                         score · evidence ·
                                         methodology · PDF
```

Key workflow properties that today's app lacks and v2 guarantees:

- **Interruptible.** Every step survives a tab close, a session refresh, a
  network drop. The run continues server-side (already true); the UI must
  make returning trivial (not true today — the URL is the only way back).
- **Concurrent.** An officer can have three assessments running while mapping
  a fourth farm. The workspace shows all in-flight work.
- **Reviewable.** A Branch Manager opens the same farm and sees the same
  history — owner-or-branch authorization already exists in the API
  (`user_can_access_owned_resource`); v2 finally gives it a surface.
- **Auditable.** Every report permanently shows: model version, weights
  version, observation window, computed-at, officer of record. (All already
  persisted; mostly unexposed.)

---

## 3 · Complete information architecture

```
TerraRisk
│
├── Overview                    ← post-login home (workspace)
│     activity feed · in-flight runs · recent reports · KPIs
│
├── Assessments                 ← every run, filterable
│     status: queued/running/failed/complete · resume · retry
│
├── Farms                       ← the registry (system of record surface)
│     list → Farm detail
│                ├── identity, boundary map, authoritative area
│                ├── assessment history (score timeline)
│                └── actions: run new assessment, open latest report
│
├── Reports                     ← issued-artifact index (auditor entry point)
│     search by village/officer/date/band → Report
│                ├── tab: Report      (the climate dashboard)
│                ├── tab: Evidence    (observations, coverage, scene dates)
│                └── tab: Method      (score anatomy, weights, bands,
│                                      assumptions & limitations)
│
├── + New Assessment            ← primary action (persistent button, not a nav item)
│
└── [Account]                   ← profile, session, sign out
      [Admin]                   ← M5: users, branches, audit log (designed-for)
      [Portfolio]               ← M4: Service 2 dashboards (designed-for)
```

Methodology is deliberately NOT a top-level destination (founder decision,
12 Jul 2026): methodology surfaces **contextually** — the report's Method
tab, and "How was this score calculated?" / "View methodology" links beside
any score, band, or confidence figure. Rationale: an officer meets the
methodology at the moment of doubt, next to the number that raised it, not
as a standalone document to go find.

Phasing note: **Overview, Assessments, Farms, Reports** and the
tabs on Report are v2 scope. Admin and Portfolio are placeholders in the IA
so navigation doesn't need re-architecting at M4/M5 — they do not appear in
the UI until built (no "coming soon" screens; empty nav slots are a demo
smell of their own).

Collapsing rule for MVP volume: if Assessments and Reports prove redundant at
DCCB scale (one branch, few officers), Reports may fold into Farms + Overview.
The IA keeps them separate because the *auditor* persona enters through
"show me all issued reports," not through farms.

---

## 4 · Navigation redesign

**Pattern: left rail + context header.** (The pattern Esri, GEE, Stripe, and
Palantir Foundry converge on for data-dense work surfaces.)

- **Left rail** (collapsible to icons): Overview, Assessments, Farms,
  Reports. Bottom: user chip (name, role, branch) → menu with
  Sign out. The persistent **"+ New assessment"** button sits at the top of
  the rail, visually distinct — it is the primary verb of the product.
- **Context header** (per page): breadcrumb (Farms / Killari · 7381b551),
  page-level actions (Download PDF, Re-assess), and a global **activity
  indicator** — a small live chip showing "2 assessments running" that opens
  the in-flight list from anywhere. This is the heartbeat that tells a user
  the engine is alive without navigating.
- **No top-level tabs for workflow steps.** The wizard is a contained flow
  with its own stepper; global nav stays stable during it (officers must be
  able to abandon/resume without feeling trapped).
- **Mobile/field**: the rail collapses to a bottom bar (Overview / Farms /
  New). Drawing on mobile is already supported by the map stack; the v2
  layout must not regress it. Full field-mode UX is Future.

Current state being replaced: a header with brand text and a Log out button
([layout.tsx](../frontend/src/app/(app)/layout.tsx)); root redirect straight
into `/farms/new`; no way to reach any prior work.

---

## 5 · Screen inventory

Every screen answers: *why does it exist / what business problem / would the
persona actually work like this?*

| # | Screen | Route | Exists because… | Primary persona |
|---|---|---|---|---|
| 1 | Login | `/login` | Institutional access control; first impression of credibility | All |
| 2 | Overview (workspace) | `/` | Officers resume work; managers see branch activity. Kills the one-shot funnel | Officer, Manager |
| 3 | New Assessment wizard | `/assessments/new` | The core verb: map → validate → submit. Server-authoritative at every step | Officer |
| 4 | Assessment Run | `/assessments/{jobId}` | The "watch the engine work" surface; resumable, shareable within branch | Officer |
| 5 | Assessments index | `/assessments` | Operational queue: what's running, what failed, what needs retry | Officer, Manager |
| 6 | Farm detail | `/farms/{id}` | The registry record: boundary, area, assessment history, re-assess | Officer, Manager |
| 7 | Farms index | `/farms` | Find any mapped farm; the bank's growing asset register | Officer, Manager |
| 8 | Climate Report | `/reports/{id}` | The decision-support artifact; three tabs (Report / Evidence / Method) | Officer, Manager, Auditor |
| 9 | Reports index | `/reports` | Auditor/manager entry: every issued artifact, searchable | Manager, Auditor |
| 10 | System states | — | Empty, loading, error, expired-session, offline — designed, not defaulted | All |

(No standalone Methodology screen — founder decision: methodology is
contextual, reached from within reports via the Method tab and "How was
this score calculated?" links.)

Screens deliberately **not** in the inventory: a marketing landing page
(out of product scope), a farmer-facing view (anti-goal), portfolio
dashboards (M4, designed-for in IA only).

---

## 6 · User journeys

### Journey A — Credit Officer, loan application day

> 09:10 — Signs in. **Overview** shows: 1 assessment still running from
> yesterday evening (CHIRPS was lagging), 3 reports issued this week, and the
> farm list for her branch. The running chip in the header pulses.
> 09:12 — Farmer Patil arrives with a loan application for a plot near
> Killari. She clicks **+ New assessment**. Village search → Killari (fly-to).
> She draws the boundary from the farmer's description and the plot's visible
> bunds on satellite imagery. The live area readout shows 2.1 ha as she draws;
> geometry validation flags a self-intersection when she overshoots a vertex —
> she drags it back, the flag clears.
> 09:16 — **Area verification**: her drawn preview says 2.14 ha; she submits;
> the confirmation shows the **server's** authoritative PostGIS area, 2.11 ha,
> labeled as such ("computed on the server from the submitted boundary").
> She confirms — this is the number that will appear on the report.
> 09:17 — **Assessment Run** page opens. She watches: *Queued → Fetching
> Sentinel-2 vegetation series (36 monthly composites, Jul 2023–Jun 2026) →
> moisture indices → rainfall series (CHIRPS) → 30-year rainfall normal →
> surface-water history (JRC) → computing climate factors → scoring →
> persisting.* Each completed stage shows its real elapsed time. She doesn't
> wait — she goes back to Overview and starts the paperwork; the header chip
> tracks the run.
> 09:21 — The chip turns green. She opens the **Report**: Moderate risk,
> 42/100, confidence 97% ("35 of 36 months usable"). The drought factor is
> High — she expands it and sees the VCI trace that drove it. She downloads
> the PDF and attaches it to the loan file.

### Journey B — Branch Manager, Thursday credit committee

> Opens **Reports**, filters to this week, sorts by band. Two High-risk
> reports. Opens the first, reads the narrative, then the **Evidence** tab:
> the NDVI series shows two failed kharif seasons — the score isn't an
> opinion, it's a history. In committee, he projects the report page; when
> the committee chair asks "how do we know this is reliable?", he switches
> to the **Method** tab: model version, weights, band thresholds, the
> confidence arithmetic, and the limitations statement. The committee
> proceeds with a smaller sanctioned amount — the product did its job:
> decision support, not decision-making.

### Journey C — Failure path (designed, not hoped away)

> An assessment fails at the rainfall stage (Earth Engine quota). The Run
> page shows exactly which stage failed, keeps the completed stages visible
> ("vegetation series: fetched and cached — will not be re-fetched"), and
> offers **Retry**. The retry reuses cached observations (visibly faster,
> honestly labeled "restored from cache"). If retry fails again, the page
> says what the officer can do (try later; contact support ref: job id) —
> never a dead end back to "draw a farm."

---

## 7 · Wireframe descriptions

Text wireframes; visual design language: calm, ink-on-paper density closer to
Stripe than to Bloomberg, MapLibre satellite surfaces treated as content (not
chrome), the existing band palette as the only status color system.

### 7.1 Overview (workspace home)

```
┌ rail ┬──────────────────────────────────────────────────────────┐
│ +New │  Good morning, Priya                    ● 2 running ▾    │
│ Over │                                                          │
│ Asmt │  ┌ In progress ─────────────────────────────────────┐    │
│ Farm │  │ ▸ Killari · 2.11 ha   fetching rainfall   3m12s  │    │
│ Rept │  │ ▸ Ausa · 1.4 ha       queued                     │    │
│ Meth │  └──────────────────────────────────────────────────┘    │
│      │  ┌ Recent reports ──────────────┐ ┌ This branch ────┐    │
│      │  │ Killari  Moderate 42  12 Jul │ │ 14 farms mapped │    │
│  ──  │  │ Nagarsoga  High 61   11 Jul  │ │ 11 reports      │    │
│ user │  │ …open all reports…           │ │ 2 high-risk     │    │
└──────┴──┴──────────────────────────────┴─┴─────────────────┴────┘
```

- "In progress" rows link to Assessment Run pages; they update live (same
  polling machinery as the run page, shared cache).
- KPI card is branch-scoped truth from list endpoints, not marketing numbers.
- Empty state (new branch, zero farms): one sentence of orientation + the
  New assessment action + a "how assessment works" link to Methodology. No
  illustration-of-emptiness filler.

### 7.2 New Assessment wizard

One page, two persistent regions: map (dominant) + step panel (side). Steps
are a visible stepper: **Village → Boundary → Verify → Submit.**

- *Village*: search with debounced results (exists today); selecting flies
  the map. The panel explains why village first: it anchors the
  administrative record (village → taluka → district on the report).
- *Boundary*: draw + vertex edit (exists). Live area readout labeled
  "preview — final area is computed on the server." Geometry problems
  (self-intersection, too few points, out-of-bounds area) surface inline on
  the panel *and* as map annotations, when they occur — real validation
  feedback, not a submit-time surprise.
- *Verify*: side-by-side: drawn preview area vs (after submit) server
  authoritative area, both labeled. The officer's confirmation is of the
  **server's** number. This step is where "the backend is authoritative"
  becomes visible product language.
- *Submit*: creates farm + triggers assessment in one action (today: two
  separate UI moments), then routes to the Run page. If a run is already in
  flight for this farm (409), the UI says so and routes to *that* run.

### 7.3 Assessment Run (the flagship trust screen)

```
┌──────────────────────────────────────────────────────────────┐
│ Killari · 2.11 ha · assessment started 09:17:04 IST          │
│                                                              │
│  ✓ Queued                                    0:02            │
│  ✓ Vegetation series (Sentinel-2, 36 months) 1:41  [cached ×0]│
│  ✓ Moisture indices (MNDWI, NDMI)            0:58            │
│  ● Rainfall series (CHIRPS daily → monthly)  0:22 …          │
│  ○ 30-year rainfall normal                                   │
│  ○ Surface-water history (JRC 1984–2021)                     │
│  ○ Climate factors                                           │
│  ○ Risk score                                                │
│  ○ Report ready                                              │
│                                                              │
│  This analysis queries the satellite record for THIS         │
│  boundary. Monthly composites already on file are reused     │
│  and labeled as cached. You can leave — it continues on      │
│  the server.                                    [Overview]   │
└──────────────────────────────────────────────────────────────┘
```

- Stages map **one-to-one to the real checkpoints in
  `report_generator.py`** — nothing invented. Per-stage elapsed times come
  from server-recorded stage timestamps, not client timers.
- Cache reuse is shown, not hidden ("restored from prior observations") —
  a re-assessment that flies through fetching stages must look *correct*,
  not suspicious.
- Failure: the failed stage is marked, completed work is preserved and said
  to be preserved, Retry is present, support reference (job id) shown.
- If the run finishes in seconds (all cached), the timeline renders
  completed with real timestamps and transitions to the report — natural,
  no minimum-duration theater.

### 7.4 Farm detail

Header: village · taluka · district, authoritative area, officer of record,
mapped date. Left: read-only boundary map. Right: **assessment history** —
a vertical timeline of runs (date, score, band, confidence, model version),
each linking to its report; the current in-flight run appears at top if any.
Actions: New assessment (subject to the re-assessment policy), open latest
report. Empty history state: "No assessments yet for this farm — run the
first one."

### 7.5 Climate Report — three tabs

**Tab: Report** — the current P5 dashboard, kept: verdict + narrative + map,
factor cards, NDVI/rainfall charts, lineage footer. Additions: factor cards
expand inline to their underlying series (MNDWI/NDMI are already in the
payload, unrendered); band chip anywhere → hover/tap explains the threshold
("Moderate = 40–59"); a **Recommendation** block under the verdict —
deterministic fixed template keyed on band + confidence qualifier (product
principle P7, pinned by twin tests like all report prose, mirrored in the
PDF); and a persistent "How was this score calculated?" link that opens the
Method tab (product principle P6 — methodology is contextual).

**Tab: Evidence** — answers *which observations contributed*:
- Observation window (start → end) and why it ends where it does (previous
  full calendar month).
- Per-index coverage strip: 36 cells (one per month), filled/empty by
  usability, with counts ("NDVI: 35 of 36 months usable").
- Scene-date coverage: per month, the real Sentinel-2 acquisition dates that
  fed the composite (`satellite_observation.source_dates` — persisted since
  M1, never yet shown to anyone).
- All four series charted, including MNDWI/NDMI.
- Confidence, derived visibly: usable months ÷ expected months.

**Tab: Method** — answers *why this score*:
- Score anatomy: factor score × weight → contribution → composite, as a
  horizontal contribution bar. Weights shown with their version id and
  effective date (persisted, unexposed today).
- Band thresholds table.
- Factor definitions in officer language (one paragraph each — source
  content from the risk methodology, reviewed by the founder as domain
  authority).
- **Assumptions & limitations** (fixed, honest, versioned text): monthly
  compositing hides sub-monthly events; cloud gaps reduce confidence; CHIRPS
  publishes with a lag; boundary accuracy is the officer's responsibility;
  the score is decision support, not a lending decision.

PDF parity: the PDF gains an "Evidence & Method" appendix rendering the same
content (bump `PDF_LAYOUT_VERSION`).

### 7.6 System states (designed globally, used everywhere)

- **Loading**: skeletons that match final layout (list rows, report panels).
  Never a full-screen spinner; never `return null` (today's auth guard blanks
  the page on refresh).
- **Empty**: one orientation sentence + one action. Written per screen.
- **Errors**: four families with distinct treatments — network (retryable,
  auto-retry with backoff indicator), authorization/expiry (session modal:
  re-authenticate in place, return to exactly where you were), not-found
  (honest 404 with navigation), server failure (reference id + support
  path). Today all failures collapse into one generic card.
- **Session**: expiry warning before the 12h JWT dies; re-login preserves
  location and unsaved wizard state (village + drawn ring held client-side).
- **Notifications**: v2 keeps it minimal and honest — the header activity
  chip + browser-tab title updates ("✓ Report ready — Killari") when a
  watched run completes. No notification center until there are enough event
  types to justify one (Future, with audit trail).

---

## 8 · Backend additions required (all additive; no redesign)

| # | Addition | What exactly | Class |
|---|---|---|---|
| B1 | List endpoints | `GET /farms` (owner-or-branch scope, joined village names + latest assessment summary), `GET /assessments` (jobs w/ farm context, filterable by status), `GET /reports` (issued reports index) | **Critical** |
| B2 | Job progress stages | Nullable `progress` JSONB on `job` (stage key + per-stage timestamps), written at the existing checkpoints in `report_generator.py`; exposed in `JobStatusResponse`. One Alembic migration | **Critical** |
| B3 | Report payload lineage | Extend `ReportResponse`: observation window, per-index usable/expected month counts, per-month `source_dates`, weights (values + version + effective date), band thresholds | **Critical** |
| B4 | Farm → runs linkage | `GET /farms/{id}/assessments` (history timeline). Note: completed jobs overwrite `entity_id` with the risk-score id (P4 decision), so history derives from `risk_score.entity_id = farm_id` — already queryable, needs an endpoint | **High** |
| B5 | 409 payload | The in-flight-conflict response includes the existing job id so the UI can route to it | **High** |
| B6 | Session refresh | Token refresh endpoint (or sliding expiry) to support the session-expiry UX | **High** |
| B7 | Cache provenance flag | Observation responses/stage events mark cached-vs-fetched so the Run page can label reuse honestly | Medium |
| B8 | Audit events | `viewed_report` / `downloaded_pdf` event log for the auditor story | Future (M5) |
| B9 | Notifications store | Only if/when a notification center is justified | Future |

Explicitly rejected: WebSockets/SSE for progress (polling with backoff is
correct at MVP volume and survives hostile bank networks/proxies better);
a queue system (Blueprint's CTO note stands — BackgroundTasks holds at pilot
volume; re-evaluate at multi-branch load, see §11).

---

## 9 · Frontend redesign roadmap

| Phase | Name | Delivers | Depends on |
|---|---|---|---|
| **P7** | Workspace foundation | App shell (rail + header + activity chip), Overview, Farms index + Farm detail, Assessments index, routing/auth-guard fixes, deep-link preservation | B1, B4, B5 |
| **P8** | Honest progress | Assessment Run page (stage timeline, real timestamps, cache labeling, failure + retry), wizard submit → run handoff, 409 routing | B2, B7 |
| **P9** | Evidence & Method | Report tabs (Evidence, Method), **deterministic recommendation block**, factor drill-downs, score anatomy, coverage strips, scene dates, assumptions & limitations; PDF appendix | B3 |
| **P10** | Wizard & session hardening | Unified wizard (stepper, inline geometry validation, verify step), session expiry UX, error taxonomy, skeletons/empty states, per-route metadata | B6 |
| **P11** | Final UX polish | Contextual "How was this score calculated?" links everywhere a score appears, band legend/hovers, notification chip refinements, print styles, dark-mode QA | — |

Each phase keeps the P0–P6 discipline: spec → implement → full test suite →
live verification against real Earth Engine → DECISIONS.md entry → commit.
The current funnel remains fully functional until P7 replaces its shell —
no big-bang rewrite; screens are replaced route by route.

---

## 10 · Prioritized implementation plan (every improvement, classified)

**Critical** (blocks the "production SaaS" claim):
1. Workspace home + farm/assessment/report lists (P7)
2. App shell with real navigation + activity indicator (P7)
3. Staged, truthful progress with server timestamps (P8)
4. Failure paths: retry, 409 → existing run, preserved work messaging (P8)
5. Evidence tab: coverage arithmetic, scene dates, window (P9)
6. Method tab: score anatomy, weights version, thresholds, limitations (P9)
7. Auth-guard/deep-link/session-expiry correctness (P7/P10)

**High Value**:
8. Farm detail with assessment history timeline (P7)
9. Unified wizard with verify step + inline geometry validation (P10)
10. Factor drill-down charts (MNDWI/NDMI finally rendered) (P9)
11. Error-state taxonomy + skeletons + empty states (P10)
12. PDF Evidence/Method appendix (P9)
13. Cache-reuse labeling in progress + report ("observations reused from
    {date} run") (P8/P9)

**High Value** (added by founder approval):
13b. Deterministic recommendation block on every completed report,
     band+confidence keyed, PDF-mirrored (P9)

**Medium**:
14. Contextual methodology links ("How was this score calculated?")
    everywhere a score appears (P11; Method tab itself is P9)
15. Band-threshold legend/hovers everywhere (P11)
16. Tab-title notifications on run completion (P8)
17. Per-route metadata, favicon, print styles (P10/P11)
18. Report search/filters on the Reports index (P7 basic, richer later)

**Future** (designed-for, not built):
19. Notification center + audit trail surface (M5)
20. Portfolio dashboards, choropleths, drill-down path (M4 — IA slot exists)
21. Admin: users, branches, roles UI (M5)
22. Field mode: offline-tolerant mobile drawing (post-pilot)
23. Marathi localization (needs founder decision on pilot requirement)
24. SSO (SAML/OIDC) for bank IT (procurement-driven)

---

## 11 · "If TerraRisk launched commercially today, what would prevent a bank from adopting it?"

Brutally, in descending order of deal-breaking:

1. **No institutional account model.** One seeded user, no user management,
   no password reset, no MFA, no SSO, no role administration. A bank cannot
   even onboard its second officer without a database insert. This is the
   first question in any bank IT procurement and today the answer is "we
   can't."
2. **No audit trail.** Banks live under RBI/NABARD inspection culture. "Who
   generated, viewed, downloaded which report, when" must be answerable.
   The data model records creation provenance well, but access events are
   not logged and nothing is surfaced.
3. **Scientific validation is asserted, not demonstrated.** The methodology
   is sound and now explainable, but no back-testing against historical NPA
   outcomes exists. A risk committee will ask: "show me that Very High
   correlates with defaults in Marathwada." Until a pilot produces that
   evidence, TerraRisk sells as *decision support with a transparent
   methodology* — the Method tab and Methodology page are the honest bridge,
   but a validation study is the real answer (this is the pilot's core job).
4. **Operational durability.** Report jobs run as in-process background
   tasks: a server restart mid-run leaves a job RUNNING forever from the
   bank's point of view (the code guarantees terminal status only if the
   process lives). No monitoring, no alerting, no SLA story, no backup/DR
   posture. Acceptable for a pilot on our infrastructure; not for a bank
   production deployment. (First genuinely architectural item on the
   horizon: durable job execution — but per the approved constraints, this
   is flagged, not redesigned here.)
5. **Licensing exposure.** Two known items already flagged in code comments:
   Esri World Imagery requires a licensing review for commercial use
   (frontend `config.ts` says so explicitly), and **Google Earth Engine
   commercial use requires a paid commercial license** — the pilot runs on
   what must be verified as an eligible tier before any commercial contract
   is signed. This is a legal/commercial workstream, not a code change, and
   it gates revenue.
6. **Security posture unproven.** JWT in localStorage, 12h fixed expiry, no
   rate limiting, no pen test, no security review artifact to hand a bank's
   infosec team. The auth design is clean for an MVP; procurement needs
   evidence, not cleanliness.
7. **Data residency and sovereignty.** Farm polygons (arguably borrower
   PII once linked to loan files) are sent to Google Earth Engine for
   processing. Indian banks and government departments will ask where data
   is processed and stored. Needs a documented data-flow answer and possibly
   contractual cover — before a government tender, certainly.
8. **Geographic coverage is one district.** Village search is real Latur
   data. Onboarding a second district is a data-pipeline task, not a
   product feature — but a bank operating across Maharashtra will test
   exactly this on day one. The onboarding runbook should become a product
   asset.
9. **Single-institution architecture.** No tenant isolation. Fine while
   each deployment serves one bank; must be a conscious deployment-model
   decision (single-tenant-per-customer is a legitimate enterprise answer —
   say it deliberately, price it deliberately).
10. **No commercial packaging.** Pricing model (per report? per branch? per
    hectare assessed?), support tiers, onboarding/training materials,
    Marathi collateral for officer training — none exist. The product can
    demo value; it cannot yet be *bought*.

None of these are reasons to pause the v2 UX work — items 1–2 and 4–7 are
M5-era engineering and commercial workstreams, and the v2 redesign (§1–§10)
is precisely what makes the pilot persuasive enough to fund them. But a
commercial launch conversation before these are addressed would fail
technical due diligence at any serious bank.

---

*Approved 12 Jul 2026: workspace-first architecture, assessment history,
honest progress, evidence-first reporting, branch-scoped visibility, phase
order P7→P11, backend additions B1–B7. Founder amendments incorporated:
principles P6–P8 (§1.1), Methodology top-level page removed in favor of
contextual entry points, deterministic recommendation added to P9 scope.
Every phase must be independently deployable, fully tested, production
ready, security reviewed, live verified, and documented in DECISIONS.md.*

---

## Addendum — Evidence-aware assessments (September 2026)

The product is moving from "here is a score" to "here is whether the evidence is sufficient for the decision you are about to make". A score of 44 means something different for a ₹50,000 seasonal crop loan than for a ₹5,00,000 term loan, and model confidence is not decision sufficiency.

**Shipped so far (backend only):**

- **Physical validation on every water report** — findings stored with the result, not only logged.
- **Evidence lineage for every new report in both services** — for each input: source product and version, acquisition dates where available, resolution and resampling, known limitations, and validation status. Retrievable through the API.
- **Nothing is labelled validated.** Every input is marked `unvalidated` until it is cross-checked against an independent source or field data.

**Not yet in the product surface:** lineage and validation findings are not shown in the dashboard or PDF. They arrive with the report redesign below rather than being built twice.

**Planned, in order:** separate *model confidence* from *decision sufficiency*; replace the band-only recommendation (§7.5) with PROCEED / VERIFY / WAIT / ESCALATE / ABSTAIN computed from score, uncertainty and stakes, with loan amount and reversibility as explicit inputs; for each factor, show what additional evidence would change the answer and what it would cost.

§11 item 3 still stands: back-testing against loan outcomes is the real validation, and it still requires the pilot.
