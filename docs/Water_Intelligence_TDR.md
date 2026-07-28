# Technical Design Review — TerraRisk Water Intelligence
## Architecture Review Committee — pre-implementation gate

**Date:** 26 July 2026
**Subject:** `docs/Water_Intelligence_Service_Blueprint.md`
**Panel:** MIT Hydrology/Earth Systems Professor, IISc Water Resources Professor, Principal Hydrologist, Principal Remote Sensing Scientist, Senior GIS Scientist, Principal Software Architect, Principal FastAPI Engineer, Principal PostgreSQL/PostGIS Engineer, Senior GEE Engineer, Principal Frontend Architect, Principal Product Manager, WELL Labs Founder, WELL Labs CTO, SatSure Technical Director, Pixxel Technical Director, Senior Climate Scientist, Senior DevOps Architect, Senior QA/Test Architect
**Charge:** determine whether the blueprint is ready to implement. Not to improve it — to decide whether it survives contact with people whose job is to find what it missed.

---

## How to read this review

The blueprint is a genuinely strong document — that gets said once, here, and then this review stops being polite about it. A design review that spends its budget on praise isn't a design review. Every section below assumes the reader has the blueprint open and goes straight at what it got wrong, missed, or asserted without earning.

---

# 1. Product Design & Requirements

**Excellent:** the PRD correctly refuses to invent a portfolio-rollup feature before a single catchment works, and the naming-conflict flag at the top of the blueprint (Service 2 vs. the existing Portfolio Dashboard numbering) is exactly the kind of thing a lazier document would have quietly ignored.

**Weak:** the primary user story promises a report "within minutes." Nothing in the blueprint establishes that this is true for a catchment-sized polygon, as opposed to a farm-sized one. Service 1's whole design envelope — GEE call cost, `getInfo()` payload size, `reduceRegion` complexity — was proven at farm scale (0.01–1000 ha, per the existing `_MAX_FARM_AREA_HA` bound in `api/farms.py`). A catchment is routinely 10–500+ km². "Reuse the GEE provider" is not the same claim as "the GEE provider performs at this scale," and the PRD states the former as if it implies the latter.

**Hidden risk:** the PRD never asks who the tenant is. Every customer type it names — CSR teams, NABARD consultants, watershed NGOs, state Water Resources Departments, international development orgs — is a *different organization*. Service 1's role model (`UserRole`: `CREDIT_OFFICER`, `BRANCH_MANAGER`, `RISK_OFFICER`, `CEO`, `CHAIRMAN`) is a bank org chart. The blueprint reuses auth "100%, zero changes" without once asking whether a NABARD consultant is a `credit_officer`. This isn't a naming quibble — it's the PRD skipping the question of who the product is actually for, structurally, not just rhetorically.

**Scientific risk:** none at this layer.

**Engineering risk:** low on its own; compounds badly with the multi-tenancy gap in §7.

**Product risk:** high. A product pitched at five different organization *types* that hasn't asked "is this multi-tenant SaaS or one deployment per customer" doesn't have a product design yet — it has a feature list with a market-sizing paragraph attached.

**Scalability risk:** N/A at this layer, but see §8.

**Security risk:** see §7 — this is where the product-design gap becomes a real vulnerability, not just an omission.

**Better alternative:** the PRD needs an explicit tenancy decision *before* Part 5's schema is finalized, because it changes the schema. Either (a) single-tenant-per-deployment (each customer gets their own database/instance — simplest, but contradicts the "generic SaaS platform" framing used across every prior session on this project), or (b) genuine multi-tenant with an `organization_id` on every new table and a generalized role model. This is a five-minute conversation that the blueprint skipped, and it's upstream of almost everything else in this review.

**Final recommendation:** **must resolve before Part 5 is implemented.** Not a blocker to *this* review's other findings, but a blocker to writing the migration.

---

# 2. Scientific Methodology — Hydrology

**Excellent:** the ✓/⚠ table is real, sourced, and the GRACE exclusion is exactly the kind of thing a less careful team would have quietly included because "groundwater" sells. The MIT-professor sentence about never claiming groundwater level or volume is the single best line in the blueprint.

