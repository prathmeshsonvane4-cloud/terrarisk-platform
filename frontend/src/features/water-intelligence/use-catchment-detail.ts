"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type CatchmentDetailResponse = components["schemas"]["CatchmentDetailResponse"];

/** GET /catchments/{id} — the one place a catchment's own analysed
 * geometry is available. Deliberately separate from useCatchments()
 * (M4-005's bulk list, CatchmentResponse — no geometry): that hook is
 * fetched wholesale by the map, Priority Queue and compare view, so
 * attaching a polygon to every row there would put a payload of
 * geometry into three screens that never draw it. This hook exists for
 * the one screen that does — the water-report page's spatial context
 * panel, which needs to know whether the catchment's actual boundary is
 * still exactly its source village or was reshaped away from it. */
export function useCatchmentDetail(catchmentId: string | undefined) {
  return useQuery({
    queryKey: ["catchments", catchmentId, "detail"],
    queryFn: async (): Promise<CatchmentDetailResponse> => {
      const { data, error, response } = await apiClient.GET("/api/v1/catchments/{catchment_id}", {
        params: { path: { catchment_id: catchmentId as string } },
      });
      if (error) {
        throw new ApiError(extractApiErrorMessage(error), (response as Response).status);
      }
      return data;
    },
    enabled: catchmentId !== undefined,
  });
}
