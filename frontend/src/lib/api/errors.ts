const GENERIC_MESSAGE = "Something went wrong. Please try again.";

/**
 * Extracts the message from the backend's single error envelope
 * ({"error": {"code", "message"}} — app/main.py's exception handlers).
 * openapi-fetch's generated `error` type is loosely typed for non-2xx
 * responses the OpenAPI schema doesn't explicitly declare (401/403/404/409
 * currently aren't — a known, non-blocking doc gap), so this reads the
 * envelope defensively rather than trusting a generated type.
 */
export function extractApiErrorMessage(error: unknown): string {
  if (typeof error !== "object" || error === null || !("error" in error)) {
    return GENERIC_MESSAGE;
  }
  const inner = (error as { error?: unknown }).error;
  if (typeof inner !== "object" || inner === null || !("message" in inner)) {
    return GENERIC_MESSAGE;
  }
  const message = (inner as { message?: unknown }).message;
  return typeof message === "string" ? message : GENERIC_MESSAGE;
}

/**
 * Reads the `job_id` the backend attaches to a 409 "already generating"
 * conflict (app/main.py's dict-detail extension, M2B P7 B5) — lets a
 * conflict route straight to the run already in flight instead of just
 * reporting failure. Returns null for any other error shape.
 */
export function extractConflictingJobId(error: unknown): string | null {
  if (typeof error !== "object" || error === null || !("error" in error)) {
    return null;
  }
  const inner = (error as { error?: unknown }).error;
  if (typeof inner !== "object" || inner === null || !("job_id" in inner)) {
    return null;
  }
  const jobId = (inner as { job_id?: unknown }).job_id;
  return typeof jobId === "string" ? jobId : null;
}

/**
 * A fetch error carrying the HTTP status the backend actually returned —
 * plain `Error` (used throughout the codebase's mutation hooks) loses this
 * the moment it's constructed. Query hooks that back the P10 error-state
 * taxonomy (`ErrorState`, `components/ui/error-state.tsx`) throw this
 * instead, so the family (network / auth / forbidden / not-found / server) can be
 * derived from a real status code rather than guessed from message text.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type ErrorFamily = "network" | "auth" | "forbidden" | "not-found" | "server";

/**
 * Classifies any error a query hook can throw into one of the four
 * families the P10 error-state design (Product Design v2 §7.6) treats
 * distinctly. Anything that isn't a classified `ApiError` — a rejected
 * `fetch()` itself (offline, DNS failure, CORS) — is the "network" family,
 * the safest default for an unrecognized failure in this codebase (no
 * other class of error is expected to reach a query's `onError`).
 */
export function classifyError(error: unknown): ErrorFamily {
  if (error instanceof ApiError) {
    // 401 and 403 were one family, so a role-permission refusal told the
    // user their session had expired. Signing out and back in then
    // reproduces it exactly, because the session was never the problem —
    // an endless loop with no way for the user to learn the real cause.
    // A chairman hitting a credit-officer-only endpoint is the case that
    // surfaced it, but every role boundary in the app had it.
    if (error.status === 401) return "auth";
    if (error.status === 403) return "forbidden";
    if (error.status === 404) return "not-found";
    return "server";
  }
  return "network";
}
