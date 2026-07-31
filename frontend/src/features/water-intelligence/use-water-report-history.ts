"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type WaterReportHistoryItem = components["schemas"]["WaterReportHistoryItem"];

export function waterReportHistoryQueryKey(catchmentId: string, limit?: number) {
  return ["catchments", catchmentId, "water-reports", "history", limit ?? "default"] as const;
}

/** Shared fetcher — used directly by useWaterReportHistory below, and by
 * use-water-report-histories.ts's useQueries-based multi-catchment
 * fetch (the compare page's data need: a dynamic, variable-length list
 * of catchment ids, which a single useQuery call can't express). One
 * fetch implementation, two hooks consuming it, rather than duplicating
 * the request logic. */
export async function fetchWaterReportHistory(catchmentId: string, limit?: number): Promise<WaterReportHistoryItem[]> {
  const { data, error, response } = await apiClient.GET("/api/v1/catchments/{catchment_id}/water-reports/history", {
    params: {
      path: { catchment_id: catchmentId },
      query: limit ? { limit } : {},
    },
  });
  if (error) {
    throw new ApiError(extractApiErrorMessage(error), (response as Response).status);
  }
  return data;
}

/** GET /catchments/{id}/water-reports/history — every past completed run,
 * newest first. An empty list is a normal steady state (a catchment with
 * no reports yet), not an error — unlike useLatestWaterReport, there is
 * no 404 case to special-case here. Powers the per-catchment trend
 * section (docs/WELL_Labs_Raichur_Founder_Review_2026.md Part 4/5). */
export function useWaterReportHistory(catchmentId: string, limit?: number) {
  return useQuery({
    queryKey: waterReportHistoryQueryKey(catchmentId, limit),
    queryFn: () => fetchWaterReportHistory(catchmentId, limit),
  });
}
