"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type AssessmentListItem = components["schemas"]["AssessmentListItem"];

const ACTIVE_POLL_MS = 20_000;

function hasInFlightRun(items: AssessmentListItem[] | undefined): boolean {
  return items?.some((item) => item.status === "pending" || item.status === "running") ?? false;
}

/** The Assessments workspace index (Product Design v2 §7, screen 5) —
 * every farm-report run in the officer's own-or-branch scope, farm
 * context resolved regardless of status. Polls lightly only while at
 * least one run is still in flight — this is what backs the app shell's
 * live activity chip as well as the full index page, so both surfaces
 * reflect real, currently-running backend work rather than a stale
 * snapshot (Product Design v2 P2 — never fake progress). */
export function useAssessments() {
  return useQuery({
    queryKey: ["assessments"],
    queryFn: async (): Promise<AssessmentListItem[]> => {
      const { data, error } = await apiClient.GET("/api/v1/jobs");
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data.items;
    },
    refetchInterval: (query) => (hasInFlightRun(query.state.data) ? ACTIVE_POLL_MS : false),
    refetchIntervalInBackground: true,
  });
}
