import { describe, expect, it } from "vitest";

import { activeHref } from "./app-shell";

// The nav hrefs as actually rendered, per role.
const WATER_INTELLIGENCE = ["/", "/catchments/map", "/catchments"];
const SERVICE_ONE = ["/", "/assessments", "/farms", "/reports"];

/**
 * Adding the Map nav item put a nested route ("/catchments/map") next to
 * its own parent ("/catchments"), which the previous prefix-match rule
 * would have highlighted simultaneously. These lock in the fix — and,
 * just as importantly, that Service 1's nav behaviour did not change as
 * collateral damage, since this is shared code every role renders.
 */
describe("activeHref", () => {
  it("highlights only the most specific match, not the parent as well", () => {
    expect(activeHref("/catchments/map", WATER_INTELLIGENCE)).toBe("/catchments/map");
  });

  it("still highlights Catchments on the list itself", () => {
    expect(activeHref("/catchments", WATER_INTELLIGENCE)).toBe("/catchments");
  });

  it("still highlights Catchments on a nested detail route that has no nav item of its own", () => {
    // The regression an "exact match" fix would have introduced.
    expect(activeHref("/catchments/abc-123", WATER_INTELLIGENCE)).toBe("/catchments");
    expect(activeHref("/catchments/abc-123/water-reports", WATER_INTELLIGENCE)).toBe("/catchments");
  });

  it("keeps the map highlighted when it carries a query-driven focus", () => {
    // Only the pathname reaches this function; the ?focus= param lives
    // outside it, so this must still resolve to the map item.
    expect(activeHref("/catchments/map", WATER_INTELLIGENCE)).toBe("/catchments/map");
  });

  it("treats Overview as exact, so it never matches every route", () => {
    expect(activeHref("/", WATER_INTELLIGENCE)).toBe("/");
    expect(activeHref("/catchments", WATER_INTELLIGENCE)).not.toBe("/");
  });

  it("leaves Service 1 nav behaviour unchanged", () => {
    expect(activeHref("/assessments", SERVICE_ONE)).toBe("/assessments");
    expect(activeHref("/assessments/new", SERVICE_ONE)).toBe("/assessments");
    expect(activeHref("/farms/xyz", SERVICE_ONE)).toBe("/farms");
    expect(activeHref("/reports/xyz", SERVICE_ONE)).toBe("/reports");
    expect(activeHref("/", SERVICE_ONE)).toBe("/");
  });

  it("returns null when nothing matches, rather than defaulting to a nav item", () => {
    expect(activeHref("/login", WATER_INTELLIGENCE)).toBeNull();
  });
});
