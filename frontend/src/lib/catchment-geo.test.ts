import { describe, expect, it } from "vitest";

import { ringFromGeometry, ringOverlapsGeometry, type Ring } from "./catchment-geo";

function square(centerLon: number, centerLat: number, halfWidth = 0.01): Ring {
  return [
    [centerLon - halfWidth, centerLat - halfWidth],
    [centerLon + halfWidth, centerLat - halfWidth],
    [centerLon + halfWidth, centerLat + halfWidth],
    [centerLon - halfWidth, centerLat + halfWidth],
    [centerLon - halfWidth, centerLat - halfWidth],
  ];
}

describe("ringFromGeometry", () => {
  it("extracts the outer ring from a Polygon", () => {
    const ring = square(76.0, 18.0);
    const geometry: GeoJSON.Polygon = { type: "Polygon", coordinates: [ring] };
    expect(ringFromGeometry(geometry)).toEqual(ring);
  });

  it("extracts the single ring from a one-polygon MultiPolygon — the real shape ST_AsGeoJSON returns for a village", () => {
    const ring = square(76.0, 18.0);
    const geometry: GeoJSON.MultiPolygon = { type: "MultiPolygon", coordinates: [[ring]] };
    expect(ringFromGeometry(geometry)).toEqual(ring);
  });

  it("picks the ring with the most vertices when a MultiPolygon has more than one", () => {
    const smallRing = square(76.0, 18.0, 0.001); // still 5 points (closed square)
    const detailedRing: Ring = [
      [76.5, 18.5],
      [76.51, 18.5],
      [76.515, 18.505],
      [76.51, 18.51],
      [76.5, 18.51],
      [76.495, 18.505],
      [76.5, 18.5],
    ];
    const geometry: GeoJSON.MultiPolygon = { type: "MultiPolygon", coordinates: [[smallRing], [detailedRing]] };
    expect(ringFromGeometry(geometry)).toEqual(detailedRing);
  });

  it("returns null for a geometry type with no polygon ring to seed from", () => {
    const geometry: GeoJSON.Point = { type: "Point", coordinates: [76.0, 18.0] };
    expect(ringFromGeometry(geometry)).toBeNull();
  });
});

describe("ringOverlapsGeometry", () => {
  it("returns true when the AOI ring still overlaps the reference geometry", () => {
    const village: GeoJSON.Polygon = { type: "Polygon", coordinates: [square(76.0, 18.0, 0.05)] };
    const aoi = square(76.0, 18.0, 0.01); // fully inside the village
    expect(ringOverlapsGeometry(aoi, village)).toBe(true);
  });

  it("returns false once the AOI has been dragged completely away from the village — the exact case the mission asks to warn about", () => {
    const village: GeoJSON.Polygon = { type: "Polygon", coordinates: [square(76.0, 18.0, 0.01)] };
    const aoi = square(80.0, 22.0, 0.01); // nowhere near the village
    expect(ringOverlapsGeometry(aoi, village)).toBe(false);
  });

  it("returns false for a degenerate ring with fewer than 3 points, never throws", () => {
    const village: GeoJSON.Polygon = { type: "Polygon", coordinates: [square(76.0, 18.0, 0.01)] };
    expect(ringOverlapsGeometry([[76.0, 18.0]], village)).toBe(false);
  });
});
