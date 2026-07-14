// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { components } from "@/lib/api/schema";

import { MethodTab } from "./method-tab";

type ReportResponse = components["schemas"]["ReportResponse"];
type FactorScore = components["schemas"]["FactorScoreResponse"];

function factor(name: FactorScore["factor"], value: number, band: FactorScore["band"]): FactorScore {
  return { factor: name, value, band, raw_inputs: {} };
}

function report(overrides: Partial<ReportResponse> = {}): ReportResponse {
  return {
    id: "r1",
    farm_id: "f1",
    farm_area_ha: 2.5,
    village_id: "v1",
    overall_score: 49,
    overall_band: "moderate",
    confidence: 92,
    model_version: "rule-engine-v1",
    computed_at: "2026-07-14T12:00:00Z",
    factors: [
      factor("drought_risk", 61, "high"),
      factor("water_availability", 60, "high"),
      factor("vegetation_stability", 70, "high"),
      factor("flood_exposure", 6, "low"),
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
      weights_version_id: "742d7e0b-636a-4273-a198-d00c68d1ea07",
      weights: {
        drought_risk: 0.25,
        water_availability: 0.25,
        vegetation_stability: 0.25,
        flood_exposure: 0.25,
      },
      weights_effective_from: "2026-07-11T03:09:58Z",
      floor_threshold: 80,
      weighted_average_score: 49,
    },
    ...overrides,
  } as unknown as ReportResponse;
}

afterEach(cleanup);

describe("MethodTab", () => {
  it("shows only the composite score, no floor-rule box, when the floor rule never fired", () => {
    render(<MethodTab report={report()} />);
    expect(screen.queryByText("Floor rule applied")).toBeNull();
    expect(screen.queryByText(/Weighted average \(before the floor rule\)/)).toBeNull();
    expect(screen.getByText(/49 \/ 100 — Moderate risk/)).not.toBeNull();
  });

  it("shows the floor-rule explanation when weighted_average_score differs from overall_score", () => {
    render(
      <MethodTab
        report={report({
          overall_score: 62,
          overall_band: "high",
          method: {
            weights_version_id: "742d7e0b-636a-4273-a198-d00c68d1ea07",
            weights: {
              drought_risk: 0.25,
              water_availability: 0.25,
              vegetation_stability: 0.25,
              flood_exposure: 0.25,
            },
            weights_effective_from: "2026-07-11T03:09:58Z",
            floor_threshold: 80,
            weighted_average_score: 45.2, // below the 50.01 High-band floor the engine would have forced
          },
        })}
      />,
    );
    expect(screen.getByText("Floor rule applied")).not.toBeNull();
    expect(screen.getByText(/Weighted average \(before the floor rule\)/)).not.toBeNull();
    expect(screen.getByText("45.2 / 100")).not.toBeNull();
    expect(screen.getByText(/62 \/ 100 — High risk/)).not.toBeNull();
  });

  it("renders the exact band-threshold cutoffs mirrored from the engine", () => {
    render(<MethodTab report={report()} />);
    expect(screen.getByText("0 – 25")).not.toBeNull();
    expect(screen.getByText("25.01 – 50")).not.toBeNull();
    expect(screen.getByText("50.01 – 75")).not.toBeNull();
    expect(screen.getByText("75.01 – 100")).not.toBeNull();
  });
});
