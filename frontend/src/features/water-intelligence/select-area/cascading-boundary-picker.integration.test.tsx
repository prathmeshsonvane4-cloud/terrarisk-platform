// @vitest-environment jsdom
/**
 * Integration test for the Select Area cascading picker, against the REAL
 * running local stack (backend on :8000 + PostGIS) — real login, real GET
 * /admin-boundaries calls at every level, no mocked network layer. Same
 * "real backend, skip cleanly if unavailable" pattern as
 * app/(app)/assessments/new/page.integration.test.ts.
 *
 * Requires the real Maharashtra/Latur and Karnataka/Raichur data loaded
 * by scripts/load_admin_boundaries.py (docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md
 * Part 4/7) — asserts against Karnataka -> Raichur -> Manvi specifically,
 * since that chain only exists once the real Raichur import has run.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { CascadingBoundaryPicker } from "./cascading-boundary-picker";
import type { AdminBoundarySummary } from "./use-admin-boundary-children";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const TEST_OFFICER_EMAIL = process.env.TEST_OFFICER_EMAIL ?? "p3-e2e@example.com";
const TEST_OFFICER_PASSWORD = process.env.TEST_OFFICER_PASSWORD ?? "demo-password-123";

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

function renderPicker(onVillageSelect: (village: AdminBoundarySummary | null) => void) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const providers = (children: ReactNode) => createElement(QueryClientProvider, { client: queryClient }, children);
  return render(providers(createElement(CascadingBoundaryPicker, { onVillageSelect })));
}

describe("CascadingBoundaryPicker (real backend)", () => {
  it(
    "cascades State -> District -> Taluka -> Village through real /admin-boundaries data, resetting descendants on every change",
    async (ctx) => {
      if (!stackAvailable) {
        ctx.skip();
        return;
      }
      const user = userEvent.setup();
      const onVillageSelect = vi.fn();
      renderPicker(onVillageSelect);

      // Districts are disabled until a state is chosen.
      const districtSelect = (await screen.findByLabelText("District")) as HTMLSelectElement;
      expect(districtSelect.disabled).toBe(true);

      const stateSelect = (await screen.findByLabelText("State")) as HTMLSelectElement;
      await waitFor(() => screen.getByText("Karnataka"));
      await user.selectOptions(stateSelect, "Karnataka");

      await waitFor(() => expect(districtSelect.disabled).toBe(false));
      await user.selectOptions(districtSelect, "Raichur");

      const talukaSelect = screen.getByLabelText("Taluka") as HTMLSelectElement;
      await waitFor(() => expect(talukaSelect.disabled).toBe(false));
      await waitFor(() => screen.getByText("Manvi"));
      await user.selectOptions(talukaSelect, "Manvi");

      // Village is a searchable combobox, not a <select> — Manvi has 73
      // real villages and Devadurga 185, which is why this one level
      // filters as you type rather than listing everything at once.
      const villageInput = screen.getByLabelText("Village") as HTMLInputElement;
      await waitFor(() => expect(villageInput.disabled).toBe(false));

      // Typing filters the list down to matching villages only.
      await user.click(villageInput);
      await user.type(villageInput, "a");
      const options = await screen.findAllByRole("option");
      expect(options.length).toBeGreaterThan(0);
      for (const option of options) {
        expect(option.textContent?.toLowerCase()).toContain("a");
      }

      const chosenName = options[0].textContent ?? "";
      await user.click(options[0]);

      expect(onVillageSelect).toHaveBeenCalledWith(
        expect.objectContaining({ name: chosenName, level: "village" }),
      );

      // Changing the state resets every level below it back to disabled.
      await user.selectOptions(stateSelect, "Maharashtra");
      expect(districtSelect.value).toBe("");
      await waitFor(() => expect(talukaSelect.disabled).toBe(true));
      await waitFor(() => expect(villageInput.disabled).toBe(true));
      expect(onVillageSelect).toHaveBeenLastCalledWith(null);
    },
    20_000,
  );
});
