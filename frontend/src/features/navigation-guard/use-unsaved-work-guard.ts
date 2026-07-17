"use client";

import { useEffect } from "react";

import { useNavigationGuard } from "./navigation-guard-context";

const DEFAULT_MESSAGE = "You have an unsaved farm boundary. Leave without saving?";

/**
 * Arms both halves of P10's navigation protection for as long as `active`
 * is true: the browser's native beforeunload prompt (covers refresh, tab
 * close, and navigating to an external site) and the in-app
 * NavigationGuardContext (covers rail links / new-assessment / sign-out —
 * a Next.js client-side <Link> transition doesn't fire beforeunload at
 * all, since the page never actually unloads). Disarms itself on
 * unmount and whenever `active` flips false, so it never warns once the
 * work is saved or there's nothing to lose.
 */
export function useUnsavedWorkGuard(active: boolean, message: string = DEFAULT_MESSAGE): void {
  const { setGuard } = useNavigationGuard();

  useEffect(() => {
    setGuard(active, message);
    return () => setGuard(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, message]);

  useEffect(() => {
    if (!active) return;
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      // Chrome requires returnValue to be set; the string itself is
      // ignored by modern browsers in favor of a generic native prompt.
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [active]);
}
