const ACRES_PER_HECTARE = 2.471054;

/** "2.51 ha (6.2 acres)" — hectares are the system of record (area_ha
 * column); acres shown alongside because Marathwada officers think in
 * acres (M2A spec §9, DCCB decision-maker review note). */
export function formatArea(hectares: number): string {
  const acres = hectares * ACRES_PER_HECTARE;
  return `${hectares.toFixed(2)} ha (${acres.toFixed(1)} acres)`;
}
