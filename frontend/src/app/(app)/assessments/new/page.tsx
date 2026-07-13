"use client";

import { useCallback, useMemo, useState } from "react";

import { ConfirmPanel } from "@/features/farm-drawing/confirm-panel";
import { FarmMap } from "@/features/farm-drawing/farm-map";
import { FarmSavedPanel } from "@/features/farm-drawing/farm-saved-panel";
import type { Village } from "@/features/farm-drawing/types";
import { useCreateFarm } from "@/features/farm-drawing/use-create-farm";
import { VillageSearch } from "@/features/farm-drawing/village-search";
import { formatArea } from "@/lib/format";
import { farmAreaBoundsIssue, ringAreaHectares, toFarmGeometry, type Ring } from "@/lib/geo";

interface DrawnPolygon {
  ring: Ring;
  complete: boolean;
}

export default function NewFarmPage() {
  // Page-scoped workflow state, single source of truth: the map reports
  // ring changes up; area, submit-eligibility, and the POST payload all
  // derive from here. Deliberately not persisted — re-entering this page
  // restarts the workflow.
  const [selectedVillage, setSelectedVillage] = useState<Village | null>(null);
  const [polygon, setPolygon] = useState<DrawnPolygon | null>(null);
  const [clearSignal, setClearSignal] = useState(0);
  const createFarm = useCreateFarm();

  const areaHectares = useMemo(
    () => (polygon && polygon.ring.length >= 3 ? ringAreaHectares(polygon.ring) : null),
    [polygon],
  );
  const boundsIssue = useMemo(
    () => (areaHectares !== null ? farmAreaBoundsIssue(areaHectares) : null),
    [areaHectares],
  );

  const handlePolygonChange = useCallback((ring: Ring | null, complete: boolean) => {
    setPolygon(ring ? { ring, complete } : null);
  }, []);

  function handleVillageSelect(village: Village) {
    setSelectedVillage(village);
    // A new village starts a new workflow — any previous save result is
    // stale context (the map clears its own drawing on village change).
    createFarm.reset();
  }

  function handleSubmit() {
    if (!selectedVillage || !polygon?.complete) return;
    createFarm.mutate({
      villageId: selectedVillage.id,
      geometry: toFarmGeometry(polygon.ring),
    });
  }

  function handleDrawAnother() {
    createFarm.reset();
    setPolygon(null);
    setClearSignal((signal) => signal + 1);
  }

  const savedFarm = createFarm.data ?? null;
  const showConfirmPanel =
    !savedFarm && selectedVillage !== null && polygon?.complete === true && areaHectares !== null;
  const showDrawingArea = !savedFarm && !showConfirmPanel && areaHectares !== null;

  return (
    <div className="flex flex-1 flex-col md:flex-row">
      <aside className="flex w-full flex-col gap-4 border-b p-4 md:w-80 md:overflow-y-auto md:border-r md:border-b-0">
        <VillageSearch onSelect={handleVillageSelect} />

        {selectedVillage && !showConfirmPanel && !savedFarm && (
          <div className="rounded-lg border p-3 text-sm">
            <p className="text-xs text-muted-foreground">Selected village</p>
            <p className="font-medium">{selectedVillage.name}</p>
            <p className="text-muted-foreground">
              {selectedVillage.taluka}, {selectedVillage.district}
            </p>
          </div>
        )}

        {showDrawingArea && areaHectares !== null && (
          <div className="rounded-lg border p-3 text-sm">
            <p className="text-xs text-muted-foreground">Drawing…</p>
            <p className="font-medium tabular-nums">{formatArea(areaHectares)}</p>
          </div>
        )}

        {showConfirmPanel && selectedVillage && areaHectares !== null && (
          <ConfirmPanel
            village={selectedVillage}
            previewAreaHectares={areaHectares}
            blockedReason={boundsIssue}
            isPending={createFarm.isPending}
            errorMessage={createFarm.isError ? createFarm.error.message : null}
            onSubmit={handleSubmit}
          />
        )}

        {savedFarm && selectedVillage && (
          <FarmSavedPanel farm={savedFarm} village={selectedVillage} onDrawAnother={handleDrawAnother} />
        )}
      </aside>

      <FarmMap
        village={selectedVillage}
        hasPolygon={polygon !== null && polygon.complete}
        onPolygonChange={handlePolygonChange}
        locked={createFarm.isPending || savedFarm !== null}
        clearSignal={clearSignal}
        className="relative min-h-[55vh] flex-1 md:min-h-0"
      />
    </div>
  );
}
