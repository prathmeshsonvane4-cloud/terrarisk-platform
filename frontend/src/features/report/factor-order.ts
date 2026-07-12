import type { RiskFactorName } from "./drivers";

/** Fixed display order for the factor cards — mirrors the Blueprint §07
 * methodology ordering (water, flood, drought, vegetation would also be
 * defensible; this order leads with the two Marathwada-critical factors). */
export const FACTOR_ORDER: RiskFactorName[] = [
  "drought_risk",
  "water_availability",
  "vegetation_stability",
  "flood_exposure",
];
