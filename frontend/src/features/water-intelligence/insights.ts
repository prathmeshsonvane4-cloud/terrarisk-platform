import type { WaterReportDetailResponse } from "./use-latest-water-report";
import { numberField } from "./raw-inputs";

/**
 * Derives short, human-readable observations from an already-fetched
 * WaterReportDetailResponse — no LLM call, no new endpoint, nothing
 * beyond simple threshold comparisons over real, already-persisted
 * fields (this ticket's own "using the existing response only"
 * instruction, read literally). Each rule cites the real field it's
 * derived from in its own comment so a reader can trace every sentence
 * back to a number the backend actually computed — the same
 * explainability discipline RiskFactorScore.raw_inputs already
 * establishes, applied to plain-language generation instead of a
 * structured breakdown.
 *
 * Deterministic and pure: the same report always produces the same
 * insights, and every insight is directly traceable to a real field —
 * never a generic/canned line unconnected to this catchment's actual
 * numbers (Product Design v2: no placeholder content, ever).
 */
export function deriveWaterReportInsights(report: WaterReportDetailResponse): string[] {
  const insights: string[] = [];
  const { water_balance: waterBalance, recharge_stress: rechargeStress } = report;

  // storage_change_mm: the water balance equation's residual (P - ET - Q
  // = dS). A negative value means this period drew down more than
  // rainfall replenished — the literal "recharge below rainfall" case.
  if (waterBalance.storage_change_mm !== null && waterBalance.rainfall_mm !== null) {
    if (waterBalance.storage_change_mm < 0) {
      insights.push(
        `Recharge is below rainfall this period — the water balance shows a net storage deficit of ${Math.abs(waterBalance.storage_change_mm).toFixed(0)} mm.`,
      );
    } else if (waterBalance.storage_change_mm > 0) {
      insights.push(
        `Recharge exceeds losses this period — storage increased by an estimated ${waterBalance.storage_change_mm.toFixed(0)} mm.`,
      );
    }
  }

  // stress_band: the composite recharge-stress classification.
  if (rechargeStress.stress_band === "high" || rechargeStress.stress_band === "very_high") {
    insights.push(
      `Groundwater stress is ${rechargeStress.stress_band === "very_high" ? "very high" : "high"} for this catchment.`,
    );
  } else if (rechargeStress.stress_band === "moderate") {
    insights.push("Groundwater stress is moderate for this catchment.");
  } else if (rechargeStress.stress_band === "low") {
    insights.push("Groundwater stress is low — conditions appear relatively stable.");
  }

  // surface_water_trend: current surface-water extent's percentile
  // position within its own historical series (0-100). Framed relative
  // to its own history, matching the backend's own documented meaning
  // of "trend" here (recharge_stress.py: current-relative-to-own-history
  // standing, not a fitted slope).
  if (rechargeStress.surface_water_trend !== null) {
    if (rechargeStress.surface_water_trend >= 60) {
      insights.push("Surface water is stable to above its own historical norm.");
    } else if (rechargeStress.surface_water_trend <= 30) {
      insights.push("Surface water presence is below its historical norm for this catchment.");
    } else {
      insights.push("Surface water presence is broadly typical of this catchment's own history.");
    }
  }

  // rainfall_anomaly_ratio: actual recent rainfall / same-months' 30-yr
  // normal. 1.0 = exactly normal.
  if (waterBalance.rainfall_mm !== null && rechargeStress.rainfall_anomaly_ratio !== null) {
    if (rechargeStress.rainfall_anomaly_ratio < 0.75) {
      insights.push(
        `Recent rainfall is running well below its 30-year seasonal normal (${Math.round(rechargeStress.rainfall_anomaly_ratio * 100)}% of normal).`,
      );
    } else if (rechargeStress.rainfall_anomaly_ratio > 1.25) {
      insights.push(
        `Recent rainfall is running well above its 30-year seasonal normal (${Math.round(rechargeStress.rainfall_anomaly_ratio * 100)}% of normal).`,
      );
    }
  }

  // cgwb_category: block-scale government context, never blended into
  // the score itself (recharge_stress.py's own explicit rule) — surfaced
  // here as context only, worded to avoid implying it drove the number
  // above.
  if (rechargeStress.cgwb_category) {
    insights.push(
      `CGWB reports this area's block-scale groundwater category as "${rechargeStress.cgwb_category}"` +
        (rechargeStress.cgwb_category_as_of
          ? ` (as of ${new Date(rechargeStress.cgwb_category_as_of).getFullYear()}).`
          : "."),
    );
  }

  // data_completeness: fraction of usable cloud-free composites behind
  // the water-balance figures above — a caveat on confidence, not a
  // separate finding.
  if (waterBalance.data_completeness < 50) {
    insights.push(
      `Data completeness for this period is low (${waterBalance.data_completeness.toFixed(0)}%) — treat these mm figures as indicative, not precise.`,
    );
  }

  // calibration_status: always "uncalibrated" at MVP (WaterBalanceResult's
  // own docstring) — stated plainly rather than silently implied.
  if (waterBalance.calibration_status === "uncalibrated") {
    insights.push("This water balance has not yet been checked against field measurements — treat mm figures as directional.");
  }

  const confidence = numberField(rechargeStress.raw_inputs, "confidence");
  if (confidence !== null && confidence < 50) {
    insights.push(
      `Recharge-stress confidence is low (${confidence.toFixed(0)}%) — few usable vegetation observations were available for this period.`,
    );
  }

  return insights;
}
