"use client";

import { Button } from "@/components/ui/button";
import { formatArea } from "@/lib/format";

import type { Village } from "./types";
import type { FarmResponse } from "./use-create-farm";

interface FarmSavedPanelProps {
  farm: FarmResponse;
  village: Village;
  onDrawAnother: () => void;
}

export function FarmSavedPanel({ farm, village, onDrawAnother }: FarmSavedPanelProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3 text-sm">
      <div>
        <p className="text-xs font-medium text-muted-foreground">Farm saved</p>
        <p className="font-medium">{village.name}</p>
        <p className="text-muted-foreground">
          {village.taluka}, {village.district}
        </p>
      </div>

      <div>
        <p className="text-xs text-muted-foreground">Recorded area (server-computed)</p>
        <p className="text-base font-medium tabular-nums">{formatArea(farm.area_ha)}</p>
      </div>

      <p className="text-xs text-muted-foreground">
        Climate report generation for this farm arrives in the next phase.
      </p>

      <Button variant="outline" onClick={onDrawAnother}>
        Draw another farm
      </Button>
    </div>
  );
}
