# TerraRisk Water Intelligence — Engineering Blueprint (v2)
## A second production-grade TerraRisk service: technical design, scientific methodology, and implementation plan

**Date:** 26 July 2026 (v2 — supersedes v1, which received a Technical Design Review verdict of **APPROVED WITH MAJOR CHANGES**)
**Status:** Pre-implementation, revised — every blocking and must-fix item from `docs/Water_Intelligence_TDR.md` is resolved inline below. Sections unchanged from v1 are marked only where the distinction matters; everything else in this document already passed review and was left alone, per instruction.
**Panel:** MIT Hydrology/Earth Systems Professor, IISc Water Resources Professor, WELL Labs Founder (practitioner review), Principal Hydrologist, Principal Remote Sensing Scientist, Principal GIS Engineer, Principal Software Architect, Senior FastAPI Engineer, Senior PostgreSQL/PostGIS Engineer, Senior GEE Engineer, Senior Frontend Engineer, Principal Product Manager
**v2 changes are marked `[v2]` inline** so a reviewer who only wants the diff can search for that tag; a full Change Log is also at the end of this document.

---

## A naming conflict to resolve before anything else

The existing `docs/Engineering_Blueprint_v1.md` already defines **"Service 2 — Portfolio Climate Risk Dashboard"** — the bank-facing loan-portfolio aggregation view, explicitly marked "reserved architecture, NOT implemented until M4" in `docs/Product_Design_v2.md`. This document's brief calls the new Water Intelligence work "the second core service." Those are two different things claiming the same ordinal.

**This is not resolved silently in this document.** Recommendation: Water Intelligence becomes **Service 2 in the current build sequence** (it ships before Portfolio Dashboard), and Portfolio Dashboard is explicitly renumbered to Service 3 in the roadmap the next time that document is touched. The founder should make this call explicitly — it's a one-line edit, but it's a real product-sequencing decision, not a documentation formality.

Throughout the rest of this document, the new work is called **Water Intelligence**, never "Service 2," to avoid begging the question.

---

## Ground truth: what the panel actually verified before designing anything

### The existing Service 1 codebase (verified by direct inspection, not memory)

| Component | File(s) | What it actually does | Reusable as-is? |
|---|---|---|---|
| Provider contract | `app/services/satellite/provider.py` | `SatelliteDataProvider` ABC — domain-vocabulary methods only, no `ee.*` object ever crosses the boundary, returns plain dataclasses | **Extend, don't duplicate** |
| GEE implementation | `app/services/satellite/gee_provider.py` | Real monthly composites, s2cloudless masking at 20% probability, CHIRPS climatology, `asyncio.to_thread()` wrapping every blocking call | **Extend the module, share helpers** |
| Pure scoring engine | `app/services/risk/engine.py` | `RiskEngine.compute(bundle, config) -> RiskResult` — zero I/O, deterministic, percentile-rank + weighted-composite + floor-rule pattern | **Clone the shape, not the code** |
| Polygon model | `app/models/farm.py` | `FarmPolygon` — PostGIS `Geometry(POLYGON, srid=4326)`, server-side `ST_Area` recompute, never trusts client-provided area | **Pattern reused, new sibling table** |
| Observation cache | `app/models/satellite.py` | `SatelliteObservation` — polymorphic `(entity_type, entity_id, index_type, period)` cache keyed to avoid re-billing GEE | **Extend enums, reuse table** |
| Scoring history | `app/models/risk.py` | `RiskScore`/`RiskFactorScore` (append-only, versioned) + `RiskRollup` (precomputed aggregate) + `ConfigWeight` (versioned config, never edited in place) | **Pattern reused, new sibling tables** |
| Async jobs | `app/models/job.py` | `Job` — durable, DB-backed, JSONB `progress` field, shared by both existing job types via `JobType` enum | **Reused directly, extend enum** |
| Reporting pipeline | `app/services/reporting/*` | Nine focused modules: map snapshot, methodology text, PDF render, progress tracking, recommendation, findings, orchestrator, statistics, report text | **Extend, mirror the module split** |
| Frontend features | `frontend/src/features/{assessment,assessment-wizard,auth,farm-drawing,navigation-guard,report,workspace}` | Feature-folder convention, `farm-drawing` is the reusable polygon-draw UI | **Generalize `farm-drawing`, add new features** |
| Decision record | `docs/DECISIONS.md` | Every non-obvious architectural choice recorded with rationale, e.g. "FastAPI BackgroundTask, no message queue, at MVP volume" | **This document follows the same discipline** |

**The single most important engineering fact this inspection surfaced:** Service 1 already solved the two hardest architecture problems this new service also needs — a provider abstraction that keeps Earth Engine out of business logic, and a pure, deterministic, testable scoring engine. Water Intelligence does not need to re-invent either. It needs to **extend** both without touching what Service 1 already ships.

### The scientific literature (verified, not assumed)

| Claim | Verified finding | Source |
|---|---|---|
| Satellite ET accuracy | FAO WaPOR correlates 0.85–0.98 at validation sites, but accuracy is seasonal (good spring/summer, degraded autumn/winter) and WaPOR ET values run systematically lower than alternative products | **[S]** |
| Water-accounting-plus (WA+) framework | Already implemented and published for groundwater balance in a semi-arid Indian river basin — this is not a novel methodology being proposed here, it's an established one being productised | **[S]** |
| GRACE/GRACE-FO groundwater | Native resolution ~300 km; even the best ML-downscaled products (Random Forest, XGBoost) only reach ~10–27 km — **confirmed unusable for farm or village-scale decisions, full stop** | **[S]** |
| Sentinel-1 SAR small-waterbody detection | 89.6% accuracy for aquaculture-pond-scale water bodies; deep-learning approaches exceed 0.80 F1; but explicitly **degrades for waterbodies below Sentinel's 10 m resolution** — most Indian farm ponds are exactly in this failure zone | **[S]** |
| SCS Curve Number in Indian semi-arid conditions | Method has documented, named weaknesses (storm duration ignored, λ=0.2 assumption often wrong, originally calibrated for US Midwest) — **but** a Western Maharashtra validation study found standard SCS-CN tables did not vary significantly from event-based data for most basins tested | **[S]** |
| GEE watershed delineation | GEE has **no native flow-tracing/pour-point delineation primitive** comparable to a GIS "Watershed" tool. HydroSHEDS flow-direction and flow-accumulation rasters exist as GEE assets, but arbitrary pour-point delineation is an inherently sequential graph-traversal problem poorly suited to GEE's map-reduce model. The established open-source tools for this (WhiteboxTools, pysheds, TauDEM) run outside GEE | **[S]** |
| CGWB groundwater data | ~22,965 observation wells, quarterly since 1969, publicly accessible via India-WRIS/data.gov.in | **[S]** |

**What this means for the design, immediately:** any claim to precise groundwater level or volume is scientifically unsupportable at the scale this service operates at. Any claim to farm-pond-scale water extent must carry a visible resolution caveat. Watershed delineation cannot be a pure-GEE feature without a real geoprocessing dependency. These aren't obstacles to design around quietly — they are the backbone of the ✓/⚠ methodology table in Part 4.

---

# PART 1 — Technical Design Document

## What this service is

**TerraRisk Water Intelligence** computes and reports on water availability, surface-water status, and watershed condition for a user-defined catchment or farm-cluster polygon, using the same satellite-and-provenance architecture as Service 1, generalized from a single farm's risk score to a catchment's water balance and stress indicators.

## Where it sits relative to Service 1

- **Shares:** authentication, user/role model, polygon-drawing pattern, GEE provider infrastructure, job tracking, provenance/confidence philosophy, PDF/dashboard report pipeline shape.
- **Diverges:** the unit of analysis (catchment, not farm-loan), the output (water balance + stress indicators, not a 0–100 lending risk score), the customer (CSR/NGO/government water-programme staff, not bank credit officers).
- **Does not depend on:** any Service 1 table being populated. A user can run Water Intelligence with zero farms in the system.

## Who it's for (generic, not WELL-Labs-specific)

CSR implementation teams, NABARD water-resources consultants, watershed development NGOs, state Water Resources Departments, international development organisations running WASH/watershed programmes. WELL Labs' public materials were used only as **domain-grounding research** — nothing in the schema, API, or UI references WELL Labs by name or assumes their specific data.

## `[v2]` Multi-tenancy — the decision the TDR flagged as blocking

The TDR correctly identified that naming five different customer *organizations* while reusing Service 1's auth "100%, zero changes" begs the question of who the tenant is. Service 1's role model (`UserRole`: `CREDIT_OFFICER`, `BRANCH_MANAGER`, `RISK_OFFICER`, `CEO`, `CHAIRMAN`) is a bank org chart, and there is no `organization_id` anywhere in the existing schema — because Service 1 was correctly scoped to one bank per deployment and never needed one.

**Decision: schema-ready, single-tenant-per-deployment for MVP.**

