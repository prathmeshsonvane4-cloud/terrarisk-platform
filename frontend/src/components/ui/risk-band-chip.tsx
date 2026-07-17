import { BAND_THRESHOLDS } from "@/lib/band-thresholds";
import { RISK_BANDS, type RiskBand } from "@/lib/risk-bands";
import { cn } from "@/lib/utils";

/** The score range a band covers, read from the same `BAND_THRESHOLDS`
 * mirror the Method tab's own table renders — one source of the cutoff
 * numbers, never restated by hand. */
function bandRange(band: RiskBand): string {
  const index = BAND_THRESHOLDS.findIndex((entry) => entry.band === band);
  const min = index <= 0 ? 0 : BAND_THRESHOLDS[index - 1].max + 0.01;
  const max = BAND_THRESHOLDS[index].max;
  return `${min.toFixed(index <= 0 ? 0 : 2)}–${max}`;
}

interface RiskBandChipProps {
  band: RiskBand;
  /** When provided, renders "{label} · {score}" — omit for a band-only
   * chip (e.g. the Method tab's threshold table, which already shows the
   * numeric range in an adjacent column). */
  score?: number;
  /** P11 contextual-help requirement: every score-bearing chip should
   * answer "how was this calculated?" at a glance. Extends the same
   * native-title pattern the P9 confidence badge already established
   * (`reports/[id]/page.tsx`) rather than introducing a new tooltip
   * primitive for one line of text. Disable only where the range is
   * already shown adjacent to the chip (redundant, not wrong, but no
   * reason to repeat it). */
  showRangeHint?: boolean;
  className?: string;
}

/** The one shared risk-band chip — previously hand-duplicated across 8
 * call sites (Overview, Farms index/detail, Assessments index, Reports
 * index, FactorCard, MethodTab), each independently reconstructing the
 * same `rounded-full px-2 py-0.5 ...` markup from `RISK_BANDS`. */
export function RiskBandChip({ band, score, showRangeHint = true, className }: RiskBandChipProps) {
  const style = RISK_BANDS[band];
  return (
    <span
      className={cn("rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", style.chipClass, className)}
      title={showRangeHint ? `${style.label} = ${bandRange(band)} / 100` : undefined}
    >
      {style.label}
      {score !== undefined && <> · {Math.round(score)}</>}
    </span>
  );
}
