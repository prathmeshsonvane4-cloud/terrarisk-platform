"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type FarmListItem = components["schemas"]["FarmListItem"];

/** The Farms workspace index (Product Design v2 §7, screen 7) — every
 * farm the officer owns or shares a branch with, each already carrying
 * its latest assessment and any in-flight job. */
export function useFarms() {
  return useQuery({
    queryKey: ["farms"],
    queryFn: async (): Promise<FarmListItem[]> => {
      const { data, error } = await apiClient.GET("/api/v1/farms");
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data.items;
    },
  });
}
