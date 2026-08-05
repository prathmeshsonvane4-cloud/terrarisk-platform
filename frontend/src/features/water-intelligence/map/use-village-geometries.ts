"use client";

import { useQueries } from "@tanstack/react-query";

import {
  adminBoundaryDetailQueryKey,
  fetchAdminBoundaryDetail,
  type AdminBoundaryDetail,
} from "../select-area/use-admin-boundary-detail";

export interface VillageGeometryQuery {
  boundaryId: string;
  data: AdminBoundaryDetail | undefined;
  isPending: boolean;
  isError: boolean;
}

/**
 * Village geometry for a caller-chosen list of admin boundaries — the
 * choropleth's data need. GET /admin-boundaries (the list endpoint) is
 * documented as "deliberately minimal, no geometry", so the only source
 * of a village polygon is the per-id detail endpoint; this fetches one
 * per monitored catchment through the same useQueries pattern
 * use-water-report-histories.ts already uses for the same
 * dynamic-length-list reason (the Rules of Hooks forbid useQuery in a
 * .map() whose length changes between renders).
 *
 * Administrative boundaries are static reference data — a village's
 * shape does not change between page views — so these are marked
 * permanently fresh. That, plus sharing adminBoundaryDetailQueryKey with
 * Select Area's own single-boundary hook, means each village is fetched
 * at most once per session no matter how many views ask for it.
 */
export function useVillageGeometries(boundaryIds: string[]): VillageGeometryQuery[] {
  const results = useQueries({
    queries: boundaryIds.map((boundaryId) => ({
      queryKey: adminBoundaryDetailQueryKey(boundaryId),
      queryFn: () => fetchAdminBoundaryDetail(boundaryId),
      staleTime: Infinity,
    })),
  });

  return boundaryIds.map((boundaryId, index) => ({
    boundaryId,
    data: results[index]?.data,
    isPending: results[index]?.isPending ?? true,
    isError: results[index]?.isError ?? false,
  }));
}
