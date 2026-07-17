import { getSessionUserId } from "@/features/auth/session";
import type { Village } from "@/features/farm-drawing/types";
import type { Ring } from "@/lib/geo";

/**
 * Persistent wizard draft (P10 requirement 1 — "refreshing the page must
 * restore everything automatically"). Scoped per officer (keyed by the
 * JWT `sub`) in localStorage so a shared branch machine can't leak one
 * officer's in-progress farm boundary into a colleague's session, and so
 * the draft survives a session expiry / re-login independently of the
 * session itself (P10 requirement 7).
 */
export type WizardStep = "village" | "boundary" | "verify" | "submit";

export const WIZARD_STEPS: readonly WizardStep[] = ["village", "boundary", "verify", "submit"];

export interface AssessmentDraft {
  step: WizardStep;
  village: Village | null;
  ring: Ring | null;
  /** Set once the combined create-farm-and-trigger-report submit has
   * created the farm — kept even if the report-trigger half then fails,
   * so a resume never re-creates a duplicate farm for the same boundary. */
  savedFarmId: string | null;
  savedFarmAreaHa: number | null;
  /** Set once a report has actually been triggered for savedFarmId — a
   * resume with this present routes straight to the Run page instead of
   * re-rendering the wizard (job recovery, P10 requirement 5). */
  triggeredJobId: string | null;
  /** True only when the session-expiry flow interrupted this draft — lets
   * the wizard auto-restore without a Resume/Discard prompt for that one
   * specific case, since the officer didn't choose to leave (P10
   * requirement 7). Consumed (cleared) the moment it's read. */
  interruptedBySessionExpiry: boolean;
  updatedAt: string;
}

const STORAGE_PREFIX = "terrarisk.assessment-draft.";

const EMPTY_DRAFT: Omit<AssessmentDraft, "updatedAt"> = {
  step: "village",
  village: null,
  ring: null,
  savedFarmId: null,
  savedFarmAreaHa: null,
  triggeredJobId: null,
  interruptedBySessionExpiry: false,
};

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

export function loadDraft(): AssessmentDraft | null {
  if (typeof window === "undefined") return null;
  const userId = getSessionUserId();
  if (!userId) return null;
  const raw = window.localStorage.getItem(storageKey(userId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AssessmentDraft;
  } catch {
    return null;
  }
}

/** Merges `patch` onto whatever draft currently exists (or a blank one)
 * and persists it — every wizard state change (village pick, boundary
 * draw, step advance) calls this with just the fields that changed. */
export function saveDraft(patch: Partial<Omit<AssessmentDraft, "updatedAt">>): AssessmentDraft {
  if (typeof window === "undefined") return { ...EMPTY_DRAFT, ...patch, updatedAt: new Date().toISOString() };
  const userId = getSessionUserId();
  const current = loadDraft() ?? EMPTY_DRAFT;
  const next: AssessmentDraft = { ...current, ...patch, updatedAt: new Date().toISOString() };
  if (userId) {
    window.localStorage.setItem(storageKey(userId), JSON.stringify(next));
  }
  return next;
}

export function clearDraft(): void {
  if (typeof window === "undefined") return;
  const userId = getSessionUserId();
  if (!userId) return;
  window.localStorage.removeItem(storageKey(userId));
}

/** Whether a draft has anything actually worth resuming — an untouched
 * fresh draft (nothing picked, nothing drawn) isn't worth a prompt. */
export function isDraftResumable(draft: AssessmentDraft | null): draft is AssessmentDraft {
  return !!draft && (draft.village !== null || draft.ring !== null);
}

/** Called by the session-expiry provider immediately before it clears the
 * session (P10 requirement 7) — flags the current officer's draft, if any,
 * as interrupted rather than abandoned. */
export function markDraftInterruptedBySessionExpiry(): void {
  const draft = loadDraft();
  if (!isDraftResumable(draft)) return;
  saveDraft({ ...draft, interruptedBySessionExpiry: true });
}

/** Reads and clears the interrupted flag in one step — the wizard calls
 * this once on mount to decide whether to auto-restore silently (true) or
 * show the normal Resume/Discard prompt (false). */
export function takeInterruptedFlag(draft: AssessmentDraft): boolean {
  if (!draft.interruptedBySessionExpiry) return false;
  saveDraft({ interruptedBySessionExpiry: false });
  return true;
}
