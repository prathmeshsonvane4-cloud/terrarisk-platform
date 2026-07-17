"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import type { FarmGeometry } from "@/lib/geo";

export type FarmResponse = components["schemas"]["FarmResponse"];

interface CreateFarmInput {
  villageId: string;
  geometry: FarmGeometry;
}

export function useCreateFarm() {
  return useMutation({
    mutationFn: async ({ villageId, geometry }: CreateFarmInput): Promise<FarmResponse> => {
      const { data, error, response } = await apiClient.POST("/api/v1/farms", {
        body: { village_id: villageId, geometry },
      });
      if (error) {
        throw new ApiError(extractApiErrorMessage(error), response.status);
      }
      return data;
    },
  });
}
