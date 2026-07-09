# TerraRisk — Phase 0 Engineering Blueprint

**Status:** Draft · Pending Approval
**Track:** TerraRisk / Phase 0

The complete implementation blueprint for TerraRisk's two MVP services — Farmer Climate Intelligence Report and Portfolio Climate Risk Dashboard — covering user journeys, screens, APIs, database, GIS, Earth Engine integration, the risk engine, reports, dashboards, and the build roadmap. No code yet — this is what gets built once you sign off.

| | |
|---|---|
| **First customer** | DCCB Latur |
| **Data pipeline** | Google Earth Engine (abstracted) |
| **Data store** | PostgreSQL + PostGIS |
| **Stack** | FastAPI · Next.js |
| **Scoring model** | Rule-based, configurable, versioned |

## Table of Contents

01. [User Journey](#01--user-journey)
02. [Screen Inventory](#02--screen-inventory)
03. [API Blueprint](#03--api-blueprint)
04. [Database Blueprint](#04--database-blueprint)
05. [GIS Blueprint](#05--gis-blueprint)
06. [Earth Engine Blueprint](#06--earth-engine-blueprint)
07. [Risk Engine Blueprint](#07--risk-engine-blueprint)
08. [Report Design](#08--report-design)
09. [Dashboard Design](#09--dashboard-design)
10. [Development Roadmap](#10--development-roadmap)
11. [Open Domain Questions](#11--open-domain-questions)

---

## 01 · User Journey

Every step below exists to solve a specific gap in how a DCCB officer currently works — not because a platform "should" have it. Where a step might look like unnecessary friction (manual polygon confirmation, an async processing screen), the reasoning is spelled out.

### Service 1 — Farmer Climate Intelligence Report

1. **Login**
   Loan and farm data is sensitive; a bank will not pilot software with no access control. Also establishes who drew a polygon and who generated a report — an audit trail a bank's internal process will expect.

2. **Search Village**
   Officers think in villages, not coordinates. India has roughly 650,000 villages — search narrows the map to something navigable in one step instead of panning a national view.

3. **Navigate to Farm**
   The map recenters on the selected village; the officer visually locates the actual field using local knowledge. This human-in-the-loop step exists because we deliberately don't have cadastral/parcel data yet — it's not a placeholder, it's the approved MVP approach.

4. **Draw Polygon → Confirm Area**
   Officer draws the boundary; the system shows the computed area (hectares) and requires explicit confirmation before submit. This turns a manual, error-prone step into an accountable one — the record shows the officer affirmed the area, not that the system silently trusted a hand-drawn line.

5. **Generate Report**
   An explicit, deliberate action — the officer decides which farms warrant analysis. The system never decides on its own who gets evaluated.

6. **Background Processing**
   Pulling three years of Sentinel-1/2 and rainfall history and computing four risk factors takes longer than a request should block on. The officer sees a status screen and can leave — the job survives a server restart because status lives in the database, not in memory.

7. **Interactive Dashboard**
   Before committing to a lending decision, the officer can explore why the score is what it is — drill into any factor, see the imagery, check the confidence indicator. Explainability has to be interactive, not just a number on a page.

8. **Professional PDF Report**
   Banks operate on files and audit trails, not live dashboards. The PDF is the artifact that actually enters the loan file — same data as the dashboard, rendered from the same source so the two never disagree.

### Service 2 — Portfolio Climate Risk Dashboard

1. **Login**
   Same access-control baseline as Service 1 — portfolio-wide exposure data is more sensitive, not less.

2. **Upload Portfolio CSV**
   Banks already export loan data from their core banking system into spreadsheets. TerraRisk meets them there rather than requiring new data entry — this is deliberately an import, not a ledger, reinforcing that we are not a CBS replacement.

3. **Validation**
   Row-level errors and unmatched village/branch names are surfaced before anything is committed. A bank needs to trust the resulting numbers — silently dropping or mis-mapping rows would poison every downstream risk figure.

4. **Background Processing**
   Village → branch → district aggregation across potentially thousands of rows runs as an async job — the same durable job pattern as Service 1's report generation, not a second bespoke mechanism.

5. **District → Branch → Village Dashboards**
   This drill order mirrors how a Chairman or CEO actually consumes the information: start at the level they're accountable for, then drill toward the specific branch or village that needs attention — not a technical hierarchy, an institutional one.

6. **Portfolio Reports**
   The artifact that actually goes into a board pack or supervisory submission is a document, not a dashboard someone has to drive live in a meeting.

---

## 02 · Screen Inventory

14 screens total across both services, plus one shared entry point. Every screen is justified by a role's actual task — nothing here is speculative navigation.

| Screen | Service | Primary user | Inputs | Outputs | Navigates to | Business value |
|---|---|---|---|---|---|---|
| Login | Shared | All roles | Credentials | Session + role | Home | Baseline access control; establishes accountability |
| Home / Service Selector | Shared | All roles | — | — | Village Search or Portfolio Upload | Keeps two services discoverable without cluttering either |
| Village Search | 1 | Credit Officer | Village name query | Selected village, map recenter | Farm Map & Draw | Matches the officer's village-first mental model |
| Farm Map & Polygon Draw | 1 | Credit Officer | Drawn polygon | Geometry + computed area | Confirm & Generate | MVP substitute for missing cadastral data |
| Report Processing Status | 1 | Credit Officer | (trigger only) | Job status | Farmer Dashboard on completion | Sets correct expectations without blocking the officer |
| Farmer Climate Dashboard | 1 | Credit Officer, Branch Manager | farm_id | Full interactive report | PDF export; back to Village Search | Builds trust through explainability before a lending call |
| Farmer PDF Report | 1 | Officer, auditors | report_id | Downloadable PDF | — | Matches the bank's existing file-based process |
| Portfolio Upload | 2 | Branch Manager, Risk Officer | CSV file | Upload receipt | Validation Review | Meets the bank where its data already lives |
| Validation Review | 2 | Risk Officer | (review only) | Accepted / rejected rows | Re-upload or Processing Status | Stops bad data from corrupting portfolio risk numbers |
| Portfolio Processing Status | 2 | Risk Officer | (trigger only) | Job status | District Dashboard | Same async pattern as Service 1 — one mental model |
| District Risk Dashboard | 2 | CEO, Chairman, Risk Officer | District filter | Choropleth + KPIs | Branch Dashboard | The first screen a Chairman actually opens |
| Branch Risk Dashboard | 2 | Branch Manager, Risk Officer | Branch selection | Ranked villages + KPIs | Village Dashboard; Farmer Dashboard | Where a manager decides which villages to visit first |
| Village Risk Dashboard | 2 | Credit Officer, Branch Manager | Village selection | Trend + linked farms | Farmer Dashboard (Service 1) | Where the two services meet |
| Portfolio Report Export | 2 | All portfolio roles | Role + scope | Role-specific PDF | — | One data source, five audiences, one report engine |

---

## 03 · API Blueprint

All endpoints live under `/api/v1`, return Pydantic-validated schemas (never raw dicts), use a single error envelope, and enforce role-scoped authorization server-side — a Branch Manager's token cannot query another branch's data no matter what the UI shows.

| Endpoint | Method | Purpose | Auth | Key business rule |
|---|---|---|---|---|
| `/auth/login` | POST | Authenticate, issue session | None | Generic failure message — no user enumeration |
| `/villages` | GET | Village search / typeahead | Bearer | Scoped to onboarded states/districts only |
| `/farms` | POST | Persist a drawn polygon | Credit Officer | Geometry must be valid & officer-confirmed area |
| `/farms/{id}/reports` | POST | Trigger report generation | Credit Officer | Async — returns 202 + job_id, never blocks |
| `/jobs/{id}` | GET | Poll any async job | Job owner / same branch | One uniform pattern for both services |
| `/reports/{id}` | GET | Full report JSON | Officer / Branch Manager | Same payload powers dashboard and PDF |
| `/reports/{id}/pdf` | GET | Rendered PDF | Officer / Branch Manager | Generated async, cached after first render |
| `/portfolio/uploads` | POST | Upload loan CSV | Branch Mgr / Risk Officer | Size limit, content-type check before parsing |
| `/portfolio/uploads/{id}/validation` | GET | Row-level validation result | Risk Officer | Unmatched villages surfaced for manual reconciliation |
| `/portfolio/uploads/{id}/commit` | POST | Commit rows, trigger aggregation | Risk Officer | Only accepted rows are committed |
| `/risk/districts · /branches · /villages` | GET | Query pre-aggregated rollups | Role-scoped | Reads precomputed tables — never a live GEE call |
| `/reports/portfolio` | GET | Role-specific portfolio report | Role-scoped | Shares the same render pipeline as the farmer PDF |

### Representative deep-dive: `POST /farms/{id}/reports`

- **Request:** `{ lookback_years: 3 }`
- **Response — 202:** `{ job_id, status: "queued" }`
- **Validation:** Farm must exist and belong to the caller's branch scope
- **Business rule:** Creates a durable job row before returning — a mid-computation restart is recoverable, not lost
- **Errors:** `404` unknown farm · `409` report already in progress for this farm
- **Dependencies:** SatelliteDataProvider adapter, Risk Engine, job table

### Representative deep-dive: `GET /portfolio/uploads/{id}/validation`

- **Response:** `{ accepted, rejected: [{row, reason}], unmatched_villages: [...] }`
- **Business rule:** Village/branch matched on `(state, district, taluka, village)`, never on village name alone
- **Failure mode:** Duplicate village names across talukas resolved by requiring the fuller tuple, not fuzzy string guessing
- **Dependencies:** village_branch_lookup table, CSV schema validator

---

## 04 · Database Blueprint

PostgreSQL with PostGIS. Every table below is designed so that when real DCCB data replaces synthetic data, only the ingestion layer changes — not the schema itself.

| Table | Purpose | Key columns | Notes |
|---|---|---|---|
| `admin_boundary` | State/district/taluka/village geometries | id, level, name, parent_id, geometry, geometry_simplified | GIST index on both geometry columns |
| `village_branch_lookup` | Configurable village→branch mapping | state, district, taluka, village, branch_id | Composite index; replaceable by official boundaries later |
| `branch` | Bank branch registry | id, name, district_id | — |
| `farm_polygon` | Officer-drawn farm boundaries | id, village_id, geometry, area_ha, drawn_by, created_at | GIST index; area recomputed server-side via `ST_Area` |
| `farmer_identity` | PII only — isolated from analytics | id, name, kcc_id, contact | Stricter access permission than loan/risk tables |
| `loan` | Portfolio record | id, farmer_identity_id (FK), farm_polygon_id (nullable), branch_id, crop, outstanding_amount | No PII fields live here directly |
| `satellite_observation` | Cached GEE outputs | id, entity_id, index_type, period, value, source_dates | Keyed so repeat requests never recompute against GEE |
| `risk_factor_score` | Per-factor breakdown, one row per compute | risk_score_id (FK), factor, value, band, raw_inputs (jsonb) | Raw inputs retained — doubles as future ML training data |
| `risk_score` | Append-only — never updated in place | id, entity_type, entity_id, overall_band, confidence, model_version, weights_version_id, computed_at | "Current" score = latest row; history is free |
| `config_weight` | Versioned risk-engine configuration | id, weights (jsonb), floor_thresholds (jsonb), effective_from | Never edited in place — new version, new row |
| `risk_rollup_village / branch / district` | Precomputed portfolio aggregates | entity_id, exposure_amount, risk_band, computed_at | Dashboards query these — never live per-request math |
| `job` | Durable async job tracking | id, type, status, entity_id, created_by, updated_at | Survives a process restart — same table for both services |

### Design commitments

- **Spatial indexing:** GIST index on every geometry column; btree on all foreign keys; composite index on `(state, district, taluka, village)` for the lookup table.
- **PII separation:** `farmer_identity` is the only table holding personally identifying fields — deliberately isolated so a future compliance requirement (data residency, RBI data-handling expectations) doesn't force a rewrite of tables the risk engine and dashboards already depend on.
- **Versioning:** `risk_score` is append-only; every row tags `model_version` and `weights_version_id`, so a "did the new model agree with the old rules" comparison is a query, not an archaeology project.
- **Future ML compatibility:** because `risk_factor_score.raw_inputs` retains the actual NDVI/MNDWI/NDMI/rainfall values behind every factor — not just the final 0–100 score — that data can become ML training features later without touching ingestion.

---

## 05 · GIS Blueprint

**Boundary hierarchy.** State → District → Taluka → Village, sourced once from public government GIS datasets for Maharashtra and loaded into `admin_boundary`. We are not waiting on DCCB's own branch boundaries — the configurable lookup table (Section 04) carries that mapping until official data exists.

**Village search.** Typeahead against village name with taluka/district shown alongside to disambiguate duplicates — a text-search index (trigram) backs it, returning a centroid for map recentering, not a full geometry payload on every keystroke.

**Polygon workflow.** Drawn client-side for immediate visual feedback; the server always recomputes the authoritative area via PostGIS on submit — the client's number is never trusted as the record of truth, only as a preview.

**Map layers.** Base imagery for navigation, an administrative boundary overlay, the officer's farm polygon overlay, and — for Service 2 — a risk choropleth layer using the exact same risk-band colors as the dashboard cards and the PDF. One legend, everywhere in the product.

**Coordinate system.** WGS84 (EPSG:4326) end to end — GEE's native CRS, so government shapefiles are reprojected to it once at ingestion rather than reconciling CRS mismatches per-request, which is a classic source of silently wrong area/overlap calculations.

**Geometry simplification.** Every boundary and polygon table carries two geometry columns: the precise one for area/analytical calculations, and a `geometry_simplified` (`ST_SimplifyPreserveTopology`) column for map rendering — government shapefiles are detailed enough that rendering them raw in a browser would be slow once Latur's full village set is loaded.

**Caching.** Boundary layers change rarely and are cached aggressively; per-farm polygon layers are cheap enough (one geometry) to serve per-request without caching.

---

## 06 · Earth Engine Blueprint

> **Architectural contract**
> All satellite/climate data access goes through one interface — `SatelliteDataProvider` — with methods framed in domain vocabulary (`get_index_time_series(geometry, index, start, end)`, `get_water_history(geometry)`), never in Earth Engine vocabulary. No `ee.Image` or `ee.FeatureCollection` object is allowed to cross this boundary. Business logic and the risk engine only ever see plain typed data. This is what makes "swap GEE for Sentinel Hub, Copernicus, or self-hosted processing later" a true statement rather than an aspiration.

- **Sentinel-2 workflow:** Image collection filtered by polygon + date range, cloud-masked via the QA band, indices computed per usable scene, composited per period to bridge monsoon cloud gaps.
- **Sentinel-1 SAR:** Interface method reserved (`get_sar_backscatter_series`) but unimplemented for MVP — flood exposure uses JRC history for now per your methodology call; SAR slots in later without touching callers.
- **Rainfall:** CHIRPS or ERA5-Land precipitation pulled over the polygon, compared against a long-term normal baseline for the SPI-style anomaly used in drought scoring.
- **Cloud masking:** Standard Sentinel-2 QA-band masking before any index runs. Exact probability threshold is an open domain parameter — see Section 11.
- **Time-series generation:** All indices composited on the same period boundaries so factor calculations line up on one shared time axis.
- **NDVI / MNDWI / NDMI:** Computed inside the adapter, returned as clean numeric series — never as raw Earth Engine objects.
- **Water indicators:** MNDWI (primary, surface water bodies) + NDMI (supporting, canopy moisture) + JRC Global Surface Water occurrence, combined by the adapter into the composite inputs the risk engine consumes.
- **Output objects:** A typed `SatelliteObservationBundle` that maps directly onto the `satellite_observation` table — the adapter's only job is to produce this, nothing else touches GEE.
- **Caching:** Persisted to `satellite_observation` keyed by entity + index + period, so a repeat report request never recomputes against GEE — this matters for cost the moment commercial GEE billing applies.
- **Future replacement:** Swapping providers means writing one new adapter class implementing the same interface — zero changes to the risk engine, API, or database schema.

---

## 07 · Risk Engine Blueprint

> **Confirmed methodology** — decided against the domain-expert review round; see your answers on water index, flood method, drought method, and aggregation.
>
> - **Water Availability** — MNDWI (primary, water-body presence) + NDMI (supporting, crop moisture stress), combined internally with rainfall and reserved for future SAR input, into one composite score. Sub-indices exposed only in the detailed technical view.
> - **Flood Exposure** — JRC Global Surface Water history (historical proneness) + recent rainfall anomaly. SAR-based event detection deferred, added later as a new input without changing the engine's contract.
> - **Drought Risk** — rainfall anomaly (SPI-style) combined with Vegetation Condition Index (NDVI vs. its own historical range) — meteorological signal plus observed crop impact, not either alone.
> - **Overall Climate Risk Score** — weighted average of the four normalized factor scores, with a floor rule: any single factor crossing its configured severe threshold forces the overall band to at least "High Risk," regardless of the average.

### Engine contract

The engine is a pure function with zero I/O: `compute(observation_bundle, config) → RiskResult`. It never calls the database or GEE directly — it receives data and configuration, returns scores. This is the single structural choice that makes "replace rules with ML later without redesigning the platform" actually achievable, because a future ML-backed engine can implement the identical contract and run in parallel with the rule engine for validation before any cutover.

- **Inputs:** An observation bundle (NDVI/MNDWI/NDMI/rainfall series, JRC water history) + the active `config_weight` row
- **Outputs:** Four factor scores (0–100 + band) plus one overall score, band, and confidence value
- **Confidence score:** Reflects data quality, not risk — e.g. how many cloud-free Sentinel-2 scenes were actually usable. A sparse-data farm is never shown with the same certainty as a well-observed one.
- **Explainability:** Every stored score ships with the raw inputs that produced it. The overall score always renders with its factor breakdown — never a bare number.
- **Versioning:** `model_version` + `weights_version_id` stamped on every row — enables direct rules-vs-ML comparison on identical farms later.
- **Weights & thresholds:** Both live in `config_weight`, never hard-coded — calibration by domain experts and historical loan performance happens by inserting a new config version, not a code change.

---

## 08 · Report Design

Structured to read the way SatSure, Pixxel, and Planet Labs enterprise deliverables read: verdict first, evidence underneath, provenance at the bottom — never a black-box number. Every section earns its place by making the report more trustworthy to the officer reading it under time pressure.

| Section | Why it exists |
|---|---|
| Executive summary | Farm identity, headline risk band, one-paragraph plain-language summary — a Branch Manager skimming a stack of files needs the verdict in ten seconds. |
| Farm information | Polygon area, village/taluka/district, officer of record, generation date — establishes provenance for anything entering a bank's file. |
| Satellite imagery | Most recent scene with the polygon overlaid — lets the officer sanity-check the report against what they actually know of the field. The fastest trust-builder in the whole document. |
| Three-year vegetation history | Directly answers the stated problem: banks currently can't see historical cultivation pattern at all. |
| Water availability | Composite score in plain language up front; MNDWI/NDMI/rainfall values available to officers who want to go deeper, in a technical appendix. |
| Drought & flood risk | Each factor shown with one line explaining what drove it — a rainfall anomaly, a historical flood-proneness figure — never just a label. |
| Overall Climate Risk Score | The composite band with a visible per-factor breakdown and confidence indicator — the explainable-AI requirement made concrete, not aspirational. |
| Recommendation | Low / Moderate / High / Very High, with the decision-support disclaimer printed on every report, not buried in a terms page: the lending decision belongs to the bank. |
| Data lineage footer | Satellite passes and dates used, data sources, model and weights version — answers "how was this number produced" without a support ticket, which any enterprise buyer and eventually a regulator will ask. |

Dashboard and PDF are rendered from the same report payload — they are two views of one artifact, never two systems that can quietly disagree.

---

## 09 · Dashboard Design

**Farmer Dashboard (Service 1).** Map with the polygon, NDVI/rainfall time-series charts with a date-range control, factor breakdown cards that expand into their underlying chart — the same content as the PDF, made explorable.

**Portfolio dashboards (Service 2).** A KPI row (total exposure, % high-risk, portfolio-wide trend) is always visible — summary before detail. District/branch/village choropleth maps use the identical risk-band palette as the farmer dashboard and PDF, so the product has one visual language throughout, not three. A sortable branch ranking table uses tabular figures so outstanding amounts actually line up in columns. Filters cover crop type, date range, risk band, and exposure threshold; a time slider compares portfolio risk as of a past date against now, so the dashboard shows trend, not just a snapshot.

**Drill-down path.** District KPI → branch ranking → village list → individual farmer report — the two services meet at this last step, which is deliberate: portfolio-level concern should always be able to resolve down to the actual evidence behind it.

**Role-specific views.** One dashboard, not five. Each role gets a different default scope and detail level on the same underlying data and permissions: a Credit Officer defaults to their own branch's village list with action items; a Branch Manager sees the full branch ranking; CEO and Chairman default to district-level KPIs and trend, with drill-down available but never required to reach the headline number.

---

## 10 · Development Roadmap

Seven milestones, sequential. Git convention throughout: Conventional Commits (`feat`/`fix`/`chore`/`test`/`docs`), one logical change per commit, every milestone merged via PR even working solo — keeps the history reviewable when a second engineer eventually joins.

### M0 — Foundations (~1–1.5 weeks)

- **Objective:** Stand up the schema, the GEE adapter skeleton, and boundary data — nothing demoable yet, everything else depends on it.
- **Deliverables:** Full PostGIS schema · GEE service-account auth + `SatelliteDataProvider` interface · Maharashtra/Latur admin boundaries loaded · `docs/DECISIONS.md` · broken `location.py` import fixed · minimal login
- **Testing:** Migrations run clean; GEE adapter smoke-test against one known polygon
- **Definition of done:** App boots; one authenticated user can log in; admin boundaries are queryable

### M1 — Service 1: backend core (~2 weeks)

- **Objective:** Polygon in, complete risk report out — no UI polish yet.
- **Deliverables:** Farm polygon CRUD · async report-generation job · Risk Engine v1 (rule-based, config-driven) · satellite_observation persistence · report JSON endpoint
- **Testing:** Unit tests for the risk engine (pure function) and job state transitions
- **Definition of done:** POST a polygon for a real Latur-area farm, trigger a report, poll the job, GET a complete report JSON

### M2 — Service 1: frontend (~2 weeks)

- **Objective:** The full officer-facing workflow, end to end.
- **Deliverables:** Village search · map + polygon draw · processing status screen · interactive dashboard · PDF export
- **Testing:** Manual QA of the full draw → report flow; PDF visually matches the dashboard
- **Definition of done:** An officer goes from login to a downloaded PDF for a real farm, unassisted

### M3 — Service 2: backend core (~2 weeks)

- **Objective:** Portfolio in, aggregated risk rollups out.
- **Deliverables:** CSV upload + validation · village→branch lookup with unmatched-row handling · synthetic portfolio dataset · aggregation job · role-scoped risk query endpoints
- **Testing:** Unit tests for aggregation math and lookup matching — the two areas most likely to be silently wrong
- **Definition of done:** Upload a synthetic CSV, get validated and aggregated rollups queryable by district/branch/village

### M4 — Service 2: frontend (~2–2.5 weeks)

- **Objective:** The full portfolio-monitoring workflow, all roles.
- **Deliverables:** District/branch/village dashboards · choropleth maps · ranking tables · filters · time slider · role-based report export
- **Testing:** Manual QA across all four role views
- **Definition of done:** A Chairman-role login sees district KPIs and can drill to one individual farm report

### M5 — Pilot hardening (~1–1.5 weeks)

- **Objective:** Close the gaps a real bank stakeholder would notice.
- **Deliverables:** PII-separation audit · CSV edge cases · geometry simplification tuning · minimal CI (lint + unit tests) · confidence-score display · data lineage footer
- **Testing:** CI green on lint + the M1/M3 unit tests
- **Definition of done:** Platform is presentable to DCCB Latur without an embarrassing gap

### M6 — DCCB Latur pilot (~1 week + ongoing)

- **Objective:** First contact with a real bank officer, on real Latur farms.
- **Deliverables:** Real Latur boundary data in place of any placeholder · 2–3 real officer accounts onboarded · a handful of real farms walked end to end
- **Definition of done:** First real pilot session completed and feedback captured

---

## 11 · Open Domain Questions

Secondary methodology parameters, deliberately deferred rather than guessed — none of them block Phase 0, but all of them need your sign-off before Milestone M1's risk engine is coded.

> **Needs domain input before M1**
> - Cloud-masking probability threshold for Sentinel-2 scene inclusion
> - Compositing window length for bridging monsoon-season cloud gaps
> - SAR polarization / orbit-pass selection — relevant once Sentinel-1 flood detection is added post-MVP
> - Source and definition of the rainfall "long-term normal" baseline (e.g. IMD 1981–2010 normals vs. the chosen rainfall product's own available history)
> - Exact severe-threshold values that trigger the overall-score floor rule, per factor
> - Confidence-score formula — what specifically counts as "low confidence" (minimum usable scene count, data-gap tolerance)
