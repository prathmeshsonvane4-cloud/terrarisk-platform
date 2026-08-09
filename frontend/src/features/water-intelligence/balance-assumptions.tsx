import { Info } from "lucide-react";

import type { components } from "@/lib/api/schema";

type DelineationMethod = components["schemas"]["DelineationMethod"];

/**
 * The assumptions the water balance rests on, stated next to the figures
 * they affect.
 *
 * `closed_catchment_assumed` and `calibration_status` were already
 * computed, persisted and served by the API, but appeared in no view —
 * so the single most consequential modelling assumption in the report
 * was invisible to the person reading its output. A reader cannot
 * discount a number by an assumption nobody told them about.
 *
 * Whether the assumption is REASONABLE depends on how the boundary was
 * drawn, which is why `delineationMethod` is an input here rather than
 * this being one fixed sentence:
 *
 *   - A DEM-delineated catchment is a real topographic watershed. Treating
 *     it as closed is the standard, defensible simplification.
 *   - A hand-drawn or uploaded boundary is usually an administrative unit
 *     (a revenue village, a project block). Water crosses those edges
 *     freely, so "no lateral flow" is not a mild simplification — the
 *     unmeasured lateral flux can rival the storage-change signal itself.
 *
 * That second case is the common one for village-scale work, and it is
 * the case a hydrologist reviewing this report will ask about first.
 */
export function WaterBalanceAssumptions({
  closedCatchmentAssumed,
  calibrationStatus,
  delineationMethod,
  className,
}: {
  closedCatchmentAssumed: boolean;
  calibrationStatus: string;
  delineationMethod: DelineationMethod;
  className?: string;
}) {
  const boundaryIsTopographic = delineationMethod === "auto_dem";
  const notes: string[] = [];

  if (closedCatchmentAssumed) {
    notes.push(
      boundaryIsTopographic
        ? "Treated as a closed catchment: no water is assumed to flow in or out across its boundary except as runoff. For a DEM-delineated watershed this is the standard simplification."
        : "Treated as a closed catchment: no water is assumed to flow in or out across its boundary except as runoff. This boundary was not delineated from terrain, so it likely follows administrative rather than drainage lines — water does cross it, and that unmeasured flow is absorbed into the storage-change residual below.",
    );
  }

  if (calibrationStatus === "uncalibrated") {
    notes.push(
      "Uncalibrated: no observed streamflow or groundwater level has been used to check these figures against reality. Treat them as relative indicators for comparing catchments and years, not as audited volumes.",
    );
  }

  if (notes.length === 0) return null;

  return (
    <div className={className}>
      <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-900">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-semibold">What this water balance assumes</p>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-xs leading-relaxed">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
