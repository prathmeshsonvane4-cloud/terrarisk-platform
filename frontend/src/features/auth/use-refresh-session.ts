"use client";

import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { extractApiErrorMessage } from "@/lib/api/errors";

/** Exchanges the current (still-valid) bearer token for a fresh one via
 * POST /auth/refresh (B6 — sliding session). Used by the expiry-warning
 * modal's "Stay signed in" action; a plain 401 elsewhere still falls back
 * to a full re-login, since a token that's already expired can't refresh
 * itself. */
export function useRefreshSession() {
  return useMutation({
    mutationFn: async () => {
      const { data, error } = await apiClient.POST("/api/v1/auth/refresh", {});
      if (error) {
        throw new Error(extractApiErrorMessage(error));
      }
      return data;
    },
  });
}
