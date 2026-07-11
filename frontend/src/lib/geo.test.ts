import { describe, expect, it } from "vitest";

import {
  farmAreaBoundsIssue,
  MAX_FARM_AREA_HA,
  MIN_FARM_AREA_HA,
  ringAreaHectares,
  toFarmGeometry,
} from "./geo";

// A ~1.1km × ~1.1km square near Latur (18.4°N) — 0.01° of longitude is
// ~1.05km at this latitude, so the true geodesic area is ~117 ha.
const OPEN_SQUARE: [number, number][] = [
  [76.45, 18.4],
  [76.46, 18.4],
  [76.46, 18.41],
  [76.45, 18.41],
];

describe("toFarmGeometry", () => {
  it("closes an open ring so it matches the backend's closed-ring rule", () => {
    const geometry = toFarmGeometry(OPEN_SQUARE);
    const ring = geometry.coordinates[0];
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
  });

  it("leaves an already-closed ring untouched", () => {
    const closed: [number, number][] = [...OPEN_SQUARE, OPEN_SQUARE[0]];
    const geometry = toFarmGeometry(closed);
    expect(geometry.coordinates[0]).toHaveLength(5);
  });

  it("produces the exact backend contract shape", () => {
    const geometry = toFarmGeometry(OPEN_SQUARE);
    expect(geometry.type).toBe("Polygon");
    expect(geometry.coordinates).toHaveLength(1); // single ring, no holes
  });

  it("rejects an empty ring", () => {
    expect(() => toFarmGeometry([])).toThrow();
  });
});

describe("ringAreaHectares", () => {
  it("computes a plausible geodesic area for a known square", () => {
    const hectares = ringAreaHectares(OPEN_SQUARE);
    // ~1.05km × ~1.11km at 18.4°N ≈ 117 ha; allow generous bounds — this
    // guards against unit mistakes (m² vs ha), not turf's precision.
    expect(hectares).toBeGreaterThan(100);
    expect(hectares).toBeLessThan(135);
  });

  it("returns 0 for fewer than 3 points instead of a degenerate polygon error", () => {
    expect(ringAreaHectares([])).toBe(0);
    expect(
      ringAreaHectares([
        [76.45, 18.4],
        [76.46, 18.4],
      ]),
    ).toBe(0);
  });
});

describe("farmAreaBoundsIssue", () => {
  it("accepts a typical smallholder farm", () => {
    expect(farmAreaBoundsIssue(2.5)).toBeNull();
  });

  it("accepts the exact bounds (mirroring the server's inclusive check)", () => {
    expect(farmAreaBoundsIssue(MIN_FARM_AREA_HA)).toBeNull();
    expect(farmAreaBoundsIssue(MAX_FARM_AREA_HA)).toBeNull();
  });

  it("blocks a degenerate speck below the minimum", () => {
    expect(farmAreaBoundsIssue(0.001)).toMatch(/too small/);
  });

  it("blocks a whole-taluka mis-trace above the maximum", () => {
    expect(farmAreaBoundsIssue(5000)).toMatch(/larger than a single farm/);
  });
});
