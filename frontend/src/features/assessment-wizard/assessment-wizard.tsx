"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmPanel } from "@/features/farm-drawing/confirm-panel";
import { FarmMap } from "@/features/farm-drawing/farm-map";
import type { Village } from "@/features/farm-drawing/types";
import { useCreateFarm } from "@/features/farm-drawing/use-create-farm";
import { VillageSearch } from "@/features/farm-drawing/village-search";
import { useUnsavedWorkGuard } from "@/features/navigation-guard/use-unsaved-work-guard";
import { ReportTriggerConflictError, useTriggerReport } from "@/features/report/use-trigger-report";
import { formatArea } from "@/lib/format";
import { farmAreaBoundsIssue, ringAreaHectares, toFarmGeometry, type Ring } from "@/lib/geo";

import type { AssessmentDraft, WizardStep } from "./draft-storage";
import { WIZARD_STEPS, clearDraft, saveDraft } from "./draft-storage";
import { Stepper } from "./stepper";

interface DrawnPolygon {
  ring: Ring;
  complete: boolean;
}

type SubmitPhase = "idle" | "saving-farm" | "starting-analysis" | "error";

const STEP_HEADING: Record<WizardStep, string> = {
  village: "Step 1: Search for the village",
  boundary: "Step 2: Draw the farm boundary",
  verify: "Step 3: Verify the boundary",
  submit: "Step 4: Submit",
};

interface AssessmentWizardProps {
  /** Non-null when resuming — either the officer chose Resume, or the
   * session-expiry flow auto-restored (P10 requirements 1, 2, 7). Null for
   * a genuinely fresh assessment. */
  initialDraft: AssessmentDraft | null;
}

/**
 * The production wizard (P10 requirement 3), replacing the old single-page
 * conditional-panel flow. Village -> Boundary -> Verify -> Submit, matching
 * Product Design v2 §7.2. The map stays the persistent dominant region
 * across all four steps (§7.2: "two persistent regions: map + step
 * panel"); only the side panel's content changes per step. Submit performs
 * farm-creation and report-trigger as one combined action (§7.2's explicit
 * "today: two separate UI moments" gap being closed here), then hands off
 * to the existing, unmodified `/assessments/{jobId}` Run page.
 */
