"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type FarmListItem = components["schemas"]["FarmListItem"];

/** The Farms workspace index (Product Design v2 §7, screen 7) — every
 * farm the officer owns or shares a branch with, each already carrying
 * its latest assessment and any in-flight job. */
export function useFarms() {
  return useQuery({
    queryKey: ["farms"],
    queryFn: async (): Promise<FarmListItem[]> => {
      const { data, error, response } = await apiClient.GET("/api/v1/farms");
      if (error) {
        // /api/v1/farms's OpenAPI doc only declares a 200 response (a known
        // gap — see lib/api/errors.ts's own note on this), so openapi-fetch
        // types `error` (and, transitively, every binding in this branch)
        // as `never` even though the backend can and does return 4xx/5xx
        // here. The cast reflects the real runtime contract the rest of
        // this codebase already treats `error` as (`extractApiErrorMessage`
        // takes `unknown`); `response` is a real `Response` object, never
        // actually `never`, at runtime regardless of what the schema omits.
        throw new ApiError(extractApiErrorMessage(error), (response as Response).status);
      }
      return data.items;
    },
  });
}
