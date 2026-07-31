/**
 * crypto.randomUUID() throws outside a secure context — HTTPS, or
 * "localhost" specifically. TerraRisk's production origin is plain HTTP
 * on a bare IP (not localhost), so it's not a secure context there;
 * local dev is exempt only because "localhost" itself is. That made
 * Select Area's editable-AOI seed (catchment-map.tsx) silently fail in
 * production — the throw happened before addFeatures ever ran, so the
 * polygon on screen was only ever the read-only village reference
 * layer, never a real, editable terra-draw feature — while working in
 * every local/dev check. crypto.getRandomValues has no such
 * restriction, so a small UUID v4 built from it works everywhere the
 * rest of the Web Crypto API already exists.
 */
export function generateFeatureId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID();
    } catch {
      // fall through to the getRandomValues-based generator below
    }
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
