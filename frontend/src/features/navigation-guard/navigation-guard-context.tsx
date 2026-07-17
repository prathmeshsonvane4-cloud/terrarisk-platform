"use client";

import { createContext, useCallback, useContext, useMemo, useRef, type ReactNode } from "react";

interface NavigationGuardContextValue {
  /** Arms/disarms the guard. Called by whichever page currently has
   * unsaved work (today: the assessment wizard) — a ref, not state, since
   * this fires on every keystroke/drag of a live drawing and must never
   * trigger a re-render of the app shell around it. */
  setGuard: (active: boolean, message?: string) => void;
  /** Returns true if navigation should proceed (either unguarded, or the
   * officer confirmed leaving) — false if it should be cancelled. Called
   * by in-app navigation triggers (rail links, new-assessment button,
   * sign-out) before they act. */
  confirmNavigation: () => boolean;
}

const DEFAULT_MESSAGE = "You have an unsaved farm boundary. Leave without saving?";

const NavigationGuardContext = createContext<NavigationGuardContextValue | null>(null);

/**
 * P10 requirement 4 — warn before leaving only when there's real unsaved
 * work (a drawn polygon / an assessment not yet submitted), never
 * unconditionally. A ref-backed guard (not context state) so arming it
 * while actively drawing a boundary can't itself cause re-renders up the
 * tree; consumers call `confirmNavigation()` imperatively at the moment of
 * a navigation attempt rather than subscribing to guard state.
 */
export function NavigationGuardProvider({ children }: { children: ReactNode }) {
  const activeRef = useRef(false);
  const messageRef = useRef<string>(DEFAULT_MESSAGE);

  const setGuard = useCallback((active: boolean, message?: string) => {
    activeRef.current = active;
    if (message) messageRef.current = message;
  }, []);

  const confirmNavigation = useCallback(() => {
    if (!activeRef.current) return true;
    return window.confirm(messageRef.current);
  }, []);

  const value = useMemo(() => ({ setGuard, confirmNavigation }), [setGuard, confirmNavigation]);

  return <NavigationGuardContext.Provider value={value}>{children}</NavigationGuardContext.Provider>;
}

export function useNavigationGuard(): NavigationGuardContextValue {
  const context = useContext(NavigationGuardContext);
  if (!context) {
    throw new Error("useNavigationGuard must be used within a NavigationGuardProvider");
  }
  return context;
}
