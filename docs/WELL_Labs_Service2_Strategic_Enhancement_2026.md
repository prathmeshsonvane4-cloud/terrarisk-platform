# TerraRisk Water Intelligence × WELL Labs — Strategic Enhancement Report

**Date:** 30 July 2026
**Scope:** Research (WELL Labs, Raichur, Latur) → Select Area architecture → Founder-level critique → Roadmap → Phase 1 implementation
**Evidence tiers:** **[S]** = sourced (link in that section or the closing bibliography), **[E]** = estimate/inference, **[D]** = a design decision made in this document, not a public fact.

## How this document relates to existing files in `docs/`

This repo already contains substantial, cited, adversarially-validated research on WELL Labs and on TerraRisk's own strategic options, written 26 July 2026 (four days before this document, uncommitted, produced in sessions not visible to this one):

- [`WELL_Labs_Digital_Vertical_Proposal.md`](WELL_Labs_Digital_Vertical_Proposal.md) — WELL Labs org profile, 20 scored service ideas, "WaterTwin" recommendation.
- [`WELL_Labs_Internship_Project_Plan.md`](WELL_Labs_Internship_Project_Plan.md) — a public-data-only version of the same, scoped as a 2-week deliverable.
- [`Problem_Discovery_2026.md`](Problem_Discovery_2026.md) — 50-problem farmer discovery, Marathwada/Latur-anchored, water-specific findings in Part 5/6/7.
- [`Nuksan_Praman_Validation.md`](Nuksan_Praman_Validation.md) — kills a previously-recommended crop-damage-evidence product on evidence.
- [`TerraRisk_Dhoran_Punarvichar_2026.md`](TerraRisk_Dhoran_Punarvichar_2026.md) — Marathi board report proposing a "Water Impact Verification" identity pivot.

Per an explicit decision on this engagement, **Parts 1–2 below build directly on that existing research** rather than re-deriving it from scratch — findings are re-cited to their original sources, not re-invented. Parts 3–6 are new work for this engagement (Latur, the Select Area architecture, the Founder Review, and the roadmap were not covered by the existing docs).

---

# Part 1 — What WELL Labs is solving (public evidence only)

## Identity

