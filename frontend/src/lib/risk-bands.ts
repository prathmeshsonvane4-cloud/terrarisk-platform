import type { components } from "@/lib/api/schema";

export type RiskBand = components["schemas"]["RiskBand"];

interface BandStyle {
  label: string;
  /** Chip styling (bg tint + readable ink). The label text ALWAYS
   * accompanies the color — band identity is never color-alone. */
  chipClass: string;
  /** Strong ink for the big verdict headline. */
  textClass: string;
}

/**
 * THE single risk-band scale (M2A spec §10: one visual language — these
 * exact colors are reused by the dashboard, the PDF (P6), and eventually
 * the M4 choropleths). Semantic status colors, reserved for risk bands
 * only — never for chart series.
 */
export const RISK_BANDS: Record<RiskBand, BandStyle> = {
  low: {
    label: "Low risk",
    chipClass: "bg-emerald-100 text-emerald-900",
    textClass: "text-emerald-700",
  },
  moderate: {
    label: "Moderate risk",
    chipClass: "bg-amber-100 text-amber-900",
    textClass: "text-amber-700",
  },
  high: {
    label: "High risk",
    chipClass: "bg-orange-100 text-orange-900",
    textClass: "text-orange-700",
  },
  very_high: {
    label: "Very high risk",
    chipClass: "bg-red-100 text-red-900",
    textClass: "text-red-700",
  },
};
