import type { components } from "@/lib/api/schema";

export type FactorScore = components["schemas"]["FactorScoreResponse"];
export type RiskFactorName = components["schemas"]["RiskFactor"];

export const FACTOR_LABELS: Record<RiskFactorName, string> = {
  vegetation_stability: "Vegetation stability",
  water_availability: "Water availability",
  drought_risk: "Drought risk",
  flood_exposure: "Flood exposure",
};

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function percentOfNormal(ratio: number): string {
  return `${Math.round(ratio * 100)}% of the seasonal normal`;
}

function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th";
  return `${n}${suffix}`;
}

/** Stated when a factor could not be computed (rule-engine-v2 onward).
 * Mirrors backend report_text.py `_NOT_COMPUTED_TEXT` verbatim. */
const NOT_COMPUTED_TEXT: Record<RiskFactorName, string> = {
  vegetation_stability:
    "Not computed — too little same-month satellite history to rank the current vegetation reading.",
  water_availability:
    "Not computed — no usable surface-water, crop-moisture or rainfall signal for this farm and period.",
  drought_risk: "Not computed — neither the Vegetation Condition Index nor the rainfall anomaly could be derived.",
  flood_exposure: "Not computed — no usable surface-water history or rainfall anomaly.",
};

/** rule-engine-v1 stored a neutral 50 for a factor it could not compute. For
 * those rows the statement is true, and names whose it was. */
const LEGACY_NEUTRAL = "a neutral score of 50 was applied by the previous engine version";

/**
 * One plain-language driver sentence per factor, composed ONLY from the
 * engine's persisted raw_inputs — fixed templates around backend numbers,
 * never invented causes. Anything absent from raw_inputs is simply not
 * mentioned (sparse data produces a shorter sentence, not a guess).
 */
export function factorDriverText(factor: FactorScore): string {
  const raw = factor.raw_inputs as Record<string, unknown>;
  if (factor.value === null) return NOT_COMPUTED_TEXT[factor.factor];

  switch (factor.factor) {
    case "vegetation_stability": {
      const percentile = asNumber(raw.ndvi_percentile);
      const current = asNumber(raw.current_ndvi);
      if (percentile === null || current === null) {
        return `Not enough usable satellite history for a vegetation comparison — ${LEGACY_NEUTRAL}.`;
      }
      return `Current NDVI ${current.toFixed(2)} sits at the ${ordinal(Math.round(percentile))} percentile of the same calendar month across the baseline years.`;
    }
    case "water_availability": {
      const parts: string[] = [];
      const mndwi = asNumber(raw.mndwi_current);
      const ndmi = asNumber(raw.ndmi_current);
      const ratio = asNumber(raw.rainfall_ratio_to_normal);
      if (mndwi !== null && ndmi !== null) {
        parts.push(
          `Surface-water (MNDWI ${mndwi.toFixed(2)}) and crop-moisture (NDMI ${ndmi.toFixed(2)}) indices compared against this farm's own range`,
        );
      }
      if (ratio !== null) {
        parts.push(`recent rainfall at ${percentOfNormal(ratio)}`);
      }
      if (parts.length === 0) {
        return `Not enough usable data for the water sub-signals — ${LEGACY_NEUTRAL}.`;
      }
      return `${parts.join("; ")}.`;
    }
    case "drought_risk": {
      const vci = asNumber(raw.vci);
      const ratio = asNumber(raw.rainfall_ratio_to_normal);
      const parts: string[] = [];
      if (vci !== null) {
        parts.push(`Vegetation Condition Index at ${Math.round(vci)} (0 = driest year observed, 100 = best)`);
      }
      if (ratio !== null) {
        parts.push(`recent rainfall at ${percentOfNormal(ratio)}`);
      }
      if (parts.length === 0) {
        return `Not enough usable data for the drought sub-signals — ${LEGACY_NEUTRAL}.`;
      }
      return `${parts.join("; ")}.`;
    }
    case "flood_exposure": {
      const jrc = asNumber(raw.jrc_water_occurrence_percent);
      const ratio = asNumber(raw.rainfall_ratio_to_normal);
      const parts: string[] = [];
      if (jrc !== null) {
        parts.push(
          `Historical surface-water occurrence on this land is ${jrc.toFixed(1)}% (JRC satellite record, 1984–2021)`,
        );
      }
      if (ratio !== null) {
        parts.push(`recent rainfall at ${percentOfNormal(ratio)}`);
      }
      if (parts.length === 0) {
        return `Not enough usable data for the flood sub-signals — ${LEGACY_NEUTRAL}.`;
      }
      return `${parts.join("; ")}.`;
    }
  }
}
