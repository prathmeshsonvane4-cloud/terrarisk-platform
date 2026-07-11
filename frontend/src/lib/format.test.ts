import { describe, expect, it } from "vitest";

import { formatArea } from "./format";

describe("formatArea", () => {
  it("shows hectares as the primary unit with acres alongside", () => {
    expect(formatArea(1)).toBe("1.00 ha (2.5 acres)");
  });

  it("handles a realistic smallholder farm size", () => {
    expect(formatArea(2.51)).toBe("2.51 ha (6.2 acres)");
  });

  it("handles zero", () => {
    expect(formatArea(0)).toBe("0.00 ha (0.0 acres)");
  });
});
