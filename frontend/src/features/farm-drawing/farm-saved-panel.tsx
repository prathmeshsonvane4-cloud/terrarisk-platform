"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useTriggerReport } from "@/features/report/use-trigger-report";
import { formatArea } from "@/lib/format";

import type { Village } from "./types";
import type { FarmResponse } from "./use-create-farm";

interface FarmSavedPanelProps {
  farm: FarmResponse;
  village: Village;
  onDrawAnother: () => void;
}

export function FarmSavedPanel({ farm, village, onDrawAnother }: FarmSavedPanelProps) {
  const router = useRouter();
  const triggerReport = useTriggerReport();

  function handleGenerate() {
    triggerReport.mutate(farm.id, {
      onSuccess: (data) => {
        router.push(`/assessments/${data.job_id}`);
      },
    });
  }

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

      {triggerReport.isError && (
        <p role="alert" className="text-xs text-destructive">
          {triggerReport.error.message}
        </p>
      )}

      <Button onClick={handleGenerate} disabled={triggerReport.isPending || triggerReport.isSuccess}>
        {triggerReport.isPending || triggerReport.isSuccess
          ? "Starting analysis…"
          : "Generate climate report"}
      </Button>
      <Button variant="outline" onClick={onDrawAnother} disabled={triggerReport.isPending}>
        Draw another farm
      </Button>
    </div>
  );
}