**Weak, and this is the sharpest finding in the entire review:** the water balance equation as specified — `P − ET − Q = ΔS` — silently assumes the catchment is **hydrologically closed**: no lateral groundwater exchange across the catchment boundary. This assumption appears nowhere in the blueprint, not in Part 4's table, not in Part 10's limitations list. For Deccan basalt terrain — weathered, fractured hard-rock aquifers, exactly the geology under most of Maharashtra and much of peninsular India — inter-catchment groundwater flow is frequently a **first-order term**, not a rounding error. A catchment abutting a fault line or a zone of differential weathering can lose or gain substantial subsurface flow that this equation has no term for. This isn't a nitpick; it's the kind of omission that gets a paper rejected at review, and it's currently absent from a document that otherwise takes real care to state its assumptions.

**Second finding, nearly as sharp:** the recharge-structure module and the water-balance module are scientifically disconnected. A check dam sitting inside a catchment captures runoff that would otherwise leave as `Q` — its presence changes the water balance. The blueprint treats "check dam monitoring" and "water balance estimation" as two independent rows in a table, with no term in the engine for structure-mediated recharge. A hydrologist reading both modules side by side would ask why the check dam's captured volume doesn't reduce effective `Q` in the same catchment's balance. It isn't answered because it isn't asked.

**Scientific risk — CHIRPS resolution vs. catchment size:** CHIRPS is a ~5.5 km grid product. Part 4 marks rainfall analysis "✓, identical reused code path." That reuse was proven at farm scale, where one CHIRPS pixel comfortably covers the whole polygon and the composite value is at least internally consistent. A genuinely small micro-watershed (a few km², which is a normal size for the "farm-cluster" framing this service also targets) can be **smaller than a single CHIRPS grid cell** — meaning the "catchment rainfall" is just the nearest grid cell's value, with zero actual spatial resolution inside the polygon. The `data_completeness` confidence field measures cloud-cover completeness. It says nothing about this — a small catchment gets a rainfall number that *looks* precise and isn't, and nothing in the schema or report distinguishes it from a catchment large enough for CHIRPS to be meaningful.

**Scientific risk — Curve Number generalization:** Part 4 cites one validation study (an urbanizing Western Maharashtra watershed) as evidence CN "did not vary significantly" from event data, and uses this to mark the module ✓ with named caveats. That citation supports CN for *one watershed type in one state*. The blueprint's own stated customer list is national — NABARD, state Water Resources Departments, international development orgs anywhere in India. Extrapolating one regional validation to a blanket-with-caveats ✓ nationally is thinner evidence than the rest of the document's standard. This should be a **region-qualified** ✓, not a general one, until more validation exists.

**Scientific risk — the baseline-window problem, inherited uncritically:** D6 reuses `RiskEngine`'s percentile-rank-against-own-3-year-history pattern for recharge-stress scoring, and defends this by saying the code "is already correct and tested." Correct for *farm loan risk scoring* does not imply correct for *regional water-stress screening* — these are different use cases with different sensitivity to baseline choice. If the trailing 3 years happen to be a drought sequence, "normal" gets redefined as "already stressed," and a catchment that's been stressed the whole time scores as merely moderate. Part 4 flags exactly this problem for the *climate resilience* indicator (correctly recommending the 30-year CHIRPS climatology instead of the 3-year window) — but doesn't apply the same logic to recharge-stress scoring, which uses the same short window for the same reason and inherits the same flaw. This is an internal inconsistency: the document identifies the right principle in one row of its own table and fails to apply it two rows down.

**Product risk — the permanently uncalibrated number:** Risk Register #7, in the blueprint's own words, admits that a generic (non-instrumented) customer has no way to ever move `calibration_status` off `UNCALIBRATED` in MVP. Combined with the closed-catchment assumption above, this means the headline `storage_change_mm` figure is a residual, from an equation missing a potentially first-order term, that can never be checked against reality for the product's entire MVP lifetime. The blueprint's mitigation — "confidence-band it, label it clearly" — treats this as a presentation problem. It is arguably a **scope** problem: should MVP even surface a quantitative `storage_change_mm` figure at all, or should it report P, ET, and Q individually (each with its own honest confidence) and describe storage change only qualitatively ("wetter/drier than the 30-year normal") until calibration exists? The panel's hydrologists lean toward the latter as the more defensible MVP.

