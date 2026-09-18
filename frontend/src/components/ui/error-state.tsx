"use client";

import { AlertTriangle, Lock, RefreshCw, SearchX, ServerCrash, ShieldX, WifiOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ErrorFamily } from "@/lib/api/errors";
import { classifyError } from "@/lib/api/errors";

interface FamilyCopy {
  icon: LucideIcon;
  title: string;
  description: string;
  showRetry: boolean;
}

const FAMILY_COPY: Record<ErrorFamily, FamilyCopy> = {
  network: {
    icon: WifiOff,
    title: "Couldn't reach the server",
    description: "Check your connection and try again. If this keeps happening, Kshetra's servers may be unreachable.",
    showRetry: true,
  },
  auth: {
    icon: Lock,
    title: "Session no longer valid",
    description: "You'll need to sign in again to continue. Any unfinished assessment is saved.",
    showRetry: false,
  },
  // Deliberately does NOT suggest signing in again. The account is
  // signed in correctly; it simply lacks the role for this action, and
  // telling the user to re-authenticate sends them round a loop that
  // cannot succeed.
  forbidden: {
    icon: ShieldX,
    title: "This account can't perform this action",
    description:
      "You're signed in, but your role doesn't have access to this. Ask an administrator for an account with the right role — drawing farms and running assessments needs a credit officer or branch manager login.",
    showRetry: false,
  },
  "not-found": {
    icon: SearchX,
    title: "Not found",
    description: "This item doesn't exist, or you don't have access to it.",
    showRetry: false,
  },
  server: {
    icon: ServerCrash,
    title: "Something went wrong on our end",
    description: "This has been logged. Try again in a moment, or contact support with the reference below if it persists.",
    showRetry: true,
  },
};

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  /** A stable identifier the officer can hand to support (e.g. the
   * farm/job/report id being fetched) — never a fabricated ticket system,
   * just whatever real identifier was already in scope (P10 requirement 6:
   * "server failure with reference id"). */
  referenceId?: string;
  className?: string;
}

/**
 * The four-family error taxonomy Product Design v2 §7.6 calls for,
 * replacing the single generic error card every index/detail page used
 * before P10. Family is derived from the real HTTP status on `ApiError`
 * (see lib/api/errors.ts) rather than guessed from message text.
 */
export function ErrorState({ error, onRetry, referenceId, className }: ErrorStateProps) {
  const family = classifyError(error);
  const copy = FAMILY_COPY[family];
  const Icon = copy.icon;
  const message = error instanceof Error ? error.message : null;

  return (
    <div role="alert" className={className}>
      <div className="flex flex-col items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
        <div className="flex items-center gap-2">
          <Icon aria-hidden className="size-4 text-destructive" />
          <p className="font-medium text-destructive">{copy.title}</p>
        </div>
        <p className="text-muted-foreground">{copy.description}</p>
        {message && family === "server" && <p className="text-xs text-muted-foreground">{message}</p>}
        {referenceId && family === "server" && (
          <p className="text-xs text-muted-foreground">
            Reference: <span className="font-mono">{referenceId}</span>
          </p>
        )}
        {copy.showRetry && onRetry && (
          <Button size="sm" variant="outline" onClick={onRetry} className="mt-1 gap-1.5">
            <RefreshCw aria-hidden className="size-3.5" />
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}

/** A more compact inline variant for use inside cards/panels rather than
 * as a full section — same taxonomy, no border/background chrome. */
export function InlineErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const family = classifyError(error);
  const copy = FAMILY_COPY[family];

  return (
    <p role="alert" className="flex items-center gap-1.5 text-xs text-destructive">
      <AlertTriangle aria-hidden className="size-3.5 shrink-0" />
      {copy.title}
      {copy.showRetry && onRetry && (
        <button type="button" onClick={onRetry} className="underline underline-offset-2">
          Retry
        </button>
      )}
    </p>
  );
}
