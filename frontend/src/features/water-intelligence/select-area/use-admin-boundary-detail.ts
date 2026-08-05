"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type AdminBoundaryDetail = components["schemas"]["AdminBoundaryDetail"];

export function adminBoundaryDetailQueryKey(boundaryId: string | null) {
  return ["admin-boundaries", "detail", boundaryId] as const;
}

/** Shared fetcher — used by useAdminBoundaryDetail below and by the
 * choropleth's useQueries-based multi-boundary fetch
 * (map/use-village-geometries.ts). Same "one fetch implementation, two
 * hooks consuming it" split use-water-report-history.ts already uses,
 * and the same query key on both sides, so a village whose geometry was
 * already loaded by Select Area is served from cache by the map rather
 * than re-requested. */
export async function fetchAdminBoundaryDetail(boundaryId: string): Promise<AdminBoundaryDetail> {
  const { data, error, response } = await apiClient.GET("/api/v1/admin-boundaries/{boundary_id}", {
    params: { path: { boundary_id: boundaryId } },
  });
  if (error) {
    throw new ApiError(extractApiErrorMessage(error), response.status);
  }
  return data;
}

/** Backs the boundary-preview step once a village (or any level) is
 * picked: its geometry (for the map overlay), resolved ancestor names,
 * and area — from GET /admin-boundaries/{id}. */
export function useAdminBoundaryDetail(boundaryId: string | null) {
  return useQuery({
    queryKey: adminBoundaryDetailQueryKey(boundaryId),
    queryFn: () => fetchAdminBoundaryDetail(boundaryId as string),
    enabled: boundaryId !== null,
  });
}
