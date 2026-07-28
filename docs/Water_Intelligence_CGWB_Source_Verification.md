# CGWB Source Verification — Research Spike (Ticket M3-002)

**Status:** Research/documentation only. No code, schema, or API was changed by this ticket — see the Decision Log's final entry for the one place a genuine defensible exception was needed to verify a claim.
**Scope:** Verify the real Central Ground Water Board (CGWB) data source before M3-003 (`cgwb_ingest.py`) is implemented, per the Implementation Plan's own explicit gate: *"M3-003 cannot start until this ticket produces a concrete, verified data-access mechanism — do not let M3-003 begin against an assumed/guessed API shape."*
**Method:** Live web research (search + page fetch) conducted during this ticket, not recalled from training data. Every claim below is tagged **[VERIFIED]** (confirmed via a live source fetched during this ticket, cited), **[CORROBORATED]** (matches across ≥2 independent live sources), or **[UNCONFIRMED]** (could not be verified live — stated as an open question, not guessed at).
**What this spike could NOT do:** fully render two of the four candidate platforms (India-WRIS's "Water Data Online" and IN-GRES), because both are JavaScript-rendered single-page applications and this ticket's fetch tooling only retrieves static HTML/PDF content. This is disclosed explicitly in the Unknowns section, not worked around by guessing at their API shape.

---

## 1. Official Data Source

**[VERIFIED]** The correct official agency is the **Central Ground Water Board (CGWB)**, under the Ministry of Jal Shakti, Department of Water Resources — this matches Blueprint v2's existing assumption and needed no correction.

**[VERIFIED] The periodic block-category assessment is a JOINT exercise, not CGWB alone.** For Maharashtra specifically (DCCB Latur's home state), the "Ground Water Resource Estimation" (GWRE) is carried out jointly by **CGWB, Nagpur** and the **Ground Water Surveys & Development Agency (GSDA), Pune** — a Maharashtra state government agency — using the **GEC-2015 methodology** (Ground Water Estimation Committee, 2015). This is a real, named, citable methodology, not the generic "SCS-CN-style" assumption Blueprint's Sources section makes for hydrology; it should be cited by its own name in any future methodology text. Source: GSDA's own published report, "GWRE-State-Report-2022-23" (gsda.maharashtra.gov.in).

**[VERIFIED] A Latur-district-specific document exists directly on cgwb.gov.in** — confirmed via live search (an 8.11 MB district-level file referenced on CGWB's Maharashtra page, cgwb.gov.in/index.php/en/node/1746). This directly confirms real coverage of DCCB Latur's target geography, not just a national-level abstraction.

**[VERIFIED] There is no single distribution mechanism — there are at least four, materially different ones**, none of which Blueprint v2 previously distinguished:

| Channel | What it is | Format | Confirmed live |
|---|---|---|---|
| **CGWB "Publications and Media Warehouse"** (`cgwb.gov.in/cgwbpnm/`) | State/district-wise assessment reports, the primary channel CGWB itself links to | **PDF documents** (e.g. "REPORT ON DYNAMIC GROUND WATER RESOURCES OF KARNATAKA 2024", "DYNAMIC GROUND WATER RESOURCES OF ANDHRA PRADESH STATE 2024") | Yes — multiple real PDF URLs found for multiple states and for Maharashtra/Latur specifically |
| **India-WRIS / "Water Data Online"** (`wdo.indiawris.gov.in`), run by the National Water Informatics Centre (NWIC) | A dedicated data-download sub-portal, described in NWIC's own material as offering "download of data... in the form of excel reports and graphs" for CGWB ground-water data specifically | Excel-style downloads (per NWIC's own description) | Partially — platform's existence and stated purpose confirmed; **could not render its actual data/API screens** (JS-rendered app) |
| **data.gov.in (Open Government Data Platform India)** | Hosts CGWB-sourced datasets, but organized as **state-level sub-portals** (e.g. `kerala.data.gov.in`, `punjab.data.gov.in`, `tn.data.gov.in`), not one national file | Varies by resource (typically CSV/XLS); the platform has a documented REST API (`api.data.gov.in`, API-key based) — a third-party Python wrapper (`datagovindia` on PyPI) exists, evidence of real-world programmatic use | Partially — dataset listings and platform-level licensing confirmed; **the specific field schema/API resource ID for a Maharashtra CGWB category dataset was not confirmed** (only Kerala/Punjab/TN state-portal examples were found) |
| **IN-GRES** (`ingres.iith.ac.in`) — CGWB + IIT-Hyderabad | The newest (as of ~2023-2024) standardized national GIS platform, described as the current system of record for computing and disseminating the Safe/Semi-Critical/Critical/Over-Exploited/Saline categorization | Unknown — likely a web map viewer at minimum | **Not confirmed** — JS-rendered app, could not inspect for API/download capability |

**Update frequency [CORROBORATED, and a correction to Blueprint's prior assumption]:** Blueprint v2's Sources table states CGWB data is available "quarterly since 1969." Live research shows this conflates two different things:
- Raw **water-level monitoring** (the piezometer readings CGWB's ~23,125 observation wells collect) genuinely is measured **four times a year** (January, March/April/May, August, November) — confirmed via the India-WRIS wiki.
- The **Safe/Semi-Critical/Critical/Over-Exploited/Saline category assessment** (the actual number `CgwbGroundwaterObservation.category` needs) is a **separate, much less frequent exercise** — recent published reports are dated 2022-23, 2023, and 2024, consistent with an annual-or-slower cadence in recent years, not quarterly. `assessment_period` should be expected to change roughly once a year, not once a quarter — this affects the ingestion job's realistic polling/scheduling cadence (M3-004).

**Licensing [VERIFIED]:** data.gov.in states its published content is "licensed under the Government Open Data License – India" (GODL-India), a standard Indian government open-data license permitting reuse with attribution. CGWB's own PDF warehouse and India-WRIS did not show an explicit license statement in what could be fetched — **treat CGWB's own PDF publications' licensing as unconfirmed** pending a direct check of a report's own front matter (most Indian government technical reports carry the same GODL-India or an equivalent "freely available for reference and educational use" notice, but this specific text was not found live during this spike).

---

## 2. Dataset Structure

**[VERIFIED] Spatial/assessment unit:** Administrative **Block / Taluka / Mandal / District** — matches `CgwbGroundwaterObservation.block_code`'s intended grain exactly, confirmed via the India-WRIS wiki's own language ("5723 assessed administrative units (Blocks/Talukas/Mandals/Districts)"). Some states assess at a finer sub-unit (Andhra Pradesh assesses "within Mandal – command and non-command-wise") — the schema's plain-string `block_code` already accommodates this variation without a schema change.

**[VERIFIED] Category values: FIVE, not four.** Blueprint v2 lists Safe/Semi-Critical/Critical/Over-Exploited. Live research found a fifth, real category: **Saline** ("assessment units with predominantly saline ground water are categorized as 'saline'"). `CgwbGroundwaterObservation.category` is already a plain `String(64)`, not a Postgres enum (a deliberate M0-006 decision, "external government vocabulary, not a value this schema defines") — **no schema change is needed** to accommodate this; it's flagged here so a future methodology-text ticket doesn't silently drop Saline as an unhandled band, and so RechargeStressScore's `cgwb_category` context field is documented as accepting five real values, not four.

**[VERIFIED] Temporal resolution:** Assessment periods published as whole-year labels (e.g. "2022-23", "2023", "2024") — matches `assessment_period: String(32)` (deliberately not a `Date` per M0-006's own docstring, "CGWB's published period granularity isn't always a clean calendar year"). This design decision is confirmed correct by live research, not just anticipated.

**[VERIFIED] Attributes beyond category:** the underlying assessment also reports Annual Ground Water Recharge, Annual Extractable Ground Water Resource, Total Annual Extraction, and Stage of Extraction (%) per unit — richer than just the category label. `CgwbGroundwaterObservation` does not currently carry these numeric fields (only `category`), which is consistent with Blueprint's own stated MVP scope (category as context only, never blended numerically) — **not a gap**, a deliberate scope boundary already correctly reflected in the schema.

**[UNCONFIRMED] Unique identifier scheme:** whether CGWB/IN-GRES publishes a stable, government-standard code (e.g. an LGD — Local Government Directory — code) per assessment unit, or only a free-text block/taluka name, could not be confirmed live (this level of schema detail lives inside the JS-rendered IN-GRES/WDO apps this spike's tooling could not inspect). This is the single most consequential unknown for M3-003 — see Matching Strategy below and the Unknowns section.

---

## 3. Access Method

**Not an API in the conventional REST/JSON sense for CGWB's own primary channel.** CGWB's own "Publications and Media Warehouse" is a **document repository of PDF reports** — the authoritative, most-directly-CGWB-branded source is not machine-readable without PDF table extraction (fragile: multi-column tables, inconsistent formatting across state reports from different CGWB regional offices, as seen even in this research: Maharashtra's report is co-branded and hosted on a *different* domain — `gsda.maharashtra.gov.in` — from CGWB's own).

**A genuine downloadable/API path likely exists, but through NWIC's India-WRIS platform, not CGWB directly** — India-WRIS's "Water Data Online" sub-portal is explicitly described (by NWIC's own published material) as providing free download of CGWB ground-water data in Excel format. This is the most promising candidate for a real, structured (non-PDF) data source, but **its actual URL structure, required registration/API key, and response schema were not confirmed live** — this spike's fetch tooling could not render the JS application. Manual/interactive browser inspection (or a direct developer/API-documentation request to NWIC) is the concrete next step, not something to guess at.

**data.gov.in is a real, documented API but its CGWB coverage is fragmented by state**, and no Maharashtra-specific resource was located during this spike (only Kerala/Punjab/Tamil Nadu examples surfaced). A Maharashtra-specific search on data.gov.in itself (not via general web search) is a concrete, cheap next step before assuming this channel is unavailable.

**Recommendation for this axis:** do not assume any single channel. **Manual publication (PDF) must be treated as the fallback of record** — CGWB's own primary channel is a PDF warehouse — while India-WRIS's Water Data Online is the leading candidate for a structured alternative, pending direct interactive verification.

---

## 4. Matching Strategy — how CGWB observations should be associated with catchments

**Key finding, not previously known to this codebase's design discussion:** `AdminBoundary` (`app/models/admin.py`, already built and populated in M0) is a state → district → taluka → village hierarchy that already carries an **`lgd_code`** field (India's national Local Government Directory code — the pan-government standard identifier system for administrative units, maintained by the Ministry of Panchayati Raj) **and real geometry** (`MULTIPOLYGON`, plus a simplified copy for map rendering).

This directly changes the matching strategy from "wait for CGWB to publish its own boundary shapefiles" to a strategy this codebase can likely execute today:

1. **Primary match: LGD code**, if CGWB/IN-GRES publishes one per assessment unit (unconfirmed — see Unknowns). LGD codes are the pan-government standard specifically designed to solve the "duplicate names across different districts" problem — the same problem `VillageBranchLookup`'s own docstring already names ("duplicate village names across talukas are a real problem in Indian administrative data").
2. **Fallback match: name + parent-hierarchy**, mirroring `VillageBranchLookup`'s own already-established, already-shipped discipline in this exact codebase — never match a CGWB block/taluka name against `AdminBoundary.name` alone; always match on the full (state, district, taluka) tuple, exactly the pattern already proven for village→branch lookups.
3. **`block_geometry` does not need to wait for CGWB to publish its own boundaries.** Once a CGWB block is matched to an `AdminBoundary` row (by LGD code or by name+hierarchy), `CgwbGroundwaterObservation.block_geometry` can be populated by copying the matched `AdminBoundary.geometry` at ingestion time — resolving the "nullable until a boundary source is confirmed" note already in `CgwbGroundwaterObservation`'s own docstring (M0-006), without needing a new geometry source at all.
4. **Catchment-to-block association at score-computation time (M3, unchanged from the existing design):** `CgwbGroundwaterObservation` deliberately has no FK to `catchment` (a catchment can span, or sit inside, one CGWB block) — the actual association remains a spatial join (`ST_Intersects`/`ST_Within` against the now-populated `block_geometry`) performed when `RechargeStressScore.cgwb_category` is populated, not a stored relationship. This part of the design needed no correction.

---

## 5. Data Quality

**[CORROBORATED] Missing values are expected, not exceptional.** Assessment coverage varies meaningfully by state and year (some states, e.g. Andhra Pradesh, use finer sub-unit assessment; others report at pure block level) — a national ingestion job should expect gaps in coverage for any given `(block_code, assessment_period)` pair, not assume uniform national coverage.

**[CORROBORATED] Update delay is real and likely multi-month-to-multi-year.** Comparing published report dates found during this spike (Maharashtra's own state report labeled "2022-23", national reports labeled "2023" and "2024" found in mid-2025-dated searches) suggests a real-world publication lag of at least several months to a year between an assessment's reference period and its public release — `cgwb_ingest.py` (M3-003) should not assume the "current year" is ever actually available; the ingestion job should query for and accept whatever the latest genuinely published `assessment_period` is, not compute an expected one from today's date.

**[VERIFIED] Known methodological limitation, worth carrying into the report methodology text later:** GEC-2015 (the assessment methodology itself) is a real, published, peer-reviewed-adjacent government methodology — but it operates at block/taluka scale, materially coarser than a catchment. This is already correctly reflected in Blueprint v2's own repeated, explicit statement that CGWB context is "block-scale... never blended numerically" and is shown only as context — this spike found nothing that weakens that existing design decision; if anything, discovering the joint CGWB+state-agency, block/taluka-scale methodology (GEC-2015) reinforces why numeric blending would be scientifically inappropriate at catchment scale.

---

## Architecture Recommendation

1. **Do not build a single generic "CGWB API client."** Build `cgwb_ingest.py` (M3-003) against **one specific, concretely-verified channel** — recommend India-WRIS's Water Data Online as the first candidate to verify interactively (highest chance of structured, non-PDF data), with CGWB's own PDF warehouse as the documented fallback (requiring a PDF-table-extraction step, e.g. `pdfplumber` or similar — a real, if unglamorous, additional dependency this plan should name explicitly if that fallback becomes necessary).
2. **Scope M3-003 to Maharashtra first**, not all-India — DCCB Latur is the only confirmed customer, a Latur-district-specific CGWB document already exists, and this avoids solving the "which of 4 channels, which format, for all 36 states/UTs" problem before it's needed.
3. **Reuse `AdminBoundary`/`lgd_code` for matching**, per Section 4 above — this is new information this spike surfaces, not something the original M0-006 schema design anticipated, and it meaningfully de-risks the "how do we get `block_geometry`" open question already named in that model's own docstring.
4. **Treat `assessment_period`'s cadence as annual-or-slower, not quarterly**, when M3-004 designs the external cron trigger's schedule.

## Proposed Ingestion Strategy (for M3-003 to execute against, not implemented here)

1. Interactively verify `wdo.indiawris.gov.in`'s actual data-request mechanism (a manual browser session, or a direct request to NWIC for API documentation) — the single highest-value next step, since it's the only candidate channel offering structured (non-PDF) data with a stated free-download policy.
2. If that channel proves usable: parse its Excel/CSV export directly — no PDF extraction needed.
3. If it proves unusable (no real API, registration barrier, or the export doesn't cover block-level category data): fall back to CGWB's own Maharashtra/Latur PDF report(s) via a PDF-table-extraction step, scoped to Maharashtra only for M3-003's first cut.
4. Either way: resolve each ingested block to an `AdminBoundary` row via LGD code (if present in the source) or name+hierarchy matching (fallback, mirroring `VillageBranchLookup`), and populate `block_geometry` from the matched boundary.
5. Idempotent upsert keyed on `(block_code, assessment_period)` — already guaranteed by the existing `uq_cgwb_block_period` constraint; no schema change needed for this ticket's findings.

## Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | India-WRIS's Water Data Online turns out to require a registration/API-key process with unknown approval time | Medium | Medium — delays M3-003's start | Verify interactively as the very first step of M3-003, before writing any ingestion code, exactly as this spike's own gating purpose intends |
| 2 | No channel provides a stable per-block identifier (LGD code or equivalent) — forcing 100% reliance on fuzzy name matching against `AdminBoundary` | Medium | Medium — degrades match accuracy, needs manual review of ambiguous matches | `VillageBranchLookup`'s existing full-tuple-match discipline already handles this class of problem; budget explicit time in M3-003 for a manual review pass of unmatched/ambiguous blocks, not an assumed 100% automatic match rate |
| 3 | CGWB's own PDF reports become the only real fallback, requiring PDF table extraction — a genuinely fragile dependency (layout varies by state/regional office, as directly observed: Maharashtra's report is hosted on a different domain than CGWB's own national warehouse) | Medium-High | Medium | Scope M3-003 to Maharashtra's specific report format only first; do not build a generic all-India PDF parser speculatively |
| 4 | The `category` assessment's real update cadence (annual-or-slower) means a "quarterly" ingestion job would poll for months finding nothing new | Low (now that this is known) | Low | M3-004's trigger cadence should match the assessment's real cadence, not the water-level-monitoring cadence — already corrected in this report |

## Unknowns (explicitly not guessed at)

1. **Exact API/download schema for India-WRIS's Water Data Online** (`wdo.indiawris.gov.in`) — JS-rendered, not inspectable by this spike's tooling. Requires interactive browser verification or direct NWIC contact.
2. **Whether IN-GRES (`ingres.iith.ac.in`) exposes any programmatic access** — same limitation.
3. **Whether Maharashtra has its own data.gov.in state sub-portal** with a CGWB category dataset (only Kerala/Punjab/Tamil Nadu examples were found; a Maharashtra-specific search was not exhaustively completed within this spike's time-box).
4. **Whether CGWB/India-WRIS publishes a stable per-block identifier code** (LGD or otherwise) alongside the category label, or only a free-text name — the single most consequential unknown for the matching strategy's accuracy.
5. **CGWB's own PDF reports' explicit reuse license** — data.gov.in's GODL-India license was confirmed for datasets hosted there; CGWB's own directly-published PDFs did not show an explicit license statement in what this spike could fetch.

## Decision Log

| Decision | Rationale |
|---|---|
| Treat CGWB's own PDF warehouse as the fallback of record, not the primary target | It is confirmed real and accessible today, but not structured — building against it first would be building against the worst-case channel by default |
| Recommend India-WRIS Water Data Online as the first channel to verify interactively in M3-003 | The only candidate with a stated (if unconfirmed in detail) free, structured Excel-download policy specifically for CGWB ground-water data |
| Recommend scoping M3-003 to Maharashtra only, not all-India | DCCB Latur is the only confirmed customer; a Latur-specific document is confirmed to exist; this avoids solving a 36-state problem before it's needed |
| Recommend `AdminBoundary`/`lgd_code` + name-hierarchy matching over waiting for CGWB-published boundaries | `AdminBoundary` already exists, is already populated, and already carries the exact fields (LGD code, geometry) this matching problem needs — a genuinely new finding from this spike, not something the original M0-006 schema anticipated |
| Corrected "quarterly" to "annual-or-slower" for the category assessment's own cadence (water-level monitoring itself remains genuinely quarterly) | Directly affects M3-004's trigger design; leaving Blueprint's original framing uncorrected would have led M3-004 to poll on the wrong cadence |
| Did not attempt to render India-WRIS/IN-GRES's JavaScript applications via any workaround (e.g. headless-browser automation) within this ticket | Out of scope for a documentation-only research spike; flagged as the top unknown for M3-003's own first step instead of extending this ticket's scope to solve it |
