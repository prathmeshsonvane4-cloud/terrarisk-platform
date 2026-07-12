"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type ReportTriggerResponse = components["schemas"]["ReportTriggerResponse"];

export function useTriggerReport() {
  return useMutation({
    mutationFn: async (farmId: string): Promise<ReportTriggerResponse> => {
      const { data, error } = await apiClient.POST("/api/v1/farms/{farm_id}/reports", {
        params: { path: { farm_id: farmId } },
        // lookback_years defaults to 3 server-side (approved methodology);
        // the M2A UI deliberately doesn't expose it as a knob.
        body: {} as components["schemas"]["ReportGenerateRequest"],
      });
      if (error) {
        // Includes the backend's 409 ("a report is already being
        // generated for this farm") verbatim — the advisory-lock guard
        // from M1 is the duplicate-submission authority; the UI's
        // disabled-while-pending button is just first-line UX.
        throw new Error(extractApiErrorMessage(error));
      }
      return data;
    },
  });
}
