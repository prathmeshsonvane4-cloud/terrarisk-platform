"use client";

import Link from "next/link";

import { useReports } from "@/features/workspace/use-reports";
import { formatArea } from "@/lib/format";
import { RISK_BANDS } from "@/lib/risk-bands";
import { cn } from "@/lib/utils";

/**
 * The Reports workspace index (Product Design v2 §7, screen 9) — every
 * issued report in scope, newest first (GET /reports, M2B P7). The
 * auditor/manager entry point: "show me every report issued," not "show
 * me every farm" — deliberately not collapsed to latest-per-farm.
 */
export default function ReportsPage() {
  const { data: reports, isPending, isError, error } = useReports();

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
      <h1 className="text-lg font-semibold">Reports</h1>

      {isPending && <p className="text-sm text-muted-foreground">Loading reports…</p>}

      {isError && (
        <p role="alert" className="text-sm text-muted-foreground">
          {error.message}
        </p>
      )}

      {!isPending && !isError && reports.length === 0 && (
        <div className="rounded-lg border p-5 text-sm">
          <p className="font-medium">No reports issued yet</p>
          <p className="mt-1 text-muted-foreground">
            Every completed climate assessment for your branch will appear here.
          </p>
        </div>
      )}

      {!isPending && !isError && reports.length > 0 && (
        <div className="flex flex-col divide-y rounded-lg border">
          {reports.map((report) => {
            const band = RISK_BANDS[report.overall_band];
            return (
              <Link
                key={report.risk_score_id}
                href={`/reports/${report.risk_score_id}`}
                className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm hover:bg-muted"
              >
                <div>
                  <p className="font-medium">
                    {report.village_name}
                    <span className="font-normal text-muted-foreground">
                      {" "}
                      · {report.taluka_name}, {report.district_name}
                    </span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatArea(report.area_ha)} · {report.officer_name} ·{" "}
                    {new Date(report.computed_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
                  </p>
                </div>
                <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", band.chipClass)}>
                  {band.label} · {Math.round(report.overall_score)}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
