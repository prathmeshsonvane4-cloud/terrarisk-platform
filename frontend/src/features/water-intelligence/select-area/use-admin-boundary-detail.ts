"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type AdminBoundaryDetail = components["schemas"]["AdminBoundaryDetail"];

/** Backs the boundary-preview step once a village (or any level) is
 * picked: its geometry (for the map overlay), resolved ancestor names,
 * and area — from GET /admin-boundaries/{id}. */
export function useAdminBoundaryDetail(boundaryId: string | null) {
  return useQuery({
    queryKey: ["admin-boundaries", "detail", boundaryId],
    queryFn: async () => {
      const { data, error, response } = await apiClient.GET("/api/v1/admin-boundaries/{boundary_id}", {
        params: { path: { boundary_id: boundaryId as string } },
      });
      if (error) {
        throw new ApiError(extractApiErrorMessage(error), response.status);
      }
      return data;
    },
    enabled: boundaryId !== null,
  });
}
