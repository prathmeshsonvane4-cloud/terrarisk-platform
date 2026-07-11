import turfArea from "@turf/area";

import type { components } from "@/lib/api/schema";

/** The exact geometry shape FarmCreateRequest expects — reused from the
 * generated schema so a backend contract change fails this build. */
export type FarmGeometry = components["schemas"]["GeoJSONPolygon"];

export type Ring = [number, number][];

const SQUARE_METERS_PER_HECTARE = 10_000;

/**
 * Builds the backend-contract polygon from a drawn ring, closing it if the
 * drawing tool left it open. Structural preparation only — full validity
 * (self-intersection, coordinate range, non-zero area) is re-checked
 * server-side by FarmCreateRequest; the client never gets to be the
 * authority on geometry (Blueprint §05).
 */
export function toFarmGeometry(ring: Ring): FarmGeometry {
  if (ring.length === 0) {
    throw new Error("Cannot build a polygon from an empty ring");
  }
  const [firstLon, firstLat] = ring[0];
  const [lastLon, lastLat] = ring[ring.length - 1];
  const closed = firstLon === lastLon && firstLat === lastLat ? ring : [...ring, ring[0]];
  return { type: "Polygon", coordinates: [closed] };
}

/**
 * Geodesic area in hectares — a PREVIEW for the officer while drawing,
 * never the recorded value. The server recomputes the authoritative area
 * with PostGIS ST_Area on submit (app/api/farms.py); if the two ever
 * disagree, the server's number is the record.
 */
export function ringAreaHectares(ring: Ring): number {
  if (ring.length < 3) {
    return 0;
  }
  const geometry = toFarmGeometry(ring);
  return turfArea({ type: "Feature", properties: {}, geometry }) / SQUARE_METERS_PER_HECTARE;
}

// Mirrors app/api/farms.py's server-side plausibility bounds. UX-only
// pre-validation: catching a whole-taluka mis-trace before the round trip
// beats surfacing a 422 after it. The server check remains authoritative —
// if these constants ever drift from the backend's, the effect is a
// slightly worse error message, never a wrongly-accepted farm.
export const MIN_FARM_AREA_HA = 0.01;
export const MAX_FARM_AREA_HA = 1000;

/** Returns a human-readable blocker if the preview area is outside the
 * plausible single-farm range, or null if it's submittable. */
export function farmAreaBoundsIssue(hectares: number): string | null {
  if (hectares < MIN_FARM_AREA_HA) {
    return "This boundary is too small to be a farm — zoom in and redraw around the field.";
  }
  if (hectares > MAX_FARM_AREA_HA) {
    return "This boundary is far larger than a single farm — it may trace a whole village or taluka. Redraw around one field.";
  }
  return null;
}
