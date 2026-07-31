import type { WaterReportHistoryItem } from "../use-water-report-history";
import type { Recommendation, RecommendationCategory } from "./recommendations";

const ZERO_COUNTS: Record<RecommendationCategory, number> = {
  needs_first_report: 0,
  needs_field_visit: 0,
  needs_validation: 0,
  unexpected_behaviour: 0,
  declining_trend: 0,
  stable: 0,
};

/** How many CATCHMENTS have at least one recommendation of each
 * category — not a raw recommendation count, which would double-count a
 * catchment that's flagged for both a field visit and validation and
 * make "3 catchments need a field visit" read as a bigger number than
 * it is. */
export function programmeSummaryCounts(recommendationsByCatchment: Recommendation[][]): Record<RecommendationCategory, number> {
  const counts = { ...ZERO_COUNTS };
  for (const recommendations of recommendationsByCatchment) {
    const categoriesPresent = new Set(recommendations.map((recommendation) => recommendation.category));
    for (const category of categoriesPresent) {
      counts[category] += 1;
    }
  }
  return counts;
}

export interface MonthOverMonthSummary {
  comparableCatchments: number;
  improved: number;
  declined: number;
  unchanged: number;
}

function yearMonth(iso: string): string {
  const date = new Date(iso);
  return `${date.getFullYear()}-${date.getMonth()}`;
}

/**
 * Compares each catchment's latest run against the most recent run from
 * a genuinely different calendar month, if one exists — deliberately
 * NOT a fabricated "monthly" cadence: no report-trigger schedule exists
 * anywhere in this system (reports are triggered on demand), so this
 * only counts a catchment when two of its real runs actually fall in
 * different calendar months, rather than assuming every catchment has
 * one (docs/WELL_Labs_Raichur_DSS_2026.md).
 */
export function summarizeMonthOverMonth(histories: WaterReportHistoryItem[][]): MonthOverMonthSummary {
  let improved = 0;
  let declined = 0;
  let unchanged = 0;

  for (const history of histories) {
    if (history.length === 0) continue;
    const [latest, ...rest] = history;
    const latestMonth = yearMonth(latest.generated_at);
    const priorMonthEntry = rest.find((item) => yearMonth(item.generated_at) !== latestMonth);
    if (!priorMonthEntry) continue;

    // Lower stress score is better — a negative delta is an improvement.
    const delta = latest.recharge_stress.stress_score - priorMonthEntry.recharge_stress.stress_score;
    if (delta < 0) improved += 1;
    else if (delta > 0) declined += 1;
    else unchanged += 1;
  }

  return { comparableCatchments: improved + declined + unchanged, improved, declined, unchanged };
}
