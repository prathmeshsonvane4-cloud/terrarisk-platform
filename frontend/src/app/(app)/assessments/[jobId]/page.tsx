"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { AssessmentTimeline } from "@/features/assessment/assessment-timeline";
import { ReportTriggerConflictError, useTriggerReport } from "@/features/report/use-trigger-report";
import { useJobStatus } from "@/features/report/use-job-status";
import { useFarms } from "@/features/workspace/use-farms";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The Assessment Run page (Product Design v2 §7.3 "the flagship trust
 * screen" — M2B P8). Entirely reconstructed from `useJobStatus`'s poll
 * of GET /jobs/{id} on every mount: a hard refresh, a closed-and-reopened
 * tab, or a different device all land here and see the exact same real
 * timeline the server has recorded — there is no client-only progress
 * state to lose.
 */
export default function AssessmentStatusPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const { data: job, isPending, isError, error, refetch } = useJobStatus(jobId);
  const { data: farms } = useFarms();
  const retry = useTriggerReport();

  // Auto-advance the moment the job completes — including the
  // refresh/reconnect case where the page loads and the job is already
  // done (entity_id carries the risk-score id once status is "done").
  useEffect(() => {
    if (job?.status === "done" && job.entity_id) {
      router.replace(`/reports/${job.entity_id}`);
    }
  }, [job, router]);

  // entity_id is the farm_id for as long as the job hasn't reached DONE
  // (P4 polymorphism) — while pending/running/failed, it's always a
  // real farm id, so this lookup is safe for exactly those three states.
  const farm = job && job.status !== "done" && job.entity_id ? farms?.find((f) => f.id === job.entity_id) : undefined;

  function handleRetry() {
    if (!job?.entity_id) return;
    retry.mutate(job.entity_id, {
      onSuccess: (data) => router.replace(`/assessments/${data.job_id}`),
      onError: (err) => {
        if (err instanceof ReportTriggerConflictError) {
          router.replace(`/assessments/${err.jobId}`);
        }
      },
    });
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4 md:p-6">
      {isPending && (
        <div role="status" aria-label="Checking assessment status" className="flex flex-col gap-3">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}

      {isError && (
        <div className="flex flex-col gap-3">
          <ErrorState error={error} onRetry={() => refetch()} referenceId={jobId} />
          <Link href="/assessments/new" className={cn(buttonVariants({ variant: "outline" }), "self-start")}>
            Start a new assessment
          </Link>
        </div>
      )}

      {job && (
        <div className="flex flex-col gap-4 rounded-lg border p-5">
          <header>
            <p className="text-base font-medium">
              {farm ? (
                <>
                  {farm.village_name}
                  <span className="font-normal text-muted-foreground"> · {formatArea(farm.area_ha)}</span>
                </>
              ) : (
                "Climate assessment"
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              Started {new Date(job.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "medium" })}
            </p>
          </header>

          {job.progress && job.progress.stages.length > 0 ? (
            <AssessmentTimeline stages={job.progress.stages} />
          ) : (
            <p className="text-sm text-muted-foreground">
              {job.status === "pending" ? "Queued — waiting to start." : "No stage detail recorded for this run."}
            </p>
          )}

          {(job.status === "pending" || job.status === "running") && (
            <p className="text-xs text-muted-foreground">
              This analysis queries the satellite record for this boundary. You can leave this page — it
              continues on the server, and this timeline will show exactly where it is when you return.
            </p>
          )}

          {job.status === "failed" && (
            <div className="flex flex-col gap-2 border-t pt-3">
              <p role="alert" className="text-sm text-destructive">
                {job.error_message ?? "The analysis could not be completed."}
              </p>
              {retry.isError && !(retry.error instanceof ReportTriggerConflictError) && (
                <p role="alert" className="text-xs text-destructive">
                  {retry.error.message}
                </p>
              )}
              <div className="flex gap-2">
                <Button onClick={handleRetry} disabled={retry.isPending || !job.entity_id} size="sm">
                  {retry.isPending ? "Starting…" : "Retry"}
                </Button>
                <Link href="/" className={buttonVariants({ variant: "outline", size: "sm" })}>
                  Back to workspace
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