**Better alternative:** (1) add an explicit "closed-catchment assumption" statement to Part 4 and Part 10, with guidance to flag or exclude catchments in known high-permeability/fractured terrain until a lateral-flow term exists; (2) either integrate recharge-structure capture into the `Q` term or explicitly document why it's out of scope for the residual calculation, not silently absent; (3) add a catchment-area-vs-CHIRPS-pixel-size check that downgrades confidence (or blocks report generation) for sub-pixel catchments; (4) re-scope Part 4's CN row to name the region it's validated for; (5) reconsider whether `storage_change_mm` should be a headline number or a qualitative descriptor for MVP.

**Final recommendation:** **major changes required.** Not because the science is bad — because the document's own standard (state every assumption, no silent omissions) is inconsistently applied to the one equation the entire product's credibility rests on.

---

# 3. Remote Sensing

**Excellent:** the resolution-limit honesty (SAR/MNDWI reliability above ~0.2–0.3 ha, explicit degradation below it) is real and well-sourced, and correctly drives the farm-pond module's ⚠ status.

**Weak:** the surface-water detection methodology, as described, implies a single global SAR backscatter threshold for water classification. Backscatter-based water thresholds are known to shift with incidence angle, surface roughness (wind-driven wave action on larger water bodies), and — critically for a *watershed* product — terrain-induced layover and shadow in hilly ground. Recharge structures and farm ponds are disproportionately sited in exactly the undulating terrain where SAR geometric distortion is worst. Nothing in Part 4, Part 6, or Part 14 mentions incidence-angle correction, terrain masking, or a locally-adaptive threshold (e.g., Otsu's method per scene) as opposed to a fixed global cutoff.

**Hidden risk:** Sentinel-1 constellation revisit frequency over India has not been consistently at full nominal cadence in recent years due to satellite-availability issues in the constellation — a fact worth verifying against current mission status before the "monthly SAR composite" assumption is treated as reliably achievable for every period in a 3-year lookback. The blueprint doesn't mention checking this at all.

**Scientific risk:** ET product choice (MODIS MOD16A2, 500m) versus catchment size interacts with the same sub-pixel problem raised in §2 for rainfall — a catchment near or below ~25 hectares (5×5 pixels) gets an ET estimate with very few independent samples, and the report should say so.

**Engineering risk:** if a per-scene adaptive threshold is eventually needed (likely, per the terrain point above), that's meaningfully more GEE compute per catchment than a fixed threshold — this changes the cost model in §8 and should be estimated now, not discovered in Phase 2.

**Product risk:** a customer operating in genuinely hilly watershed terrain (which describes a large share of the stated Indian target geography) could see systematically wrong wet/dry classifications near valley shadows, with no indication in the report that terrain is the cause rather than an actual hydrological signal.

**Better alternative:** name the terrain-distortion risk explicitly in Part 4 and Part 10 now, even if the actual correction is deferred; at minimum, flag catchments with high terrain relief (computable cheaply from the same DEM already needed for Curve Number) as lower-confidence for SAR-based surface water detection.

**Final recommendation:** **minor-to-major** depending on target terrain — if the initial rollout geography is genuinely flat (e.g., canal-command plains), this can be Phase 2; if it includes hilly watershed terrain (which "watershed development" as a category strongly implies), this needs to be named in MVP's limitations even if not fixed in MVP's code.

---

# 4. GIS

**Excellent:** reusing `FarmPolygon`'s server-side `ST_Area` recompute pattern for `Catchment` is exactly right, and the GIST index on the new geometry column is correctly specified.

**Weak — real schema defect, not a style note:** `catchment.geometry` is typed `GEOMETRY(POLYGON, 4326)`, singular. A watershed is not guaranteed to be simply connected. DEM-derived catchments, administrative-boundary-derived catchments, and even hand-drawn ones representing a fragmented service area (a canal command split by intervening non-command land, for instance) are legitimately **MULTIPOLYGON**. `FarmPolygon` correctly uses `POLYGON` because a single field is, by definition, one contiguous shape — that reasoning does not transfer to a catchment, and the blueprint copied the type without re-examining whether the assumption still held.

**Hidden risk — geometry-vs-geography consistency:** Service 1 stores `Geometry` but explicitly casts to `Geography` for area computation (`ST_Area(cast(farm.geometry, Geography))`) — a deliberate choice to get geodesically correct area rather than a meaningless square-degree planar figure. That cast is cheap and harmless at farm scale. At catchment scale (potentially hundreds of km²), *every* spatial operation — not just area — needs to be geography-aware or run through an appropriate equal-area projection: centroid computation (relevant for a future pour-point inference), intersection with admin boundaries, distance calculations. Part 5 only mentions the area computation; it doesn't establish a consistent rule for every other spatial operation this service will eventually need.

**Hidden risk — no bounds, no vertex limit:** Service 1 has an explicit, documented defensive bound (`_MIN_FARM_AREA_HA = 0.01`, `_MAX_FARM_AREA_HA = 1000.0`) specifically to catch a fat-fingered polygon before it becomes an expensive or nonsensical computation. Part 6's API spec for `POST /catchments` has no analogous bound, and no vertex-count limit either. A user tracing a real watershed ridgeline by hand can easily produce a polygon with hundreds of vertices; without a bound, nothing stops someone from drawing (accidentally or otherwise) a state-sized polygon and triggering the cost problem raised in §8.

**Engineering risk:** these are cheap fixes (a `CHECK` constraint or application-level bound, `MULTIPOLYGON` instead of `POLYGON`) but they are the kind of fix that's expensive to retrofit after real catchments are already stored under the wrong geometry type.

**Better alternative:** `GEOMETRY(MULTIPOLYGON, 4326)`, an explicit area bound analogous to the farm one (with a much wider range, since catchments are legitimately larger — but a range nonetheless, not an open ceiling), and a vertex-count cap enforced at the schema-validation boundary the way farm geometry validity already is.

**Final recommendation:** **minor changes, but must-fix before the migration is written** — this is exactly the category of thing that's a one-line change now and a data-migration problem in six months.

---

# 5. Google Earth Engine Workflows

**Excellent:** D1's decision to keep `HydrologyDataProvider` a separate interface from `SatelliteDataProvider`, implemented by extending the same underlying module, is correctly reasoned and is the single best architectural call in the blueprint.

**Weak — no `reduceRegion` scale/`maxPixels` strategy:** this is a near-certain production bug, not a hypothetical one. Every GEE workflow that runs a `reduceRegion`-style aggregation over an arbitrary user-drawn geometry has to decide what happens when pixel count exceeds `maxPixels` — either the call fails outright, or `bestEffort: true` silently drops to a coarser effective scale without telling the caller. At Sentinel's 10 m resolution over a catchment that could be hundreds of km², this is not an edge case, it's the expected case for a meaningful fraction of real catchments. Nothing in Part 4 (methodology), Part 6 (API), or Part 14 (first coding task) mentions this. A Senior GEE Engineer would not sign off on a hydrology provider design that doesn't state, explicitly, what `scale` is used per index and what happens when a catchment's pixel count would exceed a safe `maxPixels` budget.

**Hidden risk:** the blueprint's cost mitigation (Risk #3) is "reuse the caching discipline... ship it from day one" — true but insufficient. Caching avoids *re-billing* for the *same* catchment/period. It does nothing for the *first* computation of a large catchment, which is exactly where the `maxPixels` problem above bites.

**Engineering risk:** D1's "decided at M0, see Part 8" deferral of whether `GEEHydrologyProvider` is a new class or an extended `GEEProvider` is reasonable to defer *as an implementation detail*, but the `maxPixels`/scale strategy is not an implementation detail — it changes what data model choices are even correct (e.g., whether confidence needs a "computed at reduced scale" flag) and should be decided in this document, not deferred past it.

**Scalability risk:** GEE quota is per-project. Nothing in the blueprint says whether Water Intelligence shares the *same* GCP project/service-account quota as Service 1 (per `docs/DECISIONS.md`'s "dedicated GCP project... not a personal account") or gets its own. If shared, a Water Intelligence usage spike degrades Service 1's SLA — a real cross-service blast-radius risk that isn't named anywhere.

**Cost:** there is no number anywhere in this document. Not a rough one. A production-readiness review cannot approve a service whose primary compute cost driver (GEE calls scaling with catchment area and index count) has zero quantification, even an order-of-magnitude estimate.

**Better alternative:** state the `scale` parameter per index explicitly (e.g., "10 m for SAR/MNDWI, 500 m for ET, native for CHIRPS"), state the `maxPixels` policy and what happens at the boundary (reject vs. degrade-with-visible-confidence-penalty — the latter is more consistent with the rest of the document's honesty principle), and produce at least a rough GEE compute-unit estimate per report at a representative catchment size before M1 starts.

**Final recommendation:** **major changes required** — this is the most concrete, most certain-to-occur production bug identified in this entire review, and it's currently unaddressed in a document that otherwise sweats details at this level.

---

# 6. Backend Architecture & API Design

**Excellent:** the milestone sequencing (schema → provider → pure engine → API → reporting → frontend) is the right order, and it matches how Service 1 was actually built. D4's `WaterBalanceEngine` mirroring `RiskEngine`'s shape is clean and correct — zero I/O, deterministic, versioned, unit-testable without touching GEE. No notes on the engine's *shape*.

**Weak — a schema field that doesn't mean anything:** `water_balance_result.weights_version_id` references `config_weight`. Water balance, as specified, is `P − ET − Q = ΔS` — an arithmetic mass-balance sum of physical terms, not a weighted composite. `RiskScore` has a `weights_version_id` because `RiskEngine` genuinely computes a *weighted* composite of four factors. `WaterBalanceEngine` doesn't — nothing in Part 4's methodology involves a configurable weight for rainfall, ET, or runoff. This field appears to have been copied from `RiskScore`'s shape without asking whether it applies. Either there's an intended use for it that the document never states, or it's a modeling error that should be removed from `water_balance_result` and correctly kept only on `recharge_stress_score`/the village-water-security composite, where weights genuinely apply.

**Weak — a table implied in prose, missing from schema:** Part 8 (M3) says CGWB context comes from "a periodic batch job (quarterly)... static/periodic ingest." Part 5's schema has no table to ingest *into* — `recharge_stress_score.cgwb_category` and `.cgwb_category_as_of` are per-computation snapshot fields, which is fine for the *score*, but there's no raw `cgwb_observation`-style staging table anywhere for the ingestion job itself to write to, version, or be queried against independently of a specific stress-score computation. The ingestion mechanism described in prose has no corresponding schema.

**Hidden risk — resilience under partial failure, asserted not verified:** Part 3 says the water report generator "mirrors `report_generator.py`'s shape," which — per the actual source comment reviewed for this document — has a specific, deliberate incremental-persistence property: satellite observations are saved one series at a time so a later failure doesn't discard already-fetched data. Water Intelligence fetches *more* series per report than Service 1 does (rainfall, ET, SAR, MNDWI vs. Service 1's three optical indices plus rainfall) — more sequential GEE calls means more failure surface, which makes this property matter *more* here, not the same amount. The blueprint asserts the mirroring but never re-states or re-verifies that the incremental-persistence discipline specifically survives the added series — this needs to be an explicit requirement in Part 3/Part 8, not an inherited assumption.

**Product risk:** none beyond what's already covered.

**Scalability risk:** covered in §8.

**Security risk:** the API spec's auth column says "same role gate as farm creation" for every endpoint — which reuses bank-shaped roles for a non-bank product, per §1's finding. This is the same gap surfacing a second time, in a different part of the document, which is itself informative: it's not an isolated oversight, it's a load-bearing assumption the whole blueprint leans on without examining.

**Better alternative:** remove or justify `weights_version_id` on `water_balance_result`; add the missing CGWB staging table; add an explicit statement in Part 3 that the incremental-persistence property is a *requirement* for the water report generator, verified by test, not just inherited by description.

**Final recommendation:** **minor-to-moderate changes** — none of these are deep design flaws, but a Principal PostgreSQL/PostGIS reviewer would not approve the schema in Part 5 as-written; it needs one field removed, one table added, before M0's migration is hand-written.

---

# 7. Security & Multi-Tenancy

**This section is short because the finding is simple and was already surfaced twice above — consolidating it here at full weight, because it's the most consequential gap in the whole review.**

The blueprint states auth is "100% reused, zero changes" and treats this as a strength. It is a strength **only if the tenancy model doesn't need to change** — and nothing in the document establishes that. If TerraRisk Water Intelligence is genuinely meant to serve multiple independent customer organizations (as the PRD's own customer list implies), then:

- There is no `organization_id` anywhere in the new schema (`catchment`, `water_balance_result`, `recharge_stress_score`, `recharge_structure`).
- "Owner-or-branch scoped" access control, inherited unchanged, models a *single bank's internal hierarchy* — it has no concept of "customer A's data must never be visible to customer B," because Service 1 never needed one (one DCCB, one deployment, per the product's original scope).
- If two different NGOs or a government department and a corporate CSR team share one deployment, there is currently nothing in this design stopping a authorization bug from crossing that boundary, because the boundary doesn't exist in the data model to be enforced.

**This is either a non-issue (if the actual plan is one deployment per customer) or a severe gap (if the actual plan is shared multi-tenant SaaS).** The blueprint doesn't say which, and a security reviewer cannot sign off on "reused, zero changes" without knowing which one is true.

**Final recommendation:** **blocking.** This must be an explicit, written decision — not an inherited default — before Part 5's schema is finalized, because the answer changes the schema.

---

# 8. Performance, Scalability, Cost

Consolidating findings already raised in §5 and adding what's new:

- No `maxPixels`/scale policy (§5) — the most concrete risk in this review.
- No cost estimate, even rough, for GEE compute per report (§5).
- No partitioning or archival strategy for `water_balance_result`/`satellite_observation` as they grow across catchments × 36 months × index types × (potentially many) customers.
- No stated rate limit or per-user/per-org cost governance — nothing stops repeated report regeneration from burning GEE quota beyond whatever the existing (unverified, per §6) advisory-lock pattern happens to prevent.
- No discussion of whether GEE quota is shared with or separate from Service 1's (§5) — a genuine cross-service SLA risk.

**Final recommendation:** **major changes required**, specifically the `maxPixels`/scale policy and a rough cost model — these are implementable in the time it takes to write the paragraph, and their absence is the review's single strongest objection to approving M1 as currently scoped.

---

# 9. Report Generation, Dashboard, UX

**Excellent:** the decision to render methodology text with the ✓/⚠ language "verbatim, pinned by twin test" is the right level of rigor, and directly extends Service 1's own report-text testing discipline rather than inventing a weaker one.

**Weak:** the frontend plan (D2, Part 7) treats generalizing `farm-drawing` into `polygon-drawing` as primarily a refactor. It isn't, for the reason raised in §4: drawing a real, complex watershed boundary by hand is a materially harder UX problem than tracing a field, and nothing in the blueprint designs for it. More concretely: **there is no mention anywhere of shapefile/KML upload as an alternative to hand-drawing.** Every realistic customer in the PRD's own list (NABARD consultants, state Water Resources Departments, established watershed NGOs) almost certainly already has GIS-literate staff and existing boundary files. Forcing them to hand-trace a watershed on a web map when they already have the authoritative shapefile is the kind of gap that a real customer notices in the first five minutes of a demo.

**Product risk:** this is a genuine adoption risk, not a cosmetic one — it's plausible that boundary upload is a harder MVP requirement to skip than several of the things the blueprint correctly deferred to Phase 2.

**Better alternative:** re-evaluate whether shapefile/KML/GeoJSON upload belongs in MVP rather than Phase 2 — it's arguably lower engineering effort than several MVP items already in scope (it's a file-parse-and-validate problem, not a new scientific capability), and it removes the single most obvious first-demo friction point.

