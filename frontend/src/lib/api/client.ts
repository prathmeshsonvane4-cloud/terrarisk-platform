import createClient from "openapi-fetch";

import { clearSession, getToken } from "@/features/auth/session";

import type { paths } from "./schema";

// NEXT_PUBLIC_ prefix required for the value to reach the browser bundle —
// this is a base URL, not a secret, so that's the correct exposure.
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export const apiClient = createClient<paths>({ baseUrl: API_BASE_URL });

apiClient.use({
  onRequest({ request }) {
    const token = getToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },
  onResponse({ response }) {
    // A 401 means the session is gone (expired/invalid) — clear it and
    // send the officer back to login rather than let every caller
    // separately handle a half-authenticated state. Preserves ?next= like
    // the route guard does (P10 — a mid-work 401 must not drop the
    // officer's location any more than an unauthenticated visit does), and
    // flags any in-progress assessment draft as interrupted-not-abandoned
    // before the session that scopes it disappears (draft-storage.ts).
    if (response.status === 401 && typeof window !== "undefined") {
      // Dynamic import: draft-storage.ts is a feature-layer module and this
      // is a low-level infra client — a static import here would invert
      // that dependency direction for the sake of one rare error path.
      // The flag MUST be written before clearSession() runs, since it
      // needs the still-present token to resolve which officer's draft to
      // mark — hence the explicit await/ordering rather than a fire-and-
      // forget .then().
      void (async () => {
        const { markDraftInterruptedBySessionExpiry } = await import("@/features/assessment-wizard/draft-storage");
        markDraftInterruptedBySessionExpiry();
        clearSession();
        if (window.location.pathname !== "/login") {
          const next = `?next=${encodeURIComponent(window.location.pathname)}`;
          window.location.href = `/login${next}`;
        }
      })();
    }
    return response;
  },
});
