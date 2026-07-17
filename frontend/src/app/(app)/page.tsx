"use client";

import Link from "next/link";
import { ArrowRight, Plus } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/auth-context";
import { useAssessments } from "@/features/workspace/use-assessments";
import { useFarms } from "@/features/workspace/use-farms";
import { useReports } from "@/features/workspace/use-reports";
import { RISK_BANDS } from "@/lib/risk-bands";
import { cn } from "@/lib/utils";

function formatElapsed(isoDate: string): string {
  const ms = Date.now() - new Date(isoDate).getTime();
  const minutes = Math.max(0, Math.round(ms / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

/**
 * The post-login workspace home (Product Design v2 §7.1). Replaces the
 * old one-shot funnel: an officer resumes in-flight work, opens recent
 * reports, and sees branch activity before ever touching the wizard.
 * Every number here is a live read of already-persisted backend state —
 * no rollup table, no client-side estimation.
 */
export default function OverviewPage() {
  const { session } = useAuth();
  const {
    data: assessments,
    isPending: assessmentsPending,
    isError: assessmentsError,
    error: assessmentsErrorObj,
    refetch: refetchAssessments,
  } = useAssessments();
  const { data: farms, isPending: farmsPending, isError: farmsError, error: farmsErrorObj, refetch: refetchFarms } = useFarms();
  const {
    data: reports,
    isPending: reportsPending,
    isError: reportsError,
    error: reportsErrorObj,
    refetch: refetchReports,
  } = useReports();

  const inFlight = assessments?.filter((item) => item.status === "pending" || item.status === "running") ?? [];
  const recentReports = reports?.slice(0, 5) ?? [];
  const highRiskCount = reports?.filter((r) => r.overall_band === "high" || r.overall_band === "very_high").length;

  const firstName = session?.fullName.split(" ")[0];
  const isEmpty =
    !farmsPending &&
    !reportsPending &&
    !farmsError &&
    !reportsError &&
    farms?.length === 0 &&
    reports?.length === 0;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">{firstName ? `Good to see you, ${firstName}` : "Overview"}</h1>
        <Link href="/assessments/new" className={cn(buttonVariants({ size: "sm" }), "gap-1.5")}>
          <Plus aria-hidden className="size-4" />
          New assessment
        </Link>
      </header>

      {(farmsError || reportsError) && (
        <ErrorState
          error={farmsErrorObj ?? reportsErrorObj}
          onRetry={() => {
            if (farmsError) refetchFarms();
            if (reportsError) refetchReports();
          }}
        />
      )}

      {isEmpty && (
        <Card>
          <CardContent className="flex flex-col items-start gap-3 py-6">
            <p className="text-sm font-medium">No farms mapped yet</p>
            <p className="text-sm text-muted-foreground">
              Start by mapping a farm boundary — the first climate assessment follows the same
              flow, in one continuous run.
            </p>
            <Link href="/assessments/new" className={buttonVariants({ size: "sm" })}>
              Map your first farm
            </Link>
          </CardContent>
        </Card>
      )}

      {!isEmpty && (
        <>
          {(assessmentsPending || assessmentsError || inFlight.length > 0) && (
            <Card>
              <CardHeader>
                <CardTitle>In progress</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-1">
                {assessmentsPending && <Skeleton className="h-4 w-48" />}
                {assessmentsError && <ErrorState error={assessmentsErrorObj} onRetry={() => refetchAssessments()} />}
                {!assessmentsPending && !assessmentsError && inFlight.length === 0 && (
                  <p className="text-sm text-muted-foreground">Nothing running right now.</p>
                )}
                {inFlight.map((item) => (
                  <Link
                    key={item.job_id}
                    href={`/assessments/${item.job_id}`}
                    className="flex items-center justify-between gap-2 rounded-lg px-2 py-2 text-sm hover:bg-muted"
                  >
                    <span className="flex items-center gap-2">
                      <span aria-hidden className="size-1.5 shrink-0 animate-pulse rounded-full bg-primary" />
                      {item.village_name ?? "Farm"}
                      {item.area_ha !== null && (
                        <span className="text-muted-foreground">· {item.area_ha.toFixed(2)} ha</span>
                      )}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      <span className="capitalize">{item.status}</span> · started{" "}
                      {formatElapsed(item.created_at)} ago
                    </span>
                  </Link>
                ))}
              </CardContent>
            </Card>
          )}

          <div className="grid gap-4 md:grid-cols-[1fr_auto]">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>Recent reports</CardTitle>
                <Link href="/reports" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "gap-1")}>
                  View all
                  <ArrowRight aria-hidden className="size-3.5" />
                </Link>
              </CardHeader>
              <CardContent className="flex flex-col gap-1">
                {reportsPending && <Skeleton className="h-4 w-32" />}
                {!reportsPending && !reportsError && recentReports.length === 0 && (
                  <p className="text-sm text-muted-foreground">No reports issued yet.</p>
                )}
                {recentReports.map((report) => {
                  const band = RISK_BANDS[report.overall_band];
                  return (
                    <Link
                      key={report.risk_score_id}
                      href={`/reports/${report.risk_score_id}`}
                      className="flex items-center justify-between gap-2 rounded-lg px-2 py-2 text-sm hover:bg-muted"
                    >
                      <span>
                        {report.village_name}
                        <span className="text-muted-foreground"> · {report.taluka_name}</span>
                      </span>
                      <span className="flex items-center gap-2 text-xs">
                        <span className={cn("rounded-full px-2 py-0.5 font-medium", band.chipClass)}>
                          {band.label}
                        </span>
                        <span className="tabular-nums text-muted-foreground">
                          {Math.round(report.overall_score)}
                        </span>
                      </span>
                    </Link>
                  );
                })}
              </CardContent>
            </Card>

            <Card className="md:w-56">
              <CardHeader>
                <CardTitle>This branch</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <div>
                  <p className="text-2xl font-semibold tabular-nums">
                    {farmsPending || farmsError ? "—" : farms?.length}
                  </p>
                  <p className="text-xs text-muted-foreground">farms mapped</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold tabular-nums">
                    {reportsPending || reportsError ? "—" : reports?.length}
                  </p>
                  <p className="text-xs text-muted-foreground">reports issued</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold tabular-nums">
                    {reportsPending || reportsError ? "—" : (highRiskCount ?? 0)}
                  </p>
                  <p className="text-xs text-muted-foreground">high or very high risk</p>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
