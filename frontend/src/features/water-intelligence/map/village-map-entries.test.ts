import { describe, expect, it } from "vitest";

import { NO_REPORT_MAP_COLOR, STRESS_BAND_MAP_COLORS, STRESS_BAND_PDF_COLORS } from "../band-styles";
import type { CatchmentResponse } from "../use-catchments";
import type { WaterReportHistoryItem } from "../use-water-report-history";
import {
  BAND_PROPERTY,
  CATCHMENT_ID_PROPERTY,
  NO_REPORT_BAND_VALUE,
  buildVillageMapData,
  entriesBounds,
  toFeatureCollection,
  topRecommendationOf,
  type VillageMapEntry,
} from "./village-map-entries";

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

function catchment(overrides: Partial<CatchmentResponse> & Pick<CatchmentResponse, "id" | "name">): CatchmentResponse {
  return {
    area_ha: 500,
    delineation_method: "manual_draw",
    organization_id: null,
    admin_boundary_id: null,
    resolution_flags: [],
    created_by: "00000000-0000-0000-0000-000000000000",
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  } as CatchmentResponse;
}

function report(overrides: {
  stressBand?: WaterReportHistoryItem["recharge_stress"]["stress_band"];
  stressScore?: number;
  storageBand?: WaterReportHistoryItem["water_balance"]["storage_change_band"];
  confidence?: number;
  generatedAt?: string;
}): WaterReportHistoryItem {
  return {
    job_id: "job-1",
    generated_at: overrides.generatedAt ?? "2026-07-20T00:00:00Z",
    water_balance: {
      storage_change_mm: 10,
      storage_change_band: overrides.storageBand ?? "normal",
      data_completeness: 95,
      resolution_flags: [],
      period_start: "2026-06-01",
      period_end: "2026-06-30",
    },
    recharge_stress: {
      stress_score: overrides.stressScore ?? 20,
      stress_band: overrides.stressBand ?? "low",
      rainfall_anomaly_ratio: 1,
      vci: 80,
      surface_water_trend: 50,
      raw_inputs: { confidence: overrides.confidence ?? 88 },
    },
  } as unknown as WaterReportHistoryItem;
}

