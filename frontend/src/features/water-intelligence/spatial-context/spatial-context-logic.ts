import type { AdminBoundarySummary } from "../select-area/use-admin-boundary-children";
import type { SpatialNeighbour } from "./use-spatial-context";

/** The same 2% threshold the PDF's locator caption uses for "the
 * analysed area differs from the village boundary" — kept in one place
 * so the live report page and the downloaded PDF can never disagree
 * about what counts as "reshaped". */
export const AOI_DIFFERS_THRESHOLD = 0.02;

/**
 * Every sibling under a taluka except the current village itself, with
 * geometry — dropping any row the bulk fetch returned without one
 * (shouldn't happen when `include_geometry=true` succeeds, but a row
 * with no polygon can't be drawn regardless of why).
 */
export function filterNeighbours(siblings: AdminBoundarySummary[], currentVillageId: string | null): SpatialNeighbour[] {
  return siblings
    .filter((row) => row.id !== currentVillageId && row.geometry)
    .map((row) => ({ id: row.id, name: row.name, geometry: row.geometry as unknown as GeoJSON.Geometry }));
}

/**
 * The catchment's own geometry, but only when it is worth drawing as a
 * separate layer — i.e. only once it has been reshaped far enough from
 * the village boundary that the two are no longer effectively the same
 * shape. Returns null both when the AOI was left untouched (area
 * matches the village almost exactly) and when there's nothing to
 * compare against (no village area known), so the map never draws two
 * near-identical outlines on top of each other.
 */
export function deriveAnalysedGeometry(
  catchmentAreaHa: number,
  villageAreaHa: number | null,
  catchmentGeometry: GeoJSON.Geometry | null,
): GeoJSON.Geometry | null {
  if (villageAreaHa === null || catchmentGeometry === null) return null;
  const areaDiffers = Math.abs(catchmentAreaHa - villageAreaHa) / villageAreaHa > AOI_DIFFERS_THRESHOLD;
  return areaDiffers ? catchmentGeometry : null;
}
