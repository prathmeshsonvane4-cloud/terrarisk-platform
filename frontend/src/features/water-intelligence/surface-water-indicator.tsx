/**
 * Renders `surface_water_trend` (0-100: the current reading's percentile
 * position within its own historical series — recharge_stress.py's own
 * definition, not a fitted slope) as a single-value position bar. Not a
 * monthly chart: no monthly surface-water series is available from GET
 * /catchments/{id}/water-reports (see WaterBalanceChart's docstring for
 * the same gap) — this is the honest visual for the one real number
 * that exists, a percentile position, not a fabricated trend line.
 */
export function SurfaceWaterIndicator({ percentile }: { percentile: number | null }) {
  if (percentile === null) {
    return <p className="text-xs text-muted-foreground">No surface-water reading available for this period.</p>;
  }

  const clamped = Math.max(0, Math.min(100, percentile));

  return (
    <div
      role="img"
      aria-label={`Current surface water extent is at the ${Math.round(clamped)}th percentile of its own historical range`}
      className="flex flex-col gap-1.5"
    >
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-[#2a78d6]" style={{ width: `${clamped}%` }} />
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>Lowest on record</span>
        <span className="font-medium text-foreground">{Math.round(clamped)}th percentile</span>
        <span>Highest on record</span>
      </div>
    </div>
  );
}
