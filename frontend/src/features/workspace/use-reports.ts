"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type ReportListItem = components["schemas"]["ReportListItem"];

/** The Reports workspace index (Product Design v2 §7, screen 9) — every
 * issued report in the officer's own-or-branch scope, newest first. */
export function useReports() {
  return useQuery({
    queryKey: ["reports"],
    queryFn: async (): Promise<ReportListItem[]> => {
      const { data, error, response } = await apiClient.GET("/api/v1/reports");
      if (error) {
        // See the identical note in use-farms.ts: /api/v1/reports's OpenAPI
        // doc only declares a 200 response, so openapi-fetch types this
        // whole branch as `never` — the cast reflects the real runtime
        // contract, not a type-safety hole.
        throw new ApiError(extractApiErrorMessage(error), (response as Response).status);
      }
      return data.items;
    },
  });
}
