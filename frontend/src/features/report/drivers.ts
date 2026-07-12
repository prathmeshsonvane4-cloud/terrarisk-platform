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

/**
 * One plain-language driver sentence per factor, composed ONLY from the
 * engine's persisted raw_inputs — fixed templates around backend numbers,
 * never invented causes. Anything absent from raw_inputs is simply not
 * mentioned (sparse data produces a shorter sentence, not a guess).
 */
export function factorDriverText(factor: FactorScore): string {
  const raw = factor.raw_inputs as Record<string, unknown>;

  switch (factor.factor) {
    case "vegetation_stability": {
      const percentile = asNumber(raw.ndvi_percentile);
      const current = asNumber(raw.current_ndvi);
      if (percentile === null || current === null) {
        return "Not enough usable satellite history for a vegetation comparison — a neutral score was applied.";
      }
      return `Current NDVI ${current.toFixed(2)} sits at the ${ordinal(Math.round(percentile))} percentile of this farm's own 3-year range.`;
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
        return "Not enough usable data for the water sub-signals — a neutral score was applied.";
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
        return "Not enough usable data for the drought sub-signals — a neutral score was applied.";
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
        return "Not enough usable data for the flood sub-signals — a neutral score was applied.";
      }
      return `${parts.join("; ")}.`;
    }
  }
}
