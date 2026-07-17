"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type FarmAssessmentHistoryResponse = components["schemas"]["FarmAssessmentHistoryResponse"];

/** A farm's full append-only score history plus its in-flight run, if
 * any — the Farm detail timeline (Product Design v2 §7.4). */
export function useFarmAssessmentHistory(farmId: string) {
  return useQuery({
    queryKey: ["farms", farmId, "assessments"],
    queryFn: async (): Promise<FarmAssessmentHistoryResponse> => {
      const { data, error, response } = await apiClient.GET("/api/v1/farms/{farm_id}/assessments", {
        params: { path: { farm_id: farmId } },
      });
      if (error) {
        throw new ApiError(extractApiErrorMessage(error), response.status);
      }
      return data;
    },
  });
}
