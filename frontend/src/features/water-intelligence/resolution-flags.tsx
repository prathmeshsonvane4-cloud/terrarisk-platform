import { Info } from "lucide-react";

/**
 * Plain-language labels for the `resolution_flags` vocabulary
 * (app/api/catchments.py's `_derive_resolution_flags`) — a field
 * engineer should never see a raw code like "et_sub_pixel." Unknown or
 * future flags fall back to the raw string rather than being hidden,
 * since an unrecognised flag is still real information, just not yet
 * translated.
 *
 * Lives here rather than inside the priority-queue feature because the
 * flags are a property of the catchment, not of any one view: the water
 * report, the PDF and the priority queue must all describe the same
 * limitation in the same words, or the same catchment appears to have
 * different caveats depending on where it is read.
 */
export const RESOLUTION_FLAG_LABELS: Record<string, string> = {
  rainfall_sub_pixel: "this catchment is small relative to the satellite rainfall data's resolution",
  et_sub_pixel: "this catchment is small relative to the satellite evapotranspiration data's resolution",
  high_relief_terrain: "hilly terrain here can make the satellite water-detection reading less reliable",
};

export function describeResolutionFlags(flags: string[]): string {
  return flags.map((flag) => RESOLUTION_FLAG_LABELS[flag] ?? flag).join("; ");
}

/**
 * Longer, self-contained explanations for the report view, where there is
 * room to say WHY the limitation exists rather than only that it does.
 *
 * The pixel sizes are stated explicitly on purpose. "Small relative to
 * the data's resolution" is easy to read as a minor caveat; "one rainfall
 * pixel covers ~3,000 ha and this catchment is 144 ha" is the same fact
 * in a form a reader can actually weigh.
 */
const RESOLUTION_FLAG_DETAIL: Record<string, string> = {
  rainfall_sub_pixel:
    "Rainfall comes from CHIRPS, whose grid cells are about 5.5 km across (~3,000 ha). This catchment is smaller than one cell, so its rainfall figure describes the surrounding area rather than this catchment specifically.",
  et_sub_pixel:
    "Evapotranspiration comes from MODIS at 500 m resolution (25 ha per pixel). Too few whole pixels fall inside this catchment for the average to describe it rather than its surroundings.",
  high_relief_terrain:
    "Steep terrain here can produce radar shadowing and layover, which reduces the reliability of satellite surface-water detection.",
};

/**
 * The report-view disclosure for a catchment's resolution flags.
 *
 * Renders nothing when there are no flags — deliberately, rather than
 * showing an "all inputs fully resolved" reassurance. A green tick would
 * be a stronger claim than this check can support: the flags only test
 * catchment area against pixel size, and say nothing about the many other
 * ways an input can be wrong.
 */
export function ResolutionFlagNotice({ flags, className }: { flags: string[]; className?: string }) {
  if (flags.length === 0) return null;

  return (
    <div className={className}>
      <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-900">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-semibold">Resolution limits for this catchment</p>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-xs leading-relaxed">
            {flags.map((flag) => (
              <li key={flag}>{RESOLUTION_FLAG_DETAIL[flag] ?? RESOLUTION_FLAG_LABELS[flag] ?? flag}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
