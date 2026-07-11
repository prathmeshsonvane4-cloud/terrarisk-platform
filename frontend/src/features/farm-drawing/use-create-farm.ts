"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";
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
      const { data, error } = await apiClient.POST("/api/v1/farms", {
        body: { village_id: villageId, geometry },
      });
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data;
    },
  });
}
