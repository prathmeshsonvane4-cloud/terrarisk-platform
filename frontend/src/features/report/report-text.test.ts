import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/schema";

import { factorDriverText, type FactorScore } from "./drivers";
import { reportNarrative } from "./narrative";

type ReportResponse = components["schemas"]["ReportResponse"];

function factor(
  name: FactorScore["factor"],
  value: number,
  raw: Record<string, unknown>,
): FactorScore {
  return { factor: name, value, band: "moderate", computed: true, raw_inputs: raw };
}

const FULL_FACTORS: FactorScore[] = [
  factor("vegetation_stability", 30, { current_ndvi: 0.42, ndvi_percentile: 70, history_months: 34 }),
  factor("water_availability", 55, {
    mndwi_current: -0.31,
    ndmi_current: 0.12,
    rainfall_ratio_to_normal: 0.87,
  }),
  factor("drought_risk", 62, { vci: 41, rainfall_ratio_to_normal: 0.87 }),
  factor("flood_exposure", 12, { jrc_water_occurrence_percent: 1.4, rainfall_ratio_to_normal: 0.87 }),
];

describe("factorDriverText", () => {
  it("states real numbers from raw_inputs, no invented causes", () => {
    expect(factorDriverText(FULL_FACTORS[0])).toBe(
      "Current NDVI 0.42 sits at the 70th percentile of the same calendar month across the baseline years.",
    );
    expect(factorDriverText(FULL_FACTORS[2])).toContain("Vegetation Condition Index at 41");
    expect(factorDriverText(FULL_FACTORS[2])).toContain("87% of the seasonal normal");
    expect(factorDriverText(FULL_FACTORS[3])).toContain("1.4% (JRC satellite record, 1984–2021)");
  });

  it("uses correct ordinal suffixes for the NDVI percentile", () => {
    const at = (p: number) =>
      factorDriverText(factor("vegetation_stability", 30, { current_ndvi: 0.17, ndvi_percentile: p }));
    expect(at(31)).toContain("31st percentile");
    expect(at(42)).toContain("42nd percentile");
    expect(at(53)).toContain("53rd percentile");
    expect(at(11)).toContain("11th percentile");
    expect(at(12)).toContain("12th percentile");
  });

  it("degrades honestly when raw inputs are missing (sparse data)", () => {
    const sparse = factor("vegetation_stability", 50, {
      current_ndvi: null,
      ndvi_percentile: null,
      history_months: 0,
    });
    expect(factorDriverText(sparse)).toContain("neutral score of 50 was applied by the previous engine version");
  });

  it("mentions only the sub-signals actually present", () => {
    const rainfallOnly = factor("drought_risk", 40, { vci: null, rainfall_ratio_to_normal: 1.1 });
    const text = factorDriverText(rainfallOnly);
    expect(text).not.toContain("Vegetation Condition Index");
    expect(text).toContain("110% of the seasonal normal");
  });
});

describe("reportNarrative", () => {
  const report = {
    id: "r1",
    farm_id: "f1",
    farm_area_ha: 2.5,
    village_id: "v1",
    overall_score: 47.2,
    overall_band: "moderate",
    confidence: 94.4,
    model_version: "rule-engine-v1",
    computed_at: "2026-07-11T12:00:00Z",
    factors: FULL_FACTORS,
    farm: {
      geometry: { type: "Polygon", coordinates: [] },
      village_name: "Killari",
      taluka_name: "Ausa",
      district_name: "Latur",
      officer_name: "Test Officer",
    },
    series: { ndvi: [], mndwi: [], ndmi: [], rainfall: [] },
  } as unknown as ReportResponse;

  it("summarizes strictly from engine outputs", () => {
    const text = reportNarrative(report);
    expect(text).toContain("moderate overall climate risk (score 47/100)");
    expect(text).toContain("highest-scoring factor is drought risk at 62/100");
    expect(text).toContain("recent seasonal rainfall was 87% of the long-term normal");
    expect(text).toContain("Flood exposure scores lowest at 12/100");
    expect(text).toContain("Data completeness is 94%");
  });

  it("omits the rainfall clause when the engine had no ratio", () => {
    const noRatio = {
      ...report,
      factors: report.factors.map((f) => ({ ...f, raw_inputs: { ...f.raw_inputs, rainfall_ratio_to_normal: null } })),
    } as ReportResponse;
    expect(reportNarrative(noRatio)).not.toContain("long-term normal");
  });
});
