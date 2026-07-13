"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type ReportListItem = components["schemas"]["ReportListItem"];

/** The Reports workspace index (Product Design v2 §7, screen 9) — every
 * issued report in the officer's own-or-branch scope, newest first. */
export function useReports() {
  return useQuery({
    queryKey: ["reports"],
    queryFn: async (): Promise<ReportListItem[]> => {
      const { data, error } = await apiClient.GET("/api/v1/reports");
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data.items;
    },
  });
}
