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

/** "1st"/"2nd"/"3rd"/"4th"... — English ordinal suffix. Only the last
 * two digits matter (11th/12th/13th are the exception to the usual
 * last-digit rule). Shared by SurfaceWaterIndicator and the Priority
 * Queue's recommendation evidence text, both of which render a
 * percentile — found live in production reporting "3th percentile." */
export function ordinal(value: number): string {
  const rounded = Math.round(value);
  const lastTwoDigits = rounded % 100;
  if (lastTwoDigits >= 11 && lastTwoDigits <= 13) return `${rounded}th`;
  switch (rounded % 10) {
    case 1:
      return `${rounded}st`;
    case 2:
      return `${rounded}nd`;
    case 3:
      return `${rounded}rd`;
    default:
      return `${rounded}th`;
  }
}