- A new `organization` table is added in Part 5, and every new Water Intelligence table that needs it carries an `organization_id` — but MVP does **not** build application-layer cross-tenant isolation (no per-request tenant filtering, no org admin UI, no per-org billing). Each MVP deployment serves exactly one organization, exactly as Service 1 does today.
- **Why add the column now instead of when it's actually needed:** the column is a one-line schema addition today and an expensive backfill-plus-migration the day a second organization needs to share a deployment. This is the same reasoning already used elsewhere in this document (e.g., D5's `calibration_status` field existing before any calibration source is wired in) — the field exists so a true statement can be made later without surgery on data that already exists.
- **Why not build full multi-tenant isolation now:** nothing in the current MVP scope requires two organizations to share infrastructure, and building tenant-isolation enforcement, an org-admin surface, and per-org rate limiting speculatively would be exactly the kind of premature complexity this document has otherwise been careful to avoid (see D2, D6, D7's identical "not yet, named trigger for later" pattern).
- **Roles, not tenancy, is the part that changes now:** two new `UserRole` values are added — `PROGRAMME_OFFICER` and `PROGRAMME_ADMIN` — extending the existing enum exactly the way D3 already extends `SatelliteIndexType` and `RiskEntityType`, rather than forcing a NABARD consultant or WELL Labs programme officer to be modeled as a `credit_officer`. Water Intelligence's role gates use these new values; Service 1's bank-specific roles are untouched.
- **Explicit trigger condition, same pattern as D7:** the moment a second organization needs to be provisioned into the same deployment, application-layer tenant isolation (org-scoped query filtering at minimum) becomes a hard blocking requirement before that provisioning happens — not a nice-to-have, and not something MVP can grow into by accident, because nothing in MVP enforces it yet.

---

# PART 2 — Product Requirements Document (PRD)

## Primary user story

*"As a watershed programme officer, I draw or upload a catchment boundary, and within minutes I get a defensible water balance, surface-water status, and recharge-stress classification for that area — with every number showing where it came from and how confident it is — so I can decide where to intervene, and later show whether the intervention worked."*

## In scope for MVP

- Catchment polygon creation via **either** manual drawing (reusing the Service 1 polygon pattern) **or** boundary file upload (GeoJSON / KML / zipped Shapefile) `[v2 — moved into MVP, see D2 and Part 9]`
- 3-year monthly water balance (rainfall, ET, runoff), presented as a **qualitative, climatology-relative band as the headline figure**, with the underlying mm values and their confidence range available in the detailed/technical view only `[v2 — see D5 and Part 4]`
- Surface-water extent time series for the catchment (SAR + MNDWI), with an explicit terrain-reliability flag for high-relief catchments `[v2]`
- Rainfall-anomaly and vegetation-condition-based recharge-stress score, benchmarked against the 30-year CHIRPS climatology rather than the catchment's own short lookback `[v2 — see D6]`
- PDF + dashboard report, reusing the reporting pipeline shape
- CGWB groundwater-category cross-check displayed as **context**, never as the primary number, sourced from a new periodic ingestion table `[v2 — see Part 5]`

## Explicitly out of scope for MVP (see Part 8 for phase assignment)

- Automatic DEM-based watershed delineation from a pour point (requires an offline geoprocessing dependency — Phase 2)
- Named recharge-structure inventory / functionality audit (requires either a structure database or manual digitisation workflow — Phase 2)
- Reservoir volume-from-extent estimation (requires a stage-storage/bathymetry approximation — Phase 2)
- Multi-catchment portfolio rollup dashboard (mirrors the still-unbuilt Service 1 Portfolio Dashboard — Phase 3, sequenced together)
- Any groundwater-level or groundwater-volume claim at farm/village scale (**never in scope** — scientifically unsupportable per Part 0 findings, not a phasing question)

## Non-functional requirements (inherited, not re-negotiated)

Same provenance-on-every-number bar as Service 1. Same "never a demo screen, never fake progress" rule from `docs/Product_Design_v2.md`. Same test-coverage expectation as the existing `backend/tests/` suite.

---

# PART 3 — Software Architecture

## Reuse map (explicit, not implied)

```
                        ┌─────────────────────────────┐
                        │   Auth / RBAC / deps.py       │  ← reused; two roles added `[v2]`
                        │   (PROGRAMME_OFFICER/ADMIN)   │     see "Multi-tenancy" above
                        └─────────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                              │
┌───────────────┐           ┌────────────────┐            ┌────────────────┐
│  Service 1      │           │  Shared core    │            │  Water          │
│  (Farm/Risk)    │           │  infrastructure │            │  Intelligence   │
│                 │           │                 │            │  (new)          │
│ FarmPolygon     │           │ Job model        │            │ Catchment       │
│ RiskEngine      │           │ SatelliteObs.    │            │ WaterBalance    │
│ RiskScore       │           │ GEEProvider core │            │   Engine        │
│                 │           │ Report pipeline  │            │ WaterBalance    │
│                 │           │   shape          │            │   Result        │
└───────────────┘           └────────────────┘            └────────────────┘
                                     │
                        ┌─────────────────────────────┐
                        │  New: HydrologyDataProvider    │
                        │  (implemented by extending      │
                        │   GEEProvider, sharing its       │
                        │   internal helpers, not forking) │
                        └─────────────────────────────┘
```

## Key architecture decisions (recorded here in the same style as `docs/DECISIONS.md`, pending transfer into that file once implementation starts)

### D1 — A new `HydrologyDataProvider` interface, not an extension of `SatelliteDataProvider`
**Decision:** define a second abstract provider interface, separate from `SatelliteDataProvider`.
**Why:** Water Intelligence needs ET series, watershed-scale surface-water extent, and (Phase 2) structure-level water presence — a materially larger and differently-shaped contract than the four methods `SatelliteDataProvider` exposes for farm risk scoring. Bolting these onto the existing interface would force every farm-risk caller to depend on methods it never calls, violating interface segregation for no benefit.
**What's actually reused:** the *implementation*. A new `GEEHydrologyProvider` class (or an extended `GEEProvider` implementing both interfaces — decided at M0, see Part 8) shares the existing module's internal helpers: `_monthly_periods()`, the cloud-masking constant, the `asyncio.to_thread()` wrapping convention, the "dataclasses only cross the boundary" rule.

### D2 — MVP watershed input is manual drawing **or** file upload, not DEM-delineation
**Decision:** MVP ships with the manual-polygon pattern Service 1 already uses for farms, **and**, per the TDR's UX finding, boundary upload (GeoJSON/KML/zipped Shapefile) as an equally first-class MVP path — both converge on the same server-side validation before persisting. Auto-delineation from a DEM pour point remains Phase 2.
**Why manual drawing alone was insufficient (`[v2]`):** the TDR observed that every realistic customer named in the PRD — NABARD consultants, state Water Resources Departments, established watershed NGOs — almost certainly already has an authoritative boundary file, and forcing them to hand-trace a multi-hundred-vertex watershed ridgeline on a web map is real first-demo friction, not a cosmetic gap. Server-side file parsing and validation is a bounded, well-understood engineering problem (parse → validate geometry → run the exact same area/vertex checks manual drawing already needs) and is materially *less* effort than several items already inside MVP scope — there was no good reason to defer it.
**Why DEM auto-delineation is still Phase 2:** unchanged from v1 — confirmed by research that GEE has no native flow-tracing primitive, and real delineation needs WhiteboxTools or pysheds running outside GEE against a downloaded DEM tile, a genuine new infrastructure dependency. This is precisely the same judgment call Service 1 already made and documented: *"Manual polygon drawing (Service 1)"* was chosen deliberately for MVP because no cadastral data existed yet. Ship the defensible, honest version first — the honest version now includes "bring your own boundary," which is more defensible than forcing a redraw of something the customer already has surveyed correctly.
**Consequence:** the frontend's `farm-drawing` feature generalizes into a shared `polygon-drawing` primitive reused by both farm creation and catchment creation, and a new server-side boundary-file parser (Part 7) feeds the identical validation path both entry points already share — one validation boundary, two ways in.

### D3 — Extend `SatelliteObservation`'s enums rather than create a parallel cache table
**Decision:** add new values to `SatelliteIndexType` (`ET`, `SURFACE_WATER_SAR`, `SURFACE_WATER_MNDWI`) and add `CATCHMENT` to `RiskEntityType`, rather than building a second observation-cache table.
**Why:** the existing table's polymorphic `(entity_type, entity_id, index_type, period)` shape already does exactly what's needed — a keyed cache to avoid re-billing Earth Engine.
**Named tech debt, not hidden:** `RiskEntityType` becomes a slightly awkward name once it includes `CATCHMENT`, since a catchment doesn't carry "risk" the way a farm loan does. Renaming it would touch working Service 1 code for cosmetic benefit only — **accepted as debt for now, flagged here explicitly** rather than either silently living with a confusing name or destabilizing shipped code to fix it.

### D4 — A new, purpose-built `WaterBalanceEngine`, structurally identical to `RiskEngine`
**Decision:** `WaterBalanceEngine.compute(bundle, config) -> WaterBalanceResult` — zero I/O, deterministic, unit-testable with synthetic bundles, versioned via `MODEL_VERSION`, exactly mirroring `RiskEngine`'s shape. The engine's *shape* was approved without change by the TDR.
**Why:** this pattern is already proven, already tested, and already understood by whoever reviews this code next. There is no reason to invent a different shape for a structurally identical problem (turn a bundle of time series into a scored, versioned result).
**`[v2]` What the engine now states explicitly that v1 left implicit:** `compute()` documents, in its own docstring (not just this blueprint), that it implements a **closed-catchment mass balance** — no lateral subsurface flow term — and that its runoff term is **gross catchment `Q`, not net of any internal recharge-structure capture**. Both are named, deliberate MVP simplifications per Part 4's `[v2]` updates, and the engine's output includes the terrain/permeability and structure-capture flags needed for the report layer to say so, rather than leaving the caller to rediscover the limitation from the methodology page alone.

### D5 — Confidence becomes two fields, not one — and the residual isn't the headline number `[v2 extended]`
**Decision:** every `WaterBalanceResult` carries both a `data_completeness` score (the existing Service 1 concept — fraction of usable cloud-free composites) **and** a separate `calibration_status` enum (`UNCALIBRATED`, `PARTIALLY_CALIBRATED`, `FIELD_CALIBRATED`). This is unchanged from v1.
**Why:** this is the single most important scientific-honesty decision in this document. Storage change (ΔS) is a **residual** — it silently absorbs every error in rainfall, ET, and runoff estimates (and, per D4/Part 4's `[v2]` update, any lateral groundwater flow the closed-catchment assumption doesn't model). A single confidence number that blends "we had good cloud-free imagery" with "this has been checked against a real logger" would hide exactly the distinction Part 4 insists on making visible. MVP output is always `UNCALIBRATED` — there is no ground-truth data source wired in yet, and the field exists specifically so this is stated, not implied.
**`[v2]` What changed:** the TDR asked whether a number that can *never* be calibrated for a generic MVP customer should be the report's headline figure at all. The resolution: it isn't. The report's primary, prominent output is a **5-band qualitative descriptor** relative to the 30-year climatology ("much below normal" through "much above normal"). The quantitative mm value, its confidence interval, and `calibration_status` are all still computed and still fully visible — but in the detailed/technical view, not the headline. This mirrors a pattern TerraRisk already uses elsewhere (individual satellite index values live in the technical view, not the primary bank-facing report) rather than inventing a new convention.

### D6 — Recharge-stress classification uses percentile ranking, not clustering
**Decision:** MVP recharge-stress score reuses the exact `_percentile_rank()` pattern already implemented and tested in `RiskEngine` (rainfall anomaly + VCI, positioned against the catchment's own historical range) — not unsupervised clustering.
**Why:** clustering requires multiple comparable spatial units to find structure in; a single customer running this against one catchment has nothing to cluster against. Percentile-against-own-history is simpler, fully explainable to a non-technical program officer, and reuses code that is already correct and tested. Clustering across many catchments becomes viable — and valuable — once there's a real multi-catchment portfolio (Phase 3, alongside the rollup dashboard).

### D7 — Background job execution stays on `FastAPI BackgroundTask` for MVP, with an explicit trigger for revisiting it
**Decision:** MVP Water Intelligence jobs (GEE-only, manual polygon) reuse the existing `Job` model and `BackgroundTask` pattern, unchanged.
**Why the existing decision still holds:** MVP scope has no DEM geoprocessing step — every operation is a GEE time-series fetch, the same shape and cost profile as Service 1's farm report generation, which already runs safely on this pattern.
**Why this must be re-examined, not silently inherited:** the moment Phase 2's WhiteboxTools-based delineation ships, a single request can involve downloading and processing a DEM tile — a heavier, more variable-duration operation than anything Service 1 does today. **Explicit trigger condition recorded here:** if Phase 2 delineation jobs are observed to run long enough to risk blocking the process's worker threads under concurrent load, move *only that job type* to a proper out-of-process worker (a polling worker against the `job` table is the minimal change; Celery/RQ is the fallback if polling proves insufficient) — do not migrate the MVP's GEE-only jobs off `BackgroundTask` pre-emptively, per YAGNI.

### `[v2]` D8 — Multi-tenancy: schema-ready now, enforced later, by trigger condition
Full rationale lives in Part 1's "Multi-tenancy" section above — recorded here as well because it's an architecture decision with the same weight as D1–D7. Summary: `organization` table + `organization_id` column added in Part 5 now; application-layer tenant isolation deferred until a second organization actually needs to share a deployment; two new generic `UserRole` values added by extension, not by redesigning Service 1's bank-specific roles.

### `[v2]` D9 — GEE cost is bounded by construction, not detected at runtime
**Decision:** rather than computing a large or overly complex catchment and discovering mid-pipeline that it exceeds a safe `reduceRegion` budget, MVP makes that outcome structurally impossible: catchment geometry is bounded (area and vertex count, enforced as database `CHECK` constraints — see Part 5) at *creation* time, before any GEE call is ever made against it.
**Explicit scale policy per index (previously unstated, the TDR's sharpest engineering finding):**

| Index | `scale` used | Native pixel size | Rationale |
|---|---|---|---|
| Sentinel-1 SAR / Sentinel-2 MNDWI surface water | 10 m | 10 m | Matches sensor native resolution — this is the number Part 4's 0.2–0.3 ha reliability floor is actually computed from |
| ET (MODIS MOD16A2) | 500 m | 500 m | Native MODIS resolution; a catchment below ~25 ha (5×5 pixels) gets a confidence penalty via the new `resolution_flags` field (Part 5), not a silently precise-looking number |
| CHIRPS rainfall | native (no `scale` override) | ~5.5 km | Same sub-pixel penalty logic applies below ~3,000 ha, per the same `resolution_flags` mechanism |

**`maxPixels` policy:** set explicitly (not left to GEE's default), sized against the MVP catchment area ceiling defined in Part 5 (500 km² at 10 m ≈ 5×10⁶ pixels per band per composite — comfortably inside a single `reduceRegion` call's safe budget). **`bestEffort: true` is explicitly rejected** for this service — it silently degrades precision without telling the caller, which directly contradicts the confidence/provenance principle this entire document is built on. If a request would exceed the budget, it is impossible to reach that state in the first place, because the geometry that would cause it was already rejected at `POST /catchments` time (Part 5's `CHECK` constraints) — **reject-at-creation, not degrade-at-compute**, is the chosen failure mode for MVP. Auto-degrade-with-visible-confidence-penalty for catchments that legitimately need to be larger than the MVP ceiling is named in Part 13 as Phase 2 scope, not solved speculatively now.
**Quota isolation:** Water Intelligence's `GEEHydrologyProvider` uses a **separate service-account credential** from Service 1's `GEEProvider`, even though both may run against the same GCP project (extending, not replacing, the existing "dedicated GCP project for Earth Engine" decision in `docs/DECISIONS.md`). This exists specifically so a Water Intelligence usage spike cannot degrade Service 1's SLA — a risk the TDR named and this document had no answer for in v1.
**Cost estimate (order-of-magnitude, not a dollar figure — see Part 9 for why a real figure isn't available yet):** Service 1's report generator already follows the discipline of one `getInfo()` call per time series, not per month (per `gee_provider.py`'s own documented rationale), and issues roughly 6 such calls per farm report (NDVI, MNDWI, NDMI, rainfall series, rainfall climatology, JRC water history). Water Intelligence adds ET, SAR surface-water extent, and MNDWI surface-water extent as three further series-level calls, reusing the same one-call-per-series discipline — **a roughly 50% increase in GEE calls per report relative to Service 1**, not a new order of magnitude. **M1's exit criteria now explicitly includes measuring actual GEE compute-unit consumption for a representative catchment report in the staging environment** — this document states the relative multiplier now and commits to replacing it with a measured number before M1 closes, rather than guessing at an absolute figure it has no basis for.

---

# PART 4 — Scientific Methodology Document

This is the section the MIT and IISc professor seats own. Every module is tagged **✓ scientifically supported** or **⚠ requires calibration** — and several are explicitly split, because the same module can be defensible for one use and not for another.

| Module | Status | Methodology | Named limitation |
|---|---|---|---|
| **Watershed delineation** | ⚠ (MVP: manual/upload, not a science question) | MVP: user-drawn or uploaded polygon, server-recomputed area (Service 1 pattern, extended per `[v2]` D2). Phase 2: DEM flow-accumulation via WhiteboxTools from a user-specified pour point | Auto-delineated boundaries need field verification against locally-known command-area or watershed boundaries before being treated as authoritative |
| **Rainfall analysis** | ✓ above ~3,000 ha · ⚠ sub-pixel below it `[v2]` | CHIRPS monthly series + 30-year WMO-standard climatology, SPI-style seasonal anomaly — **identical, reused code path from Service 1** | CHIRPS carries known bias in complex/orographic terrain; not gauge-corrected by default **[S]**. `[v2]` CHIRPS's native grid is ~5.5 km (~3,000 ha) — a catchment smaller than one grid cell receives that cell's single value with no internal spatial resolution. This is now a named, flagged condition (`resolution_flags`, Part 5), not a silent precision-looking number |
| **Evapotranspiration** | ✓ for relative/trend use above ~25 ha · ⚠ for absolute closure or sub-pixel catchments `[v2]` | MODIS MOD16A2 (500 m native) monthly ET | FAO WaPOR validation shows 0.85–0.98 correlation but seasonally variable accuracy and systematic low bias vs. alternative products **[S]** — safe for "is this month wetter/drier than usual," not safe for "the balance closes to within X mm." `[v2]` Catchments below ~25 ha (5×5 MODIS pixels) get the same `resolution_flags` treatment as sub-pixel rainfall |
| **Water balance estimation (P − ET − Q = ΔS)** | ⚠ always, and now with a stated boundary condition `[v2]` | Standard water-accounting-plus (WA+) structure, validated for Indian semi-arid **basin-scale** groundwater balance at IWMI **[S]**. `[v2]` **The equation as implemented assumes the catchment is hydrologically closed — no lateral groundwater exchange across the boundary.** This assumption is stated here explicitly (it was absent in v1) because WA+'s basin-scale validation does not establish it holds at catchment/farm-cluster scale, and it is materially less safe to assume in weathered/fractured hard-rock terrain (e.g. Deccan basalt), where inter-catchment subsurface flow can be a first-order term. Catchments computed to sit in high-permeability or known-fractured geology (a coarse, DEM/geology-layer-derived flag, not a precise hydrogeological survey) carry an additional confidence penalty | ΔS is a **residual** — it absorbs every upstream error, *and* any lateral flow the closed-catchment assumption doesn't model. `calibration_status` defaults to `UNCALIBRATED`. `[v2]` **Presentation change:** the MVP report's headline figure is a **5-band qualitative descriptor** ("much below normal" → "much above normal," climatology-relative), not a bare mm number — the underlying mm value and its (wide) confidence interval are shown only in the detailed/technical view, mirroring the same primary-vs-technical-view split TerraRisk's Service 1 risk methodology already uses for individual index values. An unvalidatable residual should not be MVP's headline number in mm; it can be MVP's headline *direction* |
| **Surface water monitoring (catchment-scale)** | ✓ for water bodies ≳0.2–0.3 ha in low-relief terrain · ⚠ below that area **or** in high-relief terrain `[v2]` | Sentinel-1 SAR (cloud-independent) primary, Sentinel-2 MNDWI secondary confirmation, at 10 m `scale` (D9) | Documented accuracy 89%+ for aquaculture-pond-scale features at 10 m resolution, but explicitly degrades below it **[S]**. `[v2]` **Terrain caveat, previously unstated:** SAR backscatter water-detection thresholds are sensitive to incidence angle and, critically, to terrain-induced layover/shadow — exactly the geometric distortion most common in the undulating terrain where recharge structures and farm ponds are disproportionately sited. MVP uses a single fixed threshold and flags high-relief catchments (computed cheaply from the same DEM already needed elsewhere) as lower-confidence for this module rather than presenting a uniform confidence across flat and hilly terrain alike |
| **Reservoir monitoring** | ✓ extent · ⚠ volume | Same SAR/MNDWI extent method for multi-hectare reservoirs; volume-from-extent only via a DEM-based area-elevation proxy | Without a real bathymetric survey, any volume number is a rough proxy and must be labeled as such, never presented with false precision |
| **Farm pond monitoring** | ⚠ mostly | Presence/absence and gross wet/dry state, same SAR/MNDWI method | Indian farm ponds are frequently sub-0.5 ha — at or below Sentinel's reliable detection threshold **[S]**. Precise area/volume tracking is **not** MVP-defensible; only coarse wet/dry/seasonal classification is |
| **Check dam / recharge structure monitoring** | ✓ water presence · ⚠ structural health **and** ⚠ interaction with catchment water balance `[v2]` | Water-extent time series at known structure coordinates | "Functional vs. silted vs. breached" is **not observable from optical/SAR alone** — a silted structure can still show seasonal standing water. Structural-health claims require either known design-capacity metadata or field/drone survey; MVP reports water-presence trend only, and says so. `[v2]` **Stated, not silent, simplification:** MVP's `Q` (runoff) term in the water balance is *gross catchment runoff* and does **not** net out capture by recharge structures inside the catchment boundary — a check dam's captured volume currently has no term in the balance equation. This is named here as an intentional MVP simplification, not an oversight; Phase 2, once `recharge_structure.design_capacity_m3` (Part 5) is populated for a given catchment, can adjust effective `Q` by structure-captured volume |
| **Recharge stress mapping** | ✓ as a *relative screening index*, benchmarked against the 30-year climatology · never as groundwater level `[v2]` | Composite of rainfall anomaly + VCI + surface-water trend, percentile-ranked. `[v2]` **Baseline changed:** benchmarked against the 30-year CHIRPS climatology window, not the catchment's own trailing 3-year history | GRACE-based groundwater storage is **explicitly excluded** — confirmed unusable below ~10 km even after best-available ML downscaling **[S]**. `[v2]` **Why the baseline changed:** the v1 design reused `RiskEngine`'s 3-year percentile-rank pattern uncritically. That window is appropriate for farm loan risk scoring but not for regional water-stress screening — a catchment whose trailing 3 years happen to be a drought sequence would have "normal" silently redefined as "already stressed," scoring a genuinely stressed catchment as merely moderate. This is exactly the failure mode the *climate resilience* row already correctly avoids by using the 30-year window; recharge-stress now applies the same logic instead of inheriting the shorter one by default |
| **Groundwater stress indicators** | ✓ as context/cross-check | CGWB published block-level category (Safe/Semi-Critical/Critical/Over-Exploited), ~22,965 wells, quarterly since 1969, publicly accessible **[S]**, ingested via a new periodic staging table (`[v2]`, Part 5) | Block-level is far coarser than a village or catchment — shown as a **cross-check layer**, never the primary indicator, and never silently conflated with catchment-scale results |
| **Village water security indicators** | ✓ as a versioned composite — **Phase 3 scope, clarified `[v2]`** | Weighted combination of the above factors *across multiple catchments/villages*, reusing the exact `ConfigWeight`-style versioned-configuration pattern from Service 1 | `[v2]` v1 described this module without a corresponding table in Part 5, and without stating that a *cross-catchment* composite is meaningless until multiple catchments exist for one area — it is explicitly sequenced with the Phase 3 portfolio rollup (Part 8), not built as a standalone MVP table. Weights remain a modelling choice, not a discovered truth, whenever it is built |
| **Watershed health indicators** | ✓ | Multi-year NDVI/VCI trend, land-use change, surface-water trend, each reported as a **named, individually-inspectable sub-indicator** | Never collapse into a single opaque "health score" — this repeats Service 1's own report-design principle: provenance on every number |
| **Climate resilience indicators** | ✓ with an explicit window caveat | Multi-year rainfall variability (CV), VCI-based drought frequency, extreme-event frequency from the same rainfall series | A 3-year lookback (Service 1's existing window) is a *recent-conditions* indicator, not a climate-normal-caliber resilience claim — the 30-year CHIRPS climatology should be leaned on more heavily here than in Service 1, and the report must say which window backs which number. `[v2]` This row's reasoning is now also applied to recharge-stress mapping, above, rather than living only here |

**The one sentence the MIT professor seat insisted go in bold:** *nowhere in this service does any output claim to measure groundwater level or groundwater volume at farm, village, or catchment scale — every groundwater-adjacent output is either a CGWB cross-check (block-scale, sourced, dated) or a relative stress-screening index built from surface indicators, and both are labeled as such on every render.*

---

# PART 5 — Database Schema

## `[v2]` New: `organization` table (multi-tenancy, D8)

```sql
-- Minimal now; not enforced by application-layer query filtering in MVP
-- (see D8) — exists so the column below never needs a backfill later.
CREATE TABLE organization (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL,
    org_type organization_type_enum NOT NULL,   -- 'csr' | 'ngo' | 'nabard' | 'government' | 'international_dev' | 'other'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## New tables

```sql
-- Catchment/watershed polygon, sibling to farm_polygon
CREATE TABLE catchment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organization(id),   -- [v2] nullable in MVP; see D8
    name VARCHAR NOT NULL,
    geometry GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,     -- [v2] was POLYGON — a catchment is not
                                                          -- guaranteed simply-connected (§4 TDR)
    area_ha NUMERIC(10,4) NOT NULL,             -- server-recomputed via ST_Area(geography cast), never trusted from client
    delineation_method delineation_method_enum NOT NULL DEFAULT 'manual',  -- 'manual' | 'upload' | 'auto_dem' (Phase 2) [v2: added 'upload']
    pour_point GEOMETRY(POINT, 4326),            -- nullable; populated only for auto_dem delineation
    admin_boundary_id UUID REFERENCES admin_boundary(id),  -- nullable; optional link for village-level aggregation
    resolution_flags JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [v2] e.g. ["rainfall_sub_pixel", "et_sub_pixel", "high_relief_terrain"] — computed at creation, reused by every downstream report so the caveat is derived once, not recomputed per report
    created_by UUID NOT NULL REFERENCES app_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- [v2] Bounds enforced at creation (D9) — a catchment large or complex enough to
    -- threaten a safe GEE reduceRegion budget can never be persisted in the first place.
    CONSTRAINT chk_catchment_area CHECK (area_ha BETWEEN 0.5 AND 50000),   -- 0.5 ha to 500 km^2
    CONSTRAINT chk_catchment_vertex_count CHECK (ST_NPoints(geometry) <= 2000)
);
CREATE INDEX idx_catchment_geometry ON catchment USING GIST (geometry);
CREATE INDEX idx_catchment_organization ON catchment (organization_id);   -- [v2]
CREATE INDEX idx_catchment_admin_boundary ON catchment (admin_boundary_id);  -- [v2] was missing

-- Water balance result, sibling to risk_score — append-only, versioned
CREATE TABLE water_balance_result (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catchment_id UUID NOT NULL REFERENCES catchment(id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    rainfall_mm NUMERIC(10,2),
    et_mm NUMERIC(10,2),
    runoff_mm NUMERIC(10,2),
    storage_change_mm NUMERIC(10,2),              -- the residual — technical-view only, see D5 [v2]
    storage_change_band storage_change_band_enum NOT NULL,  -- [v2] the actual MVP headline: 5-band qualitative, climatology-relative
    data_completeness NUMERIC(5,2) NOT NULL,        -- 0-100, existing Service 1 confidence concept
    calibration_status calibration_status_enum NOT NULL DEFAULT 'uncalibrated',  -- D5
    closed_catchment_assumed BOOLEAN NOT NULL DEFAULT true,  -- [v2] always true in MVP; the column exists so a
                                                                -- future lateral-flow-aware model can be told apart from this one
    resolution_flags JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [v2] copied from catchment at compute time, immutable per result
    model_version VARCHAR NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL
    -- [v2] weights_version_id REMOVED — a P-ET-Q=ΔS mass balance is an arithmetic
    -- sum of physical terms, not a weighted composite; this FK was copied from
    -- RiskScore's shape in v1 without checking whether it applied here. It didn't.
);
CREATE INDEX idx_water_balance_catchment_period ON water_balance_result (catchment_id, period_start);

-- Recharge-stress score, sibling to risk_factor_score
CREATE TABLE recharge_stress_score (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catchment_id UUID NOT NULL REFERENCES catchment(id),
    computed_at TIMESTAMPTZ NOT NULL,
    stress_score NUMERIC(5,2) NOT NULL,             -- 0-100, higher = more stressed
    stress_band stress_band_enum NOT NULL,
    baseline_window baseline_window_enum NOT NULL DEFAULT 'climatology_30yr',  -- [v2] was implicitly 3-year; now explicit and versioned
    rainfall_anomaly_ratio NUMERIC(6,3),
    vci NUMERIC(5,2),
    surface_water_trend NUMERIC(6,3),
    cgwb_category VARCHAR,                          -- context field, sourced + dated, never blended into the score itself
    cgwb_category_as_of DATE,
    weights_version_id UUID REFERENCES config_weight(id),  -- [v2] moved here from water_balance_result —
                                                              -- this IS a weighted composite (rainfall anomaly + VCI + surface-water trend), unlike the water balance
    raw_inputs JSONB NOT NULL DEFAULT '{}'::jsonb    -- mirrors risk_factor_score.raw_inputs
);
CREATE INDEX idx_recharge_stress_catchment_period ON recharge_stress_score (catchment_id, computed_at);  -- [v2] was missing

-- Recharge structure inventory (Phase 2 — schema reserved now, not populated by MVP)
CREATE TABLE recharge_structure (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catchment_id UUID REFERENCES catchment(id),
    structure_type structure_type_enum NOT NULL,    -- 'check_dam' | 'farm_pond' | 'percolation_tank' | 'other'
    location GEOMETRY(POINT, 4326) NOT NULL,
    design_capacity_m3 NUMERIC(12,2),               -- nullable — only known when user provides it; Phase 2 feeds this
                                                       -- into WaterBalanceEngine's effective-Q adjustment (Part 4, check-dam row)
    source structure_source_enum NOT NULL,          -- 'user_provided' | 'osm' | 'manual_digitisation'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- [v2] CGWB raw ingestion staging table — implied in v1's Part 8/M3 prose
-- ("periodic batch ingest") but never actually given a table to ingest into.
CREATE TABLE cgwb_groundwater_observation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    block_code VARCHAR NOT NULL,           -- CGWB assessment-unit identifier (block/mandal/taluka scale)
    block_geometry GEOMETRY(MULTIPOLYGON, 4326),   -- nullable until a boundary source is confirmed at M3
    category VARCHAR NOT NULL,             -- 'safe' | 'semi_critical' | 'critical' | 'over_exploited'
    assessment_period VARCHAR NOT NULL,    -- CGWB's own period label, e.g. '2024'
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_url VARCHAR NOT NULL,           -- traceability back to the published CGWB/WRIS release
    CONSTRAINT uq_cgwb_block_period UNIQUE (block_code, assessment_period)  -- prevents duplicate ingestion
);
CREATE INDEX idx_cgwb_block_geometry ON cgwb_groundwater_observation USING GIST (block_geometry);
```

## Reused, extended, unchanged

- **`satellite_observation`**: no schema change. `SatelliteIndexType` enum extended with `ET`, `SURFACE_WATER_SAR`, `SURFACE_WATER_MNDWI`. `RiskEntityType` extended with `CATCHMENT` (see D3's named tech debt).
- **`job`**: no schema change. `JobType` extended with `CATCHMENT_WATER_REPORT` (MVP), `CATCHMENT_BOUNDARY_UPLOAD` `[v2]`, `CATCHMENT_AUTO_DELINEATION` (Phase 2).
- **`config_weight`**: reused as-is — now correctly attached only to `recharge_stress_score`, the one MVP table that's a genuine weighted composite (`[v2]`, see above).
- **`UserRole`**: `[v2]` extended with `PROGRAMME_OFFICER`, `PROGRAMME_ADMIN` (D8) — Service 1's bank-specific roles are untouched.
- **`app_user`, `admin_boundary`**: unchanged, referenced by FK.

## Migration note

Per the existing convention (`docs/DECISIONS.md` — "hand-written initial Alembic migration, not autogenerated"), the first migration for this service should be hand-written, following the same discipline: explicit enum creation with lowercase values matching the Python enum's `.value` (the `pg_enum()` gotcha already documented and must not be re-discovered the hard way). `[v2]` The migration must also create the `ST_NPoints`/`ST_Area`-based `CHECK` constraints as part of the initial DDL, not as a follow-up — a catchment created before the constraint exists is exactly the kind of retrofit problem D9 is designed to avoid.

---

# PART 6 — API Specification

Mirrors the existing router-per-resource convention (`app/api/farms.py`, `app/api/reports.py`, `app/api/jobs.py`).

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `POST` | `/catchments` | Create a catchment from a drawn polygon | `PROGRAMME_OFFICER`/`PROGRAMME_ADMIN` `[v2 — was bank-specific roles]`. Geometry, area, and vertex-count bounds enforced server-side (D9) before persistence — a request outside bounds gets a 422, never a partially-created row |
| `POST` | `/catchments/upload` | `[v2]` Create a catchment from an uploaded GeoJSON/KML/zipped-Shapefile boundary; parsed, reprojected to SRID 4326, and run through the **identical** validation path as manual creation | Same role gate |
| `GET` | `/catchments` | List catchments owned/branch-visible to the current user | Authenticated |
| `GET` | `/catchments/{id}` | Catchment detail + geometry + `resolution_flags` | Owner-or-branch scoped (same pattern as farms) |
| `POST` | `/catchments/{id}/water-reports` | Trigger a water-balance + recharge-stress report job (mirrors `POST /farms/{id}/reports`) | Same role gate |
| `GET` | `/catchments/{id}/water-reports/{report_id}` | Report status/result (mirrors existing report status endpoint) | Owner-or-branch scoped |
| `GET` | `/catchments/{id}/water-balance` | Time series of `water_balance_result` rows (headline band + technical-view mm values) | Owner-or-branch scoped |
| `GET` | `/catchments/{id}/recharge-stress` | Latest + historical `recharge_stress_score` | Owner-or-branch scoped |
| `GET` | `/catchments/{id}/water-reports/{report_id}/pdf` | PDF export (mirrors existing report PDF endpoint) | Owner-or-branch scoped |
| `GET` | `/jobs/{id}` | **Reused unchanged** — existing endpoint already handles any `JobType` |

**Deliberately not built in MVP:** any portfolio/multi-catchment rollup endpoint (Phase 3, per Part 4's `[v2]` clarification on village water security indicators); any org-admin or cross-tenant-visible endpoint (D8 — MVP is single-tenant-per-deployment).

---

# PART 7 — Repository Folder Structure

```
backend/app/
├── models/
│   ├── organization.py            # NEW [v2] — Organization (D8)
│   ├── catchment.py              # NEW — Catchment (MULTIPOLYGON, bounds, resolution_flags [v2]), RechargeStructure (Phase 2 schema, MVP unused)
│   ├── water_balance.py          # NEW — WaterBalanceResult (no weights_version_id [v2]), RechargeStressScore (weights_version_id moved here [v2])
│   ├── cgwb.py                    # NEW [v2] — CgwbGroundwaterObservation staging model
│   ├── enums.py                  # EXTENDED — CATCHMENT, ET/SURFACE_WATER_*, new JobTypes, new bands, PROGRAMME_OFFICER/ADMIN [v2], StorageChangeBand [v2], BaselineWindow [v2]
│   └── satellite.py               # UNCHANGED
├── services/
│   ├── hydrology/                # NEW — sibling to services/risk/
│   │   ├── provider.py            # HydrologyDataProvider ABC (D1)
│   │   ├── gee_hydrology_provider.py  # implementation, shares helpers with services/satellite/gee_provider.py; explicit scale/maxPixels per D9 [v2]
│   │   ├── engine.py              # WaterBalanceEngine.compute() (D4) — closed-catchment + gross-Q assumptions documented in docstring [v2]
│   │   ├── recharge_stress.py     # percentile-based stress scoring vs. 30-yr climatology (D6, revised baseline [v2])
│   │   ├── boundary_parser.py     # NEW [v2] — GeoJSON/KML/Shapefile parse + validate, shared by manual and upload creation paths
│   │   └── models.py              # WaterBalanceBundle, WaterBalanceConfig, WaterBalanceEngineResult dataclasses
│   ├── satellite/                 # UNCHANGED, helpers exposed for reuse
│   ├── ingestion/
│   │   └── cgwb_ingest.py          # NEW [v2] — periodic (quarterly) batch job populating cgwb_groundwater_observation
│   └── reporting/
│       ├── water_report_generator.py   # NEW orchestrator, mirrors report_generator.py's shape — incremental-persistence-per-series explicitly required, not just inherited [v2]
│       ├── water_methodology_text.py   # NEW — the ✓/⚠ language from Part 4, rendered per-report
│       └── ... (map_snapshot, pdf_renderer, progress reused directly)
├── api/
│   └── catchments.py               # NEW router, mirrors farms.py + reports.py conventions; includes POST /catchments/upload [v2]
└── schemas/
    ├── catchment.py                # NEW — CatchmentCreateRequest, CatchmentUploadRequest [v2], CatchmentResponse
    └── water_report.py             # NEW

backend/tests/
├── fakes/
│   └── fake_hydrology_provider.py  # NEW, mirrors fake_satellite_provider.py
├── services/
│   ├── test_water_balance_engine.py    # NEW — pure engine, synthetic bundles, no GEE
│   ├── test_water_balance_golden_dataset.py  # NEW [v2] — regression test against the published Western
│   │                                            Maharashtra CN validation study cited in Part 4/Sources
│   ├── test_recharge_stress.py         # NEW
│   ├── test_boundary_parser.py          # NEW [v2] — malformed/valid GeoJSON/KML/Shapefile fixtures
│   └── test_gee_hydrology_provider.py  # NEW, mirrors test_gee_provider.py
├── test_catchments.py                # NEW, mirrors test_farms.py — includes area/vertex-bound rejection cases [v2]
└── test_water_reports.py             # NEW, mirrors test_reports.py

frontend/src/features/
├── polygon-drawing/                 # RENAMED/generalized from farm-drawing (D2)
├── farm-drawing/                    # now a thin wrapper around polygon-drawing for farm-specific chrome
├── catchment-drawing/                # NEW, thin wrapper around polygon-drawing for catchment-specific chrome;
│                                       includes the boundary-file upload path as an equal first-class entry point [v2]
└── water-intelligence/               # NEW — dashboard + report views (band-first, technical-view-second per D5 [v2]), reuses report/ chart & PDF patterns
```

---

# PART 8 — Development Roadmap

## MVP definition (realistic 2–3 week scope) `[v2 — revised]`

Catchment creation (manual draw **or** boundary upload, bounded by area/vertex `CHECK` constraints) → 3-year water balance (rainfall, ET, runoff; **qualitative climatology-relative band as the headline**, mm values + confidence in the technical view, always `UNCALIBRATED`, closed-catchment assumption stated) → surface-water extent time series (terrain-flagged) → recharge-stress score (percentile-based, benchmarked against the 30-year climatology) → CGWB context cross-check (from the new ingestion table) → dashboard + PDF report. Nothing else.

## Milestones

| Milestone | Scope | Independently testable via |
|---|---|---|
| **M0 — Foundations** | New enums (incl. `PROGRAMME_OFFICER`/`ADMIN`, `StorageChangeBand`, `BaselineWindow` `[v2]`), `organization` `[v2]`, `catchment` (MULTIPOLYGON + bounds `[v2]`), `water_balance_result`, `recharge_stress_score`, `cgwb_groundwater_observation` `[v2]` tables + hand-written migration (constraints included, not follow-up `[v2]`), `HydrologyDataProvider` ABC (empty implementation) | `test_schema_ddl.py`-style migration test (incl. `CHECK` constraint rejection cases `[v2]`); ABC import + `NotImplementedError` contract test |
| **M1 — GEE hydrology provider** | `GEEHydrologyProvider`: ET series, SAR+MNDWI surface-water extent series, explicit `scale` per index and `maxPixels` policy (D9 `[v2]`), sharing `_monthly_periods()` and cloud-masking helpers from the existing module. **Exit criterion added `[v2]`: measure actual GEE compute-unit consumption for a representative catchment report in staging and record it, replacing D9's order-of-magnitude estimate with a real number** | `test_gee_hydrology_provider.py` against a real GEE test project, mirroring `test_gee_provider.py`'s existing pattern |
| **M2 — Water balance engine** | `WaterBalanceEngine.compute()`, pure, deterministic, with the residual/confidence/calibration-status logic from D5, closed-catchment and gross-`Q` assumptions documented in the docstring `[v2]`, `storage_change_band` derivation | `test_water_balance_engine.py` (synthetic bundles, zero GEE) **+ `test_water_balance_golden_dataset.py` `[v2]`** — regression-tested against the published Western Maharashtra CN validation study already cited in Sources |
| **M3 — Recharge-stress scoring + CGWB ingestion** | Percentile-based stress score vs. the 30-year climatology baseline `[v2]`, reusing Service 1's statistical helpers; `cgwb_ingest.py` periodic batch job (quarterly, matching CGWB's own cadence) populating the new staging table `[v2]` | `test_recharge_stress.py`; an ingestion-job test asserting `uq_cgwb_block_period` prevents duplicate ingestion |
| **M4 — API + jobs + boundary upload** | `POST /catchments`, **`POST /catchments/upload` `[v2]`**, `POST /catchments/{id}/water-reports`, job orchestration via existing `Job`/`BackgroundTask` pattern, area/vertex-bound rejection at the API boundary | `test_catchments.py` (incl. oversized/malformed-geometry rejection cases `[v2]`), `test_water_reports.py`, `test_boundary_parser.py` `[v2]` |
| **M5 — Reporting pipeline** | `water_report_generator.py` orchestrator with **verified, not just inherited, incremental-persistence-per-series** (`[v2]` — explicitly re-checked given more sequential GEE calls than Service 1), PDF export, methodology text carrying the ✓/⚠ distinctions and new `[v2]` caveats (closed-catchment, terrain, sub-pixel resolution) verbatim into every report | `test_water_report_pdf.py`-style twin test (mirrors `test_report_pdf.py`); a forced-mid-pipeline-failure test proving partial results survive `[v2]` |
| **M6 — Frontend** | `polygon-drawing` generalization, `catchment-drawing` (draw **and** upload paths `[v2]`), `water-intelligence` dashboard (band-first headline, technical view for mm values `[v2]`, charts, map, PDF download) | Vitest unit tests + one real-stack integration test (mirrors the existing farm-creation-flow integration test) |

**M0–M5 are backend-only and can proceed without frontend work blocking them — mirrors the existing project's own M1/M2 split between Service 1 backend and frontend.**

## Explicitly deferred

- **Phase 2:** DEM auto-delineation (WhiteboxTools worker + new job-execution model per D7's trigger condition), recharge-structure inventory + functionality audit, reservoir volume-from-extent estimation.
- **Phase 3:** multi-catchment portfolio rollup dashboard, sequenced together with the still-unbuilt Portfolio Dashboard question raised at the top of this document — these two probably share infrastructure and should not be designed twice.
- **Future roadmap:** clustering-based regional stress classification (once multi-catchment coverage exists to make it meaningful — D6), field-calibration ingestion workflow (the mechanism by which `calibration_status` ever becomes anything other than `UNCALIBRATED`), drone/Planet high-resolution imagery integration for sub-0.5 ha farm ponds.

---

# PART 9 — Risk Register

| # | Risk | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|
| 1 | A user or downstream report reader interprets the storage-change residual as a validated measurement | Medium | High (credibility) | `calibration_status` is a first-class field; `[v2]` the residual is no longer even the headline number — `storage_change_band` (qualitative) is, with mm values demoted to the technical view | **Strengthened `[v2]`** |
| 2 | Small farm ponds report false "dry" or missed-detection results due to Sentinel resolution limits | High | Medium | Every surface-water output states the minimum reliably-detectable feature size; sub-threshold results are labeled "below reliable detection resolution," never silently reported as "dry" | Unchanged, already adequate |
| 3 | GEE cost/quota exposure grows faster than Service 1's, since Water Intelligence adds ET + SAR + MNDWI calls per catchment on top of the existing index set | Medium | Medium | `[v2]` D9 now states the actual multiplier (~50% more calls than Service 1), an explicit `scale`/`maxPixels` policy, reject-at-creation area/vertex bounds, and a separate service-account quota so a spike can't degrade Service 1's SLA | **Resolved `[v2]`** |
| 4 | `RiskEntityType` naming debt (D3) causes confusion for a future engineer who doesn't have this document | Medium | Low | This document + a code comment at the enum definition, explicitly cross-referencing this decision | Unchanged — accepted debt, as originally recorded |
| 5 | Phase 2's WhiteboxTools dependency introduces a new deployment surface not currently in the stack | Low (Phase 2 only) | Medium | Named now, designed later, per D7 — not solved speculatively in MVP | Unchanged |
| 6 | CGWB category data goes stale if treated as a live per-request API call | Medium | Low | `[v2]` Now has an actual table (`cgwb_groundwater_observation`) and a named service (`cgwb_ingest.py`) to ingest into, not just a stated intention | **Resolved `[v2]`** |
| 7 | A generic customer has no way to supply ground-truth calibration data, so `calibration_status` never leaves `UNCALIBRATED` in practice | High | Medium (limits the product's ceiling, not its correctness) | Honest limitation, not a bug — the Future Roadmap's field-calibration ingestion workflow is the actual fix | Unchanged — still open by design |
| 8 | `[v2]` `organization_id` exists in schema but is not enforced by any application-layer tenant-isolation logic in MVP | Low while single-tenant | High if a second org is ever provisioned into the same deployment before enforcement is built | D8's explicit trigger condition: application-layer isolation is a hard blocker on provisioning a second organization, not an optional hardening pass | **New `[v2]`** |
| 9 | `[v2]` A catchment near or below one native CHIRPS (~3,000 ha) or MODIS-ET (~25 ha) pixel gets a rainfall/ET value with no real internal spatial resolution | Medium — small catchments and farm-clusters are a named use case | Medium (false precision) | `resolution_flags` on `catchment`, propagated to every `water_balance_result`, surfaced in the report rather than silently absorbed into `data_completeness` | **New `[v2]`, resolved by design** |
| 10 | `[v2]` SAR-based surface water detection degrades in high-relief terrain due to layover/shadow, independent of the existing area-based resolution limit | Medium — recharge structures and ponds are disproportionately sited in undulating terrain | Medium | Named explicitly in Part 4; catchments flagged via a DEM-derived relief check, lower confidence surfaced rather than a uniform confidence across flat and hilly terrain | **New `[v2]`, named — correction itself still Phase 2** |

---

# PART 10 — Scientific Limitations (consolidated, for the report-facing methodology page)

1. No output in this service measures groundwater level or volume directly, at any scale. GRACE-based approaches are excluded by design (confirmed unusable below ~10 km even with best-available downscaling).
2. Storage-change (ΔS) is always a residual, always confidence-banded, and always labeled with its calibration status — which defaults to `UNCALIBRATED` until a real field-data ingestion path exists. `[v2]` It is presented as a qualitative, climatology-relative band, not a quantitative headline figure, for exactly this reason.
3. `[v2]` **The water balance equation assumes the catchment is hydrologically closed — no lateral groundwater exchange across its boundary.** This is a materially riskier assumption in weathered/fractured hard-rock terrain than in the basin-scale contexts where the underlying WA+ framework has been validated. Catchments in known high-permeability or fractured geology carry an additional confidence penalty rather than being treated identically to any other catchment.
4. `[v2]` **The runoff (`Q`) term is gross catchment runoff and does not net out capture by recharge structures inside the catchment.** A check dam's captured volume currently has no term in the balance — stated here as an intentional MVP simplification, addressed in Phase 2 once structure design-capacity data exists.
5. Surface-water detection is reliable above roughly 0.2–0.3 ha in low-relief terrain; smaller features (many Indian farm ponds) are explicitly flagged as below reliable detection resolution rather than silently misreported. `[v2]` **Independently of size, SAR-based detection also degrades in high-relief terrain** due to incidence-angle sensitivity and layover/shadow — catchments with significant terrain relief carry a separate, named confidence flag.
6. Recharge-structure "functionality" (silted/breached/functional) is not derivable from optical or SAR alone without either known design-capacity metadata or field/drone verification — MVP reports water-presence trend only.
7. ET products carry seasonal accuracy variation and a documented systematic low bias — safe for trend/relative comparison, not for absolute water-balance closure claims. `[v2]` Catchments smaller than roughly 25 ha (below 5×5 MODIS pixels) carry an additional sub-pixel-resolution flag.
8. `[v2]` **Rainfall inputs carry the same sub-pixel caveat**: CHIRPS's native grid is ~5.5 km (~3,000 ha); a catchment smaller than one grid cell receives that cell's value with no internal spatial resolution, flagged accordingly rather than presented as catchment-specific precision.
9. CGWB groundwater categories are block-scale context, not a catchment-scale measurement, and are never blended numerically into the recharge-stress score.
10. `[v2]` **The Curve Number runoff method's applicability, as cited here, is validated for one watershed type in one Indian state (an urbanizing Western Maharashtra catchment)** — carrying known general limitations (storm duration, antecedent moisture, origin in US Midwest calibration). This document treats that citation as regional evidence, not a blanket national validation, and a future golden-dataset test (Part 12) checks computed runoff against that specific published study rather than an assumed-general standard.
11. `[v2]` The recharge-stress score is benchmarked against the 30-year CHIRPS climatology, not a short trailing window, specifically so a recent drought sequence cannot silently redefine "normal" as "already stressed."

---

# PART 11 — Validation Strategy

Three honest layers, same structure recommended for the internship-scale prototype, now formalized for a production service:

1. **Internal consistency (automated, every run):** does the water balance close within a plausible residual range? Are surface-water and MNDWI/SAR agree directionally on the same scenes?
2. **Cross-dataset consistency (automated, periodic):** does the CGWB category for a catchment's containing block agree directionally with the recharge-stress classification? Logged as a QA signal, never silently corrected against.
3. **Field calibration (manual, opt-in per customer):** when a customer (any customer — this is generic, not WELL-Labs-specific) supplies logger or well-level readings for a catchment, the system computes and displays calibration error directly, and flips `calibration_status` accordingly. This is the mechanism, not yet built in MVP, that the Future Roadmap names explicitly.

> **Status, September 2026.** Layer 1 is now built and runs on every report (`backend/app/services/validation/`), with findings persisted to `validation_run` / `validation_finding` and per-input lineage to `evidence_record`. Two corrections to its wording above, both recorded in `docs/DECISIONS.md` (Phases A and B):
>
> - **"Does the water balance close" cannot be tested against this engine.** ΔS is defined as P − ET − Q, so the balance closes identically on every run. Layer 1 checks *plausibility* instead: ET/P, runoff coefficient and |ΔS|/P against zone envelopes, plus physical invariants. Real closure needs an independent estimate of a term. MOD16A2 and PML_V2 already disagree by 48% on a Maski-area polygon.
> - The SAR/MNDWI agreement signal is still logged only, not persisted.
>
> Layer 2 (CGWB cross-check) and layer 3 (field calibration) remain unbuilt. See `docs/GEE_Product_Audit_2026.md` for the product audit and a validation sweep over all stored balances.

---

# PART 12 — Testing Strategy

Follows the existing suite's structure exactly, not a new philosophy:

- **Pure-engine tests** (`test_water_balance_engine.py`, `test_recharge_stress.py`): synthetic `WaterBalanceBundle` fixtures, zero I/O, zero GEE — mirrors `test_risk_engine.py`.
- **`[v2]` Golden-dataset scientific validation tests** (`test_water_balance_golden_dataset.py`): the TDR's sharpest testing-strategy finding was that every existing test proves the *code* is correct without ever checking the *hydrology* is right. This test runs the engine against inputs derived from the published Western Maharashtra Curve Number validation study already cited in Part 4/Sources, and asserts computed runoff falls within that study's reported range — a software-correctness suite that's 100% green while the science is wrong is exactly the failure mode this test exists to catch. A second golden-dataset case (an ET validation site, if a suitable public one is identified during M2) is a should-have, not a blocker.
- **Provider tests** (`test_gee_hydrology_provider.py`): real GEE calls against the test project, mirrors `test_gee_provider.py`. `[v2]` Includes explicit assertions on the `scale`/`maxPixels` values used per index (D9) — these are policy, not incidental defaults, and deserve the same test-pinning as report text.
- **`[v2]` Boundary parser tests** (`test_boundary_parser.py`): valid and malformed GeoJSON/KML/Shapefile fixtures, asserting the upload path enforces the identical area/vertex/validity checks as manual drawing — one validation boundary, tested from both entry points.
- **Fakes** (`fake_hydrology_provider.py`): deterministic stand-in for API-level integration tests, mirrors `fake_satellite_provider.py`.
- **Schema/DDL tests**: mirrors `test_schema_ddl.py` for the new tables and enums. `[v2]` Includes rejection-case tests for the new `CHECK` constraints (oversized area, excessive vertex count) and the `cgwb_groundwater_observation` uniqueness constraint.
- **Report twin-tests**: methodology text and PDF content pinned by test, exactly as `test_report_text.py`/`test_report_pdf.py` already do — the ✓/⚠ language from Part 4, including all `[v2]` additions (closed-catchment, terrain, sub-pixel resolution, structure/runoff interaction), must appear verbatim and cannot silently drift.
- **`[v2]` Partial-failure resilience test**: a forced mid-pipeline failure (e.g., the ET call succeeds, the SAR call fails) asserting already-fetched series survive — re-verifying, not just assuming, that `water_report_generator.py` inherits Service 1's incremental-persistence discipline across a longer call chain.
- **Real-stack integration test**: one end-to-end catchment-creation-to-report flow, mirroring the existing farm-creation-flow integration test, with the GL map as the only mocked seam. `[v2]` Run once via manual drawing and once via boundary upload — both entry points converge on the same backend path, and the test proves it.

---

# PART 13 — Future Enhancements (beyond Phase 2/3, not committed, named so they aren't rediscovered from scratch later)

- DEM-based auto-delineation as a first-class feature, once the WhiteboxTools worker infrastructure exists
- Recharge-structure inventory with functionality audit, once either structure metadata or a digitisation workflow exists — including, per `[v2]`'s Part 4 update, feeding `design_capacity_m3` into `WaterBalanceEngine`'s effective-`Q` adjustment
- Field-calibration ingestion UI — the actual mechanism that moves `calibration_status` beyond `UNCALIBRATED`
- Regional clustering-based stress classification, once multi-catchment coverage justifies it (D6)
- Higher-resolution imagery integration (Planet, drone) for sub-0.5 ha farm pond precision and terrain-distorted SAR readings `[v2]`
- Multi-catchment portfolio rollup and the village-water-security composite, sequenced with the Portfolio Dashboard question from the top of this document (Part 4's `[v2]` clarification)
- `[v2]` **Application-layer multi-tenant isolation** — org-scoped query filtering, an org-admin surface, per-org rate limiting — triggered the moment a second organization needs to share a deployment (D8)
- `[v2]` **Auto-degrade-with-visible-confidence-penalty** as an alternative to reject-at-creation for catchments that legitimately need to exceed the MVP area ceiling, once real usage shows the hard bound is too restrictive (D9)
- `[v2]` **A named review checkpoint at Service 3's scoping stage** for the shared-enum coupling pattern (`RiskEntityType`, `SatelliteIndexType`) — sound for two services, not yet proven to scale past that, per the TDR's maintainability finding
- `[v2]` Terrain-aware, locally-adaptive SAR water-detection thresholding (replacing the fixed global threshold) once a specific high-relief deployment justifies the added GEE compute cost

---

# PART 14 — Exact First Coding Task

**Ticket M0.1 — `HydrologyDataProvider` abstract contract + new enums + migration skeleton, no GEE calls yet. `[v2 — scope expanded to include the schema fixes from the TDR]`**

1. Add `ET`, `SURFACE_WATER_SAR`, `SURFACE_WATER_MNDWI` to `SatelliteIndexType`; add `CATCHMENT` to `RiskEntityType`; add `CATCHMENT_WATER_REPORT`, `CATCHMENT_BOUNDARY_UPLOAD` `[v2]` to `JobType`; add new `DelineationMethod` (values: `manual`, `upload` `[v2]`, `auto_dem`), `CalibrationStatus`, `StressBand`, `StorageChangeBand` `[v2]`, `BaselineWindow` `[v2]`, `OrganizationType` `[v2]` enums; add `PROGRAMME_OFFICER`, `PROGRAMME_ADMIN` `[v2]` to the existing `UserRole` — all in `app/models/enums.py`, following the existing `pg_enum()` convention exactly (values, not member names).
2. Create `app/services/hydrology/provider.py`: the `HydrologyDataProvider` ABC, following `SatelliteDataProvider`'s exact shape — abstract methods for `get_et_series`, `get_surface_water_extent_series`; dataclasses only, no `ee.*` in the signature, per the architectural contract already established. `[v2]` Method signatures document the `scale` each will use (D9) even though no implementation exists yet.
3. Create `app/models/organization.py` (`Organization` `[v2]`), `app/models/catchment.py` (`Catchment` — **`MULTIPOLYGON`, not `POLYGON`; `resolution_flags`; the two `CHECK` constraints from Part 5** `[v2]`; `RechargeStructure` schema can wait for Phase 2), `app/models/water_balance.py` (`WaterBalanceResult` — **no `weights_version_id`** `[v2]`; `RechargeStressScore` — **`weights_version_id` here instead** `[v2]`), and `app/models/cgwb.py` (`CgwbGroundwaterObservation` `[v2]`), following `FarmPolygon`'s and `RiskScore`'s exact mixin usage (`UUIDPrimaryKeyMixin`, `CreatedAtMixin`).
4. Hand-write the Alembic migration for the new tables, enums, **and `CHECK` constraints** `[v2]`, per the existing "hand-written, not autogenerated" convention.
5. **First test to write, before any implementation:** a schema/DDL test (mirroring `test_schema_ddl.py`) proving the new enums round-trip correctly through Postgres — this is exactly the kind of bug (`pg_enum()`'s member-vs-value mismatch) the existing codebase already hit once and documented. `[v2]` **Second test, same priority:** a `CHECK` constraint rejection test — insert an oversized-area and an excessive-vertex-count geometry and assert both fail at the database level, not just at the application layer, before any endpoint exists to accidentally bypass it.

**Deliberately not in this first ticket:** any GEE call, any API route, any frontend change, the boundary-file parser (that's M4, since it depends on the validation path this ticket only lays the schema for). The first coding task proves the schema and contract are right before a single line depends on them.

---

## Sources

- [FAO WaPOR water accounting](https://www.fao.org/in-action/remote-sensing-for-water-productivity/water-accounting)
- [WaPOR data quality technical evaluation](https://www.mdpi.com/2073-4441/17/14/2106)
- [IWMI WaPOR: Remote Sensing for Water Productivity](https://www.iwmi.org/projects/wapor/)
- [Implementation of satellite-based Water Accounting Plus (WA+) for groundwater balance, semi-arid India](https://www.sciencedirect.com/science/article/abs/pii/S2352801X2400314X)
- [Can remote sensing identify successful agricultural water management interventions in smallholder farms? — IWMI](https://archive.iwmi.org/wle/thrive/2022/01/04/can-remote-sensing-identify-successful-agricultural-water-management-interventions/)
- [GRACE/GRACE-FO spatial downscaling with Random Forests](https://www.sciencedirect.com/science/article/abs/pii/S0022169424011041)
- [Machine learning downscaling of GRACE/GRACE-FO for local-scale groundwater monitoring](https://environmentalsystemsresearch.springeropen.com/articles/10.1186/s40068-024-00368-1)
- [Downscaled GRACE evaluation over a fractured crystalline aquifer, southern India — HESS](https://hess.copernicus.org/articles/26/4169/2022/)
- [Assessment of coastal aquaculture from Sentinel-1 SAR time series](https://doi.org/10.3390/rs11030357)
- [Radar vs. optical: cloud cover impact on seasonal surface water mapping, monsoon India](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11760589/)
- [Sentinel-1/Sentinel-2 small waterbody mapping performance, urban/mountainous regions](https://doi.org/10.3390/w13070945)
- [A Critical Review of the SCS-CN Method in Hydrological Modelling](https://link.springer.com/article/10.1007/s13157-024-01873-w)
- [SCS-CN reliability on semi-arid reclaimed minelands](https://www.tandfonline.com/doi/abs/10.1080/09208119408964758)
- [Validating Curve Number estimation approaches, urbanizing watershed, Western Maharashtra](https://link.springer.com/article/10.1007/s40808-023-01855-7)
- [Watershed delineation using WhiteboxTools](https://sites.psu.edu/mapsgislib/2021/04/05/watershed-delineation-using-whiteboxtools/)
- [WhiteboxTools hydrological analysis manual](https://www.whiteboxgeo.com/manual/wbt_book/available_tools/hydrological_analysis.html)
- [HydroSHEDS datasets in Earth Engine catalog](https://developers.google.com/earth-engine/datasets/tags/hydrosheds)
- [Watershed analysis with pysheds](https://pythongis.org/part3/chapter-12/nb/00-watershed-analysis-with-pysheds.html)
- [Bhuvan — NRSC geoportal](https://bhuvan.nrsc.gov.in/wiki/index.php/Bhuvan_2D)
- [India-WRIS groundwater level monitoring](https://cgwb.gov.in/en/ground-water-level-monitoring)
- [Quality-controlled groundwater level data with specific yield over India — Scientific Data](https://www.nature.com/articles/s41597-025-05899-5)

---

# v1 → v2 Change Log

| TDR item | v1 gap | v2 resolution | Section(s) |
|---|---|---|---|
| Blocking 1 — Multi-tenancy | No `organization` concept; bank-shaped roles reused unexamined | New `organization` table + `organization_id` column, schema-ready but not enforced in MVP (explicit trigger for when it must be); two new generic roles (`PROGRAMME_OFFICER`/`ADMIN`) added by extension | Part 1 "Multi-tenancy", D8, Part 5, Part 6 |
| Blocking 2 — GEE scale/`maxPixels` | No stated policy; near-certain production bug | Explicit `scale` per index, `maxPixels` sized against a new hard area ceiling, `bestEffort` explicitly rejected, reject-at-creation as the chosen failure mode | D9, Part 5 (`CHECK` constraints) |
| Blocking 3 — Closed-catchment assumption | Unstated anywhere | Named explicitly in the equation's methodology row, Part 10, D4's engine docstring requirement, and reflected in a new `closed_catchment_assumed` schema column | Part 4, Part 10, D4, Part 5 |
| Schema — MULTIPOLYGON | `catchment.geometry` typed `POLYGON` | Changed to `MULTIPOLYGON` | Part 5 |
| Schema — catchment limits | No area/vertex bound, unlike `FarmPolygon` | Two `CHECK` constraints (`chk_catchment_area`, `chk_catchment_vertex_count`), enforced at the database layer | Part 5, Part 14 |
| Schema — `weights_version_id` | Present on `water_balance_result` (not a weighted composite — unexplained) | Removed from `water_balance_result`; moved to `recharge_stress_score`, which genuinely is one | Part 5, Part 6 (folder structure) |
| Schema — CGWB ingestion table | Implied in prose (Part 8/M3), absent from Part 5 | New `cgwb_groundwater_observation` staging table with a uniqueness constraint and a named ingestion service | Part 5, Part 7, Part 8 |
| Schema — missing indexes | No index on `admin_boundary_id`, no index on `recharge_stress_score(catchment_id, computed_at)` | Both added | Part 5 |
| Methodology — Curve Number regionalization | Cited one regional study, generalized nationally | Re-scoped as region-qualified evidence; a golden-dataset test checks against that specific study rather than assuming general validity | Part 10, Part 12 |
| Methodology — recharge-stress baseline | Reused `RiskEngine`'s 3-year window uncritically, inconsistent with the document's own climate-resilience row | Rebenchmarked against the 30-year CHIRPS climatology; new `baseline_window` schema field | Part 4, D6 (referenced), Part 5 |
| Methodology — storage-change presentation | Bare mm residual, confidence-banded but still the headline | Qualitative 5-band descriptor is now the headline; mm value + interval moved to the technical view | Part 4, D5, Part 5 (`storage_change_band`) |
| Methodology — recharge structure / runoff interaction | Two modules silently disconnected | Named as an explicit, intentional MVP simplification with a stated Phase 2 fix path | Part 4, Part 10, Part 13 |
| Methodology — terrain limitations (SAR) | Unstated | Named explicitly; high-relief catchments flagged for lower confidence | Part 4, Part 10, Part 9 (new risk #10) |
| Methodology — ET / rainfall sub-pixel resolution | Unstated; small catchments got false precision | New `resolution_flags` mechanism on `catchment` and `water_balance_result`, named in Part 4 and Part 10 | Part 4, Part 5, Part 10, Part 9 (new risk #9) |
| Implementation — GEE cost estimation | No estimate, not even rough | Order-of-magnitude relative estimate (~50% more calls than Service 1) stated now, with a committed M1 exit criterion to replace it with a measured figure | D9, Part 8 (M1) |
| Implementation — quota strategy | Unstated whether shared with Service 1 | Separate service-account credential, explicitly to isolate blast radius | D9 |
| Implementation — performance/caching policy | "Reuse caching discipline" asserted, not required | Made an explicit M1 requirement, not an afterthought; paired with the reject-at-creation bound so caching isn't the only safeguard | D9, Part 9 (risk #3, resolved) |
| Implementation — error handling for large catchments | Undefined behavior at GEE's `maxPixels` boundary | Structurally impossible to reach — oversized/overly-complex geometry is rejected at creation, before any GEE call | D9, Part 5, Part 6 |
| Testing — golden-dataset validation | Every test proved code correctness, none proved scientific correctness | New `test_water_balance_golden_dataset.py`, regression-tested against the Western Maharashtra CN study already in Sources | Part 12, Part 8 (M2) |
| UX — boundary upload | Absent from MVP scope entirely | Moved into MVP as `POST /catchments/upload`, sharing one validation path with manual drawing | Part 2, D2, Part 6, Part 7, Part 8 (M4/M6) |
| UX — catchment creation workflow | Single path (hand-drawing only) | Two converging paths (draw or upload), explicitly tested from both entry points | D2, Part 12 |

---

# Remaining Open Questions

These are not blocking — each has an explicit owner and trigger condition already recorded in the relevant section, named here so they're visible in one place rather than only discoverable by reading the whole document again:

1. **The Service 2/3 numbering conflict** (top of document) is still the founder's call, not resolved by this revision — it's a product-sequencing decision, not an engineering one.
2. **Whether `GEEHydrologyProvider` is a new class or an extended `GEEProvider`** (D1) remains explicitly deferred to M0 as an implementation detail — this was correctly scoped as low-stakes in v1 and stays that way.
3. **The exact GEE compute-unit cost figure** is a stated estimate (~50% more calls than Service 1) until M1's exit criterion produces a measured number — this is a known unknown with a committed resolution date, not an open-ended gap.
4. **Whether reject-at-creation (current MVP choice) or auto-degrade-with-disclosure is the right long-term failure mode** for oversized catchments is named in Part 13 as a future decision, pending real usage data on how often the MVP ceiling is actually hit.
5. **The shared-enum coupling pattern's scalability past Service 3** is flagged as a planned review checkpoint (Part 13), not resolved now — resolving it prematurely, without Service 3 actually scoped, would risk the same "invented too early" failure mode this document has otherwise been careful to avoid.
6. **A second golden-dataset case for ET** (beyond the Curve Number one) is named as a should-have in Part 12, contingent on identifying a suitable public validation site during M2 — not guaranteed to exist, not blocking if it doesn't.

---

# Final Implementation Readiness Score: **8.5 / 10**

**Why not a 10:** three of the "Remaining Open Questions" above (items 3, 4, 6) are genuinely unresolved facts, not just deferred decisions — M1 hasn't run yet, so the GEE cost figure is still an estimate, and there's no way to responsibly score those as fully closed before they are.

**Why not lower:** every blocking item and every must-fix schema and methodology issue from the TDR has a concrete, specific resolution recorded in this document — not a promise to resolve it later. The three remaining points are the kind of thing that can only be closed by running M0–M1, not by more design-review cycles; further review before implementation would be diminishing returns, not diligence.

# Recommendation: **APPROVED WITH MINOR CHANGES**

The remaining items (open questions 3, 4, 6 above) are correctly scoped as *execution-time discoveries*, not *design-time decisions still owed*. Implementation on M0 can begin. The re-review trigger the TDR specified — "once items 1–12 are addressed, this returns to the panel for a second pass focused only on those changes" — is satisfied by this document; no further design-review cycle is required before M0 starts. The panel's one standing request: **M1's exit criteria (measured GEE cost) and M2's golden-dataset test results should be reported back to this document's revision history when they land**, not left to silently update only the code.
