"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage, extractConflictingJobId } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type ReportTriggerResponse = components["schemas"]["ReportTriggerResponse"];

/** Thrown instead of a plain Error when the 409 conflict carries the id of
 * the already-running job (app/api/catchments.py::trigger_water_report's
 * advisory-lock guard, M4-006) — mirrors
 * features/report/use-trigger-report.ts's ReportTriggerConflictError
 * exactly, kept as its own class (not a shared export) since it's the
 * catchment-scoped counterpart to a farm-scoped error, not the same
 * conflict. */
export class WaterReportTriggerConflictError extends Error {
  constructor(
    message: string,
    public readonly jobId: string,
  ) {
    super(message);
    this.name = "WaterReportTriggerConflictError";
  }
}

export function useTriggerWaterReport() {
  return useMutation({
    mutationFn: async (catchmentId: string): Promise<ReportTriggerResponse> => {
      const { data, error, response } = await apiClient.POST("/api/v1/catchments/{catchment_id}/water-reports", {
        params: { path: { catchment_id: catchmentId } },
      });
      if (error) {
        // The backend's 409 ("a water report is already being generated
        // for this catchment") is the advisory-lock guard's authority,
        // not just first-line UX — a genuine race still reaches this
        // branch even with the button disabled while pending.
        const conflictingJobId = extractConflictingJobId(error);
        if (conflictingJobId) {
          throw new WaterReportTriggerConflictError(extractApiErrorMessage(error), conflictingJobId);
        }
        throw new ApiError(extractApiErrorMessage(error), response.status);
      }
      return data;
    },
  });
}
