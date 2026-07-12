import { describe, expect, it } from "vitest";

import { isTerminalStatus, STATUS_COPY } from "./status-copy";
import { pollIntervalMs } from "./use-job-status";

describe("pollIntervalMs", () => {
  it("starts at 2s for the first poll", () => {
    expect(pollIntervalMs(0)).toBe(2000);
  });

  it("backs off exponentially (×1.5)", () => {
    expect(pollIntervalMs(1)).toBe(3000);
    expect(pollIntervalMs(2)).toBe(4500);
    expect(pollIntervalMs(3)).toBe(6750);
  });

  it("caps at 15s no matter how long the job runs", () => {
    expect(pollIntervalMs(10)).toBe(15000);
    expect(pollIntervalMs(100)).toBe(15000);
  });

  it("never returns a sub-second interval that would hammer the API", () => {
    for (let polls = 0; polls < 50; polls += 1) {
      expect(pollIntervalMs(polls)).toBeGreaterThanOrEqual(1000);
    }
  });
});

describe("status copy", () => {
  it("covers every job status the backend can return", () => {
    // The Record type enforces this at compile time; this guards against
    // a future cast weakening it.
    for (const status of ["pending", "running", "done", "failed"] as const) {
      expect(STATUS_COPY[status].title.length).toBeGreaterThan(0);
      expect(STATUS_COPY[status].detail.length).toBeGreaterThan(0);
    }
  });

  it("treats exactly done and failed as terminal", () => {
    expect(isTerminalStatus("pending")).toBe(false);
    expect(isTerminalStatus("running")).toBe(false);
    expect(isTerminalStatus("done")).toBe(true);
    expect(isTerminalStatus("failed")).toBe(true);
  });
});
