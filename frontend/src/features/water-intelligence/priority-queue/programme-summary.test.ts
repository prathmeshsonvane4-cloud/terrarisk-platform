import { describe, expect, it } from "vitest";

import type { WaterReportHistoryItem } from "../use-water-report-history";
import { programmeSummaryCounts, summarizeMonthOverMonth } from "./programme-summary";
import type { Recommendation } from "./recommendations";

function stubItem(generatedAt: string, stressScore: number): WaterReportHistoryItem {
  return {
    generated_at: generatedAt,
    water_balance: {
      id: "wb",
      period_start: "2026-01-01",
      period_end: "2026-07-01",
      rainfall_mm: 500,
      et_mm: 200,
      runoff_mm: 100,
      storage_change_mm: 50,
      storage_change_band: "normal",
      data_completeness: 90,
      calibration_status: "uncalibrated",
      closed_catchment_assumed: true,
      resolution_flags: [],
      model_version: "v1",
      computed_at: generatedAt,
    },
    recharge_stress: {
      id: "rs",
      stress_score: stressScore,
      stress_band: "moderate",
      baseline_window: "climatology_30yr",
      rainfall_anomaly_ratio: 1.0,
      vci: 50,
      surface_water_trend: 50,
      cgwb_category: null,
      cgwb_category_as_of: null,
      raw_inputs: { confidence: 90 },
      computed_at: generatedAt,
    },
  };
}

function rec(category: Recommendation["category"]): Recommendation {
  return { category, severity: "medium", title: "t", why: "w", evidence: "e", confidence: "c", action: "a" };
}

describe("programmeSummaryCounts", () => {
  it("counts a catchment once per category, even with multiple recommendations in the same category", () => {
    const counts = programmeSummaryCounts([
      [rec("needs_field_visit"), rec("needs_validation")],
      [rec("needs_field_visit")],
      [rec("stable")],
    ]);
    expect(counts.needs_field_visit).toBe(2);
    expect(counts.needs_validation).toBe(1);
    expect(counts.stable).toBe(1);
    expect(counts.declining_trend).toBe(0);
  });
});

describe("summarizeMonthOverMonth", () => {
  it("counts a catchment as improved when this month's stress is lower than last month's", () => {
    const histories = [[stubItem("2026-07-15T00:00:00Z", 30), stubItem("2026-06-10T00:00:00Z", 60)]];
    expect(summarizeMonthOverMonth(histories)).toEqual({ comparableCatchments: 1, improved: 1, declined: 0, unchanged: 0 });
  });

  it("counts a catchment as declined when this month's stress is higher than last month's", () => {
    const histories = [[stubItem("2026-07-15T00:00:00Z", 70), stubItem("2026-06-10T00:00:00Z", 40)]];
    expect(summarizeMonthOverMonth(histories)).toEqual({ comparableCatchments: 1, improved: 0, declined: 1, unchanged: 0 });
  });

  it("never invents a monthly comparison when every run for a catchment falls in the same calendar month", () => {
    const histories = [[stubItem("2026-07-20T00:00:00Z", 50), stubItem("2026-07-05T00:00:00Z", 45)]];
    expect(summarizeMonthOverMonth(histories)).toEqual({ comparableCatchments: 0, improved: 0, declined: 0, unchanged: 0 });
  });

  it("skips catchments with no history at all", () => {
    expect(summarizeMonthOverMonth([[]])).toEqual({ comparableCatchments: 0, improved: 0, declined: 0, unchanged: 0 });
  });

  it("finds the nearest different-month entry, not just the second item, when the second item is same-month", () => {
    const histories = [
      [
        stubItem("2026-07-20T00:00:00Z", 20), // latest, July
        stubItem("2026-07-05T00:00:00Z", 25), // also July — must be skipped
        stubItem("2026-06-10T00:00:00Z", 80), // June — the real comparison point
      ],
    ];
    expect(summarizeMonthOverMonth(histories)).toEqual({ comparableCatchments: 1, improved: 1, declined: 0, unchanged: 0 });
  });
});
