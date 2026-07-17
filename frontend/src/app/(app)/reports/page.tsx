"use client";

import { FileTextIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { RiskBandChip } from "@/components/ui/risk-band-chip";
import { SkeletonList } from "@/components/ui/skeleton";
import { useReports } from "@/features/workspace/use-reports";
import { formatArea } from "@/lib/format";

/**
 * The Reports workspace index (Product Design v2 §7, screen 9) — every
 * issued report in scope, newest first (GET /reports, M2B P7). The
 * auditor/manager entry point: "show me every report issued," not "show
 * me every farm" — deliberately not collapsed to latest-per-farm.
 */
export default function ReportsPage() {
  const { data: reports, isPending, isError, error, refetch } = useReports();

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
      <h1 className="text-lg font-semibold">Reports</h1>

      {isPending && <SkeletonList rows={4} />}

      {isError && <ErrorState error={error} onRetry={() => refetch()} />}

      {!isPending && !isError && reports.length === 0 && (
        <EmptyState
          icon={FileTextIcon}
          title="No reports issued yet"
          description="A report appears here the moment an assessment finishes — this branch hasn't completed one yet."
          action={{ label: "Start an assessment", href: "/assessments/new" }}
        />
      )}

      {!isPending && !isError && reports.length > 0 && (
        <div className="flex flex-col divide-y rounded-lg border">
          {reports.map((report) => (
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
              <RiskBandChip band={report.overall_band} score={report.overall_score} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
