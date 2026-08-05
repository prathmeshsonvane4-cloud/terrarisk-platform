"use client";

import { NO_REPORT_LABEL, NO_REPORT_MAP_COLOR, STRESS_BANDS, STRESS_BAND_MAP_COLORS, type StressBand } from "../band-styles";
import type { VillageMapEntry } from "./village-map-entries";

const BAND_ORDER: StressBand[] = ["very_high", "high", "moderate", "low"];

/**
 * The choropleth's key, with a live count per band. Without it the map is
 * decoration — a colour a viewer has to guess the meaning of. Ordered
 * worst-first, matching the Priority Queue's own severity ordering, so
 * the thing needing attention is the thing read first.
 */
export function StressLegend({ entries }: { entries: VillageMapEntry[] }) {
  const counts = new Map<string, number>();
  for (const entry of entries) {
    const key = entry.band ?? "none";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-lg bg-background/95 p-2.5 shadow-sm">
      <p className="mb-1.5 text-xs font-medium">Recharge stress</p>
      <ul className="flex flex-col gap-1">
        {BAND_ORDER.map((band) => (
          <li key={band} className="flex items-center gap-2 text-xs">
            <span
              aria-hidden
              className="size-3 shrink-0 rounded-sm"
              style={{ backgroundColor: STRESS_BAND_MAP_COLORS[band] }}
            />
            <span className="flex-1">{STRESS_BANDS[band].label}</span>
            <span className="tabular-nums text-muted-foreground">{counts.get(band) ?? 0}</span>
          </li>
        ))}
        <li className="flex items-center gap-2 text-xs">
          <span aria-hidden className="size-3 shrink-0 rounded-sm" style={{ backgroundColor: NO_REPORT_MAP_COLOR }} />
          <span className="flex-1">{NO_REPORT_LABEL}</span>
          <span className="tabular-nums text-muted-foreground">{counts.get("none") ?? 0}</span>
        </li>
      </ul>
    </div>
  );
}
