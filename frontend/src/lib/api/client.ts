import createClient from "openapi-fetch";

import { clearSession, getToken } from "@/features/auth/session";

import type { paths } from "./schema";

// NEXT_PUBLIC_ prefix required for the value to reach the browser bundle —
// this is a base URL, not a secret, so that's the correct exposure.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

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
    // separately handle a half-authenticated state.
    if (response.status === 401 && typeof window !== "undefined") {
      clearSession();
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return response;
  },
});
