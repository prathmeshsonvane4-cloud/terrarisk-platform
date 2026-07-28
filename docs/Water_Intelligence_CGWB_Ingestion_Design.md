# CGWB Ingestion Design & Source Validation (Ticket M3-003)

**Status:** Follows the M3-002 research spike ([Water_Intelligence_CGWB_Source_Verification.md](Water_Intelligence_CGWB_Source_Verification.md)). This ticket converts that research into an interactively-verified architecture and a scoped implementation.
**Scope note:** everything below is written to be reusable for **any** Indian state — no customer, deployment geography, or sector-specific assumption is encoded anywhere in this document or the code it produced.
**Method:** live, interactive browser inspection of all four candidate channels conducted during this ticket (navigating real pages, reading rendered DOM state, and inspecting real network requests/responses) — not a repeat of M3-002's static-fetch research. Every claim is tagged **[VERIFIED]** (directly observed in a live interactive session this ticket), or **[UNCONFIRMED]** (attempted, but blocked — stated honestly, not guessed at).

---

## Step 1 — Interactive Source Inspection

### India-WRIS ("Water Data Online" / `indiawris.gov.in`)

**[VERIFIED]** The main portal (`indiawris.gov.in`) exposes a full navigation structure without authentication, including a direct **"Ground Water Resource Estimation"** viewer (`#/GWResources`) and a menu entry for an **"API Catalog"** — confirming an API surface exists somewhere on this platform, not assumed.

**[VERIFIED]** The Ground Water Resource Estimation viewer, once loaded, exposes real interactive controls: an assessment-year selector (**2011, 2013, 2017, 2020** — notably *not* any more recent year), a component selector (Ground Water Draft / Net Ground Water Availability), a state selector, and a **"Download Data"** button.

**[VERIFIED]** Clicking **"Download Data"** triggers a **SIGN IN requirement** — the button does not produce a file or an API response without an authenticated session. A separate, lighter-weight **"state your purpose of downloading this data"** dialog (asking only for name, email, and purpose — not a full account) was also observed elsewhere on the portal, suggesting two different gating tiers exist across the platform, but the specific Ground Water Resource Estimation viewer's download path led to the full SIGN IN form, not the lighter dialog.

**[VERIFIED]** No REST/JSON API call was observed in the network log for this viewer during this session — every captured request was a static asset (JS bundle, images) or a map-tile `blob:` URL. The state dropdown's actual option list did not populate in the accessibility tree either, consistent with it being populated only after an interaction this session could not complete past the sign-in gate.

**[UNCONFIRMED, and explicitly not worked around]** The exact API Catalog documentation and the "Water Data Online" (`wdo.indiawris.gov.in`) sub-portal specifically were not reachable in this session — the `wdo.` subdomain was denied by this environment's navigation policy, and the main portal's own API Catalog route consistently redirected to the same SIGN IN gate on every attempt. **Per this environment's standing rules, creating an account or entering credentials to get past this gate is out of scope for an automated research ticket** — this is the correct stopping point, not a gap to route around.

### CGWB's own publication channel (`cgwb.gov.in`)

**[VERIFIED, carried forward from M3-002, re-confirmed]** CGWB's own "Publications and Media Warehouse" distributes state/district-level assessment results as **PDF reports** — not a queryable API or a structured bulk-download file. This was not re-verified interactively in this ticket (M3-002 already fetched and confirmed real report URLs); it is restated here because it remains the fallback of record for whichever geography's structured channels prove unusable.

### data.gov.in (Open Government Data Platform India)

**[VERIFIED] A genuine, working, national-scope dataset exists**, not state-fragmented: *"Category-wise Details of Annual Ground Water Recharge, Extraction and Stage of Ground Water Extraction (SoE) Jal Shakti Abhiyan (JSA) in the Country from 2020 to 2024"*, published by Rajya Sabha (the answer to a Parliamentary question), listed with a live **"Data API"** option (17 recorded API hits at time of inspection — i.e., genuinely in active use, not a dead listing).

**[VERIFIED] Its real resource metadata page was opened and read directly.** Result: this specific dataset is **413 bytes**, with exactly five fields — `Sl. No.`, `Parameter`, and one column per assessment year (2022/2023/2024) — a **national-aggregate summary table**, not block/district-level data. `Sourced Webservices/APIs: NA` confirms it has no live upstream feed of its own; it is a one-time transcription of a Parliamentary answer. **This specific dataset is not suitable for `block_code`-level ingestion** — a concrete, verified disqualification, not an assumption.

**[VERIFIED] The platform's REST API mechanism itself is real and was exercised directly.** A live network request was captured and independently confirmed to succeed:
```
GET https://www.data.gov.in/backend/dataapi/v1/resource/{resource_id}?format=json&api-key={key}
→ HTTP 200, JSON body
```
Requesting the same endpoint without an `api-key` returns **HTTP 400** — confirming a key is required, not optional. The successful response's JSON envelope shape was directly observed:
```json
{
  "index_name": "...", "title": "...", "org_type": "...", "org": ["..."],
  "field": [{"name": "...", "id": "...", "type": "keyword"}, ...],
  "field_exposed": [{"name": "...", "id": "...", "type": "keyword", "mandatory": true}, ...],
  "total": 0, "count": 0, "limit": "0", "offset": "0",
  "status": "ok",
  "records": [ {"<field_id>": "<value>", ...}, ... ]
}
```
This envelope shape is **confirmed real** (observed on a live, successful response) — it is the one piece of this entire investigation that is fully verified independent of which specific CGWB dataset is eventually chosen, and is what Step 3's code below is built against.

