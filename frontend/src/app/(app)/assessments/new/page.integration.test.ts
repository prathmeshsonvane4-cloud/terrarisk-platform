// @vitest-environment jsdom
/**
 * Integration test for the P10 wizard's combined submit flow, against the
 * REAL running local stack (backend on :8000 + PostGIS): real login, real
 * village search (debounce and all), real POST /farms, real POST
 * /farms/{id}/reports over HTTP.
 *
 * Exactly one seam is mocked: FarmMap. A WebGL map cannot initialize in
 * jsdom (and headless panes deliver no animation frames — see
 * docs/DECISIONS.md, M2A P2/P3), so the mock exposes a button that fires
 * `onPolygonChange` with a real Killari-area ring — the same callback and
 * payload shape the real map produces. The canvas-drawing seam itself was
 * verified in a real browser during P2; the restore-onto-map seam (P10)
 * was verified live in a real browser, not here.
 *
 * P10 changed the golden path: the wizard now performs farm-creation AND
 * report-trigger as one combined action (Product Design v2 §7.2), so
 * there is no longer a "farm saved, report not yet triggered" pause point
 * to assert on directly. The proof of the full real chain (POST /farms ->
 * POST /farms/{id}/reports) is instead the navigation target itself: a
 * real job id can only come from a real POST /reports call, which can
 * only succeed against a real farm id from a real POST /farms call —
 * asserting on it verifies the whole chain, not just the first half.
 *
 * Written with React.createElement, not JSX — see the original P3 note
 * this carries forward (Next's "jsx": "preserve" vs. this Vitest's
 * rolldown-vite transform; @vitejs/plugin-react blocked by a Babel 7-vs-8
 * peer conflict via the shadcn CLI package).
 *
 * Skips cleanly when the local stack isn't running. Each run persists one
 * farm row and triggers one real (cheap, 202-only) Earth Engine job for
 * the test officer in the dev database/GEE project.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/features/auth/auth-context";
import { NavigationGuardProvider } from "@/features/navigation-guard/navigation-guard-context";
import type { Ring } from "@/lib/geo";

import NewAssessmentPage from "./page";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const TEST_OFFICER_EMAIL = process.env.TEST_OFFICER_EMAIL ?? "p3-e2e@example.com";
const TEST_OFFICER_PASSWORD = process.env.TEST_OFFICER_PASSWORD ?? "demo-password-123";

// A ~500m x ~330m field beside Killari's real centroid (~14 ha class,
// comfortably inside the 0.01–1000 ha plausibility bounds).
const KILLARI_FIELD_RING: Ring = [
  [76.592, 18.073],
  [76.5965, 18.073],
  [76.5965, 18.076],
  [76.592, 18.076],
];

interface MockFarmMapProps {
  onPolygonChange: (ring: Ring | null, complete: boolean) => void;
  locked?: boolean;
}

// The wizard calls useRouter() (navigation to the Run route); jsdom has no
// Next app router, so provide a stub. The navigation target is the test's
// primary assertion.
const routerPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: routerPush, prefetch: vi.fn() }),
}));

vi.mock("@/features/farm-drawing/farm-map", () => ({
  FarmMap: ({ onPolygonChange, locked }: MockFarmMapProps) =>
    createElement(
      "div",
      { "data-testid": "mock-farm-map", "data-locked": locked ? "true" : "false" },
      createElement(
        "button",
        { type: "button", onClick: () => onPolygonChange(KILLARI_FIELD_RING, true) },
        "mock: complete polygon",
      ),
    ),
}));

let stackAvailable = false;

beforeAll(async () => {
  try {
    const health = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(2000) });
    if (!health.ok) return;
    const login = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: TEST_OFFICER_EMAIL, password: TEST_OFFICER_PASSWORD }),
      signal: AbortSignal.timeout(5000),
    });
    if (!login.ok) return;
    const session = (await login.json()) as { access_token: string; role: string; full_name: string };
    window.localStorage.setItem(
      "terrarisk.session",
      JSON.stringify({ token: session.access_token, role: session.role, fullName: session.full_name }),
    );
    stackAvailable = true;
  } catch {
    stackAvailable = false;
  }
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderPage() {
  // Fresh QueryClient per render — no cross-test cache; retries off so a
  // real backend failure surfaces as the UI error state, not a hang.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const providers = (children: ReactNode) =>
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(AuthProvider, null, createElement(NavigationGuardProvider, null, children)),
    );
  return render(providers(createElement(NewAssessmentPage)));
}

describe("assessment wizard (real backend)", () => {
  it(
    "search -> select -> draw -> verify -> confirm triggers real POST /farms then POST /reports and routes to the run page",
    async (ctx) => {
      if (!stackAvailable) {
        ctx.skip();
        return;
      }
      const user = userEvent.setup();
      renderPage();

      // Real village search against the real endpoint (real 300ms debounce).
      await user.type(await screen.findByLabelText("Search village"), "Killari");
      const [killariResult] = await screen.findAllByText("Killari", { selector: "span" }, { timeout: 5000 });
      await user.click(killariResult);

      // Boundary step: the map seam fires the same callback the real map
      // fires on finish; the preview area renders and gates "Next".
      await user.click(await screen.findByText("mock: complete polygon"));
      const preview = await screen.findByText(/ha \(/);
      expect(preview.textContent).toMatch(/^1[0-9]\.\d{2} ha/);
      await user.click(screen.getByRole("button", { name: /next: verify/i }));

      // Verify step: the same preview, plus the combined confirm action.
      await screen.findByText("Confirm farm boundary");
      await user.click(screen.getByRole("button", { name: /confirm & generate report/i }));

      // The combined action: real POST /farms -> real POST
      // /farms/{id}/reports -> routes to the real job's Run page. A job id
      // here is only reachable through both real calls succeeding.
      await waitFor(
        () => {
          expect(routerPush).toHaveBeenCalledWith(expect.stringMatching(/^\/assessments\/[0-9a-f-]{36}$/));
        },
        { timeout: 15_000 },
      );

      // Map must be locked once submission begins — no post-submit geometry edits.
      expect(screen.getByTestId("mock-farm-map").getAttribute("data-locked")).toBe("true");
    },
    20_000,
  );
});
