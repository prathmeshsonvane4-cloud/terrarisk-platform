"use client";

import Link from "next/link";
import { ArrowRight, MapPin, Plus } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { RiskBandChip } from "@/components/ui/risk-band-chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/auth-context";
import { PriorityQueueView } from "@/features/water-intelligence/priority-queue/priority-queue-view";
import { useAssessments } from "@/features/workspace/use-assessments";
import { useFarms } from "@/features/workspace/use-farms";
import { useReports } from "@/features/workspace/use-reports";
import { isWaterIntelligenceRole } from "@/lib/roles";
import { cn } from "@/lib/utils";

// How many catchments the compact preview on this landing page shows —
// Water Intelligence's own equivalent of the Service 1 view's "Recent
// reports" cap, just ranked by urgency instead of recency.
const LANDING_PRIORITY_QUEUE_PREVIEW_SIZE = 5;

/**
 * Water Intelligence's own landing content (docs/WELL_Labs_Demo_Guide.md)
 * — a Programme Officer/Admin logging in was previously shown Service
 * 1's farm-onboarding empty state ("Map your first farm"), which has
 * nothing to do with their product and nothing they can even act on.
 * Reuses PriorityQueueView exactly as /catchments/priority-queue does —
 * no new data fetching, no new logic, just this role's own real content
 * on the route every role already lands on after login.
 */
function WaterIntelligenceOverview({ firstName }: { firstName: string | undefined }) {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">{firstName ? `Good to see you, ${firstName}` : "Overview"}</h1>
          <p className="text-sm text-muted-foreground">
            TerraRisk Water Intelligence turns satellite rainfall, vegetation, and surface-water readings into a map of
            where water stress is building, and a ranked list of which villages need attention this week, and why.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/catchments/map" className={cn(buttonVariants({ size: "sm", variant: "outline" }), "gap-1.5")}>
            <MapPin aria-hidden className="size-4" />
            Open map
          </Link>
          <Link href="/catchments/new" className={cn(buttonVariants({ size: "sm" }), "gap-1.5")}>
            <Plus aria-hidden className="size-4" />
            New catchment
          </Link>
        </div>
      </header>
      <PriorityQueueView maxCatchments={LANDING_PRIORITY_QUEUE_PREVIEW_SIZE} embedded />
    </div>
  );
}

function formatElapsed(isoDate: string): string {
  const ms = Date.now() - new Date(isoDate).getTime();
  const minutes = Math.max(0, Math.round(ms / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

/**
 * The post-login workspace home. Dispatches by role rather than by
 * route: Water Intelligence roles (programme_officer/programme_admin)
 * have no farms, assessments, or bank reports to show here at all, so
 * showing them Service 1's "map your first farm" empty state is not
 * just irrelevant, it's actively confusing. Same "/" route, same
 * useAuth() session either way — this is a presentation choice, not a
 * new page or a new workflow.
 */
export default function OverviewPage() {
  const { session } = useAuth();
  if (session && isWaterIntelligenceRole(session.role)) {
    return <WaterIntelligenceOverview firstName={session.fullName.split(" ")[0]} />;
  }
  return <ServiceOneOverview />;
}

/**
 * Service 1's post-login workspace home (Product Design v2 §7.1).
 * Replaces the old one-shot funnel: an officer resumes in-flight work,
 * opens recent reports, and sees branch activity before ever touching
 * the wizard. Every number here is a live read of already-persisted
 * backend state — no rollup table, no client-side estimation. Unchanged
 * by the role dispatch above — every line below is exactly what this
 * file already did before Water Intelligence roles got their own branch.
 */
function ServiceOneOverview() {
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
        <EmptyState
          title="Nothing mapped for this branch yet"
          description="This workspace is ready — it's just waiting on the first farm boundary. Mapping one and running its climate assessment happen in a single continuous flow."
          action={{ label: "Map your first farm", href: "/assessments/new" }}
        />
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
                {recentReports.map((report) => (
                  <Link
                    key={report.risk_score_id}
                    href={`/reports/${report.risk_score_id}`}
                    className="flex items-center justify-between gap-2 rounded-lg px-2 py-2 text-sm hover:bg-muted"
                  >
                    <span>
                      {report.village_name}
                      <span className="text-muted-foreground"> · {report.taluka_name}</span>
                    </span>
                    <RiskBandChip band={report.overall_band} score={report.overall_score} />
                  </Link>
                ))}
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
