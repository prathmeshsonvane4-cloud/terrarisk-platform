# Climate Intelligence Data Model

**Status:** living document — created 13 Sep 2026 (evidence-aware roadmap, Phase B).
**Scope:** the persisted data behind every TerraRisk assessment in both services: results, their inputs, their lineage, and their validation.
**Authority:** the SQLAlchemy models under `backend/app/models/` and the migrations under `backend/alembic/versions/`. Where this document and the code disagree, the code is right and this document is a bug.

---

## 1. Why this document exists

TerraRisk is moving from an inference pipeline — acquire, compute, emit a score — to a system that says whether the evidence behind a score is sufficient for the decision being made. That depends on the data model recording not only *what* was computed but *what it rests on* and *how far it has been checked*.

This document describes that model as it stands, and marks what is not built yet.

---

## 2. Entity overview

```
                 ┌──────────────────────┐
                 │   config_weight      │  versioned weights + floor threshold
                 └─────────┬────────────┘
                           │ FK
   SERVICE 1 (farm)        │                 WATER INTELLIGENCE (catchment)
 ┌──────────────────┐      │               ┌──────────────────────────┐
 │   risk_score     │◄─────┘               │  water_balance_result    │
 │  (append-only)   │                      │  (append-only)           │
 └───┬──────────────┘                      └───────────┬──────────────┘
     │ FK                                              │ same run,
 ┌───▼──────────────┐                      ┌───────────▼──────────────┐
 │ risk_factor_score│                      │  recharge_stress_score   │
 └──────────────────┘                      └──────────────────────────┘
         ▲                                              ▲
         │   (result_table, result_id) — polymorphic, no FK
         │                                              │
 ┌───────┴──────────────────────────────────────────────┴───────┐
 │  evidence_record     one row per input a result depended on    │
 │  validation_run      one row per validation pass over a result │
 │    └─ validation_finding   (FK, cascade)                       │
 └────────────────────────────────────────────────────────────────┘

 satellite_observation   cached monthly series per farm/catchment (Service 1 cache)
```

| Table | Kind | Written by | Mutability |
|---|---|---|---|
| `risk_score`, `risk_factor_score` | Result | `reporting/report_generator.py` | Append-only |
| `water_balance_result`, `recharge_stress_score` | Result | `hydrology/water_report_generator.py` | Append-only |
| `satellite_observation` | Input cache | Service 1 pipeline | Insert; reused across runs |
| `config_weight` | Configuration | Seed scripts | New row per version, never edited |
| `evidence_record` | Lineage | Both pipelines, same transaction as the result | Append-only |
| `validation_run`, `validation_finding` | Validation | Both pipelines (`source='pipeline'`); `scripts/backfill_validation.py` (`source='backfill'`) | Append-only |

---

## 3. Lineage — `evidence_record`

One row per input a result depended on. Two kinds:

- **`observation`** — a series read from a remote-sensing product.
- **`parameter`** — a constant the method assumes: a Curve Number, a threshold, a weight, a fallback score.

