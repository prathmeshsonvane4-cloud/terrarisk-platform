"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { getToken } from "@/features/auth/session";
import { API_BASE_URL } from "@/lib/api/client";

/** Extracts the server-chosen filename so the saved file matches what the
 * backend put in Content-Disposition (village + assessment date). */
function filenameFrom(disposition: string | null): string {
  const match = disposition?.match(/filename="([^"]+)"/);
  return match?.[1] ?? "Kshetra-Report.pdf";
}

/**
 * Downloads the rendered PDF for this report — the artifact that enters
 * the bank's loan file (Blueprint §08). Binary response, so this is a
 * plain authorized fetch rather than the JSON api client; the blob is
 * handed to the browser as a normal file download.
 */
export function DownloadPdfButton({ reportId }: { reportId: string }) {
  const [state, setState] = useState<"idle" | "downloading" | "error">("idle");

  async function download() {
    setState("downloading");
    try {
      const token = getToken();
      const response = await fetch(`${API_BASE_URL}/api/v1/reports/${reportId}/pdf`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!response.ok) {
        throw new Error(`PDF download failed (${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filenameFrom(response.headers.get("content-disposition"));
      anchor.click();
      URL.revokeObjectURL(url);
      setState("idle");
    } catch {
      setState("error");
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button size="sm" onClick={download} disabled={state === "downloading"}>
        <Download aria-hidden className="size-4" />
        {state === "downloading" ? "Preparing PDF…" : "Download PDF"}
      </Button>
      {state === "error" && (
        <p role="alert" className="text-xs text-destructive">
          Could not download the PDF. Try again.
        </p>
      )}
    </div>
  );
}
