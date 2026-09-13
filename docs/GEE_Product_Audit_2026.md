# Earth Engine Product Audit — September 2026

**Scope:** every remote-sensing product TerraRisk reads, checked for units, scale factors, valid ranges, no-data handling, compositing windows and temporal coverage.
**Method:** each product's Earth Engine catalog entry, then read-only probes against live Earth Engine where a catalog entry could not settle the question.
**Dates:** catalog checks 6 Sep 2026; live probes 6 and 13 Sep 2026.
**Machine-readable record:** `backend/app/services/validation/products.py`. This document explains it; the registry is what the code asserts against.

---

## Inventory

Six products are read. The platform has been described as ingesting ERA5-Land, SRTM and NASA POWER — **none of those are read anywhere in the codebase.** ERA5-Land appears in `Engineering_Blueprint_v1.md` §06 as an *alternative* to CHIRPS that was not chosen; SRTM and NASA POWER appear nowhere in code.

| Collection | Used for | Native res. | Coverage |
|---|---|---|---|
| `COPERNICUS/S2_SR_HARMONIZED` | NDVI, MNDWI, NDMI | 10 m (B11: 20 m) | 2017 – |
| `COPERNICUS/S2_CLOUD_PROBABILITY` | cloud masking | 10 m | 2015 – |
| `COPERNICUS/S1_GRD` | SAR surface water | 10 m | 2014 – |
| `MODIS/061/MOD16A2` | evapotranspiration | 500 m | 2001 – |
| `UCSB-CHG/CHIRPS/DAILY` | rainfall, climatology, runoff input | 5,566 m | 1981 – |
| `JRC/GSW1_4/GlobalSurfaceWater` | flood-exposure history | 30 m | Mar 1984 – Dec 2021 |

---

## Findings

| # | Product | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | JRC GSW | Occurrence read with a mask-weighted mean over a masked band — biased high twice over, feeds flood risk directly | **High** | **Fixed** |
| 2 | JRC GSW | Coverage end reported as 1 Jan 2021; dataset runs to 31 Dec 2021 | Low | **Fixed** |
| 3 | MOD16A2 | Mask at `< 32761` let 32701–32760 through; documented valid max is 32700 | Low | **Fixed** |
| 4 | CHIRPS | Negative/no-data guard on the daily path only, not monthly or climatology | Medium → Low | **Checked: not present** |
| 5 | CHIRPS | Sampled at 5,000 m against a 5,566 m grid; resampling undisclosed | Low | Open |
| 6 | (none) | No DEM read; `high_relief_terrain` is advertised in the API schema but can never be emitted | Medium | Open |
| 7 | JRC GSW | Occurrence measures water *presence*, not flood *proneness* — used directly as flood risk | Medium (semantic) | Open |

### 1 · JRC occurrence reducer — High, fixed

Google's catalog entry for this collection states that areas where water was never detected are **masked**, and that *"the mask value for the occurrence band is equal to the band value... so the dataset is double-counting the partial occurrence."*

`GeeProvider.get_water_history()` called a plain `reduceRegion(ee.Reducer.mean())`. That produces two compounding errors:

- **Wrong denominator.** Dry pixels are masked, so the mean runs over pixels that have ever been water, not over the polygon.
- **Wrong weighting.** Earth Engine reducers weight by mask, and here mask = value, so the result is Σx²/Σx rather than the mean.

The result feeds flood-exposure risk as-is, and a factor at ≥ 85 trips the floor rule that forces an assessment to HIGH.

**Measured on live polygons, before and after the fix:**

| Polygon | Old reducer | Corrected | Share of pixels ever water |
|---|---|---|---|
| Latur dryland, Shera | null → 0.0 | 0.00 | 0.00% |
| Manjara reservoir edge | **7.58** | **0.04** | 0.61% |
| Tungabhadra river edge | null → 0.0 | 0.00 | 0.00% |
| Maski-area square | **23.29** | **0.00** | < 0.01% |
| Ujani reservoir edge | **82.57** | **35.19** | 48.48% |

The bias vanishes only for a polygon containing no water at all — where the old null happened to fall back to the right answer. It is largest for a farm containing *a little* water, which is the realistic case. The Ujani figure sat 2.4 points under the floor-rule threshold.

**Fix:** `.unmask(0)` then `ee.Reducer.mean().unweighted()`. Guarded by a structural test.

**Consequence to act on:** every Service 1 assessment computed before this fix carries an inflated flood-exposure factor wherever the farm polygon touched any surface water. Those assessments are not recomputed by this change.

