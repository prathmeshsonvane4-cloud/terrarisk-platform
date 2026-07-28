"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorState, InlineErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useJobStatus } from "@/features/report/use-job-status";
import { WaterReportTriggerConflictError, useTriggerWaterReport } from "@/features/water-intelligence/use-trigger-water-report";
import { cn } from "@/lib/utils";

/**
 * Water report run status — the Water Intelligence analogue of
 * app/(app)/assessments/[jobId]/page.tsx. Reuses useJobStatus
 * (features/report/use-job-status.ts) verbatim, unmodified: GET
 * /jobs/{id} is a shared, job-type-agnostic endpoint (app/api/jobs.py),
 * so the exact same polling hook — same capped-exponential-backoff
 * refetchInterval, same terminal-status stop condition — already works
 * for a catchment_water_report job with zero changes.
 *
 * No AssessmentTimeline here, deliberately: _run_water_report_job
 * (M5-002) never writes Job.progress — there is no per-stage tracking
 * for this pipeline yet, unlike generate_farm_report's ProgressTracker.
 * Rendering AssessmentTimeline against an always-null progress would
 * either crash or silently render nothing useful; showing a fabricated
 * stage list instead would be exactly the "fake progress" this product
 * never does. This page shows only the real, coarse status the server
 * actually has (pending/running/done/failed) until a future ticket adds
 * real per-stage tracking to the water-report pipeline.
 *
 * On done, redirects back to the catchment detail page — not to a
 * separate report page — since GET /catchments/{id}/water-reports (not
 * a per-run id) is where "the latest report" lives.
 */
export default function WaterReportStatusPage() {
  const { id, jobId } = useParams<{ id: string; jobId: string }>();
  const router = useRouter();
  const { data: job, isPending, isError, error, refetch } = useJobStatus(jobId);
  const retry = useTriggerWaterReport();

  useEffect(() => {
    if (job?.status === "done") {
      router.replace(`/catchments/${id}`);
    }
  }, [job, id, router]);

  function handleRetry() {
    retry.mutate(id, {
      onSuccess: (data) => router.replace(`/catchments/${id}/water-reports/${data.job_id}`),
      onError: (err) => {
        if (err instanceof WaterReportTriggerConflictError) {
          router.replace(`/catchments/${id}/water-reports/${err.jobId}`);
        }
      },
    });
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4 md:p-6">
      {isPending && (
        <div role="status" aria-label="Checking water report status" className="flex flex-col gap-3">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {isError && (
        <div className="flex flex-col gap-3">
          <ErrorState error={error} onRetry={() => refetch()} referenceId={jobId} />
          <Link href={`/catchments/${id}`} className={cn(buttonVariants({ variant: "outline" }), "self-start")}>
            Back to catchment
          </Link>
        </div>
      )}

      {job && (
        <div className="flex flex-col gap-4 rounded-lg border p-5">
          <header>
            <p className="text-base font-medium">Water report</p>
            <p className="text-xs text-muted-foreground">
              Started {new Date(job.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "medium" })}
            </p>
          </header>

          <p className="text-sm text-muted-foreground">
            {job.status === "pending" && "Queued — waiting to start."}
            {job.status === "running" && "Generating the water balance and recharge stress report…"}
            {job.status === "done" && "Complete — redirecting to the catchment…"}
          </p>

          {(job.status === "pending" || job.status === "running") && (
            <p className="text-xs text-muted-foreground">
              You can leave this page — it continues on the server, and this status will show exactly where it is
              when you return.
            </p>
          )}

          {job.status === "failed" && (
            <div className="flex flex-col gap-2 border-t pt-3">
              <p role="alert" className="text-sm text-destructive">
                {job.error_message ?? "The water report could not be completed."}
              </p>
              {retry.isError && !(retry.error instanceof WaterReportTriggerConflictError) && (
                <InlineErrorState error={retry.error} />
              )}
              <div className="flex gap-2">
                <Button onClick={handleRetry} disabled={retry.isPending} size="sm">
                  {retry.isPending ? "Starting…" : "Retry"}
                </Button>
                <Link href={`/catchments/${id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
                  Back to catchment
                </Link>
              </div>
              <p className="text-xs text-muted-foreground">
                Reference: job {job.id}. If this keeps happening, contact support with this reference.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