export function AssessmentWizard({ initialDraft }: AssessmentWizardProps) {
  const router = useRouter();
  const createFarm = useCreateFarm();
  const triggerReport = useTriggerReport();

  const [step, setStep] = useState<WizardStep>(initialDraft?.step ?? "village");
  const [selectedVillage, setSelectedVillage] = useState<Village | null>(initialDraft?.village ?? null);
  const [polygon, setPolygon] = useState<DrawnPolygon | null>(
    initialDraft?.ring ? { ring: initialDraft.ring, complete: true } : null,
  );
  const [clearSignal, setClearSignal] = useState(0);
  const [savedFarmId, setSavedFarmId] = useState<string | null>(initialDraft?.savedFarmId ?? null);
  const [savedFarmAreaHa, setSavedFarmAreaHa] = useState<number | null>(initialDraft?.savedFarmAreaHa ?? null);
  const [submitPhase, setSubmitPhase] = useState<SubmitPhase>("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const stepHeadingRef = useRef<HTMLHeadingElement>(null);
  // Reentrancy guard for the combined submit action (P10 requirement 10 —
  // prevent duplicate API requests): a ref, not state, because two rapid
  // click events can both invoke the handler before React commits the
  // `step`/`submitPhase` state change that would otherwise unmount the
  // button — state read inside the same tick would still see the stale
  // "idle" value in both invocations. This is checked synchronously before
  // either mutation ever starts.
  const isSubmittingRef = useRef(false);

  // Accessibility (P10 requirement 9): move focus to the new step's
  // heading on every step change, so a screen-reader user gets an
  // announcement of where they landed instead of focus silently staying
  // on a button that's no longer in the new panel.
  useEffect(() => {
    stepHeadingRef.current?.focus();
  }, [step]);

  const areaHectares = useMemo(
    () => (polygon && polygon.ring.length >= 3 ? ringAreaHectares(polygon.ring) : null),
    [polygon],
  );
  const boundsIssue = useMemo(
    () => (areaHectares !== null ? farmAreaBoundsIssue(areaHectares) : null),
    [areaHectares],
  );

  // P10 requirement 1: every meaningful state change persists to the
  // per-officer draft immediately — a refresh or browser restart replays
  // this exact state on the next visit. Deliberately keyed on
  // `polygon?.complete` (not the ring array's identity, which changes on
  // every drag frame while actively drawing) — an in-progress, unclosed
  // ring is ephemeral interaction state, not a boundary worth restoring;
  // only a finished boundary is persisted.
  useEffect(() => {
    saveDraft({
      step,
      village: selectedVillage,
      ring: polygon?.complete ? polygon.ring : null,
      savedFarmId,
      savedFarmAreaHa,
      triggeredJobId: null,
    });
  }, [step, selectedVillage, polygon?.complete, polygon?.ring, savedFarmId, savedFarmAreaHa]);

  // P10 requirement 4: warn before leaving only once there's a real drawn
  // boundary and the assessment hasn't been submitted yet.
  useUnsavedWorkGuard(polygon?.complete === true && submitPhase !== "starting-analysis" && savedFarmId === null);

  const handlePolygonChange = useCallback((ring: Ring | null, complete: boolean) => {
    setPolygon(ring ? { ring, complete } : null);
  }, []);

  function handleVillageSelect(village: Village) {
    setSelectedVillage(village);
    setPolygon(null);
    setSavedFarmId(null);
    setSavedFarmAreaHa(null);
    setSubmitPhase("idle");
    setSubmitError(null);
    setStep("boundary");
  }

  async function handleConfirmAndGenerate() {
    if (isSubmittingRef.current) return;
    if (!selectedVillage || !polygon?.complete || boundsIssue) return;
    isSubmittingRef.current = true;
    setStep("submit");
    setSubmitError(null);

    try {
      let farmId = savedFarmId;
      let farmAreaHa = savedFarmAreaHa;

      if (!farmId) {
        setSubmitPhase("saving-farm");
        const farm = await createFarm.mutateAsync({
          villageId: selectedVillage.id,
          geometry: toFarmGeometry(polygon.ring),
        });
        farmId = farm.id;
        farmAreaHa = farm.area_ha;
        setSavedFarmId(farmId);
        setSavedFarmAreaHa(farmAreaHa);
        // Persisted immediately (not just via the effect above) so a crash
        // in the split-second before the effect commits still can't create
        // a duplicate farm on resume (P10 requirement 5 — never duplicate
        // jobs; the farm itself is the same guarantee one level earlier).
        saveDraft({ savedFarmId: farmId, savedFarmAreaHa: farmAreaHa, step: "submit" });
      }

      setSubmitPhase("starting-analysis");
      const trigger = await triggerReport.mutateAsync(farmId);
      saveDraft({ triggeredJobId: trigger.job_id });
      router.push(`/assessments/${trigger.job_id}`);
    } catch (err) {
      if (err instanceof ReportTriggerConflictError) {
        // Job recovery (P10 requirement 5): another run is already in
        // flight for this farm — reconnect to it, never create a second.
        saveDraft({ triggeredJobId: err.jobId });
        router.push(`/assessments/${err.jobId}`);
        return;
      }
      setSubmitPhase("error");
      setSubmitError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      // Released unconditionally — including on the success/conflict paths
      // above, which `return` before reaching here — so a genuine Retry
      // click after a failure is never permanently locked out.
      isSubmittingRef.current = false;
    }
  }

  function handleStepSelect(target: WizardStep) {
    if (submitPhase !== "idle") return;
    setStep(target);
  }

  function handleDiscardAndRestart() {
    clearDraft();
    createFarm.reset();
    triggerReport.reset();
    setSelectedVillage(null);
    setPolygon(null);
    setSavedFarmId(null);
    setSavedFarmAreaHa(null);
    setSubmitPhase("idle");
    setSubmitError(null);
    setStep("village");
    setClearSignal((signal) => signal + 1);
  }

  const maxReachableIndex = submitPhase === "idle" ? WIZARD_STEPS.length : -1;
  const mapLocked = submitPhase !== "idle" || savedFarmId !== null;

  return (
    <div className="flex flex-1 flex-col">
      <div className="border-b p-3 md:px-6">
        <Stepper currentStep={step} maxReachableIndex={maxReachableIndex} onStepSelect={handleStepSelect} />
      </div>

      <div className="flex flex-1 flex-col md:flex-row">
        <aside className="flex w-full flex-col gap-4 border-b p-4 md:w-80 md:overflow-y-auto md:border-r md:border-b-0">
          <h2 ref={stepHeadingRef} tabIndex={-1} className="text-sm font-semibold outline-none">
            {STEP_HEADING[step]}
          </h2>

          {step === "village" && (
            <>
              <VillageSearch onSelect={handleVillageSelect} />
              {selectedVillage && (
                <div className="rounded-lg border p-3 text-sm">
                  <p className="text-xs text-muted-foreground">Selected village</p>
                  <p className="font-medium">{selectedVillage.name}</p>
                  <p className="text-muted-foreground">
                    {selectedVillage.taluka}, {selectedVillage.district}
                  </p>
                  <Button size="sm" className="mt-3 w-full" onClick={() => setStep("boundary")}>
                    Next: draw boundary
                  </Button>
                </div>
              )}
            </>
          )}

          {step === "boundary" && selectedVillage && (
            <div className="flex flex-col gap-3">
              <div className="rounded-lg border p-3 text-sm">
                <p className="text-xs text-muted-foreground">Village</p>
                <p className="font-medium">{selectedVillage.name}</p>
              </div>

              {areaHectares === null && (
                <p className="text-xs text-muted-foreground">
                  Draw the farm boundary on the map — trace around the field, click the first point again to
                  finish. Self-intersecting boundaries are rejected while drawing.
                </p>
              )}

              {areaHectares !== null && (
                <div className="rounded-lg border p-3 text-sm">
                  <p className="text-xs text-muted-foreground">
                    {polygon?.complete ? "Boundary area (preview)" : "Drawing…"}
                  </p>
                  <p className="font-medium tabular-nums">{formatArea(areaHectares)}</p>
                  {boundsIssue && (
                    <p role="alert" className="mt-1 text-xs text-destructive">
                      {boundsIssue}
                    </p>
                  )}
                </div>
              )}

              <Button
                size="sm"
                onClick={() => setStep("verify")}
                disabled={!polygon?.complete || areaHectares === null || boundsIssue !== null}
              >
                Next: verify
              </Button>
            </div>
          )}

          {step === "verify" && selectedVillage && areaHectares !== null && (
            <ConfirmPanel
              village={selectedVillage}
              previewAreaHectares={areaHectares}
              blockedReason={boundsIssue}
              isPending={false}
              errorMessage={null}
              onSubmit={handleConfirmAndGenerate}
            />
          )}

          {step === "submit" && selectedVillage && (
            <div className="flex flex-col gap-3 rounded-lg border p-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Village</p>
                <p className="font-medium">{selectedVillage.name}</p>
              </div>

              {savedFarmAreaHa !== null && (
                <div>
                  <p className="text-xs text-muted-foreground">Recorded area (server-computed)</p>
                  <p className="text-base font-medium tabular-nums">{formatArea(savedFarmAreaHa)}</p>
                </div>
              )}

              <p aria-live="polite" className="text-sm">
                {submitPhase === "saving-farm" && "Saving farm boundary…"}
                {submitPhase === "starting-analysis" && "Starting climate analysis…"}
                {submitPhase === "error" && "Something went wrong."}
              </p>

              {submitPhase === "error" && (
                <>
                  {submitError && (
                    <p role="alert" className="text-xs text-destructive">
                      {submitError}
                    </p>
                  )}
                  <Button onClick={handleConfirmAndGenerate}>
                    {savedFarmId ? "Retry — start analysis" : "Retry — save farm & start analysis"}
                  </Button>
                </>
              )}
            </div>
          )}

          {(selectedVillage || polygon) && step !== "submit" && (
            <Button variant="outline" size="sm" onClick={handleDiscardAndRestart} className="mt-auto">
              Discard and start over
            </Button>
          )}
        </aside>

        <FarmMap
          village={selectedVillage}
          hasPolygon={polygon !== null && polygon.complete}
          onPolygonChange={handlePolygonChange}
          locked={mapLocked}
          clearSignal={clearSignal}
          restoreRing={initialDraft?.ring ?? null}
          className="relative min-h-[55vh] flex-1 md:min-h-0"
        />
      </div>
    </div>
  );
}