**Final recommendation:** **minor changes** — recommend moving boundary upload into MVP scope discussion at minimum, even if the final call is to defer it.

---

# 10. Testing Strategy & Maintainability

**Excellent:** the testing plan correctly mirrors Service 1's structure end-to-end (pure-engine tests, provider tests against real GEE, fakes, schema/DDL tests, report twin-tests, one real-stack integration test) — this is the right shape and the right discipline.

**Weak — the testing strategy proves the code is correct, never that the science is right.** Every test named in Part 12 is a software-correctness test: does the engine compute deterministically, does the schema round-trip, does the report render the right text. There is no test anywhere in the plan that checks computed hydrology outputs against a real, published, ground-truthed reference — for instance, running the pipeline against the very Western Maharashtra Curve Number validation study cited in Part 4's own sources, and asserting the computed CN/runoff falls within the published range. Without this, the test suite can be 100% green while the water balance is scientifically wrong in a way no test catches.

**Future extensibility risk — the shared-enum pattern won't survive Services 3–5:** D3's decision to extend `RiskEntityType` and `SatelliteIndexType` rather than create parallel tables is the right call *for two services*. It does not obviously scale to five. Every new service, under this pattern, has to make a cross-cutting edit to shared enums that every other service also depends on — a merge-conflict hotspot and a blurred bounded-context boundary. `SatelliteObservation.entity_id` is *already* documented as intentionally not a hard foreign key (polymorphic across tables by convention, not by database constraint) — acceptable risk at two entity types, a growing referential-integrity gap at five. This isn't a defect in the current design; it's a pattern that has a visible expiration date, and the blueprint doesn't name it.

