import type { components } from "@/lib/api/schema";

export type RiskBand = components["schemas"]["RiskBand"];

/**
 * Mirror of the backend's `_BAND_THRESHOLDS` (app/services/risk/engine.py)
 * — v1 fixed score→band cutoffs (equal quartiles), not part of the
 * versioned ConfigWeight surface, so there is nothing to fetch from the
 * API. Kept here for the Method tab's band-thresholds table, matching
 * the same mirrored-constant pattern as risk-bands.ts's labels/colors.
 */
export const BAND_THRESHOLDS: { band: RiskBand; max: number }[] = [
  { band: "low", max: 25 },
  { band: "moderate", max: 50 },
  { band: "high", max: 75 },
  { band: "very_high", max: 100 },
];
