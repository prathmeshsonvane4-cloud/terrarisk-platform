"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage, extractConflictingJobId } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type ReportTriggerResponse = components["schemas"]["ReportTriggerResponse"];

/** Thrown instead of a plain Error when the 409 conflict carries the id of
 * the already-running job (M2B P7 B5) — callers that want to route
 * straight to that run (Farm detail's "Re-assess") can catch this
 * specifically; callers that don't care just see it as an Error. */
export class ReportTriggerConflictError extends Error {
  constructor(
    message: string,
    public readonly jobId: string,
  ) {
    super(message);
    this.name = "ReportTriggerConflictError";
  }
}

export function useTriggerReport() {
  return useMutation({
    mutationFn: async (farmId: string): Promise<ReportTriggerResponse> => {
      const { data, error, response } = await apiClient.POST("/api/v1/farms/{farm_id}/reports", {
        params: { path: { farm_id: farmId } },
        // lookback_years defaults to 3 server-side (approved methodology);
        // the M2A UI deliberately doesn't expose it as a knob.
        body: {} as components["schemas"]["ReportGenerateRequest"],
      });
      if (error) {
        // The backend's 409 ("a report is already being generated for
        // this farm") is the advisory-lock guard's authority, not just
        // first-line UX — the disabled-while-pending button only prevents
        // the common case; a genuine race still reaches this branch.
        const conflictingJobId = extractConflictingJobId(error);
        if (conflictingJobId) {
          throw new ReportTriggerConflictError(extractApiErrorMessage(error), conflictingJobId);
        }
        throw new ApiError(extractApiErrorMessage(error), response.status);
      }
      return data;
    },
  });
}
