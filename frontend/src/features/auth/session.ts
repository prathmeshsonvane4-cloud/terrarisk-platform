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
