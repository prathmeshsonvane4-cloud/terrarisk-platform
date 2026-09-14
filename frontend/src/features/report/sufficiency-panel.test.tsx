// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { components } from "@/lib/api/schema";

import { SufficiencyPanel } from "./sufficiency-panel";

type ReportResponse = components["schemas"]["ReportResponse"];

afterEach(cleanup);

function report(overrides: Partial<ReportResponse> = {}): ReportResponse {
  return {
    model_confidence: {
      factors_computed: 1,
      factors_total: 4,
      weight_coverage: 0.25,
      overall_estimable: false,
      overall_interval: null,
      interval_coverage: "none",
      confidence_level: 0.9,
      statement: "1 of 4 factors computed (25% of the configured weight).",
    },
    decision_sufficiency: {
      policy_version: "sufficiency-v1",
      calibration_status: "uncalibrated",
      statement: "The evidence is sufficient for low-stakes decisions only. Not sufficient for medium, high.",
      caveats: [{ code: "rainfall_regional", statement: "Rainfall is the value of a CHIRPS cell.", factor: null }],
      tiers: [
        { tier: "low", sufficient: true, description: "Small, reversible.", inadequacies: [] },
        {
          tier: "medium",
          sufficient: false,
          description: "A typical limit.",
          inadequacies: [{ code: "stale_optical", statement: "The latest usable optical reading is from March.", factor: null }],
        },
        {
          tier: "high",
          sufficient: false,
          description: "A term loan.",
          inadequacies: [{ code: "no_validated_evidence", statement: "No input has been validated.", factor: null }],
        },
      ],
    },
    ...overrides,
  } as ReportResponse;
}

describe("SufficiencyPanel", () => {
  it("shows model confidence and evidence sufficiency as separate sections", () => {
    render(<SufficiencyPanel report={report()} />);
    expect(screen.getByRole("heading", { name: "Model confidence" })).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Evidence sufficiency" })).not.toBeNull();
    expect(screen.getByText(/1 of 4 factors computed/)).not.toBeNull();
  });

  it("states the verdict per tier, with every reason it falls short", () => {
    render(<SufficiencyPanel report={report()} />);
    expect(screen.getAllByText("Sufficient")).toHaveLength(1);
    expect(screen.getAllByText("Not sufficient")).toHaveLength(2);
    expect(screen.getByText("The latest usable optical reading is from March.")).not.toBeNull();
    expect(screen.getByText("No input has been validated.")).not.toBeNull();
  });

  it("says the policy is uncalibrated", () => {
    render(<SufficiencyPanel report={report()} />);
    expect(screen.getByText(/sufficiency-v1, uncalibrated/)).not.toBeNull();
  });

  it("says when an assessment predates these fields instead of silently hiding the panel", () => {
    render(<SufficiencyPanel report={report({ model_confidence: null, decision_sufficiency: null })} />);
    expect(screen.getByText(/Not recorded for this assessment/)).not.toBeNull();
  });
});
