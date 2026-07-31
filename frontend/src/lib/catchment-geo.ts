import turfArea from "@turf/area";
import turfBooleanIntersects from "@turf/boolean-intersects";

import type { components } from "@/lib/api/schema";

/** The exact geometry shape CatchmentCreateRequest expects — reused from
 * the generated schema so a backend contract change fails this build,
 * mirroring lib/geo.ts's exact FarmGeometry convention. */
export type CatchmentGeometry = components["schemas"]["GeoJSONMultiPolygon"];

export type Ring = [number, number][];

const SQUARE_METERS_PER_HECTARE = 10_000;

/**
 * Builds the backend-contract MultiPolygon from a single drawn ring,
 * closing it if the drawing tool left it open — the one-element
 * MultiPolygon case GeoJSONMultiPolygon's own docstring documents as
 * the ordinary path for "a single simply-connected boundary" (most
 * hand-drawn catchments). Structural preparation only — full validity
 * is re-checked server-side by CatchmentCreateRequest; the client never
 * gets to be the authority on geometry (mirrors lib/geo.ts's
 * toFarmGeometry).
 */
export function toCatchmentGeometry(ring: Ring): CatchmentGeometry {
  if (ring.length === 0) {
    throw new Error("Cannot build a polygon from an empty ring");
  }
  const [firstLon, firstLat] = ring[0];
  const [lastLon, lastLat] = ring[ring.length - 1];
  const closed = firstLon === lastLon && firstLat === lastLat ? ring : [...ring, ring[0]];
  return { type: "MultiPolygon", coordinates: [[closed]] };
}

/**
 * Geodesic area in hectares — a PREVIEW for the officer while drawing,
 * never the recorded value. The server recomputes the authoritative area
 * with PostGIS ST_Area on submit (app/api/catchments.py); if the two
 * ever disagree, the server's number is the record.
 */
export function ringAreaHectares(ring: Ring): number {
  if (ring.length < 3) {
    return 0;
  }
  const geometry = toCatchmentGeometry(ring);
  return turfArea({ type: "Feature", properties: {}, geometry }) / SQUARE_METERS_PER_HECTARE;
}

// Mirrors app/api/catchments.py's server-side plausibility bounds
// (_MIN_CATCHMENT_AREA_HA / _MAX_CATCHMENT_AREA_HA, also Catchment's own
// chk_catchment_area CHECK constraint). UX-only pre-validation — catching
// an implausible trace before the round trip beats surfacing a 422 after
// it. The server check remains authoritative.
export const MIN_CATCHMENT_AREA_HA = 0.5;
export const MAX_CATCHMENT_AREA_HA = 50000;

/** Returns a human-readable blocker if the preview area is outside the
 * plausible catchment range, or null if it's submittable. */
export function catchmentAreaBoundsIssue(hectares: number): string | null {
  if (hectares < MIN_CATCHMENT_AREA_HA) {
    return "This boundary is too small to be a catchment — draw a larger area.";
  }
  if (hectares > MAX_CATCHMENT_AREA_HA) {
    return "This boundary is far larger than the allowed catchment size — redraw a smaller area.";
  }
  return null;
}

/**
 * The single ring to seed an editable AOI with, taken from an admin
 * boundary's own geometry (Select Area's "Create Editable AOI" — see
 * docs/TerraRisk_Editable_AOI_2026.md) — the starting shape a user then
 * reshapes, never the boundary itself. A village's geometry is a
 * MultiPolygon (ST_AsGeoJSON of a MULTIPOLYGON column); real villages
 * are simply-connected in practice, so when more than one ring is
 * present this takes the one with the most vertices as the most
 * detailed/significant ring — a deterministic heuristic, not a claim
 * about which ring is "correct."
 */
export function ringFromGeometry(geometry: GeoJSON.Geometry): Ring | null {
  if (geometry.type === "Polygon") {
    return geometry.coordinates[0] as Ring;
  }
  if (geometry.type === "MultiPolygon") {
    const rings = geometry.coordinates.map((polygon) => polygon[0]);
    if (rings.length === 0) return null;
    return rings.reduce((largest, current) => (current.length > largest.length ? current : largest)) as Ring;
  }
  return null;
}

/**
 * Whether a (possibly user-edited) ring still overlaps a reference
 * geometry at all — the AOI/village overlap check. A warning-only
 * signal (Select Area's editable-AOI validation): there is no backend
 * rule requiring a catchment to overlap its admin_boundary_id at all,
 * so this is never used to block submission, only to explain what
 * happened.
 */
export function ringOverlapsGeometry(ring: Ring, geometry: GeoJSON.Geometry): boolean {
  if (ring.length < 3) return false;
  return turfBooleanIntersects(toCatchmentGeometry(ring), geometry);
}
