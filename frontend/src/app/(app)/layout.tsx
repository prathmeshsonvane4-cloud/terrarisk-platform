"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/auth-context";

export default function AppLayout({ children }: { children: ReactNode }) {
  const { session, isInitialized, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    // Wait for isInitialized (localStorage read on mount) before deciding
    // to redirect — otherwise a real logged-in officer gets bounced to
    // /login on every hard refresh, since session starts null server-side.
    if (isInitialized && !session) {
      router.replace("/login");
    }
  }, [isInitialized, session, router]);

  if (!isInitialized || !session) {
    return null;
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b px-4 py-2.5">
        <span className="font-heading text-sm font-semibold">TerraRisk</span>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">{session.fullName}</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              logout();
              router.replace("/login");
            }}
          >
            Log out
          </Button>
        </div>
      </header>
      <main className="flex flex-1 flex-col">{children}</main>
    </div>
  );
}
