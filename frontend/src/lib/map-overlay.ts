import type maplibregl from "maplibre-gl";

const FILL_SUFFIX = "-fill";
const LINE_SUFFIX = "-line";

/** Min/max lon/lat across every coordinate in a Polygon or MultiPolygon —
 * hand-rolled rather than pulling in @turf/bbox for one small
 * computation (catchment-geo.ts already depends on @turf/area for a
 * genuinely non-trivial geodesic calculation; a bounding box is not
 * that). */
function geometryBounds(geometry: GeoJSON.Geometry): [number, number, number, number] {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;

  function visit(coords: unknown): void {
    const arr = coords as unknown[];
    if (typeof arr[0] === "number") {
      const [lon, lat] = arr as [number, number];
      minLon = Math.min(minLon, lon);
      maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
      return;
    }
    for (const item of arr) visit(item);
  }

  if ("coordinates" in geometry) {
    visit(geometry.coordinates);
  }
  return [minLon, minLat, maxLon, maxLat];
}

/**
 * Adds (or updates, if already present) a fill+line GeoJSON overlay for
 * one geometry, optionally fitting the map to its bounds. No existing
 * component does this — base-map.tsx deliberately owns only the raster
 * basemap, catchment-map.tsx only does manual drawing, farm-map.tsx only
 * flies to a point marker (docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md
 * Part 4) — this is the first place an admin-boundary polygon gets
 * rendered as a real overlay rather than a point.
 */
export function setGeoJsonOverlay(
  map: maplibregl.Map,
  sourceId: string,
  geometry: GeoJSON.Geometry,
  options: { fitBounds?: boolean; color?: string } = {},
): void {
  const feature: GeoJSON.Feature = { type: "Feature", properties: {}, geometry };
  const existing = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined;
  const color = options.color ?? "#2563eb";

  if (existing) {
    existing.setData(feature);
  } else {
    map.addSource(sourceId, { type: "geojson", data: feature });
    map.addLayer({
      id: `${sourceId}${FILL_SUFFIX}`,
      type: "fill",
      source: sourceId,
      paint: { "fill-color": color, "fill-opacity": 0.15 },
    });
    map.addLayer({
      id: `${sourceId}${LINE_SUFFIX}`,
      type: "line",
      source: sourceId,
      paint: { "line-color": color, "line-width": 2 },
    });
  }

  if (options.fitBounds !== false) {
    const [minLon, minLat, maxLon, maxLat] = geometryBounds(geometry);
    if (Number.isFinite(minLon) && Number.isFinite(minLat) && Number.isFinite(maxLon) && Number.isFinite(maxLat)) {
      map.fitBounds(
        [
          [minLon, minLat],
          [maxLon, maxLat],
        ],
        { padding: 48, duration: 800 },
      );
    }
  }
}

/** Removes a previously-added overlay, if present — a no-op otherwise
 * (safe to call defensively on cleanup/mode changes). */
export function removeGeoJsonOverlay(map: maplibregl.Map, sourceId: string): void {
  if (map.getLayer(`${sourceId}${LINE_SUFFIX}`)) map.removeLayer(`${sourceId}${LINE_SUFFIX}`);
  if (map.getLayer(`${sourceId}${FILL_SUFFIX}`)) map.removeLayer(`${sourceId}${FILL_SUFFIX}`);
  if (map.getSource(sourceId)) map.removeSource(sourceId);
}