**[UNCONFIRMED]** The `resource_id` for a genuine **block/district-level** CGWB category-and-SoE dataset (as opposed to the tiny national-aggregate one, or the state-level "State/UT-wise Ground Water Resources of India" listings also seen but not opened) was not conclusively identified in this session. This is the single most consequential open item carried into "Unknowns" below.

### IN-GRES (`ingres.iith.ac.in`)

**[VERIFIED] This platform rendered successfully in this session** (M3-002's static fetch could not render it; this ticket's interactive browser could). Its own "GEC-Overview" page was read directly and yields the most substantive, authoritative content found across all four channels:

- **The exact Stage-of-Extraction (SoE) categorization thresholds**, stated verbatim: *"'Safe' if SoE < 70%; 'Semi-critical' if SoE > 70 and <= 90%; 'Critical' if SoE > 90 and <= 100%; 'Over-exploited' if SoE > 100%."* This is a genuinely new, precise, previously-unavailable-to-this-project fact — not previously stated anywhere in Blueprint v2 or the M3-002 report.
- IN-GRES explicitly states it provides data **"India, State/UT, District, Assessment Units-wise"** — i.e., it claims assessment-unit (block/taluk/mandal) granularity, the exact level this schema's `block_code` needs.
- The methodology is confirmed as **GEC-2015** (Ground Water Resource Estimation Committee, 2015), jointly run by CGWB and State/UT Ground Water Departments.
- A real backend API namespace was directly observed in the network log: `GET https://ingres.iith.ac.in/api/gec/getGECVisitCount → 200 OK`. This single endpoint is only a visit counter, but it **confirms IN-GRES has a genuine server-side API**, not a purely static frontend — a materially different (and more promising) finding than M3-002's earlier "could not confirm" status for this platform.
- Data values are broken into three components — Command (C), Non-Command (NC), and Poor Water Quality (PQ) — with the "dynamic ground water resources" figure (and categorization) defined as the sum of C+NC, *excluding* PQ (saline). This explains, precisely, why "Saline" is a separate flag rather than a SoE-percentage-driven category.

**[UNCONFIRMED]** No data-returning endpoint (as opposed to the visit-counter one) was identified — the dashboard content behind the "About" page was not reachable via the single navigation control available on that page within this session.

---

## Step 2 — Ingestion Design

**Source priority** (revised from M3-002's ordering, now with interactive confirmation behind it):
1. **data.gov.in's REST API**, once the correct block/district-level `resource_id` is identified by a human with portal access (the API mechanism itself is fully verified; only the specific resource selection is not) — the only channel with a confirmed, working, no-login structured API response observed directly in this ticket.
2. **IN-GRES's `/api/gec/*` namespace**, pending discovery of its actual data-returning endpoints (confirmed to exist as a real backend, not yet mapped past the visit-counter call) — the most promising channel for genuine assessment-unit-level granularity, per its own "About" page's explicit claim.
3. **India-WRIS**, deprioritized: its download path is confirmed to require authentication this ticket correctly did not attempt to bypass.
4. **CGWB's own PDF warehouse**, the fallback of record — confirmed real and accessible, but requires PDF table extraction, the least structured option.

**Refresh frequency:** per M3-002's finding, the category/SoE assessment itself is published annually-or-slower (not quarterly); an ingestion job should poll on a monthly-or-slower cadence and treat "nothing new since last run" as the expected, common case, not an error.

**Identifier strategy:** unchanged from M3-002's recommendation — match ingested records to `AdminBoundary` by LGD code where the source provides one, falling back to name + parent-hierarchy matching (state → district → sub-district), mirroring this codebase's existing `VillageBranchLookup` discipline of never matching administrative names alone.

**Parsing approach:** build against the **verified data.gov.in JSON envelope** (`field` / `records` / metadata keys) generically — accept a configurable field-name mapping rather than hardcoding assumed CGWB field names, since the exact field names for a genuine block-level resource were not confirmed. This keeps the parser correct for whichever specific `resource_id` a human ultimately confirms, without silently assuming a schema this ticket could not verify.

**Error handling:** distinguish (a) transport failures (timeout, connection error) — retryable; (b) HTTP error responses (4xx/5xx) — not retried automatically (a 400 without an API key is a configuration error, not a transient fault); (c) malformed individual records (missing a required mapped field) — skipped and logged individually, never crashing the whole batch, mirroring this codebase's established "persist what's known" resilience philosophy already used throughout the hydrology engines.

**Retry strategy:** a small, bounded number of retries (3) with exponential backoff, applied only to transport-level failures — no unbounded retry loop, no retry on 4xx client errors (retrying a bad API key or malformed request would never succeed).

**Logging:** `logging.getLogger(__name__)`, structured `extra={}` dicts on every fetch attempt, retry, and per-record parse failure — the same convention already established across every hydrology engine and provider in this codebase.

**Metadata captured:** the envelope's own `title`, `total`, `count`, `limit`, `offset`, and `updated_date` (via `created`/`updated` epoch fields observed in the real response) are extracted alongside parsed records — giving a future ingestion job the information it needs to detect pagination and staleness without re-deriving it.

---

## Step 3 — Implementation

**Source format is verified for the download/parse mechanics** (the data.gov.in JSON envelope), **not verified for the exact block-level resource/field mapping.** Per the ticket's own conditional instruction, implementation proceeds scoped exactly to what's verified: a download abstraction and parser generic enough to be correct against any data.gov.in resource once a human supplies the confirmed `resource_id` and field mapping — nothing CGWB-specific is hardcoded or guessed. Persistence is explicitly left for a later ticket, per Step 3's own instruction.
