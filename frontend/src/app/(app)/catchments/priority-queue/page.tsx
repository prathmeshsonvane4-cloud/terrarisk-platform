"use client";

import { ClipboardList } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { DELINEATION_METHOD_LABELS } from "@/features/water-intelligence/labels";
import { programmeSummaryCounts, summarizeMonthOverMonth } from "@/features/water-intelligence/priority-queue/programme-summary";
import { RecommendationCard } from "@/features/water-intelligence/priority-queue/recommendation-card";
import { compareBySeverity, deriveRecommendations, highestSeverity } from "@/features/water-intelligence/priority-queue/recommendations";
import { useCatchments } from "@/features/water-intelligence/use-catchments";
import { useWaterReportHistories } from "@/features/water-intelligence/use-water-report-histories";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

// Enough runs for the 3-run declining-trend rule plus a month-over-month
// comparison, without pulling a catchment's entire history for a queue
// view that only ever reads the most recent handful.
const HISTORY_LIMIT_FOR_QUEUE = 6;

export default function PriorityQueuePage() {
  const { data: catchments, isPending: catchmentsPending, isError, error, refetch } = useCatchments();
  const catchmentIds = catchments?.map((catchment) => catchment.id) ?? [];
  const histories = useWaterReportHistories(catchmentIds, HISTORY_LIMIT_FOR_QUEUE);

  const isPending = catchmentsPending || histories.some((history) => history.isPending);

  if (isPending) {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
        <Skeleton className="h-7 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
        <p className="text-sm text-destructive">{error instanceof Error ? error.message : "Failed to load catchments."}</p>
        <button type="button" onClick={() => refetch()} className={buttonVariants({ variant: "outline", size: "sm" })}>
          Retry
        </button>
      </div>
    );
  }

  if (!catchments || catchments.length === 0) {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
        <EmptyState
          icon={ClipboardList}
          title="No catchments to prioritise yet"
          description="Add catchments and generate water reports for them to see programme-wide recommendations here."
          action={{ label: "Back to Catchments", href: "/catchments" }}
        />
      </div>
    );
  }

  const rows = catchmentIds.map((catchmentId) => {
    const catchment = catchments.find((item) => item.id === catchmentId)!;
    const history = histories.find((item) => item.catchmentId === catchmentId)?.data ?? [];
    const recommendations = deriveRecommendations(history);
    return { catchment, recommendations };
  });
  rows.sort((a, b) => compareBySeverity(a.recommendations, b.recommendations));

  const summary = programmeSummaryCounts(rows.map((row) => row.recommendations));
  const monthOverMonth = summarizeMonthOverMonth(catchmentIds.map((id) => histories.find((h) => h.catchmentId === id)?.data ?? []));

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Priority Queue</h1>
          <p className="text-sm text-muted-foreground">Every catchment, ranked by what needs attention first — not by name.</p>
        </div>
        <Link href="/catchments" className={buttonVariants({ variant: "outline", size: "sm" })}>
          Back to Catchments
        </Link>
      </header>

      <Card size="sm">
        <CardHeader>
          <CardTitle>Programme summary</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <SummaryStat label="Needs field visit" value={summary.needs_field_visit} />
            <SummaryStat label="Needs validation" value={summary.needs_validation} />
            <SummaryStat label="Unexpected behaviour" value={summary.unexpected_behaviour} />
            <SummaryStat label="Declining trend" value={summary.declining_trend} />
            <SummaryStat label="No report yet" value={summary.needs_first_report} />
            <SummaryStat label="On track" value={summary.stable} />
          </div>

          {monthOverMonth.comparableCatchments > 0 ? (
            <p className="text-xs text-muted-foreground">
              Compared with a run from a different calendar month: {monthOverMonth.improved} improved, {monthOverMonth.declined} declined,{" "}
              {monthOverMonth.unchanged} unchanged ({monthOverMonth.comparableCatchments} catchments had a real cross-month run to compare
              against).
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              No catchment yet has runs spanning two different calendar months, so a month-over-month comparison isn&rsquo;t available.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        {rows.map(({ catchment, recommendations }) => (
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
