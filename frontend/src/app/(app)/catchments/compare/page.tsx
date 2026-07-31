"use client";

import { Droplets } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StorageChangeBandChip, StressBandChip } from "@/features/water-intelligence/band-styles";
import { formatMm, formatPercent } from "@/features/water-intelligence/format-water-report";
import { MetricTrendChart, type TrendPoint } from "@/features/water-intelligence/metric-trend-chart";
import { useCatchments, type CatchmentResponse } from "@/features/water-intelligence/use-catchments";
import { useWaterReportHistories } from "@/features/water-intelligence/use-water-report-histories";
import type { WaterReportHistoryItem } from "@/features/water-intelligence/use-water-report-history";
import { WATER_BALANCE_BAR_COLORS } from "@/features/water-intelligence/water-balance-chart";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

const MIN_CATCHMENTS_TO_COMPARE = 2;

/** Plain browser API, not useSearchParams() — same reasoning as
 * features/auth/login-form.tsx's getPostLoginPath: avoids the Suspense
 * boundary useSearchParams() would otherwise require, for a value this
 * page only ever needs after mount anyway. */
function getSelectedIdsFromUrl(): string[] {
  if (typeof window === "undefined") return [];
  const raw = new URLSearchParams(window.location.search).get("ids") ?? "";
  return raw
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean);
}

/**
 * Compare 2+ catchments side by side — the one screen this codebase had
 * no equivalent of at all before (docs/WELL_Labs_Raichur_Founder_Review_2026.md
 * Part 2/4/5): WELL Labs' own Raichur programme repeatedly frames the
 * water situation as *positional* (head-end vs. tail-end vs. dryland
 * farmers experience completely different water availability) — a
 * dashboard that can only show one catchment at a time cannot answer
 * that question, no matter how good its hydrology is. Reuses only
 * already-built pieces: the history endpoint, the existing band chips,
 * and MetricTrendChart (also new, shared with the single-catchment
 * dashboard's own trend section).
 */
