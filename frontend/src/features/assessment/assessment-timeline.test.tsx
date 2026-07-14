// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/schema";

import { AssessmentTimeline } from "./assessment-timeline";

type ProgressStage = components["schemas"]["ProgressStage"];

function stage(overrides: Partial<ProgressStage> & Pick<ProgressStage, "id" | "title" | "status">): ProgressStage {
  return {
    started_at: null,
    completed_at: null,
    metadata: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("AssessmentTimeline", () => {
  it("renders every stage's title, in the order given", () => {
    render(
      <AssessmentTimeline
        stages={[
          stage({ id: "preparing", title: "Preparing assessment", status: "done" }),
          stage({ id: "loading_geometry", title: "Loading farm geometry", status: "pending" }),
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("Preparing assessment");
    expect(items[1].textContent).toContain("Loading farm geometry");
  });

  it("labels a cache-restored stage honestly, not as a generic 'processing'", () => {
    render(
      <AssessmentTimeline
        stages={[
          stage({
            id: "vegetation_observations",
            title: "Retrieving vegetation observations (Sentinel-2 NDVI)",
            status: "done",
            started_at: "2026-07-14T02:32:37.289903+00:00",
            completed_at: "2026-07-14T02:32:37.315020+00:00",
            metadata: { source: "cache", months: 34 },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/restored from cache \(34 months\)/)).not.toBeNull();
  });

  it("labels a freshly fetched stage distinctly from a cached one", () => {
    render(
      <AssessmentTimeline
        stages={[
          stage({
            id: "rainfall_observations",
            title: "Retrieving rainfall observations (CHIRPS)",
            status: "done",
            started_at: "2026-07-14T02:32:37.0Z",
            completed_at: "2026-07-14T02:32:37.8Z",
            metadata: { source: "fetched", months: 35 },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/retrieved \(35 months\)/)).not.toBeNull();
    expect(screen.queryByText(/restored from cache/)).toBeNull();
  });

  it("shows a real elapsed duration for a stage with no cache metadata", () => {
    render(
      <AssessmentTimeline
        stages={[
          stage({
            id: "scoring",
            title: "Calculating climate risk factors and composite score",
            status: "done",
            started_at: "2026-07-14T02:32:40.000Z",
            completed_at: "2026-07-14T02:32:40.040Z",
          }),
        ]}
      />,
    );
    expect(screen.getByText("0.0s")).not.toBeNull();
  });

  it("shows nothing for a pending stage — never a fake percentage or ETA", () => {
    render(<AssessmentTimeline stages={[stage({ id: "saving", title: "Saving report", status: "pending" })]} />);
    const item = screen.getByRole("listitem");
    expect(item.textContent).not.toContain("%");
    expect(item.textContent).toBe("Saving report");
  });

  it("ticks a live elapsed counter for the running stage from its real started_at", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-14T02:32:40.000Z"));

    render(
      <AssessmentTimeline
        stages={[
          stage({
            id: "rainfall_climatology",
            title: "Retrieving 30-year rainfall normal",
            status: "running",
            started_at: "2026-07-14T02:32:38.000Z",
          }),
        ]}
      />,
    );
    expect(screen.getByText("2.0s…")).not.toBeNull();

    // 5s further — the ticking interval must fire and re-render with a
    // freshly computed elapsed time, not a value frozen at first render.
    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    expect(screen.getByText("7.0s…")).not.toBeNull();
  });

  it("marks a failed stage distinctly, without inventing a fake success state", () => {
    render(
      <AssessmentTimeline
        stages={[
          stage({
            id: "rainfall_observations",
            title: "Retrieving rainfall observations (CHIRPS)",
            status: "failed",
            started_at: "2026-07-14T02:32:37.0Z",
            completed_at: "2026-07-14T02:32:38.0Z",
          }),
        ]}
      />,
    );
    const title = screen.getByText("Retrieving rainfall observations (CHIRPS)");
    expect(title.className).toContain("text-destructive");
  });
});
