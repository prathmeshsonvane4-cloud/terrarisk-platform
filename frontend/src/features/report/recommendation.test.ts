import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/schema";

import type { FactorScore } from "./drivers";
import { buildRecommendation, NO_OVERALL_SCORE_ACTION, RECOMMENDATION_CONFIDENCE_THRESHOLD } from "./recommendation";

type ReportResponse = components["schemas"]["ReportResponse"];

function factor(
  name: FactorScore["factor"],
  value: number,
  band: FactorScore["band"],
  raw: Record<string, unknown> = {},
): FactorScore {
  return { factor: name, value, band, computed: true, raw_inputs: raw };
}

function report(overrides: Partial<ReportResponse> = {}): ReportResponse {
  return {
    id: "r1",
    farm_id: "f1",
    farm_area_ha: 2.5,
    village_id: "v1",
    overall_score: 62,
    overall_band: "high",
    confidence: 90,
    model_version: "rule-engine-v1",
    computed_at: "2026-07-14T12:00:00Z",
    factors: [
      factor("vegetation_stability", 30, "low"),
      factor("water_availability", 55, "moderate"),
      factor("drought_risk", 62, "high", { vci: 41, rainfall_ratio_to_normal: 0.87 }),
      factor("flood_exposure", 88, "very_high", { jrc_water_occurrence_percent: 40, rainfall_ratio_to_normal: 0.87 }),
    ],
    farm: {
      geometry: { type: "Polygon", coordinates: [] },
      village_name: "Killari",
      taluka_name: "Ausa",
      district_name: "Latur",
      officer_name: "Test Officer",
    },
    series: { ndvi: [], mndwi: [], ndmi: [], rainfall: [] },
    evidence: { observation_window_start: null, observation_window_end: null, expected_months: null },
    method: {
      weights_version_id: "w1",
      weights: {},
      weights_effective_from: "2026-01-01T00:00:00Z",
      floor_threshold: 80,
      weighted_average_score: 62,
    },
    ...overrides,
  } as unknown as ReportResponse;
}

describe("buildRecommendation", () => {
  it("reuses the pinned narrative as the summary, never a second description", () => {
    const rec = buildRecommendation(report());
    expect(rec.summary).toContain("high overall climate risk (score 62/100)");
  });

  it("lists only High and Very High factors as primary drivers, worst first", () => {
    const rec = buildRecommendation(report());
    expect(rec.primaryDrivers.map((d) => d.factor)).toEqual(["flood_exposure", "drought_risk"]);
    expect(rec.primaryDrivers[0].value).toBe(88);
  });

  it("returns an empty driver list when nothing scored High or Very High — never padded", () => {
    const allModerate = report({
      factors: [
        factor("vegetation_stability", 30, "low"),
        factor("water_availability", 40, "moderate"),
        factor("drought_risk", 45, "moderate"),
        factor("flood_exposure", 20, "low"),
      ],
    });
    expect(buildRecommendation(allModerate).primaryDrivers).toEqual([]);
  });

  it("maps each band to its fixed, deterministic action posture", () => {
    expect(buildRecommendation(report({ overall_band: "low", confidence: 95 })).action).toContain(
      "Standard appraisal. No climate-driven escalation",
    );
    expect(buildRecommendation(report({ overall_band: "moderate", confidence: 95 })).action).toContain(
      "Standard appraisal. Note the leading risk factor",
    );
    expect(buildRecommendation(report({ overall_band: "high", confidence: 95 })).action).toContain(
      "Escalate to branch-manager review",
    );
    expect(buildRecommendation(report({ overall_band: "very_high", confidence: 95 })).action).toContain(
      "Refer to branch manager",
    );
  });

  it("adds the indicative-only qualifier only below the confidence threshold", () => {
    const confident = buildRecommendation(report({ confidence: RECOMMENDATION_CONFIDENCE_THRESHOLD }));
    expect(confident.isIndicativeOnly).toBe(false);
    expect(confident.action).not.toContain("Indicative only");

    const sparse = buildRecommendation(report({ confidence: RECOMMENDATION_CONFIDENCE_THRESHOLD - 1 }));
    expect(sparse.isIndicativeOnly).toBe(true);
    expect(sparse.action).toContain("Indicative only — limited satellite data available (data completeness 69%)");
  });

  it("never invents advice beyond the fixed template — action is always one of the four postures", () => {
    const rec = buildRecommendation(report({ overall_band: "very_high", confidence: 50 }));
    expect(rec.action).toContain("Refer to branch manager. Recommend independent field verification");
  });
});


describe("an assessment with no overall score (rule-engine-v2)", () => {
  it("gives no band posture and says not to rely on the report", () => {
    const recommendation = buildRecommendation(report({ overall_score: null, overall_band: null }));
    expect(recommendation.action).toBe(NO_OVERALL_SCORE_ACTION);
    expect(recommendation.isIndicativeOnly).toBe(true);
    expect(recommendation.summary).toContain("No overall climate risk score could be estimated");
  });

  it("never lists an uncomputed factor as a primary driver", () => {
    const base = report();
    const uncomputed = report({
      factors: base.factors.map((f) => ({ ...f, value: null, band: null, computed: false })),
    });
    expect(buildRecommendation(uncomputed).primaryDrivers).toEqual([]);
  });
});
