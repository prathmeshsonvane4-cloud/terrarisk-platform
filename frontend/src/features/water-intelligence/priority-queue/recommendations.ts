import { ordinal } from "../format-water-report";
import { numberField } from "../raw-inputs";
import { describeResolutionFlags } from "../resolution-flags";
import type { WaterReportHistoryItem } from "../use-water-report-history";

export type RecommendationSeverity = "high" | "medium" | "low" | "info";

export type RecommendationCategory =
  | "needs_first_report"
  | "needs_field_visit"
  | "needs_validation"
  | "unexpected_behaviour"
  | "declining_trend"
  | "stable";

export interface Recommendation {
  category: RecommendationCategory;
  severity: RecommendationSeverity;
  title: string;
  /** Why this was flagged — the reasoning, not just a label. */
  why: string;
  /** The specific satellite-derived number(s) behind the "why" — never a
   * bare score. Every recommendation must be traceable to a real,
   * already-computed field. */
  evidence: string;
  /** Plain-language confidence, derived from the same fields the report
   * dashboard already shows (recharge_stress.raw_inputs.confidence,
   * water_balance.data_completeness/calibration_status) — never a new,
   * separately-invented confidence number. */
  confidence: string;
  /** What the engineer should actually do next. Never omitted — a
   * recommendation with no action is just a score with extra steps. */
  action: string;
}

const LOW_CONFIDENCE_THRESHOLD = 50; // matches insights.ts's own "confidence < 50" rule
const LOW_DATA_COMPLETENESS_THRESHOLD = 50; // matches insights.ts's own threshold
const STRESS_SCORE_SWING_THRESHOLD = 20; // points, on the 0-100 stress_score scale
const DECLINING_TREND_RUN_COUNT = 3;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** Which of the three recharge-stress sub-factors is driving the score —
 * used to give a field-specific action instead of a generic "go check it
 * out." All three come from recharge_stress.raw_inputs, the exact same
 * source the dashboard's own factor cards already read
 * (app/(app)/catchments/[id]/water-reports/page.tsx). */
function dominantStressFactor(rawInputs: Record<string, unknown>): "rainfall" | "vegetation" | "surface_water" | null {
  const rainfall = numberField(rawInputs, "rainfall_stress");
  const vegetation = numberField(rawInputs, "vegetation_stress");
  const surfaceWater = numberField(rawInputs, "surface_water_stress");
  const scored = [
    { key: "rainfall" as const, value: rainfall },
    { key: "vegetation" as const, value: vegetation },
    { key: "surface_water" as const, value: surfaceWater },
  ].filter((entry): entry is { key: "rainfall" | "vegetation" | "surface_water"; value: number } => entry.value !== null);
  if (scored.length === 0) return null;
  return scored.reduce((max, entry) => (entry.value > max.value ? entry : max)).key;
}

function confidenceLabel(confidence: number | null): string {
  if (confidence === null) return "Confidence not available for this run.";
  if (confidence < LOW_CONFIDENCE_THRESHOLD) return `Low (${Math.round(confidence)}%) — few usable satellite observations this period.`;
  return `${Math.round(confidence)}%`;
}

/**
 * Turns a catchment's real report history into a small set of concrete
 * recommendations — never a bare score (docs/WELL_Labs_Raichur_Founder_Review_2026.md
 * mission: "Never output only a score. Always output an actionable
 * recommendation."). Every rule reads only fields the backend already
 * computes and persists (WaterBalanceResult/RechargeStressScore); nothing
 * here calls a new endpoint or invents a number. Deterministic and pure
 * — same history in, same recommendations out, same discipline
 * insights.ts already established for the single-report case.
 *
 * `history` must be newest-first (the shape water-reports/history
 * already returns).
 */
