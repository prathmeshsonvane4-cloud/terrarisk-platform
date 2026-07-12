import type { components } from "@/lib/api/schema";

export type JobStatus = components["schemas"]["JobStatus"];

interface StatusCopy {
  title: string;
  detail: string;
}

/**
 * Honest, staged narration driven by the job's REAL state — never a fake
 * progress bar (M2A spec §9). The wording sets the expectation the demo
 * script relies on: this takes minutes because real satellite history is
 * being analyzed now, not served from a can.
 */
export const STATUS_COPY: Record<JobStatus, StatusCopy> = {
  pending: {
    title: "Report queued",
    detail: "Waiting to start. This screen updates automatically.",
  },
  running: {
    title: "Analyzing satellite history…",
    detail:
      "Fetching 3 years of Sentinel-2 imagery and rainfall records for this farm and computing its climate risk factors. This typically takes 2–4 minutes — you can leave this page and come back; the analysis continues on the server.",
  },
  done: {
    title: "Report ready",
    detail: "Opening the climate report…",
  },
  failed: {
    title: "Report generation failed",
    detail: "The analysis could not be completed. Return to the farm page and try again; contact support if this persists.",
  },
};

export function isTerminalStatus(status: JobStatus): boolean {
  return status === "done" || status === "failed";
}
