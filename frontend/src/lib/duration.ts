/**
 * Formats a millisecond duration as a short, honest string — real
 * elapsed time only (Product Design v2 P2: never a fake progress
 * percentage or ETA). Seconds below a minute, "Xm Ys" above.
 */
export function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, ms / 1000);
  if (totalSeconds < 60) {
    return `${totalSeconds.toFixed(totalSeconds < 10 ? 1 : 0)}s`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return `${minutes}m ${seconds}s`;
}