**Better alternative:** add one golden-dataset regression test per major hydrology module, sourced against published literature already cited in Part 4 (the CN study and, if a suitable one exists, an ET validation site) — this is a small addition with an outsized credibility return. For the enum-sharing concern: not an MVP blocker, but worth a named entry in Part 13's Future Enhancements — "revisit shared-enum coupling once Service 3 is scoped" — so it's a planned checkpoint, not a surprise.

**Final recommendation:** **minor changes** for MVP (add the golden-dataset test); **flag for future review**, not a current blocker, for the enum-coupling question.

---

# Architecture Review — direct answers to the questions asked

**Are we reusing enough from Service 1?** Yes — the provider-abstraction reuse, the pure-engine mirroring, and the reporting-pipeline shape reuse are all correctly identified and are the blueprint's strongest work.

**Are we duplicating anything?** No unjustified duplication found. The one new interface (`HydrologyDataProvider`) is correctly justified by interface segregation, not laziness.

**Is there unnecessary complexity?** No — if anything, the design under-specifies necessary complexity (GEE scale/maxPixels handling, tenancy) rather than over-building unnecessary complexity. This blueprint's risk is omission, not bloat.

**Can the architecture be simplified?** Not meaningfully beyond what's already been cut to Phase 2/3. The MVP scope is appropriately narrow.

