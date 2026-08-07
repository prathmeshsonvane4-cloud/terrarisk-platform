"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { ApiError, extractApiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type CatchmentResponse = components["schemas"]["CatchmentResponse"];

/** The endpoint's own maximum (_MAX_PAGE_SIZE in app/api/catchments.py).
 * Requesting more is rejected, so this is the largest useful page. */
const PAGE_SIZE = 200;

/** Guard against an unbounded loop if the server ever stopped honouring
 * `offset` — 100 pages is far beyond any real programme, and looping
 * forever against a paginated API is worse than showing an error. */
const MAX_PAGES = 100;

/** EVERY catchment the caller created (GET /catchments, M4-005) — the
 * Water Intelligence analogue of workspace/use-farms.ts. Unlike Farms
 * (whose GET wraps the list as {items: [...]}), this endpoint's response
 * is a bare CatchmentResponse[], so no `.items` unwrap is needed.
 *
 * Pages until the server returns a short page. The endpoint defaults to
 * 50 per page, and this hook previously sent no `limit` at all — so once
 * a real programme exceeded 50 catchments, the map, the Priority Queue
 * and the catchments list all silently showed the first 50 and nothing
 * indicated the rest existed. A district choropleth missing two thirds
 * of its villages still looks like a complete map, which is the failure
 * mode worth engineering against: a truncated list is indistinguishable
 * from a short one.
 *
 * Paging rather than a single limit=200 request: 200 is the server's own
 * cap, so hardcoding it would reintroduce exactly this bug at 201
 * catchments, and just as invisibly.
 */
export function useCatchments() {
  return useQuery({
    queryKey: ["catchments"],
    queryFn: async (): Promise<CatchmentResponse[]> => {
      const all: CatchmentResponse[] = [];

      for (let page = 0; page < MAX_PAGES; page += 1) {
        const { data, error, response } = await apiClient.GET("/api/v1/catchments", {
          params: { query: { limit: PAGE_SIZE, offset: page * PAGE_SIZE } },
        });
        if (error) {
          // Same known doc gap use-farms.ts already notes (lib/api/errors.ts):
          // this endpoint's OpenAPI doc only declares 200, so openapi-fetch
          // types `error`/`response` as `never` even though 401/403 are real
          // runtime responses.
          throw new ApiError(extractApiErrorMessage(error), (response as Response).status);
        }

        all.push(...data);
        // A short page means the last page: the only reliable end signal,
        // since this endpoint returns a bare array with no total count.
        if (data.length < PAGE_SIZE) return all;
      }

      return all;
    },
  });
}
