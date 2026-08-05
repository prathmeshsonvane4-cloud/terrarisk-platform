"use client";

import { ClipboardList, MapPin } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { DELINEATION_METHOD_LABELS } from "@/features/water-intelligence/labels";
import { useCatchments } from "@/features/water-intelligence/use-catchments";
import { useWaterReportHistories } from "@/features/water-intelligence/use-water-report-histories";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

import { programmeSummaryCounts, summarizeMonthOverMonth } from "./programme-summary";
import { RecommendationCard } from "./recommendation-card";
import { compareBySeverity, deriveRecommendations, highestSeverity } from "./recommendations";

// Enough runs for the 3-run declining-trend rule plus a month-over-month
// comparison, without pulling a catchment's entire history for a queue
// view that only ever reads the most recent handful.
const HISTORY_LIMIT_FOR_QUEUE = 6;

interface PriorityQueueViewProps {
  /** When set, shows at most this many catchments (highest priority
   * first) with a link to the full queue below them — the Overview
   * landing page's "today's priorities at a glance" use. Omit for the
   * full, unabridged Priority Queue page. */
  maxCatchments?: number;
  /** Hides the page-level heading/intro and "Back to Catchments" link —
   * for embedding inside a page that already has its own heading. */
  embedded?: boolean;
}

/**
 * Every catchment a programme is monitoring, ranked by what needs
 * attention first, with the programme-wide summary above it. Shared
 * between the standalone /catchments/priority-queue page and the
 * Overview landing page's compact preview for Water Intelligence roles
 * — one real view, two places it's reachable from, no duplicated logic.
 */
export function PriorityQueueView({ maxCatchments, embedded = false }: PriorityQueueViewProps) {
  const { data: catchments, isPending: catchmentsPending, isError, error, refetch } = useCatchments();
  const catchmentIds = catchments?.map((catchment) => catchment.id) ?? [];
  const histories = useWaterReportHistories(catchmentIds, HISTORY_LIMIT_FOR_QUEUE);

  const isPending = catchmentsPending || histories.some((history) => history.isPending);

  if (isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (isError) {
    return <ErrorState error={error} onRetry={() => refetch()} />;
  }

  if (!catchments || catchments.length === 0) {
    return (
      <EmptyState
        icon={ClipboardList}
        title="No catchments to prioritise yet"
        description="Add a catchment and generate its first water report — recommendations for what needs attention will appear here automatically, ranked highest priority first."
        action={{ label: "Add a catchment", href: "/catchments/new" }}
      />
    );
  }

  const rows = catchmentIds.map((catchmentId) => {
    const catchment = catchments.find((item) => item.id === catchmentId)!;
    const history = histories.find((item) => item.catchmentId === catchmentId)?.data ?? [];
    const recommendations = deriveRecommendations(history);
    return { catchment, recommendations };
  });
  rows.sort((a, b) => compareBySeverity(a.recommendations, b.recommendations));

  const visibleRows = maxCatchments ? rows.slice(0, maxCatchments) : rows;
  const hiddenCount = rows.length - visibleRows.length;

  const summary = programmeSummaryCounts(rows.map((row) => row.recommendations));
  const monthOverMonth = summarizeMonthOverMonth(catchmentIds.map((id) => histories.find((h) => h.catchmentId === id)?.data ?? []));

  return (
    <div className="flex flex-col gap-5">
      {!embedded && (
        <header className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">Priority Queue</h1>
            <p className="text-sm text-muted-foreground">
              Every catchment TerraRisk is monitoring, ranked by what needs attention first — using the same satellite
              water-balance data as each catchment&rsquo;s own report, not a separate model.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/catchments/map" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-1.5")}>
              <MapPin aria-hidden className="size-4" />
              View on map
            </Link>
            <Link href="/catchments" className={buttonVariants({ variant: "outline", size: "sm" })}>
              Back to Catchments
            </Link>
          </div>
        </header>
      )}

      <Card size="sm">
        <CardHeader>
          <CardTitle>Programme summary</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">How many catchments fall into each situation, right now:</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <SummaryStat label="Need a field visit" value={summary.needs_field_visit} />
            <SummaryStat label="Need validation" value={summary.needs_validation} />
            <SummaryStat label="Showing unexpected behaviour" value={summary.unexpected_behaviour} />
            <SummaryStat label="In sustained decline" value={summary.declining_trend} />
            <SummaryStat label="No report yet" value={summary.needs_first_report} />
            <SummaryStat label="On track" value={summary.stable} />
          </div>

          {monthOverMonth.comparableCatchments > 0 ? (
            <p className="text-xs text-muted-foreground">
              Compared with a report from a different calendar month: {monthOverMonth.improved} improved,{" "}
              {monthOverMonth.declined} got worse, {monthOverMonth.unchanged} unchanged ({monthOverMonth.comparableCatchments}{" "}
              {monthOverMonth.comparableCatchments === 1 ? "catchment has" : "catchments have"} a report from an earlier month to
              compare against).
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              No catchment yet has reports from two different calendar months, so a month-over-month comparison isn&rsquo;t
              available.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        {visibleRows.map(({ catchment, recommendations }) => (
          <Card key={catchment.id} size="sm">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>
                    <Link href={`/catchments/${catchment.id}`} className="hover:underline">
                      {catchment.name}
                    </Link>
                  </CardTitle>
                  <p className="text-xs text-muted-foreground">
                    {formatArea(catchment.area_ha)} · {DELINEATION_METHOD_LABELS[catchment.delineation_method]}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      highestSeverity(recommendations) === "high" && "bg-red-100 text-red-900",
                      highestSeverity(recommendations) === "medium" && "bg-amber-100 text-amber-900",
                      highestSeverity(recommendations) === "low" && "bg-sky-100 text-sky-900",
                      highestSeverity(recommendations) === "info" && "bg-emerald-100 text-emerald-900",
                    )}
                  >
                    {recommendations.length} {recommendations.length === 1 ? "recommendation" : "recommendations"}
                  </span>
                  {/* A queue row names a village; this puts it back in its
                      landscape, where whether its neighbours share the
                      problem is visible. */}
                  <Link
                    href={`/catchments/map?focus=${catchment.id}`}
                    className={cn(buttonVariants({ size: "sm", variant: "outline" }), "gap-1.5")}
                  >
                    <MapPin aria-hidden className="size-3.5" />
                    Locate on Map
                  </Link>
                </div>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {recommendations.map((recommendation, index) => (
                <RecommendationCard key={`${catchment.id}-${recommendation.category}-${index}`} recommendation={recommendation} />
              ))}
            </CardContent>
          </Card>
        ))}
      </div>

      {hiddenCount > 0 && (
        <Link
          href="/catchments/priority-queue"
          className={cn(buttonVariants({ variant: "outline", size: "sm" }), "self-start")}
        >
          View all {rows.length} catchments in the Priority Queue
        </Link>
      )}
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-xl font-semibold tabular-nums">{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