describe("map band colours", () => {
  it("derives map fills from the same source as the PDF colours, so they cannot drift apart", () => {
    // Guards the actual rule this redesign had to honour: reuse the
    // existing band colours, do not invent new ones.
    expect(STRESS_BAND_MAP_COLORS.low).toBe("#047857");
    expect(STRESS_BAND_MAP_COLORS.moderate).toBe("#b45309");
    expect(STRESS_BAND_MAP_COLORS.high).toBe("#c2410c");
    expect(STRESS_BAND_MAP_COLORS.very_high).toBe("#b91c1c");

    const asHex = ([r, g, b]: [number, number, number]) =>
      `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
    for (const band of ["low", "moderate", "high", "very_high"] as const) {
      expect(STRESS_BAND_MAP_COLORS[band]).toBe(asHex(STRESS_BAND_PDF_COLORS[band]));
    }
  });

  it("keeps the no-report grey outside the stress ramp, so missing data never reads as a good result", () => {
    expect(Object.values(STRESS_BAND_MAP_COLORS)).not.toContain(NO_REPORT_MAP_COLOR);
  });
});

describe("buildVillageMapData", () => {
  const geometryByBoundaryId = new Map<string, GeoJSON.Geometry>([
    ["boundary-a", square(76.9, 16.2)],
    ["boundary-b", square(77.0, 16.3)],
  ]);

  it("maps a village using its latest report's existing band and score", () => {
    const { entries } = buildVillageMapData({
      catchments: [catchment({ id: "c-a", name: "Maski", admin_boundary_id: "boundary-a" })],
      geometryByBoundaryId,
      historyByCatchmentId: new Map([["c-a", [report({ stressBand: "very_high", stressScore: 81, confidence: 72 })]]]),
    });

    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      catchmentId: "c-a",
      name: "Maski",
      band: "very_high",
      stressScore: 81,
      confidence: 72,
      storageChangeBand: "normal",
    });
  });

  it("marks a monitored village with no report as band null — grey, never a low-stress green", () => {
    const { entries } = buildVillageMapData({
      catchments: [catchment({ id: "c-a", name: "Maski", admin_boundary_id: "boundary-a" })],
      geometryByBoundaryId,
      historyByCatchmentId: new Map([["c-a", []]]),
    });

    expect(entries[0].band).toBeNull();
    expect(entries[0].stressScore).toBeNull();
    expect(entries[0].lastGeneratedAt).toBeNull();
    expect(entries[0].topRecommendation.category).toBe("needs_first_report");
  });

  it("reports freehand catchments as unmappable rather than guessing a location for them", () => {
    const freehand = catchment({ id: "c-draw", name: "Hand-drawn area", admin_boundary_id: null });
    const { entries, unmappable } = buildVillageMapData({
      catchments: [freehand],
      geometryByBoundaryId,
      historyByCatchmentId: new Map(),
    });

    expect(entries).toHaveLength(0);
    expect(unmappable).toEqual([freehand]);
  });

  it("omits a village whose geometry has not arrived yet, without calling it unmappable", () => {
    const { entries, unmappable } = buildVillageMapData({
      catchments: [catchment({ id: "c-z", name: "Pending", admin_boundary_id: "boundary-not-loaded" })],
      geometryByBoundaryId,
      historyByCatchmentId: new Map(),
    });

    expect(entries).toHaveLength(0);
    expect(unmappable).toHaveLength(0);
  });

  it("shows the highest-severity recommendation, matching the Priority Queue's own ordering", () => {
    // Low confidence (needs_validation, high) plus high stress
    // (needs_field_visit, medium) — the map must surface the same top
    // item the queue would rank this village by.
    const { entries } = buildVillageMapData({
      catchments: [catchment({ id: "c-a", name: "Maski", admin_boundary_id: "boundary-a" })],
      geometryByBoundaryId,
      historyByCatchmentId: new Map([["c-a", [report({ stressBand: "high", stressScore: 70, confidence: 30 })]]]),
    });

    expect(entries[0].topRecommendation.severity).toBe("high");
    expect(entries[0].topRecommendation.category).toBe("needs_validation");
  });
});

describe("topRecommendationOf", () => {
  it("returns the worst-severity recommendation regardless of its position in the list", () => {
    const recommendations = [
      { category: "stable", severity: "info", title: "On track", why: "", evidence: "", confidence: "", action: "" },
      { category: "needs_field_visit", severity: "high", title: "Very high recharge stress", why: "", evidence: "", confidence: "", action: "" },
    ] as Parameters<typeof topRecommendationOf>[0];

    expect(topRecommendationOf(recommendations).title).toBe("Very high recharge stress");
  });
});

describe("toFeatureCollection", () => {
  const entries: VillageMapEntry[] = [
    {
      catchmentId: "c-a",
      name: "Maski",
      areaHa: 500,
      geometry: square(76.9, 16.2),
      band: "high",
      stressScore: 70,
      storageChangeBand: "below_normal",
      confidence: 80,
      lastGeneratedAt: "2026-07-20T00:00:00Z",
      topRecommendation: { category: "needs_field_visit", severity: "medium", title: "t", why: "", evidence: "", confidence: "", action: "" },
    },
    {
      catchmentId: "c-b",
      name: "Watagal",
      areaHa: 400,
      geometry: square(77.0, 16.3),
      band: null,
      stressScore: null,
      storageChangeBand: null,
      confidence: null,
      lastGeneratedAt: null,
      topRecommendation: { category: "needs_first_report", severity: "high", title: "t", why: "", evidence: "", confidence: "", action: "" },
    },
  ];

  it("emits one feature per village carrying the band the fill layer matches on", () => {
    const collection = toFeatureCollection(entries);
    expect(collection.features).toHaveLength(2);
    expect(collection.features[0].properties?.[BAND_PROPERTY]).toBe("high");
    expect(collection.features[0].properties?.[CATCHMENT_ID_PROPERTY]).toBe("c-a");
  });

  it("encodes a missing report as a matchable literal, since a GL expression cannot branch on null", () => {
    expect(toFeatureCollection(entries).features[1].properties?.[BAND_PROPERTY]).toBe(NO_REPORT_BAND_VALUE);
  });

  it("computes a bounding box spanning every village", () => {
    const bounds = entriesBounds(entries);
    expect(bounds).not.toBeNull();
    const [[minLon, minLat], [maxLon, maxLat]] = bounds!;
    expect(minLon).toBeCloseTo(76.89);
    expect(minLat).toBeCloseTo(16.19);
    expect(maxLon).toBeCloseTo(77.01);
    expect(maxLat).toBeCloseTo(16.31);
  });

  it("returns no bounds when there is nothing to fit", () => {
    expect(entriesBounds([])).toBeNull();
  });
});
