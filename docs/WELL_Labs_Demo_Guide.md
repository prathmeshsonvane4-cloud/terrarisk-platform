# WELL Labs Demo Guide

**Date:** 31 July 2026
**Audience:** Founder of WELL Labs, 3-minute walkthrough
**Companion documents:** docs/WELL_Labs_Raichur_Founder_Review_2026.md (founder-lens critique this demo was built to answer), docs/WELL_Labs_Raichur_DSS_2026.md (recommendation-engine design), docs/WELL_Labs_Alignment_Report_2026.md (evidence-based validation against WELL Labs' own public methodology — read this before fielding scientific questions)

---

## 2-minute demo flow

1. **Log in as a Programme Admin.** The landing page (`/`) opens directly on Water Intelligence's own view — a one-line explanation of what the product does, then a live Priority Queue preview. No detour through Service 1's bank/farm content.
2. **Point at the Programme summary strip.** "This is every catchment we're monitoring, sorted by what needs attention first, not by name." Read the counts aloud (e.g. "1 needs a field visit, 1 has no report yet").
3. **Open the top card (highest priority).** Read the recommendation aloud, in order: **Priority → Reason → Satellite evidence → Confidence → Suggested action.** Emphasise: "This isn't a bare score — every flag tells you why, what the satellite actually saw, how much to trust it, and what to do next."
4. **Click through to that catchment's water report.** Show the Trend over time section: "This is real report-to-report history, not a projection — trigger a report today, in a month, and you'll see this catchment's own trajectory, not somebody else's."
5. **Open Compare** (from the Catchments list, select two). "This is the head-end/tail-end question your own Raichur team has already documented with drone surveys — we answer it with satellite, at wider coverage, faster, for a screening pass."
6. **Close on the honesty, not the technology.** Point at any "uncalibrated" or "confidence 62%" label on screen: "We say exactly how sure we are, every time, because a wrong confident answer is worse than a right cautious one."

## Talking points

- **What it is:** a satellite-only water-monitoring layer that turns rainfall, vegetation, and surface-water signals into a ranked list of which catchments need attention, with a reason and a next action for each — not a dashboard you have to interpret yourself.
- **Why it matters, in WELL Labs' own terms:** your own published materials say ground instrumentation in the Raichur Transformation Lab covers roughly 50 km² of a 5,500 km² target area. TerraRisk doesn't replace that network — it's the always-on, no-field-crew layer that can flag where the network's next visit should go.
- **Why it's trustworthy:** every recommendation is traceable to a real, already-computed satellite field — never a black-box score. Low-confidence or low-completeness results are flagged as needing field validation, the same discipline your own team already applies when ground-truthing satellite classifications.
- **What it doesn't claim:** it doesn't reproduce your internal models, and it isn't a replacement for the community hydrology network, the drone survey, or Jaltol. It shares inputs and intent with Jaltol specifically (both run on Google Earth Engine, both use rainfall/ET/surface-water/LULC) but is a different, complementary method, not a copy.

## Expected founder questions and concise answers

**"Is this the same as Jaltol?"**
No. Same underlying inputs and platform (Earth Engine, rainfall/ET/surface-water/LULC), different specific method and emphasis — Jaltol centres on crop-water-requirement budgeting for community planning; TerraRisk centres on a composite stress score for portfolio triage across many catchments at once. They're complementary, not duplicates.

**"How is 'recharge stress' different from what our community hydrologists measure?"**
Community hydrologists measure real water levels at real wells — ground truth. TerraRisk infers stress from satellite rainfall, vegetation, and surface-water signals — inference, not measurement. That's exactly why every stress score ships with a confidence figure and a "needs validation" flag when the underlying data is thin.

**"Has this been checked against our own data?"**
Not yet, and we say so plainly. No public WELL Labs dataset (the 191-well network, Jaltol's own outputs) was available to check TerraRisk's numbers against. That calibration is the highest-value next step, not something already done.

**"Why should I trust the surface-water reading specifically?"**
You shouldn't trust it any more than your own team trusts the same kind of data — your own Jaltol team has publicly said surface-water remote sensing has real limits and is adding a manual-input option because of it. TerraRisk applies the same caution.

**"What happens if I click 'Trigger a water report' on a real village right now?"**
A real Google Earth Engine job runs — real rainfall, ET, and surface-water data for that exact polygon, typically done in under a minute, and it never overwrites the previous run, so history builds up automatically.

**"Can this cover all of Raichur?"**
Architecturally yes — every state/district/taluka/village in the system is a data import, not a code change, and Karnataka/Raichur's real administrative boundaries are already loaded. Running it at full 5,500 km² scale is a scope and cost decision, not an engineering blocker.

## Known limitations (state these unprompted, don't wait to be asked)

- The composite 0–100 stress score is TerraRisk's own construction — no equivalent published WELL Labs score exists to validate it against.
- No TerraRisk output has been field-calibrated against real ground measurements yet (the water balance is explicitly labelled "uncalibrated").
- Village boundaries for Karnataka/Raichur (and Maharashtra/Latur) are OSM-sourced administrative polygons at state/district/taluka level, but village-level shapes are synthetic placeholder squares around a real point location, not real cadastral boundaries.
- GIS depth is currently at admin-boundary granularity — no canal-command layer, no DEM/slope analysis of the kind the drone survey produces.
- The Priority Queue's severity ranking has no published WELL Labs equivalent to check its ordering against.

## Future roadmap (described, not implemented in this engagement)

- **Calibration against real ground data** — ingest WELL Labs' own well/logger readings (with permission) and report the actual error margin per catchment, closing the single biggest scientific gap named above.
- **Canal-command / DEM layer** — a watershed/distributary-level catchment definition independent of administrative boundaries, closing the GIS gap the drone survey already fills at finer resolution.
- **Bulk village water accounts** — generate reports for every village in a district at once, matching the Jaltol/ACIWRM "water accounts for all villages" workflow instead of one catchment at a time.
- **Real cadastral village boundaries** — replace the synthetic placeholder squares once a licensed source (e.g. LGD/Bhuvan) is available.
- **Kannada localisation** of reports and recommendations for field-level use.

None of the above is built as part of this engagement, per its own explicit "no new features" constraint — they are named here only so the roadmap conversation has real, evidenced next steps ready if the founder asks "what's next."
