"use client";

import { ListChecksIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { RiskBandChip } from "@/components/ui/risk-band-chip";
import { SkeletonList } from "@/components/ui/skeleton";
import { useAssessments, type AssessmentListItem } from "@/features/workspace/use-assessments";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<AssessmentListItem["status"], string> = {
  pending: "Queued",
  running: "Running",
  done: "Done",
  failed: "Failed",
};

function targetHref(item: AssessmentListItem): string {
  return item.status === "done" && item.risk_score_id
    ? `/reports/${item.risk_score_id}`
    : `/assessments/${item.job_id}`;
}

/**
 * The Assessments workspace index (Product Design v2 §7, screen 5) —
 * every farm-report run in scope, farm context resolved regardless of
 * status (GET /jobs, M2B P7). The operational queue: what's running,
 * what failed, what's ready to open.
 */
export default function AssessmentsPage() {
  const { data: assessments, isPending, isError, error, refetch } = useAssessments();

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
      <h1 className="text-lg font-semibold">Assessments</h1>

      {isPending && <SkeletonList rows={4} />}

      {isError && <ErrorState error={error} onRetry={() => refetch()} />}

      {!isPending && !isError && assessments.length === 0 && (
        <EmptyState
          icon={ListChecksIcon}
          title="No assessments yet"
          description="Nobody at this branch has started a climate assessment yet — every run, queued through complete, will appear here."
          action={{ label: "Start an assessment", href: "/assessments/new" }}
        />
      )}

      {!isPending && !isError && assessments.length > 0 && (
        <div className="flex flex-col divide-y rounded-lg border">
          {assessments.map((item) => (
            <Link
              key={item.job_id}
              href={targetHref(item)}
              className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm hover:bg-muted"
            >
              <div>
                <p className="font-medium">
                  {item.village_name ?? "Unknown farm"}
                  {item.area_ha !== null && (
                    <span className="font-normal text-muted-foreground"> · {item.area_ha.toFixed(2)} ha</span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground">
                  {item.officer_name} · started{" "}
                  {new Date(item.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
                  {item.status === "failed" && item.error_message && (
                    <span className="text-destructive"> · {item.error_message}</span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {(item.status === "pending" || item.status === "running") && (
                  <span aria-hidden className="size-1.5 shrink-0 animate-pulse rounded-full bg-primary" />
                )}
                {item.status === "done" && item.overall_band ? (
                  <RiskBandChip band={item.overall_band} score={item.overall_score ?? 0} />
                ) : (
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      item.status === "failed" ? "bg-destructive/10 text-destructive" : "bg-muted text-foreground",
                    )}
                  >
                    {STATUS_LABEL[item.status]}
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
