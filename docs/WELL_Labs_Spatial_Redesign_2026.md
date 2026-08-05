# Spatial-First Water Intelligence — Redesign & Alignment Re-Score

**Date:** 5 August 2026
**Trigger:** Direct feedback from Vivek Srinivasan (Co-founder, WELL Labs) on the TerraRisk Water Intelligence prototype: *"This is interesting. I wanted to ask why not represent this spatially?"*
**Scope:** Presentation layer only. No backend, API, database, Earth Engine, recommendation-logic, or priority-scoring change.

---

## Part A — Why the question was asked

Four pieces of public evidence explain why a WELL Labs founder would ask this first, and why it is a methodology observation rather than a UI preference.

**1. Their flagship tool is natively a GIS tool.** Jaltol launched (Nov 2021, ATREE/CSEI) as a **QGIS plugin** — users "work within this established GIS software rather than a custom interface," defining areas of interest with "boundary shapefiles" **[S1, S2]**. The team's default mental model for water data is a map canvas with layers. A list-and-detail-page tool is the unfamiliar shape, not the map.

**2. Their impact methodology is spatial by construction.** Jaltol's web app evaluates watershed interventions with a **difference-in-differences** design: change in a treatment village is compared against **a control village** over the same period, and "researchers must identify a similar village where no structure was built" **[S3, S4]**. Selecting a control village is irreducibly spatial — it requires seeing which villages are adjacent, comparable, and untreated. A dropdown cannot support this; a map can.

**3. Raichur's central problem is a spatial gradient.** WELL Labs' community hydrology workshops in Devadurga taluk deliberately convened farmers from **canal head-end (13), tail-end (4), and dryland areas (7)**, plus neeruganti water managers **[S5]**. "Head-end vs tail-end" describes position along a canal. It is invisible in a table sorted by score and self-evident on a map. Their programme's core question is *where along the system water stops arriving.*

**4. Their ground truth is already geographic.** Workshop participants "mapped over 800 dugwells and borewells across villages" **[S5]**.

### The actual gap this exposed

The previous UI (village → generate report → dashboard) forced the user to hold the geography in their head. A ranked list can say *Village X is stressed*. It cannot say:

- X sits between two healthy villages → likely a **local, fixable** cause.
- X is one of six contiguous tail-end villages failing together → a **canal-system** problem no single-village intervention will fix.
- Y is adjacent and similar to X but untreated → Y is a defensible **control village**.

That second class of insight is what changes programme action, and it exists only spatially. Notably, the prior alignment audit (`WELL_Labs_Alignment_Report_2026.md`) had already scored **GIS workflow alignment lowest of the five dimensions, at 50%** — the founder independently pointed at the same weakness.

---

## Part B — What changed

| Before | After |
| --- | --- |
| Village → Generate Report → Dashboard | District map → every monitored village visible at once → click for reading → drill into report |
| Stress band visible one village at a time | Every village coloured simultaneously by its existing band |
| Comparison = checkbox list on a table | Comparison = click villages on the map; selection drawn as a heavy outline *on the map* |
| Priority Queue row = a name | Priority Queue row = a name + **Locate on Map** |
| "No report yet" = a row state | "No report yet" = grey polygon, visibly distinct from the stress ramp |

**Implementation notes**

- One MapLibre GeoJSON source, one fill layer with a data-driven `match` expression on the band property. Adding a village adds a *feature*, not a source and two layers.
- Colours are **derived at module load from `STRESS_BAND_PDF_COLORS`** (`STRESS_BAND_MAP_COLORS` in `band-styles.tsx`), not re-typed. The chip, the PDF chip, and the map polygon cannot drift apart — there is exactly one place the emerald/amber/orange/red families are chosen. A unit test asserts this equality.
- "No report" uses a neutral grey deliberately **outside** the emerald→red ramp, so absence of data can never be misread as a mild-but-present reading.
- Popups are real anchored `maplibregl.Popup` instances with React content portalled in — so a reading visibly belongs to its polygon.
- The popup's "priority recommendation" is chosen with the Priority Queue's **own existing severity ordering** (`highestSeverity`), so map and queue can never disagree.
- Comparison reuses the existing `/catchments/compare?ids=` page unchanged.

**Nothing new is computed.** Scores, bands, recommendations, priorities, and confidence all come from the existing engine and existing endpoints.

