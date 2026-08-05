"use client";

import { ClipboardList, Droplets, GitCompare, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StressLegend } from "@/features/water-intelligence/map/stress-legend";
import { useVillageGeometries } from "@/features/water-intelligence/map/use-village-geometries";
import { VillageChoroplethMap } from "@/features/water-intelligence/map/village-choropleth-map";
import { buildVillageMapData } from "@/features/water-intelligence/map/village-map-entries";
import { VillagePopupCard } from "@/features/water-intelligence/map/village-popup-card";
import { useCatchments } from "@/features/water-intelligence/use-catchments";
import { useWaterReportHistories } from "@/features/water-intelligence/use-water-report-histories";
import type { WaterReportHistoryItem } from "@/features/water-intelligence/use-water-report-history";
import { cn } from "@/lib/utils";

// Same window the Priority Queue reads: enough runs for the 3-run
// declining-trend rule plus a previous run to compare against, and no
// more — the map shows the latest state, not a full archive.
const HISTORY_LIMIT_FOR_MAP = 6;

const MIN_CATCHMENTS_TO_COMPARE = 2;

/** Plain browser API rather than useSearchParams(), matching the compare
 * page's own documented reasoning: avoids a Suspense boundary for a
 * value only needed after mount. Carries "Locate on Map" from a Priority
 * Queue row to the village it refers to. */
function getFocusIdFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("focus");
}

/**
 * The district at a glance — every monitored village drawn at once and
 * coloured by the recharge stress band its own report already produced.
 *
 * This exists because of a specific gap: a ranked list can say a village
 * is stressed, but it cannot show that the village sits between two
 * healthy neighbours (a local, fixable cause) or that it is one of six
 * contiguous villages failing together (a system-level problem no single
 * intervention will fix). WELL Labs' Raichur programme frames water
 * availability positionally — canal head-end vs. tail-end vs. dryland —
 * and their own impact method depends on choosing a comparable
 * *neighbouring* control village. Both are spatial judgements, and
 * neither is answerable from a table.
 *
 * Nothing here computes anything new. Scores, bands, recommendations and
 * priorities all come from the existing engine and the existing
 * endpoints; this page only decides where they are drawn.
 */
