import type { components } from "@/lib/api/schema";

export type UserRole = components["schemas"]["UserRole"];

export const ROLE_LABELS: Record<UserRole, string> = {
  credit_officer: "Credit Officer",
  branch_manager: "Branch Manager",
  risk_officer: "Risk Officer",
  ceo: "CEO",
  chairman: "Chairman",
};
