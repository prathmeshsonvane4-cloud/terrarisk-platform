"use client";

import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";
import { ReportTriggerConflictError, useTriggerReport } from "@/features/report/use-trigger-report";
import { useFarmAssessmentHistory } from "@/features/workspace/use-farm-assessment-history";
import { useFarms } from "@/features/workspace/use-farms";
import { formatArea } from "@/lib/format";
import { RISK_BANDS } from "@/lib/risk-bands";
import { cn } from "@/lib/utils";

/**
 * Farm detail — the registry record (Product Design v2 §7.4): identity,
 * the full append-only assessment history (GET /farms/{id}/assessments),
 * and the re-assess action. The boundary map from the design doc's
 * wireframe is deliberately not included yet — neither GET /farms nor
 * GET /farms/{id} carries geometry (only a completed report's payload
 * does), and this page shows no placeholder chrome for data it doesn't
 * have (Product Design v2: no placeholder content, ever).
 */
export default function FarmDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: farms, isPending: farmsPending } = useFarms();
  const { data: history, isPending: historyPending, isError, error } = useFarmAssessmentHistory(id);
  const triggerReport = useTriggerReport();

  const farm = farms?.find((item) => item.id === id);

  function handleReassess() {
    triggerReport.mutate(id, {
      onSuccess: (data) => router.push(`/assessments/${data.job_id}`),
      onError: (err) => {
        if (err instanceof ReportTriggerConflictError) {
          router.push(`/assessments/${err.jobId}`);
        }
      },
    });
  }

  if (farmsPending || historyPending) {
    return <div className="p-6 text-sm text-muted-foreground">Loading farm…</div>;
  }

  if (isError || !farm) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="flex w-full max-w-md flex-col gap-3 rounded-lg border p-5 text-sm">
          <p className="font-medium">Could not load this farm</p>
          <p role="alert" className="text-muted-foreground">
            {isError ? error.message : "This farm was not found, or you don't have access to it."}
          </p>
          <Link href="/farms" className={cn(buttonVariants({ variant: "outline" }), "self-start")}>
            Back to Farms
          </Link>
        </div>
      </div>
    );
  }

  const activeJob = history?.active_job ?? farm.active_job;
  const hasHistory = (history?.items.length ?? 0) > 0;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">
            {farm.village_name}
            <span className="font-normal text-muted-foreground">
              {" "}
              · {farm.taluka_name}, {farm.district_name}
            </span>
          </h1>
          <p className="text-sm text-muted-foreground">
            {formatArea(farm.area_ha)} · Mapped by {farm.officer_name} ·{" "}
            {new Date(farm.created_at).toLocaleDateString("en-IN", { dateStyle: "medium" })}
          </p>
        </div>
        <Button onClick={handleReassess} disabled={triggerReport.isPending || Boolean(activeJob)} size="sm">
          {activeJob ? "Assessment running…" : triggerReport.isPending ? "Starting…" : "Re-assess"}
        </Button>
      </header>

      {triggerReport.isError && !(triggerReport.error instanceof ReportTriggerConflictError) && (
        <p role="alert" className="text-sm text-destructive">
          {triggerReport.error.message}
        </p>
      )}

      {activeJob && (
        <Link
          href={`/assessments/${activeJob.job_id}`}
          className="flex items-center gap-2 rounded-lg border bg-muted/50 px-4 py-3 text-sm hover:bg-muted"
        >
          <span aria-hidden className="size-1.5 shrink-0 animate-pulse rounded-full bg-primary" />
          An assessment is {activeJob.status} for this farm — view progress
        </Link>
      )}

      <section>
        <h2 className="mb-2 text-sm font-medium">Assessment history</h2>

        {!hasHistory && (
          <div className="rounded-lg border p-5 text-sm">
            <p className="font-medium">No assessments yet for this farm</p>
            <p className="mt-1 text-muted-foreground">Run the first one to get a climate risk score.</p>
          </div>
        )}

        {hasHistory && (
          <div className="flex flex-col divide-y rounded-lg border">
            {history!.items.map((item) => {
              const band = RISK_BANDS[item.overall_band];
              return (
                <Link
                  key={item.risk_score_id}
                  href={`/reports/${item.risk_score_id}`}
                  className="flex items-center justify-between gap-2 px-4 py-3 text-sm hover:bg-muted"
                >
                  <span className="text-muted-foreground">
                    {new Date(item.computed_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", band.chipClass)}>
                      {band.label}
                    </span>
                    <span className="tabular-nums">{Math.round(item.overall_score)}</span>
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
