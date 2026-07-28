"use client";

import { Droplets } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { Button, buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState, InlineErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StorageChangeBandChip, StressBandChip } from "@/features/water-intelligence/band-styles";
import { DELINEATION_METHOD_LABELS } from "@/features/water-intelligence/labels";
import { WaterReportTriggerConflictError, useTriggerWaterReport } from "@/features/water-intelligence/use-trigger-water-report";
import { useCatchments } from "@/features/water-intelligence/use-catchments";
import { useLatestWaterReport } from "@/features/water-intelligence/use-latest-water-report";
import { ApiError } from "@/lib/api/errors";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Catchment detail — identity, the "Trigger water report" action, and a
 * slim summary of the latest completed water report, all on one page.
 * Mirrors app/(app)/farms/[id]/page.tsx's structure (header + primary
 * action + in-flight-job banner + result section).
 *
 * The full report — every field, the water-balance/factor charts, CGWB
 * context, and the generated insights — lives at its own dedicated
 * route, /catchments/[id]/water-reports (ticket M6-002's dashboard), the
 * same "condensed summary on the parent, full detail on its own page"
 * split farms/[id] already has with reports/[id]. This page only shows
 * the headline band chips; duplicating the dashboard's full stat grid
 * here would be exactly the "duplicated styling" M6-002 was told to
 * avoid.
 */
export default function CatchmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: catchments, isPending: catchmentsPending } = useCatchments();
  const report = useLatestWaterReport(id);
  const trigger = useTriggerWaterReport();

  const catchment = catchments?.find((item) => item.id === id);

  function handleTrigger() {
    trigger.mutate(id, {
      onSuccess: (data) => router.push(`/catchments/${id}/water-reports/${data.job_id}`),
      onError: (err) => {
        if (err instanceof WaterReportTriggerConflictError) {
          router.push(`/catchments/${id}/water-reports/${err.jobId}`);
        }
      },
    });
  }

  if (catchmentsPending) {
    return (
      <div role="status" aria-label="Loading catchment" className="flex flex-1 flex-col gap-4 p-4 md:p-6">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (!catchment) {
    // Not present in the caller's own catchment list — indistinguishable
    // from "doesn't exist" by design (get_catchment's IDOR-safe 404),
    // same pattern as farms/[id]/page.tsx's own not-found rendering.
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-md">
          <ErrorState error={new ApiError("Catchment not found", 404)} />
          <Link href="/catchments" className={cn(buttonVariants({ variant: "outline" }), "mt-3 w-full")}>
            Back to Catchments
          </Link>
        </div>
      </div>
    );
  }

  const reportIsMissing = report.isError && report.error instanceof ApiError && report.error.status === 404;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">{catchment.name}</h1>
          <p className="text-sm text-muted-foreground">
            {formatArea(catchment.area_ha)} · {DELINEATION_METHOD_LABELS[catchment.delineation_method]} ·{" "}
            {new Date(catchment.created_at).toLocaleDateString("en-IN", { dateStyle: "medium" })}
          </p>
        </div>
        <Button onClick={handleTrigger} disabled={trigger.isPending} size="sm">
          {trigger.isPending ? "Starting…" : "Trigger water report"}
        </Button>
      </header>

      {trigger.isError && !(trigger.error instanceof WaterReportTriggerConflictError) && (
        <InlineErrorState error={trigger.error} onRetry={handleTrigger} />
      )}

      <section>
        <h2 className="mb-2 text-sm font-medium">Latest water report</h2>

        {report.isPending && <Skeleton className="h-40 w-full" />}

        {reportIsMissing && (
          <EmptyState
            icon={Droplets}
            title="No water report yet"
            description="Trigger a water report above to compute this catchment's water balance and recharge stress."
          />
        )}

        {report.isError && !reportIsMissing && <ErrorState error={report.error} onRetry={() => report.refetch()} />}

        {report.data && (
          <Link
            href={`/catchments/${id}/water-reports`}
            className="flex flex-col gap-3 rounded-lg border p-5 hover:bg-muted"
          >
            <p className="text-xs text-muted-foreground">
              Generated{" "}
              {new Date(report.data.generated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <StorageChangeBandChip band={report.data.water_balance.storage_change_band} />
              <StressBandChip band={report.data.recharge_stress.stress_band} score={report.data.recharge_stress.stress_score} />
            </div>
            <span className="text-xs font-medium text-primary">View full report →</span>
          </Link>
        )}
      </section>
    </div>
  );
}
