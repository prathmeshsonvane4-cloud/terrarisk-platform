"use client";

import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { WaterReportDetailResponse } from "./use-latest-water-report";

/**
 * Client-side-only JSON export — no new endpoint, no server round trip:
 * exactly the already-fetched WaterReportDetailResponse this page
 * already holds, serialized to a Blob and handed to the browser as a
 * file download. Unlike DownloadPdfButton (features/report/), which
 * fetches a server-rendered binary from a dedicated /pdf endpoint, this
 * ticket's own "reuse GET /catchments/{id}/water-reports" +
 * "Do NOT: Modify APIs" rule out adding an equivalent export endpoint —
 * so this reuses data already in memory instead of fetching anything.
 */
export function DownloadWaterReportJsonButton({ report }: { report: WaterReportDetailResponse }) {
  function download() {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `water-report-${report.catchment_id}-${report.generated_at.slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Button size="sm" variant="outline" onClick={download} className="gap-1.5">
      <Download aria-hidden className="size-4" />
      Download JSON
    </Button>
  );
}