**Will this still work after adding Services #3, #4, #5?** **Provisionally, with a named caveat.** The provider-per-domain and pure-engine-per-domain patterns scale fine. The shared-enum pattern (§10) and the unresolved tenancy question (§7) do not obviously scale past two services and should both be revisited explicitly once Service 3 is scoped — not blocking now, but should be a planned checkpoint, not forgotten.

**Is the provider abstraction correct?** Yes. D1 is the best-reasoned decision in the document.

**Is the `WaterBalanceEngine` clean?** The engine's *shape* is clean. Its *equation* is missing a stated assumption (closed-catchment, no lateral flow — §2) and carries one unexplained schema field (`weights_version_id` — §6). Shape: approved. Contents: not yet.

**Is the separation of concerns correct?** Mostly — the one violation is the recharge-structure/water-balance disconnect in §2, where two modules that should inform each other don't.

---

# Scientific Review — four-tier classification

| Module | Classification | Basis |
|---|---|---|
| Rainfall analysis (CHIRPS + climatology) | **Scientifically proven**, with a named caveat for sub-pixel catchments (§2) | Direct reuse of an already-shipped, already-tested Service 1 pipeline |
| Evapotranspiration (MODIS/Landsat) | **Scientifically acceptable** for relative/trend use; **not supported** for absolute closure claims | FAO WaPOR's own validation shows seasonal accuracy variation and systematic bias |
| Water balance (P−ET−Q=ΔS) | **Scientifically acceptable at basin scale; research-stage at catchment scale** as specified, because the closed-catchment assumption is unstated and unvalidated for this product's actual unit of analysis | WA+ framework proven at basin scale; not demonstrated at the smaller scale this service targets |
| Surface water extent (SAR+MNDWI) | **Scientifically proven** above ~0.2–0.3 ha; **not supported** below it | Documented, sourced accuracy figures with an explicit resolution floor |
| Reservoir extent | **Scientifically proven** | Same method as above, at a scale where resolution isn't the limiting factor |
| Reservoir volume-from-extent | **Research-stage** | No bathymetric ground truth; area-elevation proxy is a known technique but unvalidated for this product's specific reservoirs |
| Farm pond monitoring (precise area/volume) | **Not supported** | Below reliable Sentinel resolution for a large share of real Indian farm ponds |
| Farm pond monitoring (coarse wet/dry) | **Scientifically acceptable** | Same resolution ceiling, but coarser claim fits under it |
| Check dam / structure water presence | **Scientifically acceptable** | Same SAR/MNDWI method, appropriately scoped claim |
| Check dam / structure functionality | **Not supported** without metadata or field survey | Silting/breach state is not optically observable |
| Recharge stress mapping (as relative screening index) | **Scientifically acceptable**, with the baseline-window caveat from §2 | Percentile-based, correctly excludes GRACE, but inherits an unexamined short-window assumption |
| Recharge stress mapping (if ever presented as groundwater level) | **Unsupported** | Would contradict the document's own stated principle |
| CGWB category cross-check | **Scientifically proven** as a block-scale context layer | Public, sourced, well-established government dataset |
| Curve Number runoff | **Scientifically acceptable, regionally qualified** — not yet a general national claim | One validated regional study, generalized further than the evidence supports (§2) |
| Watershed health indicators (NDVI/VCI/LULC trend) | **Scientifically proven** | Standard, published remote-sensing methodology |
| Climate resilience indicators | **Scientifically acceptable**, correctly caveated on window length | The blueprint gets this one right — it's the model for how the recharge-stress row should also read |