export default function ComparecatchmentsPage() {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  useEffect(() => {
    setSelectedIds(getSelectedIdsFromUrl());
  }, []);

  const { data: catchments, isPending: catchmentsPending } = useCatchments();
  const histories = useWaterReportHistories(selectedIds);

  const selectedCatchments = selectedIds
    .map((id) => catchments?.find((catchment) => catchment.id === id))
    .filter((catchment): catchment is NonNullable<typeof catchment> => Boolean(catchment));

  const isPending = catchmentsPending || histories.some((history) => history.isPending);

  if (selectedIds.length < MIN_CATCHMENTS_TO_COMPARE) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 p-4 md:p-6">
        <EmptyState
          icon={Droplets}
          title="Select at least two catchments to compare"
          description="Go back to Catchments, check two or more boxes, then choose Compare selected."
          action={{ label: "Back to Catchments", href: "/catchments" }}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Compare catchments</h1>
          <p className="text-sm text-muted-foreground">
            {selectedCatchments.length > 0
              ? selectedCatchments.map((catchment) => catchment.name).join(" · ")
              : `${selectedIds.length} catchments`}
          </p>
        </div>
        <Link href="/catchments" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
          Back to Catchments
        </Link>
      </header>

      {isPending ? (
        <Skeleton className="h-72 w-full" />
      ) : (
        <>
          <Card size="sm">
            <CardHeader>
              <CardTitle>Latest report, side by side</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Metric</TableHead>
                    {selectedIds.map((id) => (
                      <TableHead key={id}>
                        {catchments?.find((catchment) => catchment.id === id)?.name ?? id}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <ComparisonRow
                    label="Area"
                    histories={histories}
                    catchments={catchments}
                    render={(_latest, catchment) => (catchment ? formatArea(catchment.area_ha) : "—")}
                  />
                  <ComparisonRow
                    label="Recharge stress"
                    histories={histories}
                    catchments={catchments}
                    render={(latest) =>
                      latest ? (
                        <StressBandChip band={latest.recharge_stress.stress_band} score={latest.recharge_stress.stress_score} />
                      ) : (
                        "No report yet"
                      )
                    }
                  />
                  <ComparisonRow
                    label="Storage change (recharge)"
                    histories={histories}
                    catchments={catchments}
                    render={(latest) =>
                      latest ? (
                        <div className="flex flex-col gap-1">
                          <span>{formatMm(latest.water_balance.storage_change_mm)}</span>
                          <StorageChangeBandChip band={latest.water_balance.storage_change_band} />
                        </div>
                      ) : (
                        "—"
                      )
                    }
                  />
                  <ComparisonRow
                    label="Rainfall"
                    histories={histories}
                    catchments={catchments}
                    render={(latest) => (latest ? formatMm(latest.water_balance.rainfall_mm) : "—")}
                  />
                  <ComparisonRow
                    label="ET"
                    histories={histories}
                    catchments={catchments}
                    render={(latest) => (latest ? formatMm(latest.water_balance.et_mm) : "—")}
                  />
                  <ComparisonRow
                    label="Runoff"
                    histories={histories}
                    catchments={catchments}
                    render={(latest) => (latest ? formatMm(latest.water_balance.runoff_mm) : "—")}
                  />
                  <ComparisonRow
                    label="Surface water trend"
                    histories={histories}
                    catchments={catchments}
                    render={(latest) => (latest ? formatPercent(latest.recharge_stress.surface_water_trend) : "—")}
                  />
                  <ComparisonRow
                    label="Report generated"
                    histories={histories}
                    catchments={catchments}
                    render={(latest) =>
                      latest ? new Date(latest.generated_at).toLocaleDateString("en-IN", { dateStyle: "medium" }) : "—"
                    }
                  />
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <div className="grid gap-4 sm:grid-cols-2">
            {histories.map((history) => {
              const catchment = catchments?.find((item) => item.id === history.catchmentId);
              const oldestFirst = [...(history.data ?? [])].reverse();
              const stressPoints: TrendPoint[] = oldestFirst.map((item) => ({
                generatedAt: item.generated_at,
                value: item.recharge_stress.stress_score,
              }));
              const storageChangePoints: TrendPoint[] = oldestFirst.map((item) => ({
                generatedAt: item.generated_at,
                value: item.water_balance.storage_change_mm,
              }));

              return (
                <Card key={history.catchmentId} size="sm">
                  <CardHeader>
                    <CardTitle className="text-sm">{catchment?.name ?? history.catchmentId}</CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-4">
                    <div>
                      <p className="mb-1.5 text-xs text-muted-foreground">Recharge stress score</p>
                      <MetricTrendChart
                        points={stressPoints}
                        color="#8b5cf6"
                        ariaLabel={`Recharge stress score over time for ${catchment?.name ?? "this catchment"}`}
                        valueFormatter={(value) => `${Math.round(value)} / 100`}
                      />
                    </div>
                    <div>
                      <p className="mb-1.5 text-xs text-muted-foreground">Storage change (mm)</p>
                      <MetricTrendChart
                        points={storageChangePoints}
                        color={WATER_BALANCE_BAR_COLORS.storageChange}
                        ariaLabel={`Storage change over time for ${catchment?.name ?? "this catchment"}`}
                        valueFormatter={(value) => formatMm(value)}
                      />
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

interface ComparisonRowProps {
  label: string;
  histories: ReturnType<typeof useWaterReportHistories>;
  catchments: CatchmentResponse[] | undefined;
  render: (latest: WaterReportHistoryItem | null, catchment: CatchmentResponse | undefined) => React.ReactNode;
}

/** One metric per row, one column per selected catchment — reads better
 * for "is A worse than B" than a catchment-per-row layout would, since
 * the eye scans across a row to compare, not down two separate columns. */
function ComparisonRow({ label, histories, catchments, render }: ComparisonRowProps) {
  return (
    <TableRow>
      <TableCell className="text-muted-foreground">{label}</TableCell>
      {histories.map((history) => {
        const latest = history.data?.[0] ?? null;
        const catchment = catchments?.find((item) => item.id === history.catchmentId);
        return <TableCell key={history.catchmentId}>{render(latest, catchment)}</TableCell>;
      })}
    </TableRow>
  );
}
