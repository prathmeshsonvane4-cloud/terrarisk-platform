import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Production bug found on a real deployed server: MapLibre GL's own
// stylesheet sets `.maplibregl-map { position: relative }`, which can win
// over Tailwind's `absolute inset-0` utility (passed by every BaseMap
// consumer to make the map fill its parent) depending on stylesheet import
// order -- an order that differs between `next dev` and the production
// Turbopack build. See globals.css's own comment for the full story.
//
// jsdom does not apply real CSS cascade/specificity rules from imported
// stylesheets, so this can't be a true rendering assertion (the same
// "GL canvas contents aren't directly assertable" limitation this
// codebase already documents for MapLibre elsewhere) -- what it *can*
// catch is someone removing the fix's override rule without realizing
// why it exists.
describe("globals.css — MapLibre position override", () => {
  it("keeps .maplibregl-map pinned to position: absolute regardless of import order", () => {
    const cssPath = join(dirname(fileURLToPath(import.meta.url)), "globals.css");
    // Strip /* ... */ comments first — this file's own explanatory comment
    // quotes ".maplibregl-map { position: relative }" (MapLibre's rule,
    // being described, not asserted), which would otherwise false-match.
    const css = readFileSync(cssPath, "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

    const ruleMatch = css.match(/\.maplibregl-map\s*\{([^}]*)\}/);
    expect(ruleMatch, ".maplibregl-map override rule must exist in globals.css").not.toBeNull();

    const ruleBody = ruleMatch![1];
    expect(ruleBody).toMatch(/position:\s*absolute\s*!important/);
    expect(ruleBody).toMatch(/inset:\s*0\s*!important/);
  });
});
