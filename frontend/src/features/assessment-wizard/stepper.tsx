"use client";

import { CheckIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import { WIZARD_STEPS, type WizardStep } from "./draft-storage";

const STEP_LABELS: Record<WizardStep, string> = {
  village: "Village",
  boundary: "Boundary",
  verify: "Verify",
  submit: "Submit",
};

const STEPS = WIZARD_STEPS.map((id) => ({ id, label: STEP_LABELS[id] }));

interface StepperProps {
  currentStep: WizardStep;
  /** Steps at or before this index can be clicked to navigate back. Passed
   * explicitly (rather than derived from currentStep) so the wizard can
   * lock navigation once a submission is actually in flight. */
  maxReachableIndex: number;
  onStepSelect: (step: WizardStep) => void;
}

/**
 * Production wizard stepper (P10 requirement 3): each step visibly
 * Completed / Current / Upcoming, keyboard-navigable, and — for completed
 * steps only — clickable to go back and review/edit. Upcoming steps are
 * inert: each step's own validity gates advancing, never the stepper
 * itself.
 */
export function Stepper({ currentStep, maxReachableIndex, onStepSelect }: StepperProps) {
  const currentIndex = STEPS.findIndex((step) => step.id === currentStep);

  return (
    <nav aria-label="Assessment progress">
      <ol className="flex items-center gap-1.5 sm:gap-2">
        {STEPS.map((step, index) => {
          const status = index < currentIndex ? "completed" : index === currentIndex ? "current" : "upcoming";
          const isClickable = status === "completed" && index <= maxReachableIndex;

          return (
            <li key={step.id} className="flex flex-1 items-center gap-1.5 sm:gap-2">
              <button
                type="button"
                disabled={!isClickable}
                onClick={() => isClickable && onStepSelect(step.id)}
                aria-current={status === "current" ? "step" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  status === "current" && "font-medium text-foreground",
                  status === "completed" && "text-foreground",
                  status === "upcoming" && "text-muted-foreground",
                  isClickable && "cursor-pointer hover:bg-muted",
                  !isClickable && "cursor-default",
                )}
              >
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-medium",
                    status === "completed" && "bg-primary text-primary-foreground",
                    status === "current" && "border-2 border-primary text-primary",
                    status === "upcoming" && "border border-border text-muted-foreground",
                  )}
                  aria-hidden="true"
                >
                  {status === "completed" ? <CheckIcon className="size-3.5" /> : index + 1}
                </span>
                <span className="hidden sm:inline">{step.label}</span>
                <span className="sr-only sm:hidden">
                  {step.label} — {status}
                </span>
              </button>
              {index < STEPS.length - 1 && (
                <span aria-hidden="true" className={cn("h-px flex-1", status === "completed" ? "bg-primary" : "bg-border")} />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
