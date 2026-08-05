"use client";

import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { NO_REPORT_LABEL, STORAGE_CHANGE_BANDS, STRESS_BANDS } from "../band-styles";
import type { VillageMapEntry } from "./village-map-entries";

interface VillagePopupCardProps {
  entry: VillageMapEntry;
  isSelected: boolean;
  onToggleSelected: (catchmentId: string) => void;
}

/**
 * What a village says when you click it: the same four numbers its own
 * report already produced, its current top priority, and a way into the
 * full report — without leaving the map. The map is the workspace here;
 * the report is the drill-down, not the destination.
 *
 * Colours are explicit slate tones rather than theme tokens because this
 * renders inside MapLibre's own popup element, which is outside the app
 * shell's styling context and always light.
 */
export function VillagePopupCard({ entry, isSelected, onToggleSelected }: VillagePopupCardProps) {
  return (
    <div className="flex w-full flex-col gap-2 pr-4 text-slate-900">
      <div>
        <p className="text-sm font-semibold">{entry.name}</p>
        <p className="text-xs text-slate-500">
          {entry.lastGeneratedAt
            ? `Last report ${new Date(entry.lastGeneratedAt).toLocaleDateString("en-IN", { dateStyle: "medium" })}`
            : "No report generated yet"}
        </p>
      </div>

      <dl className="flex flex-col gap-1 text-xs">
        <div className="flex items-center justify-between gap-3">
          <dt className="text-slate-500">Recharge stress</dt>
          <dd>
            {entry.band ? (
              <span className={cn("rounded-full px-2 py-0.5 font-medium", STRESS_BANDS[entry.band].chipClass)}>
                {STRESS_BANDS[entry.band].label}
                {entry.stressScore !== null && <> · {Math.round(entry.stressScore)}</>}
              </span>
            ) : (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700">{NO_REPORT_LABEL}</span>
            )}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-slate-500">Storage change</dt>
          <dd className="font-medium">
            {entry.storageChangeBand ? STORAGE_CHANGE_BANDS[entry.storageChangeBand].label : "—"}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-slate-500">Confidence</dt>
          <dd className="font-medium">{entry.confidence !== null ? `${Math.round(entry.confidence)}%` : "—"}</dd>
        </div>
      </dl>

      <div className="rounded-md bg-slate-50 p-2">
        <p className="text-xs font-medium">{entry.topRecommendation.title}</p>
        <p className="mt-0.5 text-xs text-slate-600">{entry.topRecommendation.action}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Link
          href={`/catchments/${entry.catchmentId}/water-reports`}
          className={cn(buttonVariants({ size: "sm" }), "w-full")}
        >
          Open Full Water Report
        </Link>
        <button
          type="button"
          onClick={() => onToggleSelected(entry.catchmentId)}
          className={cn(buttonVariants({ size: "sm", variant: "outline" }), "w-full")}
        >
          {isSelected ? "Remove from comparison" : "Add to comparison"}
        </button>
      </div>
    </div>
  );
}
