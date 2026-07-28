"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import type { CatchmentGeometry } from "@/lib/catchment-geo";

export type CatchmentResponse = components["schemas"]["CatchmentResponse"];

interface CreateCatchmentInput {
  name: string;
  geometry: CatchmentGeometry;
  organizationId?: string;
}

/** POST /catchments (manual-draw path, M4-003) — mirrors
 * farm-drawing/use-create-farm.ts exactly. */
export function useCreateCatchment() {
  return useMutation({
    mutationFn: async ({ name, geometry, organizationId }: CreateCatchmentInput): Promise<CatchmentResponse> => {
      const { data, error, response } = await apiClient.POST("/api/v1/catchments", {
        body: { name, geometry, organization_id: organizationId ?? null },
      });
      if (error) {
        throw new ApiError(extractApiErrorMessage(error), response.status);
      }
      return data;
    },
  });
}
