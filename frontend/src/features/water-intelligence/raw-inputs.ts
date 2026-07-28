/**
 * Safe readers for RechargeStressScoreResponse.raw_inputs — typed as
 * `{[key: string]: unknown}` in the generated schema (a JSONB column,
 * app/models/water_balance.py). recharge_stress.py's own engine
 * populates it with {rainfall_stress, vegetation_stress,
 * surface_water_stress, weighted_average_score, confidence} — real
 * values, just not typed ones, since JSONB has no OpenAPI shape. These
 * helpers read them defensively rather than casting, so a missing or
 * differently-shaped key degrades to "—" in the UI, never a runtime
 * crash or a fabricated number.
 */
export function numberField(rawInputs: Record<string, unknown>, key: string): number | null {
  const value = rawInputs[key];
  return typeof value === "number" ? value : null;
}
