"use client";

import Link from "next/link";

import { useAssessments, type AssessmentListItem } from "@/features/workspace/use-assessments";
import { RISK_BANDS } from "@/lib/risk-bands";
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
  const { data: assessments, isPending, isError, error } = useAssessments();

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
      <h1 className="text-lg font-semibold">Assessments</h1>

      {isPending && <p className="text-sm text-muted-foreground">Loading assessments…</p>}

      {isError && (
        <p role="alert" className="text-sm text-muted-foreground">
          {error.message}
        </p>
      )}

      {!isPending && !isError && assessments.length === 0 && (
        <div className="rounded-lg border p-5 text-sm">
          <p className="font-medium">No assessments yet</p>
          <p className="mt-1 text-muted-foreground">
            Runs triggered by you or a colleague at your branch will appear here.
          </p>
        </div>
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
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      RISK_BANDS[item.overall_band].chipClass,
                    )}
                  >
                    {RISK_BANDS[item.overall_band].label} · {Math.round(item.overall_score ?? 0)}
                  </span>
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
