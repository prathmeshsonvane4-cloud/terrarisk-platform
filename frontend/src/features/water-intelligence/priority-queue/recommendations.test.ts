import { describe, expect, it } from "vitest";

import type { WaterReportHistoryItem } from "../use-water-report-history";
import { compareBySeverity, deriveRecommendations, highestSeverity } from "./recommendations";

let counter = 0;

function historyItem(overrides: {
  generatedAt: string;
  stressScore: number;
  stressBand?: WaterReportHistoryItem["recharge_stress"]["stress_band"];
  storageChangeMm?: number | null;
  storageChangeBand?: WaterReportHistoryItem["water_balance"]["storage_change_band"];
  dataCompleteness?: number;
  confidence?: number | null;
  resolutionFlags?: string[];
  rainfallStress?: number;
  vegetationStress?: number;
  surfaceWaterStress?: number;
  surfaceWaterTrend?: number;
  rainfallAnomalyRatio?: number;
  vci?: number;
}): WaterReportHistoryItem {
  counter += 1;
  return {
    generated_at: overrides.generatedAt,
    water_balance: {
      id: `wb-${counter}`,
      period_start: "2026-01-01",
      period_end: "2026-07-01",
      rainfall_mm: 500,
      et_mm: 200,
      runoff_mm: 100,
      storage_change_mm: overrides.storageChangeMm ?? 50,
      storage_change_band: overrides.storageChangeBand ?? "normal",
      data_completeness: overrides.dataCompleteness ?? 90,
      calibration_status: "uncalibrated",
      closed_catchment_assumed: true,
      resolution_flags: overrides.resolutionFlags ?? [],
      model_version: "water-balance-engine-v1",
      computed_at: overrides.generatedAt,
    },
    recharge_stress: {
      id: `rs-${counter}`,
      stress_score: overrides.stressScore,
      stress_band: overrides.stressBand ?? "moderate",
      baseline_window: "climatology_30yr",
      rainfall_anomaly_ratio: overrides.rainfallAnomalyRatio ?? 1.0,
      vci: overrides.vci ?? 50,
      surface_water_trend: overrides.surfaceWaterTrend ?? 50,
      cgwb_category: null,
      cgwb_category_as_of: null,
      raw_inputs: {
        confidence: overrides.confidence ?? 90,
        rainfall_stress: overrides.rainfallStress ?? 30,
        vegetation_stress: overrides.vegetationStress ?? 30,
        surface_water_stress: overrides.surfaceWaterStress ?? 30,
        weighted_average_score: overrides.stressScore,
      },
      computed_at: overrides.generatedAt,
    },
  };
}

