import { describe, expect, it } from "vitest";

import { extractApiErrorMessage, extractConflictingJobId } from "./errors";

describe("extractApiErrorMessage", () => {
  it("reads the message from the single error envelope", () => {
    expect(extractApiErrorMessage({ error: { code: 404, message: "Farm not found" } })).toBe(
      "Farm not found",
    );
  });

  it("still reads the message when extra fields ride alongside it (M2B P7 409)", () => {
    expect(
      extractApiErrorMessage({
        error: { code: 409, message: "A report is already being generated for this farm", job_id: "abc" },
      }),
    ).toBe("A report is already being generated for this farm");
  });

  it("falls back to a generic message for any other shape", () => {
    expect(extractApiErrorMessage(null)).toBe("Something went wrong. Please try again.");
    expect(extractApiErrorMessage({})).toBe("Something went wrong. Please try again.");
    expect(extractApiErrorMessage({ error: {} })).toBe("Something went wrong. Please try again.");
    expect(extractApiErrorMessage({ error: { message: 42 } })).toBe("Something went wrong. Please try again.");
  });
});

describe("extractConflictingJobId", () => {
  it("reads job_id from a 409 conflict envelope", () => {
    expect(
      extractConflictingJobId({
        error: { code: 409, message: "A report is already being generated for this farm", job_id: "abc-123" },
      }),
    ).toBe("abc-123");
  });

  it("returns null for a plain error with no job_id (every other status code)", () => {
    expect(extractConflictingJobId({ error: { code: 404, message: "Farm not found" } })).toBeNull();
  });

  it("returns null for any malformed or unexpected shape", () => {
    expect(extractConflictingJobId(null)).toBeNull();
    expect(extractConflictingJobId({})).toBeNull();
    expect(extractConflictingJobId({ error: { job_id: 12345 } })).toBeNull();
  });
});
