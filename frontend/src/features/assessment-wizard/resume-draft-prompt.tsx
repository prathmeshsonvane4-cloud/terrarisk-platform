"use client";

import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatArea } from "@/lib/format";
import { ringAreaHectares } from "@/lib/geo";

import type { AssessmentDraft } from "./draft-storage";

interface ResumeDraftPromptProps {
  draft: AssessmentDraft;
  onResume: () => void;
  onDiscard: () => void;
}

/**
 * P10 requirement 2 — an unfinished assessment is never silently
 * overwritten. Shown whenever the officer arrives at a fresh wizard visit
 * (not a session-expiry bounce-back, which auto-restores instead) and a
 * resumable draft already exists for them.
 */
export function ResumeDraftPrompt({ draft, onResume, onDiscard }: ResumeDraftPromptProps) {
  const previewAreaHa = draft.ring && draft.ring.length >= 3 ? ringAreaHectares(draft.ring) : null;
  const containerRef = useRef<HTMLDivElement>(null);

  // Accessibility: this decision gate replaces the whole page rather than
  // layering as a modal, so move focus to it explicitly on mount — a
  // screen-reader user should hear "Resume previous assessment?" the
  // moment it appears, not land wherever focus happened to already be.
  useEffect(() => {
    containerRef.current?.focus();
  }, []);

  return (
    <div ref={containerRef} tabIndex={-1} className="flex flex-1 items-center justify-center p-6 outline-none">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Resume previous assessment?</CardTitle>
          <CardDescription>
            You have an unfinished assessment from {new Date(draft.updatedAt).toLocaleString()}. Continue where you
            left off, or discard it and start fresh.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            {draft.village && (
              <>
                <dt className="text-muted-foreground">Village</dt>
                <dd className="font-medium">
                  {draft.village.name} — {draft.village.taluka}, {draft.village.district}
                </dd>
              </>
            )}
            {previewAreaHa !== null && (
              <>
                <dt className="text-muted-foreground">Boundary</dt>
                <dd className="font-medium tabular-nums">{formatArea(previewAreaHa)} drawn</dd>
              </>
            )}
            {draft.savedFarmId && (
              <>
                <dt className="text-muted-foreground">Farm</dt>
                <dd className="font-medium">Already saved — resuming will continue to report generation</dd>
              </>
            )}
          </dl>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button onClick={onResume} className="flex-1">
              Resume
            </Button>
            <Button variant="outline" onClick={onDiscard} className="flex-1">
              Discard and start fresh
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