WELL Labs (Water, Environment, Land and Livelihoods) is an autonomous research centre inside the IFMR Society, Bengaluru, founded **April 2023** by **Dr. Veena Srinivasan**, a water-systems scientist **[S: [About Us](https://welllabs.org/about-well-labs/), [The Org](https://theorg.com/org/water-environment-land-and-livelihoods-well-labs)]**. Revenue is CSR/philanthropy/FCRA-funded, not commercial **[S: WELL_Labs_Digital_Vertical_Proposal.md]**.

## Current workflow

- **Urban Water programme**: a water-balance framework published as static reports (Bengaluru, Chintamani), which WELL Labs is *manually* "codifying into a Python model and web tool" **[S]** — i.e. this is presently a research-engineering bottleneck, not a shipped product.
- **Rural Futures programme** (Raichur + Chikkaballapur): the single most important fact in the existing research — the **Raichur Transformation Lab covers ~5,500 km²**, but ground-instrumented monitoring is a **~50 km² pilot (Distributary 10)** with **191 identified wells and only 4 loggers installed**; everything else is **community hydrologists manually reading canal/stream gauges** **[S]**. In Chikkaballapur, WELL Labs is manually classifying abandoned vs. working borewells **[S]**.
- **Remote sensing is partnered, not owned**: a 2023–2027 collaboration with **IHE Delft** and Karnataka's **ACIWRM** (Advanced Centre for Integrated Water Resources Management) to build community-facing remote-sensing applications in the Krishna basin, using LULC maps to compute **village-level water accounts** **[S: [WELL Labs × IHE Delft/ACIWRM](https://welllabs.org/well-labs-partnership-ihe-delft-aciwrm-water-remote-sensing-data/)]**.
- **Framework**: the Raichur Transformation Lab operates on a "**Five Levers**" systems-transformation model — irrigation infrastructure, community institutions/knowledge systems, labour & mechanisation, agricultural inputs, and market access — chosen because fragmented, single-lever interventions (canal infra without equitable distribution, watershed works without productivity gains) reproduce inequity **[S: [Why Raichur Needs Systems Transformation](https://welllabs.org/five-levers-systems-transformation-in-raichur/)]**.

## Technologies they appear to use

Remote sensing / LULC via the IHE Delft/ACIWRM partnership (not confirmed in-house), a Python water-balance model (Urban Water, being converted to a web tool), physical loggers and manual gauge-reading for rural hydrology, GSDA-style well inventories. **No public GitHub, open-source repository, or productised dashboard was found** in either this session's search or the prior session's — confirmed absence, not an oversight (searched explicitly; see Part 1 research log below).

## Strengths

Deep hydrology/science credibility (Dr. Srinivasan's background), genuine field trust built through a community-hydrologist network, a coherent systems-transformation framework already tested with farmers in Raichur, and real institutional relationships (ACIWRM, BWSSB, BBMP, Karnataka government, IHE Delft) **[S]**.

## Weaknesses (evidenced)

1. **Ground instrumentation covers roughly 1% of their own stated target area** (4 loggers / 191 wells against 5,500 km²) **[S]** — a scaling wall they have themselves published.
2. **Remote-sensing capability is borrowed, not owned** — the IHE Delft/ACIWRM partnership exists precisely because WELL Labs does not yet run this in-house **[S]**.
3. **The urban water-balance tool is stuck in manual "codification"** — an engineering resourcing gap, not a science gap **[S]**.
4. **No public GitHub, API, or self-serve dashboard product was found** — every published artefact located in this research is a static PDF report or blog post, not interactive software.

## Opportunities TerraRisk can complement

This is exactly the "WaterTwin" opportunity already scored #1 of 20 in `WELL_Labs_Digital_Vertical_Proposal.md` **[S]**: a satellite-first water balance and recharge-structure monitoring engine that starts precisely where WELL Labs' own ground instrumentation stops, calibrated against their own 191-well/4-logger dataset once shared, using TerraRisk's already-built GEE hydrology pipeline (`backend/app/services/hydrology/`). Nothing in this document's fresh research changes that conclusion — it is reaffirmed, not superseded.

**Research log for this section (2026-07-30, this session):** confirmed no WELL Labs GitHub/open-source presence (`WebSearch: "WELL Labs" GitHub OR "open source"` — no relevant hits); confirmed the ACIWRM/IHE Delft partnership and its stated purpose (`WebSearch: "WELL Labs" "ACIWRM"`); confirmed founder/org/location facts (`WebSearch: "WELL Labs" Bengaluru founded founder`); confirmed the Five Levers framework (`WebSearch: WELL Labs Raichur Transformation Lab systems approach five levers`). Three specific `welllabs.org` URLs returned HTTP 403 to direct WebFetch in this session (`situation-analysis-raichur-transformation-lab`, `solution-to-challenges-in-canal-irrigated-regions`, `community-hydrology-programme-insights`) — content from them is cited only via WebSearch's own retrieved snippets, not full-page extraction; flagged here rather than silently worked around.

---

# Part 2 — Raichur District

## What's actually happening in Raichur (public evidence)

- The **Tungabhadra reservoir** is the lifeline for the drought-prone districts of Ballari, Vijayanagara, Koppal and **Raichur** **[S: [Deccan Herald](https://www.deccanherald.com/india/karnataka/rice-bowl-state-may-prove-2351766)]**.
- Water delivered via the **NRBC (Narayanpur Right Bank Canal)** and **TLBC (Tungabhadra Left Bank Canal)** systematically fails to reach the **tail-end** — farmers in tail-end hoblis of Sindhanur, Raichur, and Manvi taluks have gone seasons without sowing for want of water **[S: existing research, `WELL_Labs_Digital_Vertical_Proposal.md`]**.
- Documented income effect of the 2015 water shortage: **head-reach** household income fell from ₹6,35,293 → ₹5,59,970; **tail-reach** fell from ₹5,66,263 → ₹4,19,895 — the tail-end started poorer and fell further **[S: `WELL_Labs_Digital_Vertical_Proposal.md`, citing academic literature on TBP command-area income]**.
- **Salt-affected soils** are concentrating in tail-end command areas from continued use of poor-quality drain (nala) water and groundwater irrigation **[S: [Journal of Soil Salinity and Water Quality](https://epubs.icar.org.in/index.php/JoSSWQ/article/view/171657)]**.
- Raichur cycles between flood and drought in adjoining seasons — reported flood damage followed immediately by drought conditions for the same farmers **[S: [Deccan Herald](https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Fafter-devastating-flood-raichur-farmers-face-drought-757751.html)]**.
- WELL Labs' own diagnosis (Five Levers) attributes this to **infrastructure without equitable distribution** — the canal exists, the water doesn't arrive fairly **[S, Part 1]**.

## How TerraRisk Water Intelligence can directly support these activities

The existing hydrology pipeline (`gee_hydrology_provider.py`, SAR/MNDWI surface-water extent, water-balance generation) already computes the building blocks of every one of these problems; none require new remote-sensing science, only new geography and a different *unit of analysis*:

| Raichur problem | Water Intelligence capability that applies | What's net-new |
|---|---|---|
| Tail-end farmers don't get water the canal was designed to deliver | SAR+MNDWI surface-water/irrigated-extent time series over the **design command area polygon** vs. **actually-irrigated extent** — makes the head/tail gap a satellite-measured, dated fact instead of an assertion | A command-area boundary layer (distinct from admin boundaries) — Phase 2, see Part 6 |
| WELL Labs' 4 loggers can't cover 5,500 km² | The existing water-balance engine (rainfall − ET − runoff = storage change), already built for Latur, run over Raichur watersheds | Real AdminBoundary/catchment geometry for Karnataka/Raichur — **Part 4/7 of this document** |
| Salt-affected soils from poor-quality irrigation water in tail-ends | MNDWI/SAR water-source classification (canal-fed vs. drain/groundwater-fed) is a straightforward extension of the existing surface-water classifier | Not in Phase 1 scope — flagged for Phase 2 |
| No independent verification of recharge-structure or canal-command performance for CSR/government funders | Directly matches TerraRisk's existing provenance/confidence-first PDF+dashboard report renderer | Reuse as-is once Karnataka geometry exists |

The payer here is structurally different from Latur (see Part 3) — WELL Labs, CSR, ACIWRM, or Karnataka government are the plausible payers, not an individual farmer or a single DCCB, because the underlying problem (canal-command inequity) is a collective/institutional one.

---

# Part 3 — Latur District, and how it differs from Raichur

## Latur's own water situation (independent of WELL Labs, which has no confirmed Latur presence — see below)

- Latur faced the **worst drought in a century** in 2016, alongside Beed and Osmanabad, as part of the wider Marathwada drought **[S: [SANDRP](https://sandrp.in/2016/04/20/latur-drinking-water-crisis-highlights-absence-of-water-allocation-policy-and-management/)]**.
- **61 of 76 talukas** across Marathwada's eight districts had groundwater levels severely below the prior five-year average; over **90,000 borewells** existed in Latur district alone, with **~10,000 new borewells being sunk per month** across Marathwada — withdrawal exceeding recharge until aquifers went dry in many villages **[S: [Nexteel](https://nexteel.in/latur-water-crisis-2016-the-train-that-brought-water-to-maharashtra/)]**.
- Indian Railways ran the **"Jaldoot Express"** water train (April–July 2016, Miraj→Latur, eventually 50 wagons) delivering **~24 crore litres** of drinking water to the city **[S: same, and [BBC](https://feeds.bbci.co.uk/news/world-asia-india-36013263)]**.
- The crisis was diagnosed as **both** a failed monsoon/depleted-aquifer problem **and** an absent water-allocation policy problem — unlike neighbouring Solapur, no comparable groundwater-recharge movement took hold in Latur **[S: SANDRP]**.
- This matches and reinforces TerraRisk's own prior domain research: Marathwada borewells now drilled 90–250m, with farmers going to 400–800 ft and finding nothing, and **borewell success rates as low as ~40% without scientific siting** **[S: `Problem_Discovery_2026.md`, Part 5, P8]**.

## WELL Labs and Latur: a confirmed absence, stated plainly

A dedicated search for a WELL Labs presence in Latur (`WebSearch: WELL Labs Latur Maharashtra project`) found **no evidence** of any WELL Labs programme, project, or publication tied to Latur or Maharashtra. WELL Labs' rural footprint, per every source found across both this session and the prior one, is **Karnataka only** (Raichur, Chikkaballapur). This is stated as an absence of evidence, not evidence of absence — but per this engagement's "never invent" rule, Latur is analysed here as **TerraRisk's own pilot territory** (DCCB Latur is TerraRisk's first customer, per persistent project context), independent of any WELL Labs relationship, not as a WELL Labs opportunity.

## Raichur vs. Latur — where the product must behave differently

| Dimension | Raichur | Latur | Why it matters to the product |
|---|---|---|---|
| **Dominant water-stress mechanism** | Surface water / canal-command inequity (NRBC, TLBC) **[S]** | Groundwater over-extraction in hard-rock (Deccan trap) aquifers, individually-owned borewells **[S]** | Raichur needs command-area/tail-end analysis; Latur needs well-yield/recharge analysis. These are different hydrology modules, not a relabelled map |
| **Unit of institutional decision-making** | Collective — canal distributary, Water Users' Association, government scheme **[S]** | Individual — one farmer, one borewell, one loan account **[E]**, consistent with `Problem_Discovery_2026.md`'s farm-level framing | The Catchment model's `admin_boundary_id` must be able to point at **any level** (village *or* taluka/distributary), which it already does — see Part 4 |
| **Plausible payer** | WELL Labs / CSR / ACIWRM / Karnataka government **[D, following the existing `WELL_Labs_Digital_Vertical_Proposal.md` analysis]** | DCCB Latur (loan-linked risk), individual farmer only as a beneficiary, never as payer **[S: `Problem_Discovery_2026.md` Part 9]** | Confirms these are two genuinely different go-to-market motions running on one shared engine, not one product with two labels |
| **Administrative data available today** | **None** — no Karnataka AdminBoundary rows exist in this system | Maharashtra/Latur exists, but village polygons are **synthetic ~150m placeholder squares around OSM points**, not real cadastral boundaries — a known, disclosed limitation from the existing `fetch_latur_villages_osm.py` script | Part 4/7 must source Karnataka data through the *same* disclosed methodology, not a better-looking but undisclosed one |
| **Framing WELL Labs itself uses** | Five Levers — multi-stakeholder systems view, not single-farmer risk scoring **[S]** | TerraRisk's existing single-entity risk-score framing (`RiskScore` keyed to one `FarmPolygon`) | A Raichur-facing report cannot just be a Latur report with new coordinates — it needs a command-area/collective framing option. Flagged for Phase 2, not attempted in Phase 1 |

---

# Part 4 — Select Area workflow: architecture

Grounded in a direct read of the current codebase (`backend/app/api/catchments.py`, `backend/app/api/villages.py`, `backend/app/models/admin.py`, `backend/scripts/load_admin_boundaries.py`, `frontend/src/app/(app)/catchments/new/page.tsx`, `frontend/src/features/water-intelligence/catchment-map.tsx`, `backend/app/api/reports.py`) — not assumed.

## What already exists and needs zero changes

- `Catchment.admin_boundary_id` is already a nullable FK to any-level `AdminBoundary`, already validated server-side, already round-tripped in `CatchmentCreateRequest` / `CatchmentUploadRequest` / `CatchmentResponse` (`backend/app/schemas/catchment.py`). **No backend schema or endpoint change is needed to attach admin metadata to a catchment.**
- A real, working, source-agnostic loader (`backend/scripts/load_admin_boundaries.py`) already exists: it reads a GeoJSON `FeatureCollection` (each feature tagged `level`/`name`/`parent_level`/`parent_name`/optional `lgd_code`), inserts parents before children, dedupes on the real unique constraint `(level, name, parent_id)`, and computes `geometry_simplified`. **This is already "every future district or state is only a data import" — it doesn't need to be built, only used.**
- `backend/app/api/reports.py`'s aliased-join pattern (`taluka = aliased(AdminBoundary); district = aliased(AdminBoundary)`) is the established way to walk the hierarchy upward from a village-level FK; it needs generalising to variable depth (a catchment may be linked at village, taluka, district, or state level) rather than copied as-is.
- `frontend/src/app/(app)/catchments/new/page.tsx` already uses a plain two-button toggle for Draw/Upload (not a UI-kit `Tabs` primitive) — Select Area follows the same convention rather than introducing a new one.

## What is genuinely new

### 1. Two minimal backend read endpoints (additive — Service 1's `GET /villages?q=` is untouched)

```
GET /admin-boundaries?parent_id={id | null}&level={STATE|DISTRICT|TALUKA|VILLAGE}
```
Returns direct children of `parent_id` (or all top-level `STATE` rows when `parent_id` is omitted), optionally filtered by `level`. Backs all four cascading dropdowns with **one** endpoint rather than four bespoke ones — the same shape serves "list states," "list districts in Raichur... wait, Karnataka," "list talukas in Raichur," and "list villages in a taluka."

```
GET /admin-boundaries/{id}
```
Returns one boundary's `name`, `level`, `lgd_code`, its full parent chain (state/district/taluka names, via the generalised variable-depth alias-join), `geometry` as GeoJSON (`ST_AsGeoJSON(geometry_simplified)` — the already-simplified copy, matching the existing "simplified copy is what map layers render" convention from `admin.py`'s own docstring), and `area_ha` (`ST_Area` on geography, same pattern `catchments.py` already uses for catchment area). Backs the boundary-preview map and the pre-save metadata panel.

### 2. Frontend `features/water-intelligence/select-area/` subtree

- `cascading-boundary-picker.tsx` — four sequential `<select>` elements (State → District → Taluka → Village), each backed by `useAdminBoundaryChildren(level, parentId)` (a `useQuery` hook against the new endpoint, mirroring `use-village-search.ts`'s existing style). Each dropdown is disabled until its parent is chosen; changing a parent clears its descendants.
- `village-boundary-preview.tsx` — a new map component. No existing component renders a GeoJSON overlay (`BaseMap` deliberately owns only the raster basemap; `CatchmentMap` only does manual drawing; `FarmMap` only flies to a point marker) — this adds a `map.addSource`/`addLayer` polygon overlay plus `map.fitBounds()` via `@turf/bbox` (already a dependency, used in `catchment-geo.ts`), fetched from `GET /admin-boundaries/{id}`.
- Two follow-on choices once a village is selected and previewed: **"Use Entire Village"** (submits the village's own geometry as the catchment) or **"Draw Inside Village"** (re-enters the existing, unmodified `CatchmentMap` draw flow, with the village polygon shown as a non-editable reference underlay so the user can see the boundary while drawing inside it — Phase 1 does not hard-block drawing outside the village, since that would need a real server-side containment check; it shows a warning instead, and full enforcement is a Phase 2 item, see Part 6).
- An area/admin-metadata panel (ha, acres, Village/Taluka/District names) shown before save, reusing the existing `ringAreaHectares`/`catchmentAreaBoundsIssue` helpers from `lib/catchment-geo.ts`.
- `catchments/new/page.tsx` gains a third toggle button (`"draw" | "upload" | "select-area"`), and both `useCreateCatchment`/`useUploadCatchment` calls are updated to pass `admin_boundary_id` when it's set — the only change to an existing file's submit path, and it's additive (an optional field that was already accepted and silently dropped).

### 3. Geographic scope and data sourcing (the actual hard constraint)

Real `AdminBoundary` rows exist today **only** for Maharashtra → Latur, and even those village-level polygons are synthetic ~150 m placeholder squares around OSM point nodes (`fetch_latur_villages_osm.py`'s own documented limitation — not something introduced by this work). Karnataka has **zero** rows. Supporting "State: Karnataka, Maharashtra; District: Raichur, Latur" as the mega-prompt specifies therefore requires a real Karnataka import, sourced legitimately:

- **State/District/Taluka polygons**: fetched via OpenStreetMap Nominatim (verified OSM relation IDs), exactly matching `fetch_latur_villages_osm.py`'s existing, already-reviewed method — real administrative polygons, properly licensed (OSM/ODbL, attribution required).
- **Village polygons**: OSM point nodes wrapped in the same small synthetic buffer used for Latur, for parity and honesty (not a worse method silently introduced for the new geography, nor a better one claimed without evidence). `datameet/indian_village_boundaries` (GitHub, ODbL, community-digitized from LGD/Bhuvan/Survey of India sources) was evaluated as a source of *real* village polygons for Karnataka **[S: [datameet/indian_village_boundaries](https://github.com/datameet/indian_village_boundaries)]**; it is real, appropriately licensed, and a legitimate Phase 2 upgrade path for *both* Latur and Raichur — but reconciling its village names/geometries against this system's LGD-code join keys is real, non-trivial data-engineering work, scoped out of Phase 1 (see Part 6) rather than rushed.

---

# Part 5 — Founder Review

*Roleplayed as a WELL Labs founder reviewing TerraRisk Water Intelligence cold — the existing implementation acknowledged, not re-litigated line by line, but not given credit it hasn't earned either. Ranked by priority: the things that would stop me adopting this, first.*

## 1. (Engineering/data — blocking) "Your village boundaries aren't real villages."

A 150-metre square centred on an OpenStreetMap point is not a cadastral village boundary. If I hand you our Distributary 10 well inventory to calibrate against, and your "village" polygon for the well's location is a synthetic square that may or may not contain the well, your calibration is measuring noise you introduced, not the noise that's actually there. This has to be labelled loudly in the product itself, not just in an engineering doc — a hydrologist using this without reading your source code has no way to know the boundary under their well is fake.

## 2. (Scientific — blocking) "You have no calibration workflow against ground truth at all."

We have 191 wells and 4 loggers specifically because we know satellite-only water balance needs checking against something real. I see a water-balance *generator*. I don't see anywhere in this product where I'd upload our logger CSV and get back "your model was within 15% of what we measured, here's where it wasn't." Without that loop, this is a nicer-looking version of the same unverified estimate every remote-sensing vendor already pitches me.

## 3. (UX/framing gap — high priority) "This is built for one farmer. My problem is a canal system with a hundred farmers on it."

Every screen I've been shown is a single polygon with a single risk score. Raichur's actual problem — the one in every public document we've published — is *relative* (head-end vs. tail-end), not absolute. A dashboard that can't put two catchments side by side and show "this one gets water, this one doesn't, and here's the gap, dated and measured" hasn't actually addressed our situation, it's addressed a rebranded version of it.

## 4. (GIS gap — high priority) "Your catchments are administrative units. Mine are watersheds and canal distributaries."

A village boundary is a governance construct. Water doesn't respect it. Distributary 10 is not a village — it's a hydraulic unit that crosses several. If "select area" only lets me pick administrative polygons, I still can't define my actual unit of analysis, and I'm back to drawing it by hand, which is what I'm already trying to get away from with a community-hydrologist network I can't scale.

## 5. (Scalability, honestly rated as *not* as bad as I expected) "The data-import story is real, at least."

I'll say something positive: `load_admin_boundaries.py` genuinely is a real, source-agnostic loader — not a hardcoded list dressed up as one. That's the right instinct. But a mechanism that can import data isn't the same as having the data, and right now you have one Maharashtra district with fake villages. Don't let the existence of the pipeline make you overstate the coverage.

## 6. (Trust/customer pain point) "Are you replacing my community hydrologists, or serving them?"

If this product's pitch to me is "your loggers are inadequate, use satellite instead," I will not adopt it — that network is core to our theory of change, not a stopgap. If the pitch is "here's the water balance for the 5,450 km² your loggers will never reach, and here's exactly where it disagrees with your loggers so your people can go check," that's a completely different conversation, and it's the one I'd actually take.

## 7. (Localisation — lower priority but real) "Everything I've seen is in English."

Our field staff and the farmers we work with operate in Kannada. A PDF report nobody in the district office can read past the header is a report that gets filed, not used.

## 8. (Engineering — lower priority) "What happens with no signal?"

Raichur's rural mobile coverage is inconsistent. If "Select Area" requires four live network round-trips to populate four dropdowns before a field officer can even start, that's a demo-day workflow, not a field workflow.

---

# Part 6 — Roadmap

## Phase 1 — needed for the WELL Labs demo

| Item | Engineering effort | GIS data required | Risk | Business impact |
|---|---|---|---|---|
| Generic Select Area architecture (cascading dropdowns, boundary preview, Use Entire Village / Draw Inside Village, admin metadata on save) | ~1 week | None beyond existing Latur data to build/test against | Low — purely additive, no existing endpoint touched | Unblocks any future geography without another architecture change |
| Karnataka/Raichur AdminBoundary import (state/district/taluka via OSM Nominatim, villages as disclosed synthetic placeholders, same method as Latur) | ~2–3 days | OSM (free, attribution required) | Medium — placeholder villages must be visibly labelled or item 1 of the Founder Review recurs immediately | Makes the Raichur conversation possible at all; without it, WELL Labs can't even see their own geography in the product |
| Tests (backend endpoint tests, loader script test, frontend hook/component tests) | ~2 days | — | Low | Prevents this from being a demo-only path that regresses silently |
| Deploy + end-to-end verification (Draw, Upload, Select Area, Water Report, Dashboard, PDF) | ~1 day | — | Low | Required before any external demo |

**Explicitly out of Phase 1**, and why: real cadastral village polygons (real data engineering, not a quick win — see Founder Review #1), calibration-against-ground-truth workflow (Founder Review #2 — needs WELL Labs' actual logger data, which we do not have and should not simulate), watershed/distributary-level catchment definition (Founder Review #4 — a real hydrology/GIS feature, not a data import), multi-catchment comparison view (Founder Review #3), Kannada localisation (Founder Review #7), offline-tolerant field UX (Founder Review #8).

## Phase 2 — needed for a real pilot deployment

| Item | Engineering effort | GIS data required | Risk | Business impact |
|---|---|---|---|---|
| Replace synthetic village polygons with real cadastral boundaries (Latur *and* Raichur), via LGD/Bhuvan/`datameet/indian_village_boundaries` reconciled against existing LGD codes | 2–3 weeks | Real, licensed third-party data — the actual blocker, not the code | Medium-high — data quality/reconciliation risk, not engineering risk | Removes Founder Review's #1 blocking objection entirely |
| Ground-truth calibration module (ingest WELL Labs' logger/well CSV, compute confidence bands against modelled water balance) — this is the "WaterTwin" MVP already designed in `WELL_Labs_Digital_Vertical_Proposal.md` | 3–4 weeks | WELL Labs' own data — requires a data-sharing agreement, not a technical step | Medium — depends on WELL Labs actually sharing data | Directly answers Founder Review #2, the single highest-priority scientific gap |
| Watershed/canal-distributary catchment layer, independent of admin boundaries (DEM-based delineation) | 3–4 weeks | SRTM/CartoDEM (free) | Medium — new hydrology-GIS capability, not a data import | Answers Founder Review #4 — lets Raichur's actual hydraulic units be defined, not just its villages |
| Head-end vs. tail-end / multi-catchment comparison view | 1–2 weeks | None beyond above | Low | Answers Founder Review #3 — turns the product from single-farm to systems framing for Raichur |
| Kannada + Marathi report localisation | 1 week | None | Low | Answers Founder Review #7 |

## Phase 3 — needed for a commercial product

| Item | Engineering effort | GIS data required | Risk | Business impact |
|---|---|---|---|---|
| Recharge-structure functionality audit (subscription) — already scored #3/20 in `WELL_Labs_Digital_Vertical_Proposal.md` | 2 weeks | Structure coordinates (WELL Labs already has these) | Low | Fastest real revenue line once Phase 2's engine exists |
| Watershed prioritisation engine — scored #3/20 | 2–3 weeks | Composite index inputs, all already computed | Low-medium | Turns "where next" from relationship-driven to defensible |
| Corporate water-stewardship verification (white-labelled via WELL Labs) — scored #4/20 | 3 weeks | Same stack, reformatted for AWS/BRSR/CDP language | Medium — market wants a certificate more than an audit, per existing risk analysis | Highest revenue ceiling of the scored options |
| Multi-tenant white-label branding for WELL Labs | 2 weeks | None | Low | Required before any of the above can be sold *as* a WELL Labs product rather than a TerraRisk one |

---

# Part 7 — Phase 1 implementation

Implemented immediately following this document, per the instruction to implement Phase 1 only after research/architecture/critique/roadmap were complete. See commit history and the verification notes reported in chat for what was built, tested, and deployed.

---

## Sources

In addition to every source already cited inline above and in `WELL_Labs_Digital_Vertical_Proposal.md` / `WELL_Labs_Internship_Project_Plan.md` / `Problem_Discovery_2026.md`:

- [WELL Labs — About Us](https://welllabs.org/about-well-labs/)
- [WELL Labs — Remote Sensing for Communities: Partnership with IHE Delft and ACIWRM](https://welllabs.org/well-labs-partnership-ihe-delft-aciwrm-water-remote-sensing-data/)
- [WELL Labs — Why Raichur Needs Systems Transformation (Five Levers)](https://welllabs.org/five-levers-systems-transformation-in-raichur/)
- [ACIWRM — Government of Karnataka](https://aciwrm.karnataka.gov.in/english)
- [The Org — WELL Labs](https://theorg.com/org/water-environment-land-and-livelihoods-well-labs)
- [Deccan Herald — Raichur farmers face drought after flood](https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Fafter-devastating-flood-raichur-farmers-face-drought-757751.html)
- [Deccan Herald — Rice bowl state may prove... (Tungabhadra)](https://www.deccanherald.com/india/karnataka/rice-bowl-state-may-prove-2351766)
- [Journal of Soil Salinity and Water Quality — Salt-affected soil mapping, Tungabhadra Project command](https://epubs.icar.org.in/index.php/JoSSWQ/article/view/171657)
- [SANDRP — Latur Drinking Water Crisis](https://sandrp.in/2016/04/20/latur-drinking-water-crisis-highlights-absence-of-water-allocation-policy-and-management/)
- [Nexteel — Latur Water Crisis 2016: The Train That Brought Water](https://nexteel.in/latur-water-crisis-2016-the-train-that-brought-water-to-maharashtra/)
- [BBC — India 'water train' brings relief to drought affected state](https://feeds.bbci.co.uk/news/world-asia-india-36013263)
- [datameet/indian_village_boundaries — GitHub](https://github.com/datameet/indian_village_boundaries)
