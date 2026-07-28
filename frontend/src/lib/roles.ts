import type { components } from "@/lib/api/schema";

export type UserRole = components["schemas"]["UserRole"];

export const ROLE_LABELS: Record<UserRole, string> = {
  credit_officer: "Credit Officer",
  branch_manager: "Branch Manager",
  risk_officer: "Risk Officer",
  ceo: "CEO",
  chairman: "Chairman",
  // Water Intelligence's own roles (Blueprint v2 D8) — generic roles for
  // non-bank customers, distinct from Service 1's bank roles above.
  programme_officer: "Programme Officer",
  programme_admin: "Programme Admin",
};

// Used only to decide whether the Catchments nav item should render
// (components/workspace/app-shell.tsx) — the real access boundary is
// still the backend's require_role() gate on every catchment endpoint
// (README.md: "the guard is a UX convenience, not the actual
// access-control boundary").
const WATER_INTELLIGENCE_ROLES: ReadonlySet<UserRole> = new Set(["programme_officer", "programme_admin"]);

export function isWaterIntelligenceRole(role: string): boolean {
  return WATER_INTELLIGENCE_ROLES.has(role as UserRole);
}
