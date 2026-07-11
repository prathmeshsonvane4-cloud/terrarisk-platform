import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  // Next.js pins tsconfig "jsx": "preserve", which the test transformer
  // would otherwise honor and then fail to execute. This Vitest runs on
  // rolldown-vite (oxc transform), so the JSX override is the oxc option,
  // not the esbuild one.
  oxc: {
    jsx: { runtime: "automatic" },
  },
  test: {
    // Default: pure-logic tests (geo, formatting) in a plain node
    // environment. Integration tests that need a DOM opt in per-file via
    // the `// @vitest-environment jsdom` pragma.
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
