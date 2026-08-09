// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { WaterBalanceAssumptions } from "./balance-assumptions";

afterEach(() => {
  cleanup();
});

/**
 * These assertions are about WHICH caveat a reader sees, not about
 * wording. The component's whole reason to exist is that a village
 * boundary and a DEM watershed cannot carry the same closed-catchment
 * caveat, so the branch between them is the behaviour worth pinning.
 */
describe("WaterBalanceAssumptions", () => {
  it("warns that water crosses a boundary that was not delineated from terrain", () => {
    render(
      <WaterBalanceAssumptions
        closedCatchmentAssumed
        calibrationStatus="uncalibrated"
        delineationMethod="manual"
      />,
    );

    expect(screen.getByText(/not delineated from terrain/i)).toBeTruthy();
    expect(screen.getByText(/water does cross it/i)).toBeTruthy();
  });

  it("calls the closed assumption standard for a DEM-delineated watershed", () => {
    render(
      <WaterBalanceAssumptions
        closedCatchmentAssumed
        calibrationStatus="uncalibrated"
        delineationMethod="auto_dem"
      />,
    );

    expect(screen.getByText(/standard simplification/i)).toBeTruthy();
    expect(screen.queryByText(/not delineated from terrain/i)).toBeNull();
  });

  it("states the uncalibrated caveat alongside the closed-catchment one", () => {
    render(
      <WaterBalanceAssumptions
        closedCatchmentAssumed
        calibrationStatus="uncalibrated"
        delineationMethod="manual"
      />,
    );

    expect(screen.getByText(/not been checked against|no observed streamflow/i)).toBeTruthy();
  });

  // Renders nothing rather than an "assumptions: none" reassurance —
  // same reasoning as ResolutionFlagNotice's empty case.
  it("renders nothing when no assumption applies", () => {
    const { container } = render(
      <WaterBalanceAssumptions
        closedCatchmentAssumed={false}
        calibrationStatus="calibrated"
        delineationMethod="auto_dem"
      />,
    );

    expect(container.firstChild).toBeNull();
  });
});
