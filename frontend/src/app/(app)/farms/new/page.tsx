"use client";

import { useState } from "react";

import { VillageSearch } from "@/features/farm-drawing/village-search";
import type { Village } from "@/features/farm-drawing/types";

export default function NewFarmPage() {
  // Ephemeral, page-scoped UI state — the map (P2) and the draw/confirm
  // step (P3) both read this once they land on this same route, so it's
  // deliberately not persisted (URL/localStorage): re-entering this page
  // is meant to restart the workflow.
  const [selectedVillage, setSelectedVillage] = useState<Village | null>(null);

  return (
    <div className="mx-auto flex w-full max-w-md flex-1 flex-col gap-4 p-6">
      <VillageSearch onSelect={setSelectedVillage} />

      {selectedVillage && (
        <div className="rounded-lg border p-4 text-sm">
          <p className="font-medium">{selectedVillage.name}</p>
          <p className="text-muted-foreground">
            {selectedVillage.taluka}, {selectedVillage.district}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Map and boundary drawing arrive in the next phase.
          </p>
        </div>
      )}
    </div>
  );
}
