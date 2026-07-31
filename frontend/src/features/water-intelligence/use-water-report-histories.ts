"use client";

import { useQueries } from "@tanstack/react-query";

import {
  fetchWaterReportHistory,
  waterReportHistoryQueryKey,
  type WaterReportHistoryItem,
} from "./use-water-report-history";

export interface CatchmentHistoryQuery {
  catchmentId: string;
  data: WaterReportHistoryItem[] | undefined;
  isPending: boolean;
  isError: boolean;
}

/** History for a variable-length, caller-chosen list of catchments — the
 * compare page's actual data need, which a single useQuery/useQueryFn
 * call can't express (the Rules of Hooks forbid calling useQuery in a
 * .map() with a count that can change between renders). useQueries is
 * the documented TanStack pattern for exactly this: a dynamic array of
 * independent queries, still one React Query cache, still per-query
 * loading/error state. */
export function useWaterReportHistories(catchmentIds: string[], limit?: number): CatchmentHistoryQuery[] {
  const results = useQueries({
    queries: catchmentIds.map((catchmentId) => ({
      queryKey: waterReportHistoryQueryKey(catchmentId, limit),
      queryFn: () => fetchWaterReportHistory(catchmentId, limit),
    })),
  });

  return catchmentIds.map((catchmentId, index) => ({
    catchmentId,
    data: results[index]?.data,
    isPending: results[index]?.isPending ?? true,
    isError: results[index]?.isError ?? false,
  }));
}
