"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { MonthlyTrendChart } from "@/components/charts/monthly-trend-chart";
import { buttonVariants } from "@/components/ui/button";
import { DownloadPdfButton } from "@/features/report/download-pdf-button";
import { FACTOR_ORDER } from "@/features/report/factor-order";
import { FactorCard } from "@/features/report/factor-card";
import { reportNarrative } from "@/features/report/narrative";
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

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data: report, isPending, isError, error } = useReport(id);

  if (isPending) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-sm text-muted-foreground">
        Loading report…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="flex w-full max-w-md flex-col gap-3 rounded-lg border p-5 text-sm">
          <p className="font-medium">Could not load this report</p>
          <p role="alert" className="text-muted-foreground">
            {error.message}
          </p>
          <Link href="/" className={cn(buttonVariants({ variant: "outline" }), "self-start")}>
            Back to workspace
          </Link>
        </div>
      </div>
    );
  }

  const band = RISK_BANDS[report.overall_band];
  const factors = FACTOR_ORDER.map((name) => report.factors.find((f) => f.factor === name)).filter(
    (f) => f !== undefined,
  );
  const droughtRatio = report.factors.find((f) => f.factor === "drought_risk")?.raw_inputs?.[
    "rainfall_ratio_to_normal"
  ];
  const computedAt = new Date(report.computed_at);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-5 p-4 md:p-6">
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
        <div className="flex items-start gap-2">
          <Link href={`/farms/${report.farm_id}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
            View farm
          </Link>
          <Link href="/assessments/new" className={buttonVariants({ variant: "outline", size: "sm" })}>
            New assessment
          </Link>
          <DownloadPdfButton reportId={report.id} />
        </div>
      </header>

      {/* Verdict + map */}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="flex flex-col gap-3 rounded-lg border p-5">
          <div>
            <p className="text-xs text-muted-foreground">Overall climate risk</p>
            <p className={`text-4xl font-semibold ${band.textClass}`}>{band.label}</p>
            <p className="mt-1 text-sm text-muted-foreground tabular-nums">
              Score {Math.round(report.overall_score)} / 100 ·{" "}
              <span
                className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground"
                title="Reflects how many usable satellite observations were available — data quality, not risk."
              >
                Confidence {Math.round(report.confidence)}%
              </span>
            </p>
          </div>
          <p className="text-sm leading-relaxed">{reportNarrative(report)}</p>
        </section>
        <section className="relative min-h-64 overflow-hidden rounded-lg border">
          <ReportMap geometry={report.farm.geometry} className="absolute inset-0" />
        </section>
      </div>

      {/* Factor breakdown — the explainability requirement made concrete */}
      <section>
        <h2 className="mb-2 text-sm font-medium">Risk factor breakdown</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {factors.map((factor) => (
            <FactorCard key={factor.factor} factor={factor} />
          ))}
        </div>
      </section>

      {/* History charts — the "banks can't see cultivation history" answer */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border p-4">
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
        <section className="rounded-lg border p-4">
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
      <footer className="flex flex-col gap-1 rounded-lg border bg-muted/30 p-4 text-xs text-muted-foreground">
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
    </div>
  );
}
