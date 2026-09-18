"use client";

import { FileDown } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";

import type { WaterReportDetailResponse } from "../use-latest-water-report";
import { generateWaterReportPdf } from "./generate-water-report-pdf";
import { loadWaterReportMapContext } from "./load-map-context";

type CatchmentResponse = components["schemas"]["CatchmentResponse"];

function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

/**
 * Client-side PDF generation and download (ticket M6-003) — mirrors
 * DownloadWaterReportJsonButton's shape (features/water-intelligence/,
 * M6-002): synchronous, no server round trip, built entirely from data
 * this page already has. Unlike DownloadPdfButton (features/report/),
 * which fetches a server-rendered binary from a dedicated /pdf
 * endpoint, generateWaterReportPdf() runs the whole layout in the
 * browser — `Do NOT modify backend APIs` rules out an equivalent
 * endpoint for Water Intelligence.
 */
export function DownloadWaterReportPdfButton({
  report,
  catchment,
}: {
  report: WaterReportDetailResponse;
  catchment: CatchmentResponse;
}) {
  const [state, setState] = useState<"idle" | "generating" | "error">("idle");

  async function download() {
    setState("generating");
    try {
      // Fetched on click, not on mount: most visits to this page never
      // download a PDF, and the locator costs four extra requests.
      const mapContext = await loadWaterReportMapContext(catchment);
      const doc = generateWaterReportPdf(report, catchment, mapContext);
      doc.save(`Kshetra-Water-Report-${slugify(catchment.name)}-${report.generated_at.slice(0, 10)}.pdf`);
      setState("idle");
    } catch {
      setState("error");
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button size="sm" onClick={download} disabled={state === "generating"} className="gap-1.5">
        <FileDown aria-hidden className="size-4" />
        {state === "generating" ? "Preparing PDF…" : "Download PDF"}
      </Button>
      {state === "error" && (
        <p role="alert" className="text-xs text-destructive">
          Could not generate the PDF. Try again.
        </p>
      )}
    </div>
  );
}