### 3 · MOD16A2 valid range — Low, fixed

The provider masked at `ET < 32761`, commented as excluding reserved fill codes. The catalog states codes 32761–32767 *"are excluded from Earth Engine assets"* already, so that guard was largely redundant, and it passed 32701–32760 — outside the documented valid range of −32767 to 32700 — as real ET. Now masks at `<= 32700`, and a test pins the provider constant to the registry's value so the two cannot drift.

### 4 · CHIRPS no-data asymmetry — checked, not present

The daily path filters negative values ("CHIRPS's own no-data convention"); the monthly and climatology paths `.sum()` with no guard. The catalog does not document the convention. **Probed directly:** 1,096 daily images over Latur and Raichur, June 2023 – June 2026 — zero negative pixels, fully unmasked.

No code was changed. The asymmetry is latent, not live, over the deployment area. If it ever appears, the new ingestion check on `rainfall_monthly_mm` fails with an ERROR on the negative total. **Re-check on any new geography.**

### 6 · No DEM, but a terrain flag is advertised — open

`catchment.resolution_flags` documents `high_relief_terrain` in the ORM model and the public API schema, and Blueprint v2 Part 4 and Part 9 risk #10 require it to disclose that the fixed −15 dB SAR water threshold degrades in hilly terrain. `_derive_resolution_flags()` takes area only. The disclosure is specified, advertised, and structurally impossible to emit.

---

## Stored production water balances — what is actually wrong

> **Correction, 13 Sep 2026.** An earlier version of this section said the Maski report "predates the ET fix and was never regenerated". That was wrong. The figures it relied on do not exist in production. The claim was made before production was checked, and it was also repeated in the message of commit `f17c514`.

### The Maski figures in the project brief

The brief quotes, for Maski (233.48 ha), over three years: rainfall 1,692.3 mm, ET 339.9 mm, runoff 688.1 mm, recharge 664.3 mm — **ET at 20% of rainfall**, at 97% confidence.

**Production holds five Maski water balances, and none match.** All five were computed 7 Aug 2026, put ET at 77–78% of rainfall and runoff at 15–17%, and pass every check in the harness:

| Computed | P | ET | Q | ΔS | ET / P |
|---|---|---|---|---|---|
| 7 Aug 12:26 | 1,692 | 1,300 | 283 | 110 | 77% |
| 7 Aug 14:23 | 1,730 | 1,348 | 263 | 118 | 78% |
| (three further runs repeat these two results) | | | | | |

The brief's figures share the same 1,692 mm of rainfall but carry **both** pre-audit defects: ET about 4× low (the MOD16A2 8-day-composite error) and a ~41% runoff coefficient from SCS-CN applied to monthly totals. They come from a run that predates the hydrology fixes, not from what production serves. They remain in the test suite as a regression fixture, because they are exactly what those defects produce.

An independent re-computation agrees with production: the current MOD16A2 code gives **499.6 mm** of ET on a Maski-area polygon for water year 2022-23, an ET/P of 0.82.

### Every catchment, validated

The deployed harness was run read-only inside the production container against the latest stored balance for each catchment (13 Sep 2026). Zone was taken from each catchment's annualised rainfall.

| | Count |
|---|---|
| Catchments | 142 |
| With a stored water balance | 135 |
| **Pass all plausibility checks** | **121** |
| ET ≥ 95% of rainfall | 13 |
| — of which ET exceeds rainfall outright | 6 |
| Annual rainfall outside the assigned zone | 1 |

**No stored balance shows the factor-of-four ET defect.** The earlier statement in this project that most catchments carried pre-fix numbers is also not supported: ET/P across the fleet sits between 63% and 109%.

**The real finding points the opposite way — ET too high, not too low.** Thirteen Raichur catchments have ET at 95–109% of rainfall, highest at Kanoor (109%), Yeddal Dinni (105%) and Jangamarhalli (104%). In a closed catchment ET cannot exceed rainfall. This matches what PML_V2 showed at Maski, and is consistent with **canal irrigation importing water** the balance has no term for. Because ΔS is the residual, those catchments report storage *loss* that may reflect irrigation rather than depletion. **Not verified** — whether these catchments lie in a Tungabhadra command area has not been checked.

129 of the 135 latest balances have no per-water-year breakdown stored. They pre-date that feature, and the Curve Number in force when they ran cannot be recovered from the stored row.

### A false positive in the harness