### One honest constraint

`GET /catchments` returns no geometry, and `GET /admin-boundaries` is explicitly *"deliberately minimal, no geometry"* — only `GET /admin-boundaries/{id}` carries a polygon. With backend/API changes out of scope, the map draws every **monitored** village (one cached, permanently-fresh request each), not all 542 Raichur villages. Catchments drawn or uploaded freehand have no `admin_boundary_id` and therefore no polygon in any endpoint; they are surfaced in an explicit on-map note rather than given a fabricated location.

A future "every village in the district, monitored or not" view would need one bulk-geometry endpoint. That is a backend change, deliberately not made here.

---

## Part C — Alignment re-score

Same five dimensions, same evidence base, same scoring discipline as `WELL_Labs_Alignment_Report_2026.md`.

| Dimension | Before | After | Why it moved (or didn't) |
| --- | --- | --- | --- |
| **Scientific alignment** | 65% | 65% | **No change, correctly.** No input, equation, or threshold was touched. Any movement here would mean the redesign had quietly changed the science, which it must not. |
| **Hydrological alignment** | 60% | 60% | **No change, correctly.** Same mass-balance, same recharge-stress engine. |
| **Decision-support alignment** | 55% | 75% | The programme question WELL Labs actually asks — *where do teams go first, and is this village's problem shared by its neighbours?* — is now answerable without opening a report. Still docked: no published WELL Labs prioritisation output exists to validate the severity ordering against, which was the original reason for the low score and remains true. |
| **GIS workflow alignment** | 50% | 80% | The largest move, and the one Vivek's question targeted. Village-level choropleth, spatial selection, spatial comparison, and locate-from-queue now match how a QGIS-native team works **[S1, S2]**. Still docked: no canal-command layer, no DEM/slope, no LULC overlay, and no bulk district-wide village rendering — Jaltol integrates 10 m IndiaSAT LULC **[S3]**; TerraRisk shows administrative polygons only. |
| **Field-validation alignment** | 70% | 72% | Small, honest move only. "Needs validation" is now locatable on a map, which is genuinely how a field visit gets planned. But TerraRisk's outputs still have never been ground-truthed the way WELL Labs' own cropping classification was (QField, 10 enumerators, published 96–99% accuracy) **[S6]**. That gap is unchanged and is the reason this is not higher. |

### Overall: **60% → 70%**

*(Simple average of the five dimensions, same method as the original report.)*

**What this number means.** The redesign moved exactly the two dimensions it should have moved — how work is presented and decided on — and correctly moved neither of the two scientific dimensions. A redesign claiming to improve scientific alignment while touching only the presentation layer would be a false claim.

**What it still does not mean.** TerraRisk does not reproduce, replace, or validate against Jaltol or any WELL Labs methodology. The ceiling on GIS alignment is real: without canal-command geometry, LULC, and terrain layers, this is a village-polygon choropleth, not a watershed-planning GIS. The honest positioning is unchanged from the original report — **a wide-area, always-on screening layer that flags where WELL Labs' own more precise but scarcer methods should be pointed next** — now with the screening output presented in the form that programme actually reasons in.

---

## Sources

- **[S1]** [Jaltol — WELL Labs](https://welllabs.org/jaltol/)
- **[S2]** [Jaltol: Addressing the capacity bottleneck in rural water security — CSEI/ATREE](https://medium.com/centre-for-social-and-environmental-innovation/jaltol-addressing-the-capacity-bottleneck-in-rural-water-security-440dafa72894)
- **[S3]** [Evaluating Watershed Interventions Using Jaltol](https://welllabs.org/mel-toolbox-part-4/)
- **[S4]** [Jaltol Use Case: Tracking the Impact of Watershed Management](https://welllabs.org/jaltol-johad-tracking-impact-water-management-rajasthan/)
- **[S5]** [Building Community Expertise in Hydrology: Insights from Raichur](https://welllabs.org/community-hydrology-programme-insights/)
- **[S6]** [How Often are India's Farming Patterns Changing?](https://welllabs.org/indian-agriculture-land-use-cover-maps-raichur-iit-delhi/)
- [Why Raichur Needs Systems Transformation](https://welllabs.org/five-levers-systems-transformation-in-raichur/)
- [Press Release — Jaltol launch, November 2021](https://welllabs.org/press-release-jaltol-launch-november-2021/)
