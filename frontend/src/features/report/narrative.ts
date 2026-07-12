import type { components } from "@/lib/api/schema";

import { FACTOR_LABELS, type FactorScore } from "./drivers";

type ReportResponse = components["schemas"]["ReportResponse"];

const BAND_PHRASE: Record<ReportResponse["overall_band"], string> = {
  low: "low",
  moderate: "moderate",
  high: "high",
  very_high: "very high",
};

function rainfallClause(factors: FactorScore[]): string | null {
  // The rainfall-vs-normal ratio is stored identically on the drought
  // factor's raw inputs — one factual clause about the season, only if
  // the engine actually had the data.
  const drought = factors.find((f) => f.factor === "drought_risk");
  const ratio = drought?.raw_inputs?.["rainfall_ratio_to_normal"];
  if (typeof ratio !== "number" || !Number.isFinite(ratio)) return null;
  const percent = Math.round(ratio * 100);
  if (percent < 95) return `recent seasonal rainfall was ${percent}% of the long-term normal`;
  if (percent > 105) return `recent seasonal rainfall was ${percent}% of the long-term normal (above average)`;
  return `recent seasonal rainfall was close to the long-term normal (${percent}%)`;
}

/**
 * Decision-support narrative composed STRICTLY from engine outputs: the
 * overall band/score, the highest- and lowest-scoring factors (an
 * arithmetic fact, not a causal claim), and the stored rainfall-to-normal
 * ratio. Fixed templates — nothing here states a cause the backend didn't
 * compute.
 */
export function reportNarrative(report: ReportResponse): string {
  const sorted = [...report.factors].sort((a, b) => b.value - a.value);
  const highest = sorted[0];
  const lowest = sorted[sorted.length - 1];

  const sentences: string[] = [
    `This farm shows ${BAND_PHRASE[report.overall_band]} overall climate risk (score ${Math.round(report.overall_score)}/100).`,
  ];

  if (highest && lowest && highest.factor !== lowest.factor) {
    const clauses = [
      `The highest-scoring factor is ${FACTOR_LABELS[highest.factor].toLowerCase()} at ${Math.round(highest.value)}/100`,
    ];
    const rainfall = rainfallClause(report.factors);
    if (rainfall) clauses.push(rainfall);
    sentences.push(`${clauses.join("; ")}.`);
    sentences.push(
      `${FACTOR_LABELS[lowest.factor]} scores lowest at ${Math.round(lowest.value)}/100.`,
    );
  }

  sentences.push(
    `Assessment confidence is ${Math.round(report.confidence)}%, reflecting how many usable satellite observations were available.`,
  );

  return sentences.join(" ");
}
