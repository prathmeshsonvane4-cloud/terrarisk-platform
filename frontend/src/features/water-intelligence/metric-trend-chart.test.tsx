// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MetricTrendChart, type TrendPoint } from "./metric-trend-chart";

afterEach(() => {
  cleanup();
});

describe("MetricTrendChart", () => {
  it("shows an honest empty state with fewer than two real points, never a fabricated single-point line", () => {
    const points: TrendPoint[] = [{ generatedAt: "2026-07-01T00:00:00Z", value: 42 }];
    render(<MetricTrendChart points={points} color="#8b5cf6" ariaLabel="Stress score over time" />);

    expect(screen.getByText(/Not enough history yet/)).not.toBeNull();
    expect(screen.queryByRole("img", { name: "Stress score over time" })).toBeNull();
  });

  it("shows an honest empty state when every point is null (no usable data yet)", () => {
    const points: TrendPoint[] = [
      { generatedAt: "2026-06-01T00:00:00Z", value: null },
      { generatedAt: "2026-07-01T00:00:00Z", value: null },
    ];
    render(<MetricTrendChart points={points} color="#8b5cf6" ariaLabel="Stress score over time" />);

    expect(screen.getByText(/Not enough history yet/)).not.toBeNull();
  });

  it("renders the chart once at least two real runs exist", () => {
    const points: TrendPoint[] = [
      { generatedAt: "2026-06-01T00:00:00Z", value: 30 },
      { generatedAt: "2026-07-01T00:00:00Z", value: 55 },
    ];
    render(<MetricTrendChart points={points} color="#8b5cf6" ariaLabel="Stress score over time" />);

    expect(screen.queryByText(/Not enough history yet/)).toBeNull();
    expect(screen.getByRole("img", { name: "Stress score over time" })).not.toBeNull();
  });
});
