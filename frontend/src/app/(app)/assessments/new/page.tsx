"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { AssessmentWizard } from "@/features/assessment-wizard/assessment-wizard";
import {
  clearDraft,
  isDraftResumable,
  loadDraft,
  takeInterruptedFlag,
  type AssessmentDraft,
} from "@/features/assessment-wizard/draft-storage";
import { ResumeDraftPrompt } from "@/features/assessment-wizard/resume-draft-prompt";

type Gate =
  | { kind: "checking" }
  | { kind: "prompt"; draft: AssessmentDraft }
  | { kind: "ready"; draft: AssessmentDraft | null };

/**
 * P10 requirements 1, 2, 5, 7: on mount, decides whether to show a fresh
 * wizard, silently auto-restore an interrupted-by-session-expiry draft, or
 * ask the officer to Resume/Discard. A draft that already has a
 * triggered report routes straight to the existing Run page instead of
 * ever rendering the wizard (job recovery — never re-create a running
 * assessment).
 */
export default function NewAssessmentPage() {
  const router = useRouter();
  const routerRef = useRef(router);
  routerRef.current = router;
  const [gate, setGate] = useState<Gate>({ kind: "checking" });
  // React StrictMode double-invokes effects in development to surface
  // exactly this class of bug: `takeInterruptedFlag` below is a
  // read-and-clear side effect, not a pure read, so a naive `useEffect`
  // would consume the flag on its first (development-only) invocation and
  // find it already gone on the second — silently falling back to the
  // Resume/Discard prompt instead of the intended silent auto-restore.
  // This ref makes the check-and-consume genuinely run once per mount.
  const hasCheckedDraftRef = useRef(false);

  // Deliberately an empty dependency array: this is a mount-time check, run
  // exactly once, not something that should re-run if the router
  // reference ever changes — `routerRef` avoids needing `router` as a
  // dependency for the one imperative `.replace()` call inside.
  useEffect(() => {
    if (hasCheckedDraftRef.current) return;
    hasCheckedDraftRef.current = true;

    const draft = loadDraft();

    if (isDraftResumable(draft) && draft.triggeredJobId) {
      clearDraft();
      routerRef.current.replace(`/assessments/${draft.triggeredJobId}`);
      return;
    }

    if (!isDraftResumable(draft)) {
      setGate({ kind: "ready", draft: null });
      return;
    }

    if (takeInterruptedFlag(draft)) {
      setGate({ kind: "ready", draft });
    } else {
      setGate({ kind: "prompt", draft });
    }
  }, []);

  if (gate.kind === "checking") {
    return (
      <div role="status" aria-label="Checking for an unfinished assessment" className="flex flex-1 flex-col gap-3 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (gate.kind === "prompt") {
    return (
      <ResumeDraftPrompt
        draft={gate.draft}
        onResume={() => setGate({ kind: "ready", draft: gate.draft })}
        onDiscard={() => {
          clearDraft();
          setGate({ kind: "ready", draft: null });
        }}
      />
    );
  }

  return <AssessmentWizard initialDraft={gate.draft} />;
}
