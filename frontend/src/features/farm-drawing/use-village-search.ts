"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const MIN_QUERY_LENGTH = 2;
const DEBOUNCE_MS = 300;

export function useVillageSearch(query: string) {
  const debouncedQuery = useDebouncedValue(query.trim(), DEBOUNCE_MS);
  const enabled = debouncedQuery.length >= MIN_QUERY_LENGTH;

  const result = useQuery({
    queryKey: ["villages", "search", debouncedQuery],
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/villages", {
        params: { query: { q: debouncedQuery } },
      });
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data;
    },
    enabled,
  });

  return { ...result, isQueryTooShort: !enabled && query.trim().length > 0 };
}
