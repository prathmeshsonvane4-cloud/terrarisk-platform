import { describe, expect, it } from "vitest";

import type { AdminBoundarySummary } from "../select-area/use-admin-boundary-children";
import { AOI_DIFFERS_THRESHOLD, deriveAnalysedGeometry, filterNeighbours } from "./spatial-context-logic";

function square(centerLon: number, centerLat: number, half = 0.01): GeoJSON.Polygon {
  return {
    type: "Polygon",
    coordinates: [
      [
        [centerLon - half, centerLat - half],
        [centerLon + half, centerLat - half],
        [centerLon + half, centerLat + half],
        [centerLon - half, centerLat + half],
        [centerLon - half, centerLat - half],
      ],
    ],
  };
}

function boundary(overrides: Partial<AdminBoundarySummary> & Pick<AdminBoundarySummary, "id" | "name">): AdminBoundarySummary {
  return { level: "village", lgd_code: null, geometry: square(76.6, 15.9), ...overrides } as AdminBoundarySummary;
}

describe("filterNeighbours", () => {
  it("excludes the current village from its own sibling list", () => {
    const siblings = [boundary({ id: "a", name: "A" }), boundary({ id: "b", name: "B" }), boundary({ id: "c", name: "C" })];
    const neighbours = filterNeighbours(siblings, "b");
    expect(neighbours.map((n) => n.id)).toEqual(["a", "c"]);
  });

  it("drops a sibling with no geometry rather than drawing an undefined shape", () => {
    const siblings = [boundary({ id: "a", name: "A" }), boundary({ id: "b", name: "B", geometry: null })];
    expect(filterNeighbours(siblings, "z").map((n) => n.id)).toEqual(["a"]);
  });

  it("returns an empty list, not an error, when there are no siblings at all", () => {
    expect(filterNeighbours([], "any-id")).toEqual([]);
  });
});

describe("deriveAnalysedGeometry", () => {
  const catchmentGeometry = square(76.6, 15.9, 0.02);

  it("returns null when the AOI area matches the village almost exactly (never reshaped)", () => {
    expect(deriveAnalysedGeometry(100, 100, catchmentGeometry)).toBeNull();
    expect(deriveAnalysedGeometry(101, 100, catchmentGeometry)).toBeNull(); // 1% — under threshold
  });

  it("returns the geometry once the area differs by more than the threshold", () => {
    const overThreshold = 100 * (1 + AOI_DIFFERS_THRESHOLD + 0.001);
    expect(deriveAnalysedGeometry(overThreshold, 100, catchmentGeometry)).toBe(catchmentGeometry);
  });

  it("is symmetric — a contracted AOI is flagged the same as an expanded one", () => {
    const shrunk = 100 * (1 - AOI_DIFFERS_THRESHOLD - 0.001);
    expect(deriveAnalysedGeometry(shrunk, 100, catchmentGeometry)).toBe(catchmentGeometry);
  });

  it("returns null when the village area is unknown, rather than guessing", () => {
    expect(deriveAnalysedGeometry(500, null, catchmentGeometry)).toBeNull();
  });

  it("returns null when no catchment geometry was supplied", () => {
    expect(deriveAnalysedGeometry(500, 100, null)).toBeNull();
  });
});
