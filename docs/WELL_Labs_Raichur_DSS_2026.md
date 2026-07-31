# From Dashboard to Decision Support — Raichur DSS Addendum

**Date:** 31 July 2026
**Scope:** Extends docs/WELL_Labs_Raichur_Founder_Review_2026.md with research targeted specifically at weekly field/programme decisions, and the resulting recommendation engine design.
**Evidence tiers:** **[S]** = sourced. **[D]** = a design decision made here, not a public fact.

## What's newly evidenced (this round)

- **WELL Labs' own established practice is "satellite-classify, then field-validate."** With IIT Delhi, Gram Vaani, and Prarambha, WELL Labs built a single-vs-double-cropped land-use classifier for Raichur, validated against real field data collected by **10 trained enumerators using a QField mobile app** (GPS field-boundary delineation + structured cropping surveys), April–May 2023, covering the 2021–2022 agricultural years. Reported accuracy: **96–99% overall, 83–93% producer accuracy for the double-cropped class**, standard error under 2.5% **[S: [How Often are India's Farming Patterns Changing?](https://welllabs.org/indian-agriculture-land-use-cover-maps-raichur-iit-delhi/)]**. This is the clearest public evidence that WELL Labs treats a remote-sensing output as provisional until field-checked, and reports its own accuracy honestly rather than asserting it — the same posture this product's `calibration_status`/`data_completeness`/`confidence` fields already take.
- **No public evidence of a specific weekly review or escalation cadence was found**, despite three separate targeted searches. Stated as a confirmed absence, not assumed to be zero — the recommendation engine below is therefore built around *when a number itself changes or looks wrong*, not around a fabricated weekly meeting structure this product has no evidence for.

## What this means for the recommendation engine

Every recommendation category below maps to a real, evidenced pattern rather than a generic "AI insight":

| Recommendation category | Evidenced by |
|---|---|
| **Needs field validation** (low confidence / low data completeness / resolution flags) | WELL Labs' own field-validation practice for satellite classifications **[S]**, and this product's own pre-existing `calibration_status`/`confidence`/`data_completeness` fields (already computed, never surfaced as an action before this) |
| **Needs a field visit** (high/very-high recharge stress, with a factor-specific reason) | Matches the drone survey's own pattern of translating a detected satellite signal (elevation, canal defect) into a concrete field follow-up **[S, docs/WELL_Labs_Raichur_Founder_Review_2026.md Part 1]** |
| **Unexpected behaviour** (a sharp run-over-run swing) | Direct evidence-gap fill for the Founder Review's own Decision support = 3/10 finding — "is this better or worse than it used to be" was previously unanswerable at all |
| **Declining trend** (3+ consecutive runs worsening) | Same evidence base as "before vs after intervention" and recharge-structure siting quality concerns already documented **[S, Founder Review Part 1/4]** |
| **Programme summary** | Built from real `generated_at` timestamps only — deliberately NOT framed as "monthly" unless real report pairs actually span two different calendar months, since no monthly trigger cadence is evidenced anywhere |

## What was deliberately not built

- **A literal "escalation" workflow** (assigning a recommendation to a person, marking it resolved) — no evidence any such process exists today, and inventing one would be designing an organisational process WELL Labs hasn't described, not supporting one they have.
- **Any new database table or column.** Every recommendation is derived, at read time, from `WaterBalanceResult`/`RechargeStressScore` fields that already exist and are already returned by `GET /catchments/{id}/water-reports/history` — this is a new client-side reasoning layer over existing data, not a platform redesign.
