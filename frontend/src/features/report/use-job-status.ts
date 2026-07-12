"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import { isTerminalStatus } from "./status-copy";

export type JobStatusResponse = components["schemas"]["JobStatusResponse"];

const INITIAL_POLL_MS = 2_000;
const BACKOFF_FACTOR = 1.5;
const MAX_POLL_MS = 15_000;

/**
 * Capped exponential backoff for job polling: 2s, 3s, 4.5s, … capped at
 * 15s. Report generation typically takes 2–4 minutes (a real multi-year
 * Earth Engine computation) — polling every 2s for the whole run would be
 * ~90 requests for zero added freshness, while a flat 15s would make the
 * first status change (pending→running, usually within seconds) feel
 * stuck. Exported for unit testing.
 */
export function pollIntervalMs(completedPolls: number): number {
  return Math.min(INITIAL_POLL_MS * BACKOFF_FACTOR ** completedPolls, MAX_POLL_MS);
}

export function useJobStatus(jobId: string) {
  return useQuery({
    queryKey: ["jobs", jobId],
    queryFn: async (): Promise<JobStatusResponse> => {
      const { data, error } = await apiClient.GET("/api/v1/jobs/{job_id}", {
        params: { path: { job_id: jobId } },
      });
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data;
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && isTerminalStatus(status)) {
        return false; // job finished — stop polling entirely
      }
      return pollIntervalMs(query.state.dataUpdateCount);
    },
    // Keep polling while the tab is backgrounded — the officer is told
    // they can leave and come back; a hidden tab should still converge.
    // (Browsers clamp hidden-tab timers to ~1/min, which is fine.)
    refetchIntervalInBackground: true,
    staleTime: 0,
  });
}
