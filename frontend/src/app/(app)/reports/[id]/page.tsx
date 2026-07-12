"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { buttonVariants } from "@/components/ui/button";
import { useReport } from "@/features/report/use-report";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

// P4 scope: the real report headline from the real M1 endpoint — proof the
// pipeline completed, rendered from live data. The full interactive
// dashboard (factor cards, NDVI/rainfall charts, map panel, lineage
// footer) replaces this page's content in P5.

const BAND_LABEL: Record<string, string> = {
  low: "Low risk",
  moderate: "Moderate risk",
  high: "High risk",
  very_high: "Very high risk",
};

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data: report, isPending, isError, error } = useReport(id);

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="flex w-full max-w-md flex-col gap-3 rounded-lg border p-5 text-sm">
        {isPending && <p className="text-muted-foreground">Loading report…</p>}

        {isError && (
          <>
            <p className="font-medium">Could not load this report</p>
            <p role="alert" className="text-muted-foreground">
              {error.message}
            </p>
            <Link
              href="/farms/new"
              className={cn(buttonVariants({ variant: "outline" }), "mt-1 self-start")}
            >
              Back to farm mapping
            </Link>
          </>
        )}

        {report && (
          <>
            <div>
              <p className="text-xs text-muted-foreground">Overall climate risk</p>
              <p className="text-2xl font-semibold">{BAND_LABEL[report.overall_band] ?? report.overall_band}</p>
              <p className="text-muted-foreground tabular-nums">
                {/* confidence is already 0–100 (engine contract: full
                    coverage == 100.0) — do not multiply */}
                Score {report.overall_score.toFixed(0)} / 100 · Confidence{" "}
                {Math.round(report.confidence)}%
              </p>
            </div>
            <div className="text-muted-foreground">
              <p>Farm area: {formatArea(report.farm_area_ha)}</p>
              <p>
                Computed:{" "}
                {new Date(report.computed_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </p>
            </div>
            <p className="text-xs text-muted-foreground">
              The full interactive dashboard — factor breakdown, vegetation and rainfall history,
              and data lineage — arrives in the next phase.
            </p>
            <Link
              href="/farms/new"
              className={cn(buttonVariants({ variant: "outline" }), "mt-1 self-start")}
            >
              Map another farm
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
