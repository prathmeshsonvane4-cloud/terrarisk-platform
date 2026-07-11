import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    // Pure-logic tests only (geo, formatting) — no DOM environment needed.
    // Component/browser behavior is covered by manual E2E per the M2A
    // testing strategy; add jsdom here only if that changes.
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
