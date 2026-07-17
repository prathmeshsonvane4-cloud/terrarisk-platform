/**
 * Session storage: localStorage, not an httpOnly cookie.
 *
 * Deliberate M2A pilot trade-off (docs/DECISIONS.md): a real XSS on this
 * app could exfiltrate the token, whereas an httpOnly cookie couldn't be.
 * The correct long-term shape is a cookie-based BFF, which needs a backend
 * change out of scope for M2A. Acceptable for a controlled pilot with a
 * handful of named officer accounts; revisit before any public deployment.
 */

export interface Session {
  token: string;
  role: string;
  fullName: string;
}

interface JwtPayload {
  sub?: string;
  role?: string;
  exp?: number;
  iat?: number;
}

const STORAGE_KEY = "terrarisk.session";

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

export function setSession(session: Session): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

/**
 * Decodes a JWT's payload segment client-side — display/expiry-tracking
 * only, never a substitute for the server's signature verification
 * (`app/core/security.py` `decode_access_token` remains the sole authority
 * on validity). Returns null for any malformed token rather than throwing,
 * since this only ever drives non-critical UX (an expiry countdown).
 */
function decodeJwtPayload(token: string): JwtPayload | null {
  const segments = token.split(".");
  if (segments.length !== 3) return null;
  try {
    const base64 = segments[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = typeof window === "undefined" ? Buffer.from(base64, "base64").toString("utf-8") : window.atob(base64);
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

/** Epoch milliseconds the current session's token expires at, or null if
 * there is no session or the token can't be decoded. */
export function getSessionExpiresAt(): number | null {
  const token = getToken();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  if (!payload?.exp) return null;
  return payload.exp * 1000;
}

/** The current session's user id (JWT `sub`), used to scope per-officer
 * localStorage data (e.g. the assessment draft) so a shared machine can't
 * leak one officer's in-progress work into another's session. */
export function getSessionUserId(): string | null {
  const token = getToken();
  if (!token) return null;
  return decodeJwtPayload(token)?.sub ?? null;
}