---

# FINAL DECISION

## APPROVED WITH MAJOR CHANGES

The core architecture — provider abstraction, pure deterministic engine, phased MVP scope, the ✓/⚠ scientific-honesty framework — is sound and does not need to be re-designed. This is not a rejection of the approach. It is a rejection of treating the current document as implementation-ready, because it contains one unstated hydrological assumption load-bearing enough to matter, one near-certain production bug, and one unresolved product question big enough to change the schema.

## Exact change list before implementation begins

**Blocking (must resolve before Part 5's migration is written):**
1. Explicit tenancy decision — single-tenant-per-deployment vs. genuine multi-tenant — and the resulting schema/role-model change this implies (§1, §7).
2. State the GEE `scale`/`maxPixels` policy per index and what happens at the boundary (reject vs. flagged degradation) (§5, §8).
3. Add the missing "closed catchment / no lateral groundwater flow" assumption to Part 4 and Part 10, with guidance for flagging high-permeability or fractured-terrain catchments (§2).

**Must-fix before M0's migration (cheap now, expensive later):**
4. `catchment.geometry` → `GEOMETRY(MULTIPOLYGON, 4326)`, not `POLYGON` (§4).
5. Add an explicit area-bound and vertex-count cap for catchment geometry, analogous to `FarmPolygon`'s existing bounds (§4).
6. Remove or justify `water_balance_result.weights_version_id` — currently an unexplained field on a table that isn't a weighted composite (§6).
7. Add the missing CGWB raw-ingestion staging table implied by Part 8/M3's prose but absent from Part 5's schema (§6).

**Must-fix before M1/M2 close (methodology-level, not schema-level):**
8. Re-scope the Curve Number row in Part 4 as regionally qualified, not a general claim (§2).
9. Apply the same short-baseline-window caveat already correctly written for climate resilience to the recharge-stress module, which currently inherits the same flaw without the same disclosure (§2).
10. Decide, explicitly, whether `storage_change_mm` ships as a quantitative headline number or a qualitative descriptor for MVP, given it can never be calibrated in MVP for a generic customer (§2).
11. Either integrate recharge-structure capture into the water-balance `Q` term or explicitly document why it's excluded — currently neither (§2).
12. Add a rough GEE compute-cost estimate per representative report, and state whether GEE quota is shared with or isolated from Service 1 (§5, §8).

**Should-fix, strong recommendation, not blocking:**
13. Add one golden-dataset regression test per major hydrology module against literature already cited in Part 4 (§10).
14. Re-evaluate whether shapefile/KML upload belongs in MVP rather than Phase 2 (§9).
15. Name the terrain-distortion risk to SAR water detection explicitly in Part 4/Part 10, even if the correction itself is deferred (§3).
16. Add a named future-review checkpoint for the shared-enum coupling pattern once Service 3 is scoped (§10).

**Re-review trigger:** once items 1–12 are addressed, this returns to the panel for a second pass focused only on those changes — not a full re-review. Items 13–16 do not block that second pass.
