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
