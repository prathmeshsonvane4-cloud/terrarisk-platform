import { afterEach, describe, expect, it, vi } from "vitest";

import { generateFeatureId } from "./feature-id";

describe("generateFeatureId", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses crypto.randomUUID when available (secure contexts — https, or localhost)", () => {
    const spy = vi.spyOn(crypto, "randomUUID");
    const id = generateFeatureId();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(id).toBe(spy.mock.results[0]?.value);
  });

  it("falls back to a crypto.getRandomValues-based UUID v4 when randomUUID is absent — the exact production condition (plain HTTP, not localhost)", () => {
    const original = crypto.randomUUID;
    // @ts-expect-error - simulating an insecure context, where this
    // property is not present on the Crypto prototype at all.
    delete crypto.randomUUID;

    try {
      const id = generateFeatureId();
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    } finally {
      crypto.randomUUID = original;
    }
  });

  it("falls back when crypto.randomUUID exists but throws (NotSupportedError-style behaviour)", () => {
    const original = crypto.randomUUID;
    crypto.randomUUID = () => {
      throw new DOMException("randomUUID is only supported in secure contexts", "NotSupportedError");
    };

    try {
      const id = generateFeatureId();
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    } finally {
      crypto.randomUUID = original;
    }
  });

  it("produces unique ids across repeated calls in the fallback path", () => {
    const original = crypto.randomUUID;
    // @ts-expect-error - see above
    delete crypto.randomUUID;

    try {
      const ids = new Set(Array.from({ length: 50 }, () => generateFeatureId()));
      expect(ids.size).toBe(50);
    } finally {
      crypto.randomUUID = original;
    }
  });
});
