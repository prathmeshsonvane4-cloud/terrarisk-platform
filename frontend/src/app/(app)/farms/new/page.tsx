"use client";

import { useCallback, useMemo, useState } from "react";

import { FarmMap } from "@/features/farm-drawing/farm-map";
import type { Village } from "@/features/farm-drawing/types";
import { VillageSearch } from "@/features/farm-drawing/village-search";
import { formatArea } from "@/lib/format";
import { ringAreaHectares, type Ring } from "@/lib/geo";

interface DrawnPolygon {
  ring: Ring;
  complete: boolean;
}

export default function NewFarmPage() {
  // Page-scoped workflow state, single source of truth: the map reports
  // ring changes up, everything else (area, hasPolygon, the P3 submit
  // payload via toFarmGeometry) derives from here. Deliberately not
  // persisted — re-entering this page restarts the workflow.
  const [selectedVillage, setSelectedVillage] = useState<Village | null>(null);
  const [polygon, setPolygon] = useState<DrawnPolygon | null>(null);

  const areaHectares = useMemo(
    () => (polygon && polygon.ring.length >= 3 ? ringAreaHectares(polygon.ring) : null),
    [polygon],
  );

  const handlePolygonChange = useCallback((ring: Ring | null, complete: boolean) => {
    setPolygon(ring ? { ring, complete } : null);
  }, []);

  return (
    <div className="flex flex-1 flex-col md:flex-row">
      <aside className="flex w-full flex-col gap-4 border-b p-4 md:w-80 md:overflow-y-auto md:border-r md:border-b-0">
        <VillageSearch onSelect={setSelectedVillage} />

        {selectedVillage && (
          <div className="rounded-lg border p-3 text-sm">
            <p className="text-xs text-muted-foreground">Selected village</p>
            <p className="font-medium">{selectedVillage.name}</p>
            <p className="text-muted-foreground">
              {selectedVillage.taluka}, {selectedVillage.district}
            </p>
          </div>
        )}

        {areaHectares !== null && (
          <div className="rounded-lg border p-3 text-sm">
            <p className="text-xs text-muted-foreground">
              {polygon?.complete ? "Farm boundary" : "Drawing…"}
            </p>
            <p className="font-medium tabular-nums">{formatArea(areaHectares)}</p>
            {polygon?.complete && (
              <p className="mt-1 text-xs text-muted-foreground">
                Preview only — the recorded area is computed on the server when the farm is
                submitted.
              </p>
            )}
          </div>
        )}
      </aside>

      <FarmMap
        village={selectedVillage}
        hasPolygon={polygon !== null && polygon.complete}
        onPolygonChange={handlePolygonChange}
        className="relative min-h-[55vh] flex-1 md:min-h-0"
      />
    </div>
  );
}
