import type { StressBand } from "./band-styles";

/**
 * Mirrors app/services/hydrology/recharge_stress.py's own
 * _STRESS_BAND_THRESHOLDS exactly ((25, LOW), (50, MODERATE), (75,
 * HIGH), (100, VERY_HIGH)) — used here only to color-code each
 * *individual* factor sub-score (raw_inputs.rainfall_stress /
 * vegetation_stress / surface_water_stress) for the dashboard's
 * "color-coded cards" requirement. The backend itself never classifies
 * these three sub-scores into a named band — only the composite
 * stress_score is banded — so this is a display-only bucketing of an
 * already-real number using the identical cutoffs the composite score
 * uses, not a new methodology or a fabricated classification.
 */
export function bandForFactorScore(score: number): StressBand {
  if (score <= 25) return "low";
  if (score <= 50) return "moderate";
  if (score <= 75) return "high";
  return "very_high";
}