| Column | Meaning |
|---|---|
| `result_table`, `result_id` | Which result this input belongs to |
| `quantity` | The input in the method's vocabulary: `et_monthly_mm`, `curve_number`, `ndvi_baseline` |
| `source` | Earth Engine collection id; the defining module for a parameter; `config_weight:<id>` for a configured value |
| `product_version` | As the publisher states it — `Collection 6.1`, `2.0 Final`, `1.4` |
| `band` | Band name, or the index formula for a derived index |
| `units` | Units of the value *as delivered to the engine* (e.g. mm per calendar month, not the product's mm per 8-day composite) |
| `value` | Scalar value of a parameter. Null for a series |
| `native_resolution_m`, `requested_scale_m`, `resampled` | Product pixel size, the scale Earth Engine was asked for, and whether they differ |
| `reducer` | How pixels became a number — `unweighted mean over polygon after unmask(0)` |
| `temporal_aggregation` | Masking and compositing, in words |
| `period_start`, `period_end` | The window this input covers |
| `observations_expected`, `observations_used` | e.g. 36 months expected, 34 usable |
| `acquisition_dates` | Scene dates that fed the series |
| `retrieval` | `fetched` for this run, or `cache` if reused from an earlier retrieval |
| `known_limitations` | Product caveats, open product defects, location-specific flags, known method defects |
| `validation_status` | `unvalidated` · `cross_checked` · `field_validated` |
| `spec_verified_on` | When the product specification was checked against its catalog; null if never |

Every value describing *how* a number was produced is imported from the provider or engine module that actually uses it (`provenance/lineage.py`), never restated. If a provider changes a scale or threshold, the lineage changes with it.

---

## 4. Validation — `validation_run` and `validation_finding`

A run records one pass of the physical validation harness (`backend/app/services/validation/`) over one result: the harness version, the agro-climatic zone it validated against, counts of checks run and skipped, error and warning counts, and whether it failed.

Findings record each outcome: check name, severity (`error` · `warning` · `info`), the observed value, the expected range in words, the message, and the source of the bound.

- **`error`** — physically or arithmetically impossible (runoff exceeding rainfall; a negative term; an impossible index value).
- **`warning`** — possible but outside the literature envelope for the zone (ET at 105% of rainfall in a semi-arid catchment).
- **`info`** — context, including every check that *could not run*. These are persisted deliberately.

`harness_version` is bumped whenever a check, envelope, tolerance or zone rule changes, so a finding can always be read against the rules that produced it.

---

## 5. Honesty rules the schema encodes

These are design constraints, not conventions. Each is enforced by code, a test, or a database constraint.

1. **There is no "plausibility checked" validation level.** Passing a literature envelope is not validation; a value inside it has only failed to look broken. `evidence_record.validation_status` admits exactly `unvalidated`, `cross_checked` and `field_validated`, enforced by a database `CHECK` constraint. Today every input to every result is `unvalidated`.
2. **Null is "not recorded"; an empty list is "recorded, none".** `acquisition_dates` is null for MODIS ET and Sentinel-1 surface water, because the hydrology provider does not return scene dates. It is never written as `[]`, which would claim no scenes were used.
3. **No provenance is reconstructed for results that pre-date it.** A result computed before migration `0012` has no evidence rows, and the lineage API returns `provenance_recorded: false` with a note explaining why. The parameters those results used — including a Curve Number that changed during the hydrology audit — cannot be recovered from stored values.
4. **Validation findings may be backfilled, and say so.** They can be derived honestly from stored values. Backfilled runs carry `source='backfill'` and an INFO finding recording that the zone came from observed rainfall rather than the 30-year climatology a pipeline run uses.
5. **A result and its lineage commit together or not at all.** Evidence and validation rows are written in the same transaction as the result.
6. **A skipped check is recorded, not dropped.** `checks_skipped` and INFO findings make a check that never ran distinguishable from one that passed.

---

## 6. Vocabulary storage

Evidence and validation vocabularies (`kind`, `validation_status`, `severity`, `result_table`, `source`) are **strings behind `CHECK` constraints**, not native Postgres enum types. Every other enum in this schema is a native type.

The reason is change cost. Each value added to a native enum needs an `ALTER TYPE ... ADD VALUE` migration, and forgetting one fails silently until the first insert (see `0010_extend_existing_enums`). The evidence vocabulary will grow through the remaining roadmap phases. The constraints are generated from the Python enums in `app/models/enums.py`, and `test_schema_ddl.py` asserts both the model constraints and migration `0012` admit exactly those values.

---

## 7. What each pipeline records

### Service 1 — farm climate risk (`risk_score`)

| Observations | Parameters |
|---|---|
| NDVI, MNDWI, NDMI — report window and 8-year seasonal baseline | Factor weights and floor threshold (`config_weight:<id>`) |
| Monthly rainfall (CHIRPS) | Band thresholds (25 / 50 / 75) |
| 30-year rainfall climatology | Neutral score for an uncomputable factor (50) |
| JRC surface-water occurrence | Rainfall anomaly window, baseline years, minimum baseline samples, cloud probability threshold |

Validation: ingestion checks over every input series.

### Water Intelligence (`water_balance_result`, `recharge_stress_score`)

| Result | Observations | Parameters |
|---|---|---|
| Water balance | Monthly rainfall, daily rainfall, monthly ET (MOD16A2) | Curve Number, initial abstraction ratio, storage-change band thresholds, closed-catchment assumption |
| Recharge stress | Monthly rainfall, climatology, NDVI (window and baseline), SAR surface water (window and baseline) | Factor weights, neutral score, baseline years, minimum samples, SAR water threshold, cloud probability threshold |

Validation: water balance physics and zone plausibility plus input series checks on the balance; input series checks on recharge stress.

---

## 8. Reading lineage

| Endpoint | Returns | Access |
|---|---|---|
| `GET /api/v1/reports/{risk_score_id}/lineage` | One `ResultLineageResponse` | Same guard as the report |
| `GET /api/v1/catchments/{catchment_id}/water-reports/lineage` | Lineage for both results of the latest completed run | Same roles, ownership rule and 404s as the report |

Lineage is **not yet rendered in either report**. The report's output is redesigned in the confidence, sufficiency and decision phases, and rendering it now would mean building it twice.

---

## 9. Known gaps

| Gap | Consequence | Where it is addressed |
|---|---|---|
| Hydrology provider returns no scene or composite dates | ET and SAR lineage has `acquisition_dates` null | Needs a provider contract change; not scheduled |
| No DEM is read | `high_relief_terrain` cannot be emitted; SAR terrain caveat is recorded as "not assessed" | Open (audit finding 6) |
| Polymorphic references have no cascade | Deleting a result would orphan its lineage | Application code never deletes results; the test suite sweeps orphans at session end |
| Service 1 results before Phase B | No lineage and no backfilled validation | Superseded by recomputing affected assessments after the JRC fix |
| Cross-product ET check not wired | No input is `cross_checked` | Awaits the uncertainty-propagation phase |

---

## 10. Roadmap additions to this model

Recorded here so the model is designed forward, not patched later. Not built.

- **Model confidence vs decision sufficiency** — two distinct fields per assessment, with the reason evidence is inadequate when it is.
- **Decision output** — the recommended action (PROCEED / VERIFY / WAIT / ESCALATE / ABSTAIN) with the stakes it was computed for: loan amount and reversibility as explicit, persisted inputs.
- **Observation policy** — per factor: the dominant uncertain input, the alternative source, the bounded expected effect, retrieval cost, and the recommendation.
- **Evidence decision log** — per assessment: evidence available and missing, what the policy recommended, whether it was acted on, and the final decision.
- **Uncertainty** — interval or distribution per input and per result, replacing point estimates with a confidence number attached at the end.
