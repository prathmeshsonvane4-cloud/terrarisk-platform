import { MonthlyTrendChart } from "@/components/charts/monthly-trend-chart";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

type ReportResponse = components["schemas"]["ReportResponse"];
type ObservationPoint = components["schemas"]["ObservationPoint"];

interface CoverageCell {
  periodStart: string;
  usable: boolean;
}

/** Reconstructs the full expected monthly grid for display: which
 * calendar months existed in the window (server-persisted, authoritative
 * — see ReportEvidenceContext) versus which of those the payload's sparse
 * series actually lists as usable. Pure calendar enumeration, not risk
 * logic — the engine already decided what's usable; this only lays it
 * out visually. */
function buildCoverage(windowStart: string, windowEnd: string, points: ObservationPoint[]): CoverageCell[] {
  const usable = new Set(points.map((p) => p.period_start));
  const cells: CoverageCell[] = [];
  let cursor = new Date(`${windowStart}T00:00:00Z`);
  const end = new Date(`${windowEnd}T00:00:00Z`);
  while (cursor < end) {
    const iso = cursor.toISOString().slice(0, 10);
    cells.push({ periodStart: iso, usable: usable.has(iso) });
    cursor = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + 1, 1));
  }
  return cells;
}

function formatMonth(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-IN", {
    month: "short",
    year: "2-digit",
    timeZone: "UTC",
  });
}

function CoverageStrip({ cells }: { cells: CoverageCell[] }) {
  if (cells.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-0.5" role="img" aria-label="Monthly observation coverage">
      {cells.map((cell) => (
        <span
          key={cell.periodStart}
          title={`${formatMonth(cell.periodStart)} — ${cell.usable ? "usable" : "skipped"}`}
          className={cn("h-3 w-2 rounded-[1px]", cell.usable ? "bg-emerald-500" : "bg-muted")}
        />
      ))}
    </div>
  );
}

interface IndexSectionProps {
  title: string;
  points: ObservationPoint[];
  expectedMonths: number | null;
  windowStart: string | null;
  windowEnd: string | null;
  skipReason: string;
  chartColor: "green" | "blue";
  chartVariant: "line" | "bar";
  formatValue: (v: number) => string;
  ariaLabel: string;
}

