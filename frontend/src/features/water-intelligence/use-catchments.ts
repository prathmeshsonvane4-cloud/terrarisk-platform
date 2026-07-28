"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type CatchmentResponse = components["schemas"]["CatchmentResponse"];

/** Every catchment the caller created (GET /catchments, M4-005) — the
 * Water Intelligence analogue of workspace/use-farms.ts. Unlike Farms
 * (whose GET wraps the list as {items: [...]}), this endpoint's response
 * is a bare CatchmentResponse[], so no `.items` unwrap is needed. */
export function useCatchments() {
  return useQuery({
    queryKey: ["catchments"],
    queryFn: async (): Promise<CatchmentResponse[]> => {
      const { data, error, response } = await apiClient.GET("/api/v1/catchments");
      if (error) {
        // Same known doc gap use-farms.ts already notes (lib/api/errors.ts):
        // this endpoint's OpenAPI doc only declares 200, so openapi-fetch
        // types `error`/`response` as `never` even though 401/403 are real
        // runtime responses.
        throw new ApiError(extractApiErrorMessage(error), (response as Response).status);
      }
      return data;
    },
  });
}
