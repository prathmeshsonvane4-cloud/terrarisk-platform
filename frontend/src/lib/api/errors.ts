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
