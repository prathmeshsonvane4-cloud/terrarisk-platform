import { describe, expect, it } from "vitest";

import { formatDuration } from "./duration";

describe("formatDuration", () => {
  it("shows one decimal place under 10 seconds", () => {
    expect(formatDuration(800)).toBe("0.8s");
    expect(formatDuration(3_700)).toBe("3.7s");
  });

  it("shows whole seconds from 10s up to a minute", () => {
    expect(formatDuration(12_000)).toBe("12s");
    expect(formatDuration(59_000)).toBe("59s");
  });

  it("switches to minutes and seconds at 60s", () => {
    expect(formatDuration(60_000)).toBe("1m 0s");
    expect(formatDuration(72_000)).toBe("1m 12s");
    expect(formatDuration(185_000)).toBe("3m 5s");
  });

  it("never returns a negative duration for clock skew", () => {
    expect(formatDuration(-500)).toBe("0.0s");
  });
});
