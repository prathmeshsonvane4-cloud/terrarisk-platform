import { describe, expect, it } from "vitest";

import { ApiError, classifyError, extractApiErrorMessage, extractConflictingJobId } from "./errors";

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
/**
 * 401 and 403 shared one family, so a role-permission refusal rendered
 * as "Session no longer valid" — sending the user to sign in again,
 * which reproduces the same 403. These pin them apart.
 */
describe("classifyError", () => {
  it("treats an expired session as an auth failure", () => {
    expect(classifyError(new ApiError("Not authenticated", 401))).toBe("auth");
  });

  it("treats a wrong-role refusal as forbidden, not an auth failure", () => {
    expect(classifyError(new ApiError("Insufficient role for this operation", 403))).toBe("forbidden");
  });

  it("keeps the other families unchanged", () => {
    expect(classifyError(new ApiError("Not found", 404))).toBe("not-found");
    expect(classifyError(new ApiError("Boom", 500))).toBe("server");
    expect(classifyError(new TypeError("Failed to fetch"))).toBe("network");
  });
});