export function deriveRecommendations(history: WaterReportHistoryItem[]): Recommendation[] {
  if (history.length === 0) {
    return [
      {
        category: "needs_first_report",
        severity: "high",
        title: "No water report yet",
        why: "This catchment has never had a water report generated, so it isn't part of programme monitoring yet.",
        evidence: "No satellite-derived water balance or recharge-stress data exists for this catchment.",
        confidence: "N/A — nothing has been computed yet.",
        action: "Trigger a water report for this catchment to bring it into monitoring.",
      },
    ];
  }

  const recommendations: Recommendation[] = [];
  const [latest, previous] = history;
  const confidence = numberField(latest.recharge_stress.raw_inputs, "confidence");

  // Data-quality / trustworthiness flags — checked first, since a
  // recommendation built on low-confidence data should say so before
  // anything else about that data is trusted.
  const lowConfidence = confidence !== null && confidence < LOW_CONFIDENCE_THRESHOLD;
  const lowCompleteness = latest.water_balance.data_completeness < LOW_DATA_COMPLETENESS_THRESHOLD;
  const hasResolutionFlags = latest.water_balance.resolution_flags.length > 0;
  if (lowConfidence || lowCompleteness || hasResolutionFlags) {
    const reasons: string[] = [];
    if (lowCompleteness) reasons.push(`only ${latest.water_balance.data_completeness.toFixed(0)}% of the usual satellite images were usable this period (likely cloud cover)`);
    if (lowConfidence) reasons.push(`confidence in this result is only ${Math.round(confidence ?? 0)}%`);
    if (hasResolutionFlags) reasons.push(describeResolutionFlags(latest.water_balance.resolution_flags));
    recommendations.push({
      category: "needs_validation",
      severity: lowCompleteness || lowConfidence ? "high" : "medium",
      title: "Needs field validation",
      why: `This result is less reliable than usual: ${reasons.join("; ")}.`,
      evidence: `Usable satellite coverage ${latest.water_balance.data_completeness.toFixed(0)}%, confidence ${confidence !== null ? `${Math.round(confidence)}%` : "unavailable"}${hasResolutionFlags ? ` — ${describeResolutionFlags(latest.water_balance.resolution_flags)}` : ""}.`,
      confidence: confidenceLabel(confidence),
      action:
        "Re-run the water report once more cloud-free satellite images are available, and check this catchment's condition on the ground before acting on this result.",
    });
  }

  // High/very-high recharge stress — the direct "go look at this place"
  // signal, same stress_band the dashboard already surfaces, with a
  // factor-specific action rather than a generic one.
  if (latest.recharge_stress.stress_band === "high" || latest.recharge_stress.stress_band === "very_high") {
    const dominant = dominantStressFactor(latest.recharge_stress.raw_inputs);
    // Plain-language names for the demo/field audience — "surface_water"
    // reads as jargon, "surface water" doesn't.
    const factorLabel: Record<"rainfall" | "vegetation" | "surface_water", string> = {
      rainfall: "rainfall shortfall",
      vegetation: "vegetation stress",
      surface_water: "surface water decline",
    };
    const factorEvidence: Record<"rainfall" | "vegetation" | "surface_water", string> = {
      rainfall: `Rainfall over the recent period was ${latest.recharge_stress.rainfall_anomaly_ratio !== null ? `${Math.round(latest.recharge_stress.rainfall_anomaly_ratio * 100)}%` : "an unknown fraction"} of the normal amount for this time of year, based on 30 years of satellite rainfall records.`,
      vegetation: `Vegetation greenness, as read from satellite imagery, is at ${latest.recharge_stress.vci?.toFixed(0) ?? "an unknown level"}% of what's normal for this time of year — lower means more crop/vegetation stress.`,
      surface_water: `The amount of visible surface water (ponds, tanks, canals) is at the ${latest.recharge_stress.surface_water_trend !== null ? ordinal(latest.recharge_stress.surface_water_trend) : "an unknown"} percentile of this catchment's own satellite-monitoring history — i.e. lower than most past readings.`,
    };
    const factorAction: Record<"rainfall" | "vegetation" | "surface_water", string> = {
      rainfall: "Cross-check against local rain-gauge records — this may reflect a real regional shortfall, not a local issue specific to this catchment.",
      vegetation: "Verify crop condition and irrigation access on the ground.",
      surface_water: "Verify canal, tank, or pond water levels on the ground.",
    };
    recommendations.push({
      category: "needs_field_visit",
      severity: latest.recharge_stress.stress_band === "very_high" ? "high" : "medium",
      title: latest.recharge_stress.stress_band === "very_high" ? "Very high recharge stress" : "High recharge stress",
      why: `This catchment's recharge stress is ${latest.recharge_stress.stress_band === "very_high" ? "very high" : "high"} (${Math.round(latest.recharge_stress.stress_score)}/100)${dominant ? `, mainly because of ${factorLabel[dominant]}` : ""}.`,
      evidence: dominant ? factorEvidence[dominant] : "No single satellite signal could be isolated as the main driver for this run.",
      confidence: confidenceLabel(confidence),
      action: dominant ? factorAction[dominant] : "Schedule a field visit to assess ground conditions.",
    });
  }

  // Unexpected swing between the two most recent runs — a real change
  // detector, not a threshold on one snapshot. Only evaluated when a
  // previous run actually exists.
  if (previous) {
    const scoreDelta = latest.recharge_stress.stress_score - previous.recharge_stress.stress_score;
    if (Math.abs(scoreDelta) >= STRESS_SCORE_SWING_THRESHOLD) {
      const previousConfidence = numberField(previous.recharge_stress.raw_inputs, "confidence");
      recommendations.push({
        category: "unexpected_behaviour",
        severity: "medium",
        title: scoreDelta > 0 ? "Stress score jumped sharply" : "Stress score dropped sharply",
        why: `Recharge stress moved from ${Math.round(previous.recharge_stress.stress_score)} to ${Math.round(latest.recharge_stress.stress_score)} (${scoreDelta > 0 ? "+" : ""}${Math.round(scoreDelta)} points) between the ${formatDate(previous.generated_at)} and ${formatDate(latest.generated_at)} runs.`,
        evidence: `Storage change moved from ${previous.water_balance.storage_change_band.replace(/_/g, " ")} to ${latest.water_balance.storage_change_band.replace(/_/g, " ")}.`,
        confidence: confidenceLabel(confidence !== null && previousConfidence !== null ? Math.min(confidence, previousConfidence) : confidence),
        action:
          "Confirm this reflects a real event (rainfall, a completed intervention, or a genuine drawdown) rather than a data or boundary issue, before relying on this trend.",
      });
    }
  }

  // Sustained decline over 3+ consecutive runs — the "before vs after"/
  // structure-monitoring signal: a single bad run can be noise, three in
  // a row is a trend worth prioritising.
  if (history.length >= DECLINING_TREND_RUN_COUNT) {
    const recent = history.slice(0, DECLINING_TREND_RUN_COUNT);
    const values = recent.map((item) => item.water_balance.storage_change_mm);
    const allKnown = values.every((value): value is number => value !== null);
    // `values` is newest-first (history's own order). A genuine decline
    // over time means each OLDER run's value is larger than the one
    // after it — i.e. the array itself is strictly increasing in index
    // order (index 0 = newest = smallest, last index = oldest = largest).
    const strictlyDeclining = allKnown && values.every((value, index) => index === 0 || value > values[index - 1]);
    if (strictlyDeclining) {
      recommendations.push({
        category: "declining_trend",
        severity: "medium",
        title: "Sustained decline in storage change",
        why: `Storage change has declined for ${DECLINING_TREND_RUN_COUNT} consecutive runs: ${[...values].reverse().map((v) => v.toFixed(0)).join(" -> ")} mm.`,
        evidence: `Dates: ${[...recent].reverse().map((item) => formatDate(item.generated_at)).join(", ")}.`,
        confidence: confidenceLabel(confidence),
        action: "This is a sustained decline, not a single-run fluctuation — prioritise this catchment for a field visit or a recharge-structure review.",
      });
    }
  }

  if (recommendations.length === 0) {
    recommendations.push({
      category: "stable",
      severity: "info",
      title: "On track",
      why: "No stress, data-quality, or trend flags for the latest run.",
      evidence: `Recharge stress ${latest.recharge_stress.stress_band.replace(/_/g, " ")} (${Math.round(latest.recharge_stress.stress_score)}/100), storage change ${latest.water_balance.storage_change_band.replace(/_/g, " ")}.`,
      confidence: confidenceLabel(confidence),
      action: "No action needed right now — continue routine monitoring.",
    });
  }

  return recommendations;
}

const SEVERITY_RANK: Record<RecommendationSeverity, number> = { high: 0, medium: 1, low: 2, info: 3 };

/** The queue's own sort key — the highest-severity recommendation a
 * catchment has, so a catchment with any "high" flag always outranks one
 * with only "medium"/"info" flags, regardless of how many it has. */
export function highestSeverity(recommendations: Recommendation[]): RecommendationSeverity {
  return recommendations.reduce<RecommendationSeverity>(
    (worst, recommendation) => (SEVERITY_RANK[recommendation.severity] < SEVERITY_RANK[worst] ? recommendation.severity : worst),
    "info",
  );
}

export function compareBySeverity(a: Recommendation[], b: Recommendation[]): number {
  return SEVERITY_RANK[highestSeverity(a)] - SEVERITY_RANK[highestSeverity(b)];
}
