"use client";

import { Button } from "@/components/ui/button";
import { formatArea } from "@/lib/format";

import type { Village } from "./types";

interface ConfirmPanelProps {
  village: Village;
  previewAreaHectares: number;
  /** Non-null blocks submission (e.g. implausible area) — shown verbatim. */
  blockedReason: string | null;
  onSubmit: () => void;
}

/**
 * The Blueprint §01 accountability step: the officer explicitly affirms
 * the computed area before anything is persisted. The submit click IS the
 * affirmation — recorded server-side as drawn_by on the created farm. P10:
 * this click now also triggers report generation in the same action
 * (Product Design v2 §7.2 — farm-creation and report-trigger are one
 * officer decision, not two separate UI moments). Pending/error state for
 * that combined action is owned and rendered by the wizard's own "submit"
 * step (`assessment-wizard.tsx`), since this panel's own click immediately
 * advances past it — the panel itself is only ever shown pre-submit.
 */
export function ConfirmPanel({ village, previewAreaHectares, blockedReason, onSubmit }: ConfirmPanelProps) {
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

      <Button onClick={onSubmit} disabled={blockedReason !== null}>
        Confirm &amp; generate report
      </Button>
    </div>
  );
}
