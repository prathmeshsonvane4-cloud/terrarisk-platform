"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type WaterReportDetailResponse = components["schemas"]["WaterReportDetailResponse"];

/** GET /catchments/{id}/water-reports (M5-003) — the latest completed
 * WaterBalanceResult + RechargeStressScore pair. A 404 here is a real,
 * expected steady state ("no completed report yet"), not a transient
 * failure — retry is disabled for it so the query doesn't spend three
 * rounds hammering an endpoint that's correctly saying "nothing yet";
 * callers distinguish this case via `error instanceof ApiError &&
 * error.status === 404` to render an EmptyState instead of ErrorState
 * (see app/catchments/[id]/page.tsx). */
export function useLatestWaterReport(catchmentId: string) {
  return useQuery({
    queryKey: ["catchments", catchmentId, "water-reports", "latest"],
    queryFn: async (): Promise<WaterReportDetailResponse> => {
      const { data, error, response } = await apiClient.GET("/api/v1/catchments/{catchment_id}/water-reports", {
        params: { path: { catchment_id: catchmentId } },
      });
      if (error) {
        throw new ApiError(extractApiErrorMessage(error), (response as Response).status);
      }
      return data;
    },
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 3;
    },
  });
}