function IndexEvidenceSection({
  title,
  points,
  expectedMonths,
  windowStart,
  windowEnd,
  skipReason,
  chartColor,
  chartVariant,
  formatValue,
  ariaLabel,
}: IndexSectionProps) {
  const usable = points.length;
  const skipped = expectedMonths !== null ? expectedMonths - usable : null;
  const cells = windowStart && windowEnd ? buildCoverage(windowStart, windowEnd, points) : [];
  const scenePoints = points.filter((p) => p.source_dates && p.source_dates.length > 0);

  return (
    <div className="flex flex-col gap-2 rounded-lg border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h3 className="text-sm font-medium">{title}</h3>
        <p className="text-xs tabular-nums text-muted-foreground">
          {expectedMonths !== null ? `${usable} of ${expectedMonths} months usable` : `${usable} months usable`}
          {skipped !== null && skipped > 0 && ` · ${skipped} skipped (${skipReason})`}
        </p>
      </div>
      <CoverageStrip cells={cells} />
      <MonthlyTrendChart
        points={points}
        variant={chartVariant}
        color={chartColor}
        formatValue={formatValue}
        ariaLabel={ariaLabel}
      />
      {scenePoints.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
            View Sentinel-2 acquisition dates ({scenePoints.length} months)
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {scenePoints.map((p) => (
              <li key={p.period_start}>
                <span className="tabular-nums text-muted-foreground">{formatMonth(p.period_start)}:</span>{" "}
                {(p.source_dates ?? []).join(", ")}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/**
 * The Evidence tab (Product Design v2 §7.5) — answers "which observations
 * contributed": the observation window, per-index monthly coverage, real
 * Sentinel-2 scene acquisition dates, and the confidence calculation
 * spelled out arithmetically. Every value comes directly from the report
 * payload; nothing here is computed against live data.
 */
export function EvidenceTab({ report }: { report: ReportResponse }) {
  const { evidence } = report;
  const expected = evidence.expected_months;

  // Mirrors the backend's _compute_confidence exactly (average completeness
  // across the three optical indices only — rainfall is not cloud-limited
  // the same way and is intentionally excluded, per app/services/risk/
  // engine.py). Presentational arithmetic over already-persisted counts,
  // not a re-derivation of anything the engine decided.
  const opticalCoverage = [
    { label: "NDVI", usable: report.series.ndvi.length },
    { label: "MNDWI", usable: report.series.mndwi.length },
    { label: "NDMI", usable: report.series.ndmi.length },
  ];
  const confidenceFromCoverage =
    expected !== null && expected > 0
      ? (opticalCoverage.reduce((sum, c) => sum + c.usable / expected, 0) / opticalCoverage.length) * 100
      : null;

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-lg border p-4">
        <h3 className="text-sm font-medium">Observation window</h3>
        {evidence.observation_window_start && evidence.observation_window_end ? (
          <p className="mt-1 text-sm text-muted-foreground">
            {new Date(evidence.observation_window_start).toLocaleDateString("en-IN", { dateStyle: "medium" })} →{" "}
            {new Date(evidence.observation_window_end).toLocaleDateString("en-IN", { dateStyle: "medium" })} (
            {expected} months). The window ends at the previous full calendar month — the current month is
            still incomplete on the satellite record.
          </p>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">
            Not available for this report — computed before this detail was recorded.
          </p>
        )}
      </section>

      <section className="rounded-lg border p-4">
        <h3 className="text-sm font-medium">Confidence calculation</h3>
        {confidenceFromCoverage !== null ? (
          <>
            <p className="mt-1 text-sm text-muted-foreground">
              Average share of usable months across the three optical indices (NDVI, MNDWI, NDMI). Rainfall is
              not included — CHIRPS coverage is not limited by cloud cover the same way.
            </p>
            <p className="mt-2 font-mono text-sm">
              ({opticalCoverage.map((c) => `${c.label} ${c.usable}/${expected}`).join(" + ")}) / 3 ={" "}
              <span className="font-semibold">{Math.round(confidenceFromCoverage)}%</span>
            </p>
          </>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">Not available for this report.</p>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-medium">Vegetation observations</h3>
        <IndexEvidenceSection
          title="NDVI — vegetation index (Sentinel-2)"
          points={report.series.ndvi}
          expectedMonths={expected}
          windowStart={evidence.observation_window_start}
          windowEnd={evidence.observation_window_end}
          skipReason="cloud cover"
          chartColor="green"
          chartVariant="line"
          formatValue={(v) => v.toFixed(2)}
          ariaLabel="Monthly NDVI vegetation index coverage"
        />
      </section>

      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-medium">Water observations</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <IndexEvidenceSection
            title="MNDWI — surface water (Sentinel-2)"
            points={report.series.mndwi}
            expectedMonths={expected}
            windowStart={evidence.observation_window_start}
            windowEnd={evidence.observation_window_end}
            skipReason="cloud cover"
            chartColor="blue"
            chartVariant="line"
            formatValue={(v) => v.toFixed(2)}
            ariaLabel="Monthly MNDWI surface-water index coverage"
          />
          <IndexEvidenceSection
            title="NDMI — crop moisture (Sentinel-2)"
            points={report.series.ndmi}
            expectedMonths={expected}
            windowStart={evidence.observation_window_start}
            windowEnd={evidence.observation_window_end}
            skipReason="cloud cover"
            chartColor="green"
            chartVariant="line"
            formatValue={(v) => v.toFixed(2)}
            ariaLabel="Monthly NDMI crop-moisture index coverage"
          />
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-medium">Rainfall observations</h3>
        <IndexEvidenceSection
          title="CHIRPS — monthly rainfall"
          points={report.series.rainfall}
          expectedMonths={expected}
          windowStart={evidence.observation_window_start}
          windowEnd={evidence.observation_window_end}
          skipReason="not yet published — CHIRPS publishes with a lag"
          chartColor="blue"
          chartVariant="bar"
          formatValue={(v) => `${Math.round(v)} mm`}
          ariaLabel="Monthly rainfall coverage"
        />
      </section>
    </div>
  );
}
