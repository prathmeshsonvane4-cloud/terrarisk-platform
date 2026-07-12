"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { buttonVariants } from "@/components/ui/button";
import { STATUS_COPY } from "@/features/report/status-copy";
import { useJobStatus } from "@/features/report/use-job-status";
import { cn } from "@/lib/utils";

export default function ReportStatusPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const { data: job, isPending, isError, error } = useJobStatus(jobId);

  // Auto-advance the moment the job completes — including the
  // refresh/reconnect case where the page loads and the job is already
  // done (entity_id carries the risk-score id once status is "done").
  useEffect(() => {
    if (job?.status === "done" && job.entity_id) {
      router.replace(`/reports/${job.entity_id}`);
    }
  }, [job, router]);

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="flex w-full max-w-md flex-col gap-3 rounded-lg border p-5 text-sm">
        {isPending && <p className="text-muted-foreground">Checking report status…</p>}

        {isError && (
          <>
            <p className="font-medium">Could not load this job</p>
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

        {job && (
          <>
            <div className="flex items-center gap-2.5">
              {(job.status === "pending" || job.status === "running") && (
                <span
                  aria-hidden
                  className="size-2.5 shrink-0 animate-pulse rounded-full bg-primary"
                />
              )}
              <p className="text-base font-medium">{STATUS_COPY[job.status].title}</p>
            </div>
            <p className="text-muted-foreground">{STATUS_COPY[job.status].detail}</p>

            {job.status === "failed" && (
              <Link
                href="/farms/new"
                className={cn(buttonVariants({ variant: "outline" }), "mt-1 self-start")}
              >
                Back to farm mapping
              </Link>
            )}
            {job.status === "done" && job.entity_id && (
              <Link
                href={`/reports/${job.entity_id}`}
                className={cn(buttonVariants(), "mt-1 self-start")}
              >
                View climate report
              </Link>
            )}
          </>
        )}
      </div>
    </div>
  );
}
