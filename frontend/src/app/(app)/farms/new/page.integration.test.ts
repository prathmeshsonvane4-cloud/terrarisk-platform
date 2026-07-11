// @vitest-environment jsdom
/**
 * Integration test for the P3 confirm-and-save flow, against the REAL
 * running local stack (backend on :8000 + PostGIS): real login, real
 * village search (debounce and all), real POST /farms over HTTP, real
 * server-computed area rendered in the saved panel.
 *
 * Exactly one seam is mocked: FarmMap. A WebGL map cannot initialize in
 * jsdom (and headless panes deliver no animation frames — see
 * docs/DECISIONS.md, M2A P2/P3), so the mock exposes a button that fires
 * `onPolygonChange` with a real Killari-area ring — the same callback and
 * payload shape the real map produces. The canvas-drawing seam itself was
 * verified in a real browser during P2.
 *
 * Written with React.createElement, not JSX: Next.js pins tsconfig
 * "jsx": "preserve", which Vitest's transformer executes literally, and
 * the available JSX plugin (@vitejs/plugin-react) is blocked by a Babel
 * 7-vs-8 peer conflict via the shadcn CLI package. createElement avoids
 * the transform entirely at the cost of slightly denser test code.
 *
 * Skips cleanly (like the backend suite's PostGIS-gated tests) when the
 * local stack isn't running. Each run persists one farm row for the test
 * officer in the dev database.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/features/auth/auth-context";
import type { Ring } from "@/lib/geo";

import NewFarmPage from "./page";

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

afterEach(cleanup);

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
      createElement(AuthProvider, null, children),
    );
  return render(providers(createElement(NewFarmPage)));
}

describe("farm creation flow (real backend)", () => {
  it("search -> select -> polygon -> confirm -> POST /farms -> saved panel shows server area", async (ctx) => {
    if (!stackAvailable) {
      ctx.skip();
      return;
    }
    const user = userEvent.setup();
    renderPage();

    // Real village search against the real endpoint (real 300ms debounce).
    await user.type(screen.getByLabelText("Search village"), "Killari");
    const [killariResult] = await screen.findAllByText("Killari", { selector: "span" }, { timeout: 5000 });
    await user.click(killariResult);

    // The map seam: fire the same callback the real map fires on finish.
    await user.click(screen.getByText("mock: complete polygon"));

    // Confirm panel: preview area present and plausible (~14.7 ha class).
    await screen.findByText("Confirm farm boundary");
    const preview = await screen.findByText(/ha \(/);
    expect(preview.textContent).toMatch(/^1[0-9]\.\d{2} ha/);

    // The accountability click -> real POST /farms.
    await user.click(screen.getByRole("button", { name: /confirm area & save farm/i }));

    // Saved panel renders the SERVER's recorded area (the source of truth).
    await screen.findByText("Farm saved", undefined, { timeout: 10000 });
    const recorded = await screen.findByText(/ha \(/);
    expect(recorded.textContent).toMatch(/^1[0-9]\.\d{2} ha/);

    // Map must be locked after the save — no post-save geometry edits.
    expect(screen.getByTestId("mock-farm-map").getAttribute("data-locked")).toBe("true");

    // And the workflow is restartable.
    await user.click(screen.getByRole("button", { name: /draw another farm/i }));
    expect(screen.queryByText("Farm saved")).toBeNull();
  });
});
