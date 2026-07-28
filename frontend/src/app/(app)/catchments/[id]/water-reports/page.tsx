"use client";

import { Droplets, Printer, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { StorageChangeBandChip, StressBandChip } from "@/features/water-intelligence/band-styles";
import { DownloadWaterReportJsonButton } from "@/features/water-intelligence/download-water-report-json-button";
import { formatMm, formatPercent, formatRatio } from "@/features/water-intelligence/format-water-report";
import { deriveWaterReportInsights } from "@/features/water-intelligence/insights";
import { DELINEATION_METHOD_LABELS } from "@/features/water-intelligence/labels";
import { DownloadWaterReportPdfButton } from "@/features/water-intelligence/pdf/download-water-report-pdf-button";
import { numberField } from "@/features/water-intelligence/raw-inputs";
import { bandForFactorScore } from "@/features/water-intelligence/stress-factor-bands";
import { SurfaceWaterIndicator } from "@/features/water-intelligence/surface-water-indicator";
import { useCatchments } from "@/features/water-intelligence/use-catchments";
import { useLatestWaterReport } from "@/features/water-intelligence/use-latest-water-report";
import { WaterBalanceChart } from "@/features/water-intelligence/water-balance-chart";
import { ApiError } from "@/lib/api/errors";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

const JOB_STATUS_BADGE_VARIANT: Record<string, "default" | "secondary" | "destructive"> = {
  done: "secondary",
  failed: "destructive",
  running: "default",
  pending: "default",
};

/**
 * The Water Intelligence Report dashboard (ticket M6-002) — every
 * section sourced from ONE already-built endpoint,
 * GET /catchments/{id}/water-reports (M5-003), plus the catchment's own
 * basic fields (useCatchments, already fetched this way by the M6-001
 * detail page). No new backend reads, no fabricated series: two
 * requested pieces of data don't exist in this response at all — a
 * monthly water-balance/surface-water series, and a distinct
 * "recharge" figure separate from storage_change_mm — both are
 * substituted with the closest real, honest equivalent, documented
 * inline at each spot (WaterBalanceChart's and SurfaceWaterIndicator's
 * own docstrings) rather than invented. Rendered as one continuous,
 * fully printable page (no tabs) — reports/[id]/page.tsx's tabs would
 * only print whichever tab was open, which this "print-friendly
 * layout" requirement rules out.
 */
export default function WaterReportDashboardPage() {
  const { id } = useParams<{ id: string }>();
  const { data: catchments, isPending: catchmentsPending } = useCatchments();
  const report = useLatestWaterReport(id);

  const catchment = catchments?.find((item) => item.id === id);
  const isPending = catchmentsPending || report.isPending;
  const reportIsMissing = report.isError && report.error instanceof ApiError && report.error.status === 404;

  if (isPending) {
    return (
      <div role="status" aria-label="Loading water report" className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 p-4 md:p-6">
        <Skeleton className="h-7 w-72" />
        <Skeleton className="h-4 w-56" />
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      </div>
    );
  }

  if (!catchment) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-md">
          <ErrorState error={new ApiError("Catchment not found", 404)} />
          <Link href="/catchments" className={cn(buttonVariants({ variant: "outline" }), "mt-3 w-full")}>
            Back to Catchments
          </Link>
        </div>
      </div>
    );
  }

  if (reportIsMissing) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 p-4 md:p-6">
        <h1 className="text-lg font-semibold">{catchment.name} — Water report</h1>
        <EmptyState
          icon={Droplets}
          title="No water report yet"
          description="Trigger a water report from the catchment page to see its dashboard here."
          action={{ label: "Back to catchment", href: `/catchments/${id}` }}
        />
      </div>
    );
  }

  if (report.isError) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 p-4 md:p-6">
        <ErrorState error={report.error} onRetry={() => report.refetch()} referenceId={id} />
        <Link href={`/catchments/${id}`} className={cn(buttonVariants({ variant: "outline" }), "self-start")}>
          Back to catchment
        </Link>
      </div>
    );
  }

  const data = report.data;
  const waterBalance = data.water_balance;
  const rechargeStress = data.recharge_stress;
  const confidence = numberField(rechargeStress.raw_inputs, "confidence");
  const insights = deriveWaterReportInsights(data);

  const factorCards = [
    {
      key: "rainfall",
      label: "Rainfall anomaly",
      rawValue: rechargeStress.rainfall_anomaly_ratio,
      rawLabel: formatRatio(rechargeStress.rainfall_anomaly_ratio),
      stressScore: numberField(rechargeStress.raw_inputs, "rainfall_stress"),
    },
    {
      key: "vegetation",
      label: "Vegetation condition (VCI)",
      rawValue: rechargeStress.vci,
      rawLabel: formatPercent(rechargeStress.vci),
      stressScore: numberField(rechargeStress.raw_inputs, "vegetation_stress"),
    },
    {
      key: "surface_water",
      label: "Surface water trend",
      rawValue: rechargeStress.surface_water_trend,
      rawLabel: formatPercent(rechargeStress.surface_water_trend),
      stressScore: numberField(rechargeStress.raw_inputs, "surface_water_stress"),
    },
  ];

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-5 p-4 md:p-6 print:max-w-none print:p-0">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">{catchment.name} — Water report</h1>
          <p className="text-sm text-muted-foreground">
            {formatArea(catchment.area_ha)} · {DELINEATION_METHOD_LABELS[catchment.delineation_method]}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          <Link href={`/catchments/${id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
            Back to catchment
          </Link>
          <Button size="sm" variant="outline" onClick={() => report.refetch()} disabled={report.isFetching} className="gap-1.5">
            <RefreshCw aria-hidden className={cn("size-4", report.isFetching && "animate-spin")} />
            Refresh
          </Button>
          <DownloadWaterReportJsonButton report={data} />
          <DownloadWaterReportPdfButton report={data} catchment={catchment} />
          <Button size="sm" variant="outline" onClick={() => window.print()} className="gap-1.5">
            <Printer aria-hidden className="size-4" />
            Print
          </Button>
        </div>
      </header>

      {/* 1. Report Summary */}
      <Card size="sm" className="print:break-inside-avoid">
        <CardHeader>
          <CardTitle>Report summary</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableBody>
              <TableRow>
                <TableCell className="text-muted-foreground">Generated</TableCell>
                <TableCell>
                  {new Date(data.generated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="text-muted-foreground">Job status</TableCell>
                <TableCell>
                  <Badge variant={JOB_STATUS_BADGE_VARIANT[data.job.status] ?? "default"}>{data.job.status}</Badge>
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="text-muted-foreground">Catchment name</TableCell>
                <TableCell>{catchment.name}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="text-muted-foreground">Catchment area</TableCell>
                <TableCell>{formatArea(catchment.area_ha)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="text-muted-foreground">Delineation method</TableCell>
                <TableCell>{DELINEATION_METHOD_LABELS[catchment.delineation_method]}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* 2. Water Balance */}
      <Card size="sm" className="print:break-inside-avoid">
        <CardHeader>
          <CardTitle>Water balance</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">
            {new Date(waterBalance.period_start).toLocaleDateString("en-IN", { dateStyle: "medium" })} –{" "}
            {new Date(waterBalance.period_end).toLocaleDateString("en-IN", { dateStyle: "medium" })} · Data
            completeness {waterBalance.data_completeness.toFixed(0)}% · {waterBalance.calibration_status.replace(/_/g, " ")}
          </p>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-muted-foreground">Total rainfall</p>
              <p className="text-lg font-semibold tabular-nums">{formatMm(waterBalance.rainfall_mm)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">ET</p>
              <p className="text-lg font-semibold tabular-nums">{formatMm(waterBalance.et_mm)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Runoff</p>
              <p className="text-lg font-semibold tabular-nums">{formatMm(waterBalance.runoff_mm)}</p>
            </div>
            <div>
              {/* "Recharge" and "Storage change" are the same backend
               * field — WaterBalanceEngine computes no separate recharge
               * term (P - ET - Q = dS is the whole equation). Labeled to
               * say so, rather than repeating the identical number under
               * two different headings. */}
              <p className="text-xs text-muted-foreground">Recharge (storage change)</p>
              <p className="text-lg font-semibold tabular-nums">{formatMm(waterBalance.storage_change_mm)}</p>
              <StorageChangeBandChip band={waterBalance.storage_change_band} className="mt-1" />
            </div>
          </div>

          <WaterBalanceChart
            rainfallMm={waterBalance.rainfall_mm}
            etMm={waterBalance.et_mm}
            runoffMm={waterBalance.runoff_mm}
            storageChangeMm={waterBalance.storage_change_mm}
          />
        </CardContent>
      </Card>

      {/* 3. Recharge Stress */}
      <Card size="sm" className="print:break-inside-avoid">
        <CardHeader>
          <CardTitle>Recharge stress</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-2xl font-semibold tabular-nums">
              {Math.round(rechargeStress.stress_score)}
              <span className="text-sm font-normal text-muted-foreground"> / 100</span>
            </p>
            <StressBandChip band={rechargeStress.stress_band} />
            {confidence !== null && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground">
                Confidence {Math.round(confidence)}%
              </span>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            {factorCards.map((factor) => (
              <div key={factor.key} className="flex flex-col gap-2 rounded-lg border p-4">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium">{factor.label}</p>
                  {factor.stressScore !== null && <StressBandChip band={bandForFactorScore(factor.stressScore)} />}
                </div>
                <p className="text-lg font-semibold tabular-nums">{factor.rawLabel}</p>
                {factor.stressScore !== null && (
                  <p className="text-xs text-muted-foreground">Stress contribution: {Math.round(factor.stressScore)} / 100</p>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 4. Surface Water */}
      <Card size="sm" className="print:break-inside-avoid">
        <CardHeader>
          <CardTitle>Surface water</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div>
            <p className="mb-1.5 text-xs text-muted-foreground">Surface water trend (percentile of own history)</p>
            <SurfaceWaterIndicator percentile={rechargeStress.surface_water_trend} />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Surface water stress contribution</p>
            <p className="text-lg font-semibold tabular-nums">
              {formatPercent(numberField(rechargeStress.raw_inputs, "surface_water_stress"))}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* 5. Groundwater */}
      <Card size="sm" className="print:break-inside-avoid">
        <CardHeader>
          <CardTitle>Groundwater</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="text-xs text-muted-foreground">Recharge trend (from water balance)</p>
              <StorageChangeBandChip band={waterBalance.storage_change_band} className="mt-1" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Stress indicator</p>
              <StressBandChip band={rechargeStress.stress_band} score={rechargeStress.stress_score} className="mt-1" />
            </div>
          </div>

          {rechargeStress.cgwb_category ? (
            <div className="rounded-lg border p-4">
              <p className="text-sm font-medium">CGWB block-scale category</p>
              <p className="text-lg font-semibold">{rechargeStress.cgwb_category}</p>
              {rechargeStress.cgwb_category_as_of && (
                <p className="text-xs text-muted-foreground">
                  As of {new Date(rechargeStress.cgwb_category_as_of).toLocaleDateString("en-IN", { dateStyle: "medium" })}
                </p>
              )}
              <p className="mt-2 text-xs text-muted-foreground">
                Government block-scale context — never blended numerically into the stress score above.
              </p>
            </div>
          ) : (
            <EmptyState
              title="CGWB category not yet available"
              description="No CGWB groundwater-category observation is on file for this catchment's block yet."
            />
          )}
        </CardContent>
      </Card>

      {/* 6. Insights */}
      <Card size="sm" className="print:break-inside-avoid">
        <CardHeader>
          <CardTitle>Insights</CardTitle>
        </CardHeader>
        <CardContent>
          {insights.length > 0 ? (
            <ul className="flex flex-col gap-2 text-sm">
              {insights.map((insight) => (
                <li key={insight} className="flex gap-2">
                  <span aria-hidden className="text-muted-foreground">
                    ·
                  </span>
                  {insight}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No notable observations for this report.</p>
          )}
        </CardContent>
      </Card>

      <footer className="text-xs text-muted-foreground print:break-inside-avoid">
        Water balance model {waterBalance.model_version} · Reference: report generated{" "}
        {new Date(data.generated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}.
      </footer>
    </div>
  );
}
