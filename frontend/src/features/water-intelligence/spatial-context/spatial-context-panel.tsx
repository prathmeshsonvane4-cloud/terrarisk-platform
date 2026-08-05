"use client";

import { Skeleton } from "@/components/ui/skeleton";

import { useCatchmentDetail } from "../use-catchment-detail";
import { SpatialContextMap } from "./spatial-context-map";
import { useSpatialContext } from "./use-spatial-context";

interface SpatialContextPanelProps {
  catchmentId: string;
}

/**
 * "Where is this village? What surrounds it? Why is this report about
 * this place?" — orientation only, never analysis: no stress colouring,
 * no per-village data, nothing this map draws is a satellite-derived
 * value. That is what keeps this an honest answer to "why not represent
 * this spatially" rather than a second, thinner copy of the choropleth
 * at /catchments/map (docs/WELL_Labs_Spatial_Redesign_2026.md's Option
 * B, chosen over Option C's raster tile serving specifically because
 * TerraRisk has no per-pixel outputs to show — only per-catchment
 * scalars).
 *
 * Fetches CatchmentDetailResponse itself (the one screen that needs
 * geometry) rather than requiring the page around it to switch off
 * useCatchments() — the rest of the report page's data flow is
 * unchanged.
 */
export function SpatialContextPanel({ catchmentId }: SpatialContextPanelProps) {
  const catchmentDetail = useCatchmentDetail(catchmentId);
  const context = useSpatialContext(catchmentDetail.data);

  if (catchmentDetail.isPending || context.isPending) {
    return <Skeleton className="h-72 w-full" />;
  }

  if (catchmentDetail.isError || context.isError) {
    // Supplementary, not load-bearing — the rest of the report still
    // works without a locator, so this degrades quietly rather than
    // blocking the page the way a failed water-report fetch does.
    return (
      <p className="text-sm text-muted-foreground">Could not load the map for this catchment right now.</p>
    );
  }

  if (!context.village) {
    return (
      <p className="text-sm text-muted-foreground">
        This catchment was drawn or uploaded directly, so it has no administrative village to show on a map.
      </p>
    );
  }

  const talukaLabel = context.talukaName ? ` in ${context.talukaName} taluka` : "";

  return (
    <div className="flex flex-col gap-2">
      <div className="relative h-72 w-full overflow-hidden rounded-lg border">
        <SpatialContextMap context={context} className="absolute inset-0" />
      </div>
      <p className="text-xs text-muted-foreground">
        {context.villageName}
        {talukaLabel}
        {context.neighbours.length > 0
          ? `, shown alongside its ${context.neighbours.length} neighbouring ${context.neighbours.length === 1 ? "village" : "villages"}`
          : ""}
        . North is up.
        {context.analysedGeometry &&
          " The dashed blue outline is the area actually analysed — it was reshaped from the village boundary shown in green."}
      </p>
    </div>
  );
}
