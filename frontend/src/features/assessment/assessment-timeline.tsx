"use client";

import { CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import type { components } from "@/lib/api/schema";
import { formatDuration } from "@/lib/duration";
import { cn } from "@/lib/utils";

type ProgressStage = components["schemas"]["ProgressStage"];

interface CacheMetadata {
  source?: "cache" | "fetched";
  months?: number;
}

/** Every stage id that persists observation series to satellite_observation
 * and therefore carries {source, months} metadata — see
 * app/services/reporting/progress.py. Stages outside this set (preparing,
 * loading_geometry, rainfall_climatology, water_history, scoring, saving,
 * completed) have no cache path and never carry this metadata shape. */
function cacheLabel(metadata: ProgressStage["metadata"]): string | null {
  const meta = metadata as CacheMetadata | null;
  if (!meta?.source) return null;
  const monthsSuffix = meta.months ? ` (${meta.months} months)` : "";
  return meta.source === "cache" ? `restored from cache${monthsSuffix}` : `retrieved${monthsSuffix}`;
}

/** The trailing descriptor for one stage row — never a percentage, never
 * an ETA, only real timestamps (Product Design v2 P2). A running stage
 * shows a live-ticking elapsed count derived from its real started_at;
 * a completed stage shows either its cache/fetch provenance (more
 * informative) or its real duration; a pending stage shows nothing. */
function trailingLabel(stage: ProgressStage, now: number): string | null {
  if (stage.status === "pending") return null;

  if (stage.status === "running") {
    const startedAtMs = stage.started_at ? new Date(stage.started_at).getTime() : now;
    return `${formatDuration(now - startedAtMs)}…`;
  }

  const cache = cacheLabel(stage.metadata);
  if (cache) return cache;

  if (stage.started_at && stage.completed_at) {
    const durationMs = new Date(stage.completed_at).getTime() - new Date(stage.started_at).getTime();
    return formatDuration(durationMs);
  }

  return null;
}

function completedAtClock(stage: ProgressStage): string | null {
  if (stage.status === "pending" || stage.status === "running" || !stage.completed_at) return null;
  return new Date(stage.completed_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/**
 * The vertical execution timeline (Product Design v2 §7.3 "Assessment
 * Run" — M2B P8). Every row is a direct, unmodified rendering of one
 * stage from the backend's `job.progress.stages` — this component
 * computes nothing about WHAT happened, only how to display real
 * timestamps it was given. A hard refresh remounts this component with
 * fresh data from the server poll; there is no client-only state here
 * that could drift from backend truth (the `now` tick is purely a
 * rendering aid for the currently-running stage's elapsed counter).
 */
export function AssessmentTimeline({ stages }: { stages: ProgressStage[] }) {
  const [now, setNow] = useState(() => Date.now());
  const hasRunningStage = stages.some((stage) => stage.status === "running");

  useEffect(() => {
    if (!hasRunningStage) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [hasRunningStage]);

  return (
    <ol className="flex flex-col">
      {stages.map((stage) => (
        <li key={stage.id} className="flex items-start gap-3 py-1.5">
          <span className="mt-0.5 shrink-0" aria-hidden>
            {stage.status === "done" && <CheckCircle2 className="size-4 text-emerald-600" />}
            {stage.status === "running" && <Loader2 className="size-4 animate-spin text-primary" />}
            {stage.status === "failed" && <XCircle className="size-4 text-destructive" />}
            {stage.status === "pending" && <CircleDashed className="size-4 text-muted-foreground/40" />}
          </span>
          <div className="flex flex-1 flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <span
              className={cn(
                "text-sm",
                stage.status === "pending" && "text-muted-foreground/60",
                stage.status === "failed" && "font-medium text-destructive",
                stage.status === "running" && "font-medium",
              )}
            >
              {stage.title}
              {stage.status === "running" && (
                <span className="sr-only"> — in progress</span>
              )}
              {stage.status === "failed" && <span className="sr-only"> — failed</span>}
            </span>
            <span className="text-xs tabular-nums text-muted-foreground">
              {trailingLabel(stage, now)}
              {completedAtClock(stage) && <span className="ml-1.5 text-muted-foreground/70">{completedAtClock(stage)}</span>}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}
