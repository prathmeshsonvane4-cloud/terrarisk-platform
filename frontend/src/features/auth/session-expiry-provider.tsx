"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { markDraftInterruptedBySessionExpiry } from "@/features/assessment-wizard/draft-storage";

import { useAuth } from "./auth-context";
import { clearSession, getSessionExpiresAt } from "./session";
import { useRefreshSession } from "./use-refresh-session";

/** How long before the JWT actually expires to warn the officer — long
 * enough that "Stay signed in" always lands well before the hard cutoff. */
const WARNING_LEAD_MS = 2 * 60 * 1000;

/**
 * Sliding-session UX (Product Design v2 B6, §7.6 "Session"): warns before
 * the 12h JWT dies, offers a one-click refresh (POST /auth/refresh), and if
 * the officer doesn't act, redirects to login preserving both the return
 * path and — via the assessment draft's own `interruptedBySessionExpiry`
 * flag — a way for the wizard to auto-restore in-progress work without a
 * Resume/Discard prompt, since this interruption wasn't the officer's
 * choice. Mounted once inside the authenticated app shell; no-ops outside
 * an active session.
 */
export function SessionExpiryProvider({ children }: { children: ReactNode }) {
  const { session, login, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  // Refs, not direct deps, for the router/pathname this callback closes
  // over — keeps `handleExpired` (and therefore the timer-arming effect
  // below, which depends on it) from re-running merely because a
  // navigation library handed back a differently-identical object on some
  // render. The effect's real trigger is `session` changing (login/logout/
  // refresh), never router/pathname identity.
  const routerRef = useRef(router);
  routerRef.current = router;
  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;
  const refreshMutation = useRefreshSession();
  const [showWarning, setShowWarning] = useState(false);
  const warningTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const expiryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleExpired = useCallback(() => {
    // The draft (if any) is flagged BEFORE clearSession() runs, since the
    // flag lookup is scoped by the current user id decoded from the token
    // that's about to disappear.
    markDraftInterruptedBySessionExpiry();
    clearSession();
    setShowWarning(false);
    const currentPathname = pathnameRef.current;
    const next = currentPathname && currentPathname !== "/" ? `?next=${encodeURIComponent(currentPathname)}` : "";
    routerRef.current.replace(`/login${next}`);
  }, []);

  useEffect(() => {
    if (warningTimerRef.current) clearTimeout(warningTimerRef.current);
    if (expiryTimerRef.current) clearTimeout(expiryTimerRef.current);
    if (!session) return;

    const expiresAt = getSessionExpiresAt();
    if (expiresAt === null) return;
    const msLeft = expiresAt - Date.now();

    if (msLeft <= 0) {
      handleExpired();
      return;
    }
    expiryTimerRef.current = setTimeout(handleExpired, msLeft);

    if (msLeft <= WARNING_LEAD_MS) {
      setShowWarning(true);
    } else {
      warningTimerRef.current = setTimeout(() => setShowWarning(true), msLeft - WARNING_LEAD_MS);
    }

    return () => {
      if (warningTimerRef.current) clearTimeout(warningTimerRef.current);
      if (expiryTimerRef.current) clearTimeout(expiryTimerRef.current);
    };
    // session.token changes on every successful refresh, re-arming the
    // timers against the new expiry — the entire point of "sliding."
  }, [session, handleExpired]);

  function handleStaySignedIn() {
    refreshMutation.mutate(undefined, {
      onSuccess: (data) => {
        if (!data) return;
        login({ token: data.access_token, role: data.role, fullName: data.full_name });
        setShowWarning(false);
      },
    });
  }

  function handleSignOutNow() {
    logout();
    setShowWarning(false);
    router.replace("/login");
  }

  return (
    <>
      {children}
      <Dialog open={showWarning} onOpenChange={setShowWarning}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Your session is about to expire</DialogTitle>
            <DialogDescription>
              You&apos;ll be signed out soon for security. Stay signed in to keep working — any unfinished
              assessment is saved and won&apos;t be lost either way.
            </DialogDescription>
          </DialogHeader>
          {refreshMutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              Couldn&apos;t refresh your session — check your connection and try again.
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={handleSignOutNow}>
              Sign out
            </Button>
            <Button onClick={handleStaySignedIn} disabled={refreshMutation.isPending}>
              {refreshMutation.isPending ? "Staying signed in…" : "Stay signed in"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
