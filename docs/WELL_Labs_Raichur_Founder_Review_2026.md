# Water Intelligence, Through a WELL Labs Founder's Eyes — Raichur Programme Review

**Date:** 31 July 2026
**Frame:** Not "can TerraRisk generate a water report" — "if I opened this tomorrow for the Raichur programme, would I actually use it?"
**Evidence tiers:** **[S]** = sourced to a public WELL Labs page/partner page cited inline. **[R]** = recommendation/design decision made in this document, not a public fact — never asserted as something WELL Labs does or wants.

---

# Part 1 — What WELL Labs is ACTUALLY doing in Raichur (public evidence only)

## 1. What is WELL Labs actually doing in Raichur?

Two distinct, named workstreams, not one generic "programme":

- **Raichur Transformation Lab / Rural Futures — the technical/hydrology track.** Centred on **Distributary 10 of the Narayanpur Right Bank Canal (NRBC)**, run on the "Five Levers" systems-transformation framework (irrigation infrastructure, community institutions, labour/mechanisation, agricultural inputs, market access) **[S: [Five Levers](https://welllabs.org/five-levers-systems-transformation-in-raichur/)]**. Three concrete sub-programmes sit inside it:
  - **Community Hydrology Programme** — citizen-science capacity building. Four workshops, November 2024–September 2025, cohort of 35 aspiring "community hydrologists." Workshop 1 taught well water-depth measurement and mapped **800+ dugwells and borewells**. Workshop 3 (20–22 May, Devadurga taluk) focused on **water budgeting and water-balance estimation**, with 31 participants deliberately drawn **7 from dryland areas, 13 from head-end canal regions, 4 from tail-end, 3 "neerugantis" (traditional local water distributors), 4 from Prarambha** (a long-standing north-Karnataka rural-development NGO and named collaborator) **[S: [Building Community Expertise in Hydrology](https://welllabs.org/community-hydrology-programme-insights/), [From Science to Strategy](https://welllabs.org/community-hydrology-3/)]**.
  - **Drone-based canal survey.** WELL Labs flew drones over **64 km² of canal command area** in Raichur, generating orthophotos and DEMs, digitising the field-channel network, and identifying **specific canal sections with blockages or structural damage**. The DEM revealed **centimetre-level slope changes** — in some locations, low-lying elevation differences were shown to directly **reduce water availability for tail-end farmers** **[S: [Solution to a Decades-Old Challenge in Canal-Irrigated Regions](https://welllabs.org/solution-to-challenges-in-canal-irrigated-regions/)]**.
  - **Remote-sensing partnership (IHE Delft + ACIWRM, Krishna basin, 2023–2027).** LULC-based village water accounts intended for participatory local planning **[S: [Remote Sensing for Communities](https://welllabs.org/well-labs-partnership-ihe-delft-aciwrm-water-remote-sensing-data/)]**.
  - **WUCS (Water User Cooperative Societies) strengthening** — funded by CLARE's CLARITY project, IHE Delft, Nvidia CSR, and DCB Bank CSR. WUCS are the legally-mandated farmer-led water-governance body in Karnataka, but public materials describe them as struggling with "mismanagement, weak institutional support, and lack of farmer participation" **[S: [Reimagining WUCS in Karnataka](https://welllabs.org/reimagining-wucs-karnataka-water-governance/)]**.
- **Futures Research — the participatory/socio-ecological track.** A "Raichur 2047: Imagining Flourishing Futures" visioning workshop (July 2025, with Prarambha) and the "Raichur Jigsaw," a participatory game-based aspiration-capture tool (January 2026) **[S: [Designing Climate Resilient Futures in Raichur](https://welllabs.org/designing-climate-resilient-futures-raichur/)]**. Separately, a land-restoration pilot and socio-ecological documentation effort in the specific village of **Mukkannal**, run with Prarambha and ATREE **[S: [Raichur Land Restoration Pilot](https://welllabs.org/restoring-raichur-degraded-land-pilot-how-we-studied-local-context/), [Journey Mapping — Mukkannal](https://welllabs.org/journey-mapping-interview-mukkanal-raichur-farmers-future/)]**.

**Government context that shapes both tracks:** the Karnataka government is running its own **canal automation programme** — concrete lining, automated gates, SCADA, IoT devices, soil-moisture sensors — which WELL Labs explicitly frames as an opportunity to embed farmer-group water control into, not a competing effort **[S: [Reimagining WUCS](https://welllabs.org/reimagining-wucs-karnataka-water-governance/)]**. And on 26 March 2026, WELL Labs convened a multi-stakeholder roundtable with ACIWRM and Stanford's Doerr School of Sustainability specifically on **soil-moisture decision support** — the stated finding was that soil moisture remains "weakly integrated" into irrigation planning, drought monitoring, and watershed management **despite advances in remote sensing** **[S: [Soil Moisture Decision Support](https://welllabs.org/soil-moisture-decision-support-karnataka/)]** — i.e., WELL Labs has publicly named this as an open, unsolved gap as recently as four months before this review.

## 2. What decisions are engineers/technical staff making every week?

Inferred from the above, not asserted as literal fact: where the 4 loggers and 191-well network should be extended next; how to reconcile manually-collected canal/streamflow readings from community hydrologists into "hydroclimatic models" **[S]**; how to QA drone orthophoto/DEM data and translate detected canal defects into a defensible tail-end-inequity case; how to design each successive community-hydrology workshop so head-end/tail-end/dryland farmer representation stays balanced (workshop 3's 13/4/7 split looks deliberate, not incidental); and — per the March 2026 roundtable — how to actually operationalise soil moisture into a decision a WUCS or a government partner can act on, which by their own account is still unsolved.

## 3. What data do they collect?

**Manual/field:** well water-depth readings (rope-and-tape method) across 800+ dugwells/borewells; manual canal and natural-stream flow observations by community hydrologists; 4 logger time series in Distributary 10 **[S]**.
**Aerial:** drone orthophotos + DEM over 64 km² of canal command **[S]**.
**Remote sensing (via the IHE Delft/ACIWRM partnership, not confirmed in-house):** LULC classification feeding village-level water accounts in the Krishna basin **[S]**.
**Participatory/qualitative:** stratified workshop input (head-end/tail-end/dryland farmers, neerugantis); visioning-workshop and Jigsaw-game input; socio-ecological documentation in named villages like Mukkannal **[S]**.

## 4. What GIS layers do they use? (inferred from documented outputs)

Distributary 10 command-area boundary; drone orthophoto mosaic and DEM/slope layer over 64 km²; a digitised field-channel network; a canal-defect point layer (blockages/structural damage); a well-point inventory (191 + 800); an LULC classification raster for the Krishna basin. **No GIS software or platform is publicly named anywhere I searched** (no QGIS, ArcGIS, or Earth Engine mention specific to WELL Labs) — stated as a confirmed absence of evidence, not a claim they don't use one.

## 5. What satellite products are likely involved?

**[R], explicitly an inference, not a fact:** consistent with the LULC/village-water-account methodology and the broader remote-sensing-for-community-hydrology literature (and consistent with TerraRisk's own GEE pipeline), Sentinel-1/2-class optical+SAR and a DEM product are the plausible inputs. WELL Labs has not publicly named a specific satellite product for Raichur.

## 6. What are the bottlenecks? (all evidenced)

- **Instrumentation coverage:** 4 loggers / 191 wells against a 5,500 km² target — roughly 1% **[S]**.
- **Manual field survey limits — WELL Labs' own stated reason for going to drones**: "field teams find it tough to navigate dense overgrowth, thorny bushes, and waterlogged patches," face snake-bite and slipping risk, can't work through extreme heat or rain, and manual surveys "can be incomplete or inaccurate" — drones cover 400 ha/day against "several weeks" for a manual survey **[S: Solution to a Decades-Old Challenge]**.
- **WUCS institutional weakness** — legally mandated, publicly described as mismanaged with low farmer participation **[S]**.
- **Soil moisture named, as of March 2026, as still "weakly integrated"** into irrigation/drought/watershed decision-making despite remote-sensing advances — an open, self-acknowledged gap, not a solved problem **[S]**.
- **Recharge-structure siting quality**, in WELL Labs' general (not Raichur-specific) public commentary: check dams, farm ponds and trenches "often fall short due to issues like suboptimal site selection and siltation" **[S]**. No Raichur-specific before/after monitoring publication was found — stated as an evidence gap in the public record, not a claim about what WELL Labs does or doesn't do internally.

## 7. Which parts are still manual?

Canal/streamflow reading by community hydrologists ("manually monitoring") **[S]**; well water-depth measurement (rope/tape, described as "simple, low-cost") **[S]**; the water-budgeting/crop-water-budget exercise itself, run as a facilitated workshop, with no public evidence of a supporting software tool **[S]**. Tellingly, the **one field-survey task WELL Labs has already automated is canal surveying itself** — replacing weeks of hazardous manual walking with a single day of drone flight **[S]**. That is the exact category TerraRisk's satellite pipeline already operates in, at a scale (whole-district, recurring, zero field crew) drones structurally cannot reach.

---

# Part 2 — Gap Analysis: would a WELL Labs engineer actually use Service 2?

Grounded in a direct inventory of every current screen (not a guess):

| Screen | What it shows today | Would I use this weekly? | Why / why not |
|---|---|---|---|
| **Catchments list** (`/catchments`) | Name, area, delineation-method label per row. Nothing else. | **No.** | Managing dozens of catchments across Distributary 10 and beyond needs, at a glance, which ones are stressed and which need a re-run — this shows neither. No filter by taluk/district, no map thumbnail, no sort. |
| **Catchment detail** (`/catchments/[id]`) | Name, area, method, created date, "Trigger water report," and a minimal "latest report" summary (band chips only). | Acceptable as a landing page. | Fine for what it is — the real gap is one level down. |
| **Water report dashboard** (`/catchments/[id]/water-reports`) | A single snapshot: water balance (4 stat tiles + one grouped bar chart, not a time series), recharge-stress score/band + 3 factor cards, one surface-water percentile bar, groundwater band chips + CGWB context, rule-based insight bullets, PDF/JSON export. | **No, not for the decisions WELL Labs actually makes.** | Every number here is a **snapshot of right now.** WELL Labs' own documented workflow is fundamentally comparative and longitudinal: workshop 3 exists because the same water situation looks completely different for head-end vs. tail-end vs. dryland farmers **[S]**; the drone survey's headline finding is a **before/after, place-to-place comparison** (elevation differences reducing tail-end water availability) **[S]**; recharge-structure evaluation is inherently a **before/after** question **[S]**. A dashboard that can only say "here is one place, right now" cannot answer a single one of the three questions WELL Labs has publicly said it cares about. |
| **Select Area workflow** (this session's own prior work) | Cascading State→District→Taluka→Village picker, boundary preview, Use Entire Village / Draw Inside Village. | **Yes, this one holds up.** | It directly removes a real friction (drawing every catchment by hand) and uses real, source-agnostic administrative data. No change recommended here. |

**The single largest, most evidence-backed gap:** there is **no history and no comparison view anywhere in the product.** Confirmed by direct inspection of the backend: `WaterBalanceResult` and `RechargeStressScore` are explicitly modelled as **append-only** — every triggered report writes new rows, nothing is ever overwritten — but the only read endpoint (`GET /catchments/{id}/water-reports`) discards everything except the single most recent run, and no endpoint or screen anywhere lets two catchments, or two runs of the same catchment, be seen side by side. **The data to answer WELL Labs' actual questions already exists in the database. Nothing in the product surfaces it.**

Two more concrete, smaller findings from the same inspection: `resolution_flags` (per-run caveats) and `baseline_window` (which climatology a stress score was benchmarked against) are both returned by the API but never rendered anywhere — a WELL Labs hydrologist checking whether a score is trustworthy has no way to see either.

---

# Part 3 — Founder Review: scores

Scored 1–10, brutally, against what a WELL Labs founder would actually need for the Raichur programme specifically — not against a generic SaaS bar.

| Dimension | Score | Why |
|---|---|---|
| **Usability** | 5/10 | Clean, uncluttered, no jargon-hostile UI — but the catchments list gives no operational signal, and there is no way to ask the two questions ("how does this compare to that" / "how has this changed") that the Raichur programme's own public materials say matter most. |
| **Scientific usefulness** | 4/10 | The water-balance and recharge-stress methodology is sound and honestly caveated (uncalibrated status, confidence, data completeness are all shown) — genuinely more careful than most vendors in this space. But science that can only be read as a single snapshot, with `baseline_window` hidden, is scientifically incomplete for a programme whose own methodology is comparative and longitudinal. |
| **Hydrology quality** | 6/10 | P−ET−Q=dS is the right model, and the explicit "closed_catchment_assumed," "resolution_flags," and non-blended CGWB-context fields show real hydrological discipline. Docked because none of that discipline reaches the screen. |
| **GIS quality** | 4/10 | WELL Labs is already doing centimetre-level DEM slope analysis and canal-defect digitisation via drone **[S]** — genuinely sophisticated GIS work. TerraRisk's current GIS ceiling is an administrative-boundary polygon. That is a real capability gap, not a UI gap, and it's the most honest score on this table. |
| **Decision support** | 3/10 | The lowest score, deliberately. A dashboard that answers "what is the water situation here, today" but not "is here worse than there" or "is this better than it was" does not support the decisions Raichur's own public record says get made. |
| **Field usefulness** | 5/10 | Select Area genuinely helps a field officer who doesn't want to hand-draw a boundary. Everything downstream of that assumes reliable connectivity and a desk, which does not match WELL Labs' own description of field conditions (drones exist specifically because field access in this terrain is hard). |
| **Engineering quality** | 7/10 | The highest score, and deserved — append-only result tables, explicit caveat fields, honest confidence/calibration language, a real source-agnostic boundary loader. The foundation is unusually solid for what's built on top of it. The gap in Part 2 is a genuine product gap sitting on genuinely good engineering, not a symptom of bad engineering. |

**Overall verdict:** the engineering and the underlying science are good enough to trust. What's missing is not more hydrology — it's making the hydrology that already exists answerable to the two questions WELL Labs has told the public, repeatedly and specifically, that it actually asks: *is this place worse off than that place, and is this place better or worse than it used to be.*

---

# Part 4 — Raichur decision-support features (evidence-filtered)

Only features directly supported by Part 1's findings are listed. Each is checked against real evidence, not assumed.

| Candidate feature | Supported by | Verdict |
|---|---|---|
| **Multi-catchment comparison** (e.g. head-end village vs. tail-end village, side by side) | Workshop 3's deliberate head/tail/dryland stratification **[S]**; the drone survey's own headline finding is exactly this comparison, done manually with DEM data **[S]** | **Include — directly evidenced, highest priority** |
| **Water-report history / trend over time for one catchment** | The community hydrology programme's stated goal is "water balances and crop water budgets **for irrigation scheduling decisions**" **[S]** — a decision made repeatedly over a season, not once; recharge-structure evaluation is inherently before/after **[S]** | **Include — directly evidenced** |
| Village prioritisation (rank villages by water stress) | No direct evidence WELL Labs currently does this in Raichur; plausible given the Five Levers framework but not documented | **[R] Not included — not evidenced, deferred** |
| Intervention (check dam / farm pond) before-vs-after monitoring | General WELL Labs commentary that structures "fall short due to siting/siltation" exists **[S]**, but no Raichur-specific monitoring programme was found | **Partially covered** by the history/trend feature above, once a structure's catchment exists in the system — no separate feature built |
| Canal command-area / tail-end equity monitoring | Directly evidenced by the drone survey finding **[S]** | **Covered by comparison feature** (a head-end and a tail-end catchment, compared) rather than a bespoke canal-specific tool — TerraRisk has no canal-command polygon layer to build a dedicated tool on top of yet |
| Rainfall anomaly | Already computed and shown per-catchment today | Not new — already exists |
| Groundwater recovery tracking | Satellite cannot see groundwater level directly (established repeatedly in this codebase's own prior research); WELL Labs' own groundwater data comes from the 191-well/4-logger network, which TerraRisk has no access to | **[R] Not included — would require inventing a capability satellite doesn't have** |
| Tank / check-dam surface-water monitoring dashboard | Plausible extension of the existing MNDWI/SAR pipeline, but no Raichur-specific tank inventory or WELL Labs request for this was found | **[R] Not included this round — no catchment-level tank layer exists to monitor yet, would need new data first** |

**What gets built:** one capability — **surfacing the water-report history that already exists in the database, and letting it be viewed either as one catchment's trend over time, or as multiple catchments side by side** — because it is the only feature on this list that is directly evidenced by *three separate* pieces of Part 1 research (workshop stratification, drone tail-end finding, and the "for irrigation scheduling decisions" framing), uses zero new data, and requires no platform redesign.

---

# Part 5/6 — Implementation and verification

Implemented immediately following this document: one new backend endpoint exposing the already-persisted, already-append-only water-report history, and one new frontend feature (per-catchment trend view + multi-catchment comparison) built on it. See commit history and the verification notes reported in chat for what was built, tested, and deployed — each commit kept separate per the instruction to commit each improvement independently.

---

## Sources

- [WELL Labs — Why Raichur Needs Systems Transformation (Five Levers)](https://welllabs.org/five-levers-systems-transformation-in-raichur/)
- [WELL Labs — Building Community Expertise in Hydrology: Insights from Raichur](https://welllabs.org/community-hydrology-programme-insights/)
- [WELL Labs — From Science to Strategy: A Community Approach to Hydrology](https://welllabs.org/community-hydrology-3/)
- [WELL Labs — Solution to a Decades-Old Challenge in Canal-Irrigated Regions](https://welllabs.org/solution-to-challenges-in-canal-irrigated-regions/)
- [WELL Labs — Remote Sensing for Communities: Partnership with IHE Delft and ACIWRM](https://welllabs.org/well-labs-partnership-ihe-delft-aciwrm-water-remote-sensing-data/)
- [WELL Labs — Reimagining WUCS in Karnataka](https://welllabs.org/reimagining-wucs-karnataka-water-governance/)
- [WELL Labs — Soil Moisture Decision Support for Land & Water Management in Karnataka](https://welllabs.org/soil-moisture-decision-support-karnataka/)
- [WELL Labs — Designing Climate Resilient Futures in Raichur](https://welllabs.org/designing-climate-resilient-futures-raichur/)
- [WELL Labs — Raichur Land Restoration Pilot: How We Studied The Local Context](https://welllabs.org/restoring-raichur-degraded-land-pilot-how-we-studied-local-context/)
- [WELL Labs — Journey Mapping to Plan the Future of Mukkanal's Farmers](https://welllabs.org/journey-mapping-interview-mukkanal-raichur-farmers-future/)
