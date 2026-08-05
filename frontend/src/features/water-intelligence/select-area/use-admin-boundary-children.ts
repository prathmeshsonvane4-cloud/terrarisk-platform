"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type AdminBoundarySummary = components["schemas"]["AdminBoundarySummary"];

/**
 * Backs one dropdown level of the State -> District -> Taluka -> Village
 * cascade off the single generic GET /admin-boundaries?parent_id= endpoint
 * (docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md Part 4) — the
 * same endpoint serves every level, so there's one hook, not four.
 * `parentId` of `null` means "list top-level states"; `undefined` means
 * "this level isn't ready to query yet" (its own parent hasn't been
 * chosen), which the `enabled` flag turns into a no-op query rather than
 * a request for every boundary in the country.
 */
/** Shared fetcher — used by the hook below and by the PDF's map-context
 * loader, which walks the hierarchy imperatively on click rather than
 * subscribing to four levels it doesn't render. Same "one fetch
 * implementation, two consumers" split use-admin-boundary-detail.ts
 * already uses. */
export async function fetchAdminBoundaryChildren(parentId: string | null): Promise<AdminBoundarySummary[]> {
  const { data, error, response } = await apiClient.GET("/api/v1/admin-boundaries", {
    params: { query: parentId ? { parent_id: parentId } : {} },
  });
  if (error) {
    throw new ApiError(extractApiErrorMessage(error), response.status);
  }
  return data;
}

export function useAdminBoundaryChildren(parentId: string | null | undefined) {
  // `null` (root/top-level) and `undefined` (not ready yet, disabled) must
  // map to DIFFERENT cache keys, not both to the same fallback string —
  // otherwise every disabled lower-level dropdown shares react-query's
  // cache entry for the real top-level states query and renders its data
  // even though its own fetch never ran (found via a real UI test: every
  // dropdown showed the states list until this was fixed).
  const queryKeyPart = parentId === null ? "root" : (parentId ?? "pending");
  return useQuery({
    queryKey: ["admin-boundaries", "children", queryKeyPart],
    queryFn: () => fetchAdminBoundaryChildren(parentId ?? null),
    enabled: parentId !== undefined,
  });
}
