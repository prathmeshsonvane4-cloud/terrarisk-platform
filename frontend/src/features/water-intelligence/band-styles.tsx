import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";

export type StressBand = components["schemas"]["StressBand"];
export type StorageChangeBand = components["schemas"]["StorageChangeBand"];

interface BandStyle {
  label: string;
  chipClass: string;
}

/**
 * Mirrors lib/risk-bands.ts's exact convention (one semantic scale, the
 * label always accompanies the color — band identity is never
 * color-alone) for Water Intelligence's two independent bands. A
 * deliberate visual echo of RISK_BANDS' red/amber/green language, not a
 * shared type: StressBand/StorageChangeBand are their own backend
 * vocabulary, not RiskBand relabeled (recharge_stress.py's own docstring
 * is explicit that these outputs are never blended with RiskEngine's).
 */
export const STRESS_BANDS: Record<StressBand, BandStyle> = {
  low: { label: "Low stress", chipClass: "bg-emerald-100 text-emerald-900" },
  moderate: { label: "Moderate stress", chipClass: "bg-amber-100 text-amber-900" },
  high: { label: "High stress", chipClass: "bg-orange-100 text-orange-900" },
  very_high: { label: "Very high stress", chipClass: "bg-red-100 text-red-900" },
};

export const STORAGE_CHANGE_BANDS: Record<StorageChangeBand, BandStyle> = {
  much_below_normal: { label: "Much below normal", chipClass: "bg-red-100 text-red-900" },
  below_normal: { label: "Below normal", chipClass: "bg-orange-100 text-orange-900" },
  normal: { label: "Normal", chipClass: "bg-emerald-100 text-emerald-900" },
  above_normal: { label: "Above normal", chipClass: "bg-sky-100 text-sky-900" },
  much_above_normal: { label: "Much above normal", chipClass: "bg-blue-100 text-blue-900" },
};

/**
 * The same color families as the chipClass values above, as RGB triples
 * — exported for canvas/PDF contexts (generate-water-report-pdf.ts)
 * where a Tailwind class has no meaning. One source of truth for "which
 * color family represents this band": both the on-screen chip and the
 * PDF's native-drawn chip point at the same emerald/amber/orange/red/
 * sky/blue families, never independently chosen hexes that could drift
 * apart from each other.
 */
export const STRESS_BAND_PDF_COLORS: Record<StressBand, [number, number, number]> = {
  low: [4, 120, 87], // emerald-700
  moderate: [180, 83, 9], // amber-700
  high: [194, 65, 12], // orange-700
  very_high: [185, 28, 28], // red-700
};

export const STORAGE_CHANGE_BAND_PDF_COLORS: Record<StorageChangeBand, [number, number, number]> = {
  much_below_normal: [185, 28, 28], // red-700
  below_normal: [194, 65, 12], // orange-700
  normal: [4, 120, 87], // emerald-700
  above_normal: [3, 105, 161], // sky-700
  much_above_normal: [29, 78, 216], // blue-700
};

function rgbToHex([red, green, blue]: [number, number, number]): string {
  return `#${[red, green, blue].map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
}

/**
 * Map-layer fill/outline colors, derived at module load from
 * STRESS_BAND_PDF_COLORS rather than written out again as fresh hexes.
 * MapLibre paint properties take concrete colors (a Tailwind class means
 * nothing to a GL layer), so the choropleth needs hex — but deriving
 * them keeps the existing "one source of truth for which color family
 * represents this band" rule literally true: the chip, the PDF chip, and
 * the map polygon cannot drift apart, because there is only one place
 * the emerald/amber/orange/red families are chosen.
 */
export const STRESS_BAND_MAP_COLORS: Record<StressBand, string> = {
  low: rgbToHex(STRESS_BAND_PDF_COLORS.low),
  moderate: rgbToHex(STRESS_BAND_PDF_COLORS.moderate),
  high: rgbToHex(STRESS_BAND_PDF_COLORS.high),
  very_high: rgbToHex(STRESS_BAND_PDF_COLORS.very_high),
};

/**
 * A monitored village with no completed water report yet — a real,
 * already-modelled state (recommendations.ts's "needs_first_report"),
 * not an error and not a fifth stress level. Deliberately a neutral grey
 * outside the emerald→red stress ramp so it reads as "no reading taken"
 * rather than "a reading that happens to be mild": on a choropleth,
 * absence of data must not be mistakable for presence of a good result.
 */
export const NO_REPORT_MAP_COLOR = "#94a3b8"; // slate-400

export const NO_REPORT_LABEL = "No report yet";

interface StressBandChipProps {
  band: StressBand;
  /** When provided, renders "{label} · {score}" — mirrors RiskBandChip's
   * same optional-score convention. */
  score?: number;
  className?: string;
}

export function StressBandChip({ band, score, className }: StressBandChipProps) {
  const style = STRESS_BANDS[band];
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", style.chipClass, className)}>
      {style.label}
      {score !== undefined && <> · {Math.round(score)}</>}
    </span>
  );
}

export function StorageChangeBandChip({ band, className }: { band: StorageChangeBand; className?: string }) {
  const style = STORAGE_CHANGE_BANDS[band];
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", style.chipClass, className)}>
      {style.label}
    </span>
  );
}
