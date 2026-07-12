"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type ReportResponse = components["schemas"]["ReportResponse"];

export function useReport(riskScoreId: string) {
  return useQuery({
    queryKey: ["reports", riskScoreId],
    queryFn: async (): Promise<ReportResponse> => {
      const { data, error } = await apiClient.GET("/api/v1/reports/{risk_score_id}", {
        params: { path: { risk_score_id: riskScoreId } },
      });
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data;
    },
    // A persisted report is immutable (risk_score is append-only) — no
    // point refetching it on focus/reconnect.
    staleTime: Infinity,
  });
}