export default function CatchmentMapPage() {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [focusId, setFocusId] = useState<string | null>(null);
  useEffect(() => {
    setFocusId(getFocusIdFromUrl());
  }, []);

  const { data: catchments, isPending: catchmentsPending, isError, error, refetch } = useCatchments();

  const catchmentIds = useMemo(() => catchments?.map((catchment) => catchment.id) ?? [], [catchments]);
  const boundaryIds = useMemo(
    () =>
      Array.from(
        new Set(
          (catchments ?? [])
            .map((catchment) => catchment.admin_boundary_id)
            .filter((id): id is string => typeof id === "string"),
        ),
      ),
    [catchments],
  );

  const geometries = useVillageGeometries(boundaryIds);
  const histories = useWaterReportHistories(catchmentIds, HISTORY_LIMIT_FOR_MAP);

  const geometriesPending = geometries.some((geometry) => geometry.isPending);
  const historiesPending = histories.some((history) => history.isPending);
  const isPending = catchmentsPending || geometriesPending || historiesPending;

  // useQueries hands back a fresh array on every render, so memoising on
  // those arrays directly would produce a new `entries` identity each
  // time — which would re-run the map's focus effect and reopen the
  // popup continuously. Memoise on a signature of the resolved content
  // instead: catchment identity, which geometries have arrived, and each
  // catchment's latest report. Those are exactly the inputs
  // buildVillageMapData reads, so the signature changes precisely when
  // the map's contents genuinely change.
  const dataSignature = [
    (catchments ?? []).map((catchment) => `${catchment.id}:${catchment.admin_boundary_id ?? ""}`).join(","),
    geometries.filter((geometry) => geometry.data).map((geometry) => geometry.boundaryId).join(","),
    histories.map((history) => `${history.catchmentId}:${history.data?.length ?? 0}:${history.data?.[0]?.generated_at ?? ""}`).join(","),
  ].join("|");

  const { entries, unmappable } = useMemo(
    () => {
      const geometryByBoundaryId = new Map<string, GeoJSON.Geometry>();
      for (const geometry of geometries) {
        // AdminBoundaryDetail.geometry is `dict[str, Any]` server-side and
        // so arrives typed as an open record; it is ST_AsGeoJSON output,
        // i.e. always real GeoJSON. Same narrowing Select Area's own
        // boundary preview already relies on.
        if (geometry.data) {
          geometryByBoundaryId.set(geometry.boundaryId, geometry.data.geometry as unknown as GeoJSON.Geometry);
        }
      }
      const historyByCatchmentId = new Map<string, WaterReportHistoryItem[]>();
      for (const history of histories) {
        historyByCatchmentId.set(history.catchmentId, history.data ?? []);
      }
      return buildVillageMapData({ catchments: catchments ?? [], geometryByBoundaryId, historyByCatchmentId });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see dataSignature above: it is a content hash of exactly these three inputs
    [dataSignature],
  );

  function toggleSelected(catchmentId: string) {
    setSelectedIds((current) =>
      current.includes(catchmentId) ? current.filter((id) => id !== catchmentId) : [...current, catchmentId],
    );
  }

  return (
    <div className="flex flex-1 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b p-4 md:px-6">
        <div>
          <h1 className="text-lg font-semibold">Water Intelligence map</h1>
          <p className="text-sm text-muted-foreground">
            Every village being monitored, coloured by its latest recharge stress. Click a village for its reading, or
            shift-click several to compare them.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/catchments/priority-queue"
            className={cn(buttonVariants({ size: "sm", variant: "outline" }), "gap-1.5")}
          >
            <ClipboardList aria-hidden className="size-4" />
            Priority Queue
          </Link>
          <Link href="/catchments/new" className={cn(buttonVariants({ size: "sm" }), "gap-1.5")}>
            <Plus aria-hidden className="size-4" />
            New catchment
          </Link>
        </div>
      </header>

      {isError && (
        <div className="p-4 md:p-6">
          <ErrorState error={error} onRetry={() => refetch()} />
        </div>
      )}

      {!isError && isPending && (
        <div className="flex flex-1 flex-col gap-3 p-4 md:p-6">
          <Skeleton className="h-full min-h-80 w-full flex-1" />
        </div>
      )}

      {!isError && !isPending && entries.length === 0 && (
        <div className="p-4 md:p-6">
          <EmptyState
            icon={Droplets}
            title="No villages to map yet"
            description={
              unmappable.length > 0
                ? "The catchments being monitored were drawn or uploaded freehand, so they have no village boundary to place on the district map. Add a catchment using Select Area to see it here."
                : "Add a catchment using Select Area and generate its first water report — it will appear on this map, coloured by its recharge stress."
            }
            action={{ label: "Add a catchment", href: "/catchments/new" }}
          />
        </div>
      )}

      {!isError && !isPending && entries.length > 0 && (
        <div className="relative flex-1">
          <VillageChoroplethMap
            entries={entries}
            selectedIds={selectedIds}
            onToggleSelected={toggleSelected}
            focusCatchmentId={focusId}
            renderPopup={(entry) => (
              <VillagePopupCard
                entry={entry}
                isSelected={selectedIds.includes(entry.catchmentId)}
                onToggleSelected={toggleSelected}
              />
            )}
            className="absolute inset-0"
          />

          <StressLegend entries={entries} />

          {selectedIds.length > 0 && (
            <div className="absolute top-3 right-3 z-10 flex items-center gap-2 rounded-lg bg-background/95 p-2 shadow-sm">
              <span className="text-xs font-medium">
                {selectedIds.length} selected to compare
              </span>
              {selectedIds.length >= MIN_CATCHMENTS_TO_COMPARE && (
                <Link
                  href={`/catchments/compare?ids=${selectedIds.join(",")}`}
                  className={cn(buttonVariants({ size: "sm" }), "gap-1.5")}
                >
                  <GitCompare aria-hidden className="size-4" />
                  Compare
                </Link>
              )}
              <button
                type="button"
                onClick={() => setSelectedIds([])}
                className={cn(buttonVariants({ size: "sm", variant: "ghost" }))}
              >
                Clear
              </button>
            </div>
          )}

          {unmappable.length > 0 && (
            <p className="absolute right-3 bottom-3 z-10 max-w-64 rounded-lg bg-background/95 p-2 text-xs text-muted-foreground shadow-sm">
              {unmappable.length} {unmappable.length === 1 ? "catchment is" : "catchments are"} not shown: drawn or
              uploaded freehand, so {unmappable.length === 1 ? "it has" : "they have"} no village boundary to place on
              this map.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
