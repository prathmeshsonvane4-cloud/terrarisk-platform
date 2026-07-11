"use client";

import { Button } from "@/components/ui/button";
import { formatArea } from "@/lib/format";

import type { Village } from "./types";

interface ConfirmPanelProps {
  village: Village;
  previewAreaHectares: number;
  /** Non-null blocks submission (e.g. implausible area) — shown verbatim. */
  blockedReason: string | null;
  isPending: boolean;
  errorMessage: string | null;
  onSubmit: () => void;
}

/**
 * The Blueprint §01 accountability step: the officer explicitly affirms
 * the computed area before anything is persisted. The submit click IS the
 * affirmation — recorded server-side as drawn_by on the created farm.
 */
export function ConfirmPanel({
  village,
  previewAreaHectares,
  blockedReason,
  isPending,
  errorMessage,
  onSubmit,
}: ConfirmPanelProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3 text-sm">
      <div>
        <p className="text-xs text-muted-foreground">Confirm farm boundary</p>
        <p className="font-medium">{village.name}</p>
        <p className="text-muted-foreground">
          {village.taluka}, {village.district}
        </p>
      </div>

      <div>
        <p className="text-xs text-muted-foreground">Boundary area (preview)</p>
        <p className="text-base font-medium tabular-nums">{formatArea(previewAreaHectares)}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          The recorded area is computed on the server from your boundary.
        </p>
      </div>

      {blockedReason && (
        <p role="alert" className="text-xs text-destructive">
          {blockedReason}
        </p>
      )}
      {errorMessage && (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage} — check the boundary and try again.
        </p>
      )}

      <Button onClick={onSubmit} disabled={isPending || blockedReason !== null}>
        {isPending ? "Saving farm…" : errorMessage ? "Retry — confirm area & save farm" : "Confirm area & save farm"}
      </Button>
    </div>
  );
}
