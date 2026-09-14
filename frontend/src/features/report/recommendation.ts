import type { components } from "@/lib/api/schema";

import { factorDriverText, FACTOR_LABELS, type FactorScore } from "./drivers";
import { reportNarrative } from "./narrative";

type ReportResponse = components["schemas"]["ReportResponse"];
type RiskBand = components["schemas"]["RiskBand"];

/**
 * Below this confidence, the recommended action carries an "indicative
 * only" qualifier (Product Design v2 §1.1 principle P7). Not part of the
 * versioned risk-engine config — a fixed product-level constant, exactly
 * like BAND_THRESHOLDS. 70% was chosen as a conservative cut: below it,
 * on average more than 10 of the 36 expected optical months were
 * unusable, which is enough missing history that a lending decision
 * should not lean on the number alone. Documented for founder review in
 * DECISIONS.md — adjustable without touching any other logic.
 */
export const RECOMMENDATION_CONFIDENCE_THRESHOLD = 70;

/**
 * Fixed posture per band (Product Design v2 §1.1 P7) — deterministic,
 * never generated. The credit decision remains the bank's; this states a
 * review posture, not a lending instruction.
 */
const ACTION_BY_BAND: Record<RiskBand, string> = {
  low: "Standard appraisal. No climate-driven escalation required.",
  moderate: "Standard appraisal. Note the leading risk factor below in the loan file.",
  high: "Escalate to branch-manager review. Consider risk-adjusted terms.",
  very_high: "Refer to branch manager. Recommend independent field verification before sanction.",
};

/** When no overall score could be estimated — mirrors backend
 * recommendation.py `NO_OVERALL_SCORE_ACTION` verbatim. */
export const NO_OVERALL_SCORE_ACTION =
  "No overall risk score could be estimated from the available satellite evidence. Do not rely on this report for a credit decision; verify the farm in the field.";

export interface PrimaryDriver {
  factor: FactorScore["factor"];
  label: string;
  value: number;
  text: string;
}

export interface Recommendation {
  /** Reuses the existing pinned narrative — one summary, never two
   * competing descriptions of the same score. */
  summary: string;
  /** Every factor scored High or Very High, worst first — empty when
   * nothing scored that severely, never padded with a lower factor to
   * avoid an empty list. */
  primaryDrivers: PrimaryDriver[];
  action: string;
  isIndicativeOnly: boolean;
}

/**
 * The Recommendation block (Product Design v2 §1.1 P7, §7.5): Assessment
 * Summary / Primary Drivers / Recommended Action, derived ONLY from
 * already-computed backend outputs (overall_band, confidence, factor
 * scores) — no new inference, no invented advice.
 */
export function buildRecommendation(report: ReportResponse): Recommendation {
  const primaryDrivers = report.factors
    .filter((f): f is FactorScore & { value: number } => f.value !== null)
    .filter((f) => f.band === "high" || f.band === "very_high")
    .sort((a, b) => b.value - a.value)
    .map((f) => ({
      factor: f.factor,
      label: FACTOR_LABELS[f.factor],
      value: f.value,
      text: factorDriverText(f),
    }));

  if (report.overall_band === null) {
    // No composite could be estimated: there is no band posture to give.
    return { summary: reportNarrative(report), primaryDrivers, action: NO_OVERALL_SCORE_ACTION, isIndicativeOnly: true };
  }

  const isIndicativeOnly = report.confidence < RECOMMENDATION_CONFIDENCE_THRESHOLD;
  const posture = ACTION_BY_BAND[report.overall_band];
  const action = isIndicativeOnly
    ? `Indicative only — limited satellite data available (data completeness ${Math.round(report.confidence)}%). ${posture}`
    : posture;

  return {
    summary: reportNarrative(report),
    primaryDrivers,
    action,
    isIndicativeOnly,
  };
}
