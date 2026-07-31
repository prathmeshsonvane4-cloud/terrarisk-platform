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
  /** Set when the catchment came from Select Area — links it to the
   * chosen AdminBoundary row (docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md
   * Part 4). Undefined for Draw/Upload, which have no administrative
   * boundary to attach. */
  adminBoundaryId?: string;
}

/** POST /catchments (manual-draw and Select Area paths) — mirrors
 * farm-drawing/use-create-farm.ts exactly. */
export function useCreateCatchment() {
  return useMutation({
    mutationFn: async ({
      name,
      geometry,
      organizationId,
      adminBoundaryId,
    }: CreateCatchmentInput): Promise<CatchmentResponse> => {
      const { data, error, response } = await apiClient.POST("/api/v1/catchments", {
        body: {
          name,
          geometry,
          organization_id: organizationId ?? null,
          admin_boundary_id: adminBoundaryId ?? null,
        },
      });
      if (error) {
        throw new ApiError(extractApiErrorMessage(error), response.status);
      }
      return data;
    },
  });
}