The identity guard (ΔS = P − ET − Q) fired an ERROR on **17** stored balances. That is not an engine regression. Production stores each term as `NUMERIC(10,2)`, so recomputing the identity from four independently rounded values drifts: the largest drift is exactly 0.0100 mm, and none exceed 0.02 mm. The guard's 0.01 mm tolerance was set for in-memory arithmetic.

**The live pipeline is unaffected** — it validates the engine's unrounded result before persistence. The false positive appears only when stored rows are re-validated. The tolerance has **not** been changed: see Decisions needed.

---

## Cross-product ET — a disagreement that needs a decision

Same polygon and year, second ET product:

| Product | ET | ET / P |
|---|---|---|
| MOD16A2 (current) | 499.6 mm | 0.82 |
| PML_V2 v018 (Ec + Es + Ei) | 811.5 mm | **1.33** |
| Symmetric relative difference | **48%** | |

Two MODIS-driven algorithms disagree by 48% on the same catchment-year. PML_V2 reports more ET than rainfall, which a closed catchment cannot do. Two hypotheses, not distinguished by anything here:

- **Irrigation import.** Raichur district is heavily canal-irrigated from the Tungabhadra system. If this polygon is in a command area, PML_V2 may be seeing irrigated ET the closed-catchment balance has no term for. *Not verified.*
- **Algorithm bias** for this land cover in one or both products.

**Independence is partial.** Both products are driven by MODIS inputs; agreement would show algorithm independence, not sensor independence.

**Coverage is partial.** PML_V2 v018 is deprecated and ends 27 Dec 2023. Its successor, `projects/pml_evapotranspiration/PML/OUTPUT/PML_V22a`, ends 26 Dec 2024 and — usefully — carries a `PET` band. Neither reaches the last 18–20 months of a current report window.

---

## What now runs on every water report

- **Ingestion assertions** on ET, monthly rainfall and daily rainfall: a hard physical range per value (ERROR) and a median plausibility band (WARNING). The median check is the one that catches a uniform scale error — the ET series with its 8-day-to-monthly conversion missing has no individually impossible value, and only its median gives it away.
- **Water balance plausibility** against the catchment's agro-climatic zone, derived from its own 30-year CHIRPS climatology: ET/P, runoff coefficient, |ΔS|/P, and annual rainfall consistency with the assigned zone.
- **Physical invariants:** non-negative terms, runoff ≤ rainfall, and the P − ET − Q = ΔS identity — the last explicitly a refactor guard. **It is not a closure test**: ΔS is defined as the residual, so the identity cannot fail on real data.

Findings are merged into one report, returned with the result, and logged at ERROR (arithmetic violation), WARNING (implausible) or INFO (clean). **They are not yet persisted** — that is item 5.

---

## Limits of this audit

- The Maski probe used an approximate polygon and a single water year.
- The zone envelopes in `validation/zones.py` are the author's reading of the published literature. **They are uncalibrated and have not been reviewed by a domain expert.** Every finding derived from them says so.
- Zone classification uses rainfall alone. The correct discriminator is the aridity index (P/PET), which needs PET — available from PML_V22a but not yet wired in.
- `COASTAL` is never inferred; a coastal catchment is currently validated against a moisture-zone envelope that omits tidal and saline effects.
- Sentinel-1 and Sentinel-2 specs were checked against the catalog but not probed live; no defect was suspected in how they are read.

## Decisions needed

1. **ET cross-product tolerance.** The check exists with no default. At 25% it fails Maski; it passes only near 50%. Which is it — and is a 48% disagreement acceptable ET uncertainty for a product going to a bank?
2. **Whether to wire PML_V22a live**, given it covers roughly the first half of a current report window.
3. **Recomputing Service 1 assessments** computed before the JRC fix, which carry an inflated flood-exposure factor wherever a farm polygon touched surface water. (Water balances do not need recomputing for the ET defect — see above.)
5. **The identity-guard tolerance for stored rows.** Proposed: keep 0.01 mm for in-memory results, and use 0.02 mm (four terms × 0.005 rounding) only when validating values read back from `NUMERIC(10,2)` columns. This is derived from storage precision, not widened to make the check pass — but you asked to decide tolerance changes, so it is unchanged.
6. **The 13 catchments with ET ≥ 95% of rainfall** — check them against Tungabhadra canal command areas before treating their storage-loss bands as real.
4. **The zone envelopes** — particularly the semi-arid ET/P floor of 0.55, set deliberately generous against a Budyko expectation near 0.95 for Raichur.