describe("deriveRecommendations", () => {
  it("flags a catchment with no report at all, with severity high and no fabricated numbers", () => {
    const recommendations = deriveRecommendations([]);
    expect(recommendations).toHaveLength(1);
    expect(recommendations[0].category).toBe("needs_first_report");
    expect(recommendations[0].severity).toBe("high");
    expect(recommendations[0].action).toMatch(/trigger a water report/i);
  });

  it("flags very-high stress as needing a field visit, citing the dominant factor", () => {
    const history = [
      historyItem({
        generatedAt: "2026-07-01T00:00:00Z",
        stressScore: 85,
        stressBand: "very_high",
        surfaceWaterStress: 90,
        rainfallStress: 20,
        vegetationStress: 30,
        surfaceWaterTrend: 8,
      }),
    ];
    const recommendations = deriveRecommendations(history);
    const visit = recommendations.find((r) => r.category === "needs_field_visit");
    expect(visit).toBeDefined();
    expect(visit?.severity).toBe("high");
    expect(visit?.why).toMatch(/surface water/i);
    expect(visit?.evidence).toMatch(/8th percentile/i);
    expect(visit?.action).toMatch(/canal, tank, or pond/i);
  });

  it("uses correct English ordinal suffixes for the surface-water percentile — found via a real run reporting '3th percentile'", () => {
    const cases: [number, string][] = [
      [1, "1st"],
      [2, "2nd"],
      [3, "3rd"],
      [8, "8th"],
      [11, "11th"],
      [12, "12th"],
      [13, "13th"],
      [21, "21st"],
    ];
    for (const [percentile, expected] of cases) {
      const [recommendation] = deriveRecommendations([
        historyItem({
          generatedAt: "2026-07-01T00:00:00Z",
          stressScore: 85,
          stressBand: "very_high",
          surfaceWaterStress: 90,
          rainfallStress: 20,
          vegetationStress: 30,
          surfaceWaterTrend: percentile,
        }),
      ]);
      expect(recommendation.evidence).toContain(`${expected} percentile`);
    }
  });

  it("gives a rainfall-specific action when rainfall is the dominant stress factor", () => {
    const history = [
      historyItem({
        generatedAt: "2026-07-01T00:00:00Z",
        stressScore: 80,
        stressBand: "high",
        rainfallStress: 95,
        vegetationStress: 20,
        surfaceWaterStress: 20,
        rainfallAnomalyRatio: 0.4,
      }),
    ];
    const recommendations = deriveRecommendations(history);
    const visit = recommendations.find((r) => r.category === "needs_field_visit");
    expect(visit?.action).toMatch(/rain-gauge/i);
  });

  it("flags low data completeness and low confidence as needing validation, never silently", () => {
    const history = [
      historyItem({
        generatedAt: "2026-07-01T00:00:00Z",
        stressScore: 40,
        stressBand: "moderate",
        dataCompleteness: 30,
        confidence: 25,
        resolutionFlags: ["et_sub_pixel"],
      }),
    ];
    const recommendations = deriveRecommendations(history);
    const validation = recommendations.find((r) => r.category === "needs_validation");
    expect(validation).toBeDefined();
    expect(validation?.severity).toBe("high");
    expect(validation?.evidence).toMatch(/30%/);
    expect(validation?.evidence).toMatch(/et_sub_pixel/);
  });

  it("flags a sharp swing between the two most recent runs as unexpected behaviour", () => {
    const history = [
      historyItem({ generatedAt: "2026-07-15T00:00:00Z", stressScore: 75, stressBand: "high" }),
      historyItem({ generatedAt: "2026-06-15T00:00:00Z", stressScore: 30, stressBand: "low" }),
    ];
    const recommendations = deriveRecommendations(history);
    const unexpected = recommendations.find((r) => r.category === "unexpected_behaviour");
    expect(unexpected).toBeDefined();
    expect(unexpected?.why).toMatch(/30 to 75/);
    expect(unexpected?.why).toMatch(/\+45 points/);
  });

  it("does not flag unexpected behaviour for a small, ordinary run-over-run change", () => {
    const history = [
      historyItem({ generatedAt: "2026-07-15T00:00:00Z", stressScore: 42 }),
      historyItem({ generatedAt: "2026-06-15T00:00:00Z", stressScore: 38 }),
    ];
    const recommendations = deriveRecommendations(history);
    expect(recommendations.find((r) => r.category === "unexpected_behaviour")).toBeUndefined();
  });

  it("flags three consecutive declining storage-change runs as a sustained trend", () => {
    const history = [
      historyItem({ generatedAt: "2026-07-01T00:00:00Z", stressScore: 40, storageChangeMm: 10 }),
      historyItem({ generatedAt: "2026-06-01T00:00:00Z", stressScore: 38, storageChangeMm: 40 }),
      historyItem({ generatedAt: "2026-05-01T00:00:00Z", stressScore: 35, storageChangeMm: 90 }),
    ];
    const recommendations = deriveRecommendations(history);
    const declining = recommendations.find((r) => r.category === "declining_trend");
    expect(declining).toBeDefined();
    expect(declining?.why).toMatch(/90 -> 40 -> 10/);
  });

  it("does not flag a decline when the middle run is a real improvement, not monotonic", () => {
    const history = [
      historyItem({ generatedAt: "2026-07-01T00:00:00Z", stressScore: 40, storageChangeMm: 10 }),
      historyItem({ generatedAt: "2026-06-01T00:00:00Z", stressScore: 38, storageChangeMm: 90 }),
      historyItem({ generatedAt: "2026-05-01T00:00:00Z", stressScore: 35, storageChangeMm: 40 }),
    ];
    const recommendations = deriveRecommendations(history);
    expect(recommendations.find((r) => r.category === "declining_trend")).toBeUndefined();
  });

  it("returns exactly one 'stable' recommendation when nothing is flagged, never an empty list", () => {
    const history = [historyItem({ generatedAt: "2026-07-01T00:00:00Z", stressScore: 30, stressBand: "low" })];
    const recommendations = deriveRecommendations(history);
    expect(recommendations).toEqual([expect.objectContaining({ category: "stable", severity: "info" })]);
  });

  it("every recommendation has a non-empty why, evidence, confidence, and action — never a bare score", () => {
    const histories: WaterReportHistoryItem[][] = [
      [],
      [historyItem({ generatedAt: "2026-07-01T00:00:00Z", stressScore: 30, stressBand: "low" })],
      [historyItem({ generatedAt: "2026-07-01T00:00:00Z", stressScore: 90, stressBand: "very_high" })],
      [historyItem({ generatedAt: "2026-07-01T00:00:00Z", stressScore: 50, dataCompleteness: 10, confidence: 10 })],
    ];
    for (const history of histories) {
      for (const recommendation of deriveRecommendations(history)) {
        expect(recommendation.why.length).toBeGreaterThan(0);
        expect(recommendation.evidence.length).toBeGreaterThan(0);
        expect(recommendation.confidence.length).toBeGreaterThan(0);
        expect(recommendation.action.length).toBeGreaterThan(0);
      }
    }
  });
});

describe("highestSeverity / compareBySeverity", () => {
  it("ranks a catchment with any high-severity recommendation above one with only medium/info", () => {
    const highSeverity = deriveRecommendations([historyItem({ generatedAt: "2026-07-01T00:00:00Z", stressScore: 90, stressBand: "very_high" })]);
    const infoSeverity = deriveRecommendations([historyItem({ generatedAt: "2026-07-01T00:00:00Z", stressScore: 20, stressBand: "low" })]);

    expect(highestSeverity(highSeverity)).toBe("high");
    expect(highestSeverity(infoSeverity)).toBe("info");
    expect(compareBySeverity(highSeverity, infoSeverity)).toBeLessThan(0);
  });
});
