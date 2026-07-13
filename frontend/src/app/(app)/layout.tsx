"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/workspace/app-shell";
import { useAuth } from "@/features/auth/auth-context";

export default function AppLayout({ children }: { children: ReactNode }) {
  const { session, isInitialized } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Wait for isInitialized (localStorage read on mount) before deciding
    // to redirect — otherwise a real logged-in officer gets bounced to
    // /login on every hard refresh, since session starts null server-side.
    // The current path travels along as ?next= so login-form.tsx can
    // return the officer to exactly where they were, not always to the
    // workspace home (deep-link preservation, M2B P7).
    if (isInitialized && !session) {
      const next = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${next}`);
    }
  }, [isInitialized, session, pathname, router]);

  if (!isInitialized) {
    // A real loading state, not a blank flash — isInitialized only takes
    // one render tick (localStorage read on mount), but a bare `return
    // null` here was indistinguishable from a broken page on a slow device.
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (!session) {
    // The redirect above is already in flight — render nothing rather
    // than flash the authenticated shell before it takes effect.
    return null;
  }

  return <AppShell>{children}</AppShell>;
}
