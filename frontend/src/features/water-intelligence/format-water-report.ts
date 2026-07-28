/** Small display formatters specific to the water-report detail view —
 * kept in this feature dir rather than lib/format.ts, mirroring
 * features/report/'s own convention of feature-scoped formatting
 * helpers (narrative.ts, drivers.ts) instead of growing the shared
 * lib/format.ts with concerns only one feature has. */

export function formatMm(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)} mm`;
}

export function formatRatio(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

export function formatPercent(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(0)}%`;
}
