"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { MonthlyTrendChart } from "@/components/charts/monthly-trend-chart";
import { buttonVariants } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { DownloadPdfButton } from "@/features/report/download-pdf-button";
import { EvidenceTab } from "@/features/report/evidence-tab";
import { FACTOR_ORDER } from "@/features/report/factor-order";
import { FactorCard } from "@/features/report/factor-card";
import { MethodTab } from "@/features/report/method-tab";
import { reportNarrative } from "@/features/report/narrative";
import { SufficiencyPanel } from "@/features/report/sufficiency-panel";
import { RecommendationBlock } from "@/features/report/recommendation-block";
import { ReportMap } from "@/features/report/report-map";
import { useReport } from "@/features/report/use-report";
import { formatArea } from "@/lib/format";
import { RISK_BANDS } from "@/lib/risk-bands";
import { cn } from "@/lib/utils";

// The datasets behind every number on this page — these are the actual
// collections queried by the GEE adapter (gee_provider.py), stated for
// the Blueprint §08 lineage footer.
const DATA_SOURCES =
  "Sentinel-2 SR Harmonized (ESA/Copernicus) · CHIRPS Daily rainfall (UCSB) · JRC Global Surface Water v1.4 (EC-JRC)";

type TabValue = "report" | "evidence" | "method";

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data: report, isPending, isError, error, refetch } = useReport(id);
  const [tab, setTab] = useState<TabValue>("report");

  if (isPending) {
    return (
      <div role="status" aria-label="Loading report" className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 p-4 md:p-6">
        <Skeleton className="h-7 w-72" />
        <Skeleton className="h-4 w-56" />
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-md">
          <ErrorState error={error} onRetry={() => refetch()} referenceId={id} />
          <Link href="/" className={cn(buttonVariants({ variant: "outline" }), "mt-3 w-full")}>
            Back to workspace
          </Link>
        </div>
      </div>
    );
  }

  // Null when no composite could be estimated (rule-engine-v2 onward).
  const band = report.overall_band ? RISK_BANDS[report.overall_band] : null;
  const factors = FACTOR_ORDER.map((name) => report.factors.find((f) => f.factor === name)).filter(
    (f) => f !== undefined,
  );
  const droughtRatio = report.factors.find((f) => f.factor === "drought_risk")?.raw_inputs?.[
    "rainfall_ratio_to_normal"
  ];
  const computedAt = new Date(report.computed_at);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-5 p-4 md:p-6 print:max-w-none print:p-0">
      {/* Farm identity strip — provenance first (Blueprint §08) */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">
            {report.farm.village_name}
            <span className="font-normal text-muted-foreground">
              {" "}
              · {report.farm.taluka_name}, {report.farm.district_name}
            </span>
          </h1>
          <p className="text-sm text-muted-foreground">
            {formatArea(report.farm_area_ha)} · Mapped by {report.farm.officer_name} · Assessed{" "}
            {computedAt.toLocaleDateString("en-IN", { dateStyle: "medium" })}
          </p>
        </div>
        {/* Actions are interactive-only — no place on a printed page (P11);
         * the authoritative printed artifact is the server-rendered PDF via
         * Download PDF, not a browser print of this live view. */}
        <div className="flex items-start gap-2 print:hidden">
          <Link href={`/farms/${report.farm_id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
            View farm
          </Link>
          <Link href="/assessments/new" className={buttonVariants({ variant: "outline", size: "sm" })}>
            New assessment
          </Link>
          <DownloadPdfButton reportId={report.id} />
        </div>
      </header>

      <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
        <TabsList className="print:hidden">
          <TabsTab value="report">Report</TabsTab>
          <TabsTab value="evidence">Evidence</TabsTab>
          <TabsTab value="method">Method</TabsTab>
        </TabsList>

        <TabsPanel value="report" className="flex flex-col gap-5">
          {/* Verdict + map. The map is a live WebGL canvas that a browser's
           * print pipeline cannot reliably capture — hidden in print rather
           * than risking blank/clipped output; the verdict panel takes the
           * full width in its place. */}
          <div className="grid gap-4 md:grid-cols-2 print:grid-cols-1">
            <section className="flex flex-col gap-3 rounded-lg border p-5 print:break-inside-avoid">
              <div>
                <p className="text-xs text-muted-foreground">Overall climate risk</p>
                {band ? (
                  <p className={`text-4xl font-semibold ${band.textClass}`}>{band.label}</p>
                ) : (
                  <p className="text-4xl font-semibold text-muted-foreground">Not estimable</p>
                )}
                <p className="mt-1 text-sm text-muted-foreground tabular-nums">
                  {report.overall_score === null ? "No overall score" : `Score ${Math.round(report.overall_score)} / 100`}{" "}
                  ·{" "}
                  <span
                    className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground"
                    title="The share of expected monthly satellite observations that were usable — data quality, not confidence in the score and not risk."
                  >
                    Data completeness {Math.round(report.confidence)}%
                  </span>
                </p>
              </div>
              <p className="text-sm leading-relaxed">{reportNarrative(report)}</p>
              <button
                type="button"
                onClick={() => setTab("method")}
                className="self-start text-xs font-medium text-primary underline-offset-2 hover:underline print:hidden"
              >
                How was this score calculated?
              </button>
            </section>
            <section className="relative min-h-64 overflow-hidden rounded-lg border print:hidden">
              <ReportMap geometry={report.farm.geometry} className="absolute inset-0" />
            </section>
          </div>

          <SufficiencyPanel report={report} />

          <RecommendationBlock report={report} />

          {/* Factor breakdown — the explainability requirement made concrete */}
          <section className="print:break-inside-avoid">
            <h2 className="mb-2 text-sm font-medium">Risk factor breakdown</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {factors.map((factor) => (
                <FactorCard key={factor.factor} factor={factor} />
              ))}
            </div>
          </section>

          {/* History charts — the "banks can't see cultivation history" answer */}
          <div className="grid gap-4 lg:grid-cols-2 print:break-before-page">
            <section className="rounded-lg border p-4 print:break-inside-avoid">
              <h2 className="text-sm font-medium">Vegetation health — 3-year NDVI</h2>
              <p className="mb-2 text-xs text-muted-foreground">
                Monthly cloud-free composite over this farm. Higher is greener, denser vegetation.
              </p>
              <MonthlyTrendChart
                points={report.series.ndvi}
                variant="line"
                color="green"
                formatValue={(v) => v.toFixed(2)}
                ariaLabel="Three-year monthly NDVI vegetation index trend for this farm"
              />
            </section>
            <section className="rounded-lg border p-4 print:break-inside-avoid">
              <h2 className="text-sm font-medium">Monthly rainfall</h2>
              <p className="mb-2 text-xs text-muted-foreground">
                {typeof droughtRatio === "number"
                  ? `Total rainfall per month (mm). Most recent season: ${Math.round(droughtRatio * 100)}% of the 30-year seasonal normal.`
                  : "Total rainfall per month (mm) over this farm."}
              </p>
              <MonthlyTrendChart
                points={report.series.rainfall}
                variant="bar"
                color="blue"
                formatValue={(v) => `${Math.round(v)}`}
                ariaLabel="Three-year monthly rainfall totals in millimetres for this farm"
              />
            </section>
          </div>

          {/* Lineage footer — "how was this number produced", on the page itself */}
          <footer className="flex flex-col gap-1 rounded-lg border bg-muted/30 p-4 text-xs text-muted-foreground print:break-inside-avoid">
            <p>
              <span className="font-medium text-foreground">Data sources:</span> {DATA_SOURCES}
            </p>
            <p>
              Model {report.model_version} · Generated{" "}
              {computedAt.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })} · Confidence{" "}
              {Math.round(report.confidence)}% (share of usable cloud-free observations)
            </p>
            <p>
              This report is decision support for the lending officer. The credit decision remains with
              the bank.
            </p>
          </footer>
        </TabsPanel>

        <TabsPanel value="evidence">
          <EvidenceTab report={report} />
        </TabsPanel>

        <TabsPanel value="method">
          <MethodTab report={report} />
        </TabsPanel>
      </Tabs>
    </div>
  );
}
