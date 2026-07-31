"use client";

import { Droplets, FileText, LayoutDashboard, ListChecks, LogOut, Map, Menu, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type MouseEvent, type ReactNode } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useAuth } from "@/features/auth/auth-context";
import { useNavigationGuard } from "@/features/navigation-guard/navigation-guard-context";
import { useAssessments } from "@/features/workspace/use-assessments";
import { isWaterIntelligenceRole, ROLE_LABELS, type UserRole } from "@/lib/roles";
import { cn } from "@/lib/utils";
import { OfflineBanner } from "@/components/ui/offline-banner";

// Shown for every role — "/" itself is role-aware (app/(app)/page.tsx
// dispatches to Water Intelligence's own landing content for
// programme_officer/programme_admin), so "Overview" always points
// somewhere that role can actually use.
const COMMON_NAV_ITEM = { href: "/", label: "Overview", icon: LayoutDashboard } as const;

// Service 1's own nav — a Water Intelligence role has no farms,
// assessments, or bank reports, and these routes have nothing for that
// role to do (previously shown to every role regardless; a real, now-
// fixed UX gap — see docs/WELL_Labs_Demo_Guide.md).
const SERVICE_ONE_NAV_ITEMS = [
  { href: "/assessments", label: "Assessments", icon: ListChecks },
  { href: "/farms", label: "Farms", icon: Map },
  { href: "/reports", label: "Reports", icon: FileText },
] as const;

const WATER_INTELLIGENCE_NAV_ITEM = { href: "/catchments", label: "Catchments", icon: Droplets } as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  const { confirmNavigation } = useNavigationGuard();
  const { session } = useAuth();
  const isWaterIntelligence = Boolean(session && isWaterIntelligenceRole(session.role));
  const navItems = [
    COMMON_NAV_ITEM,
    ...(isWaterIntelligence ? [] : SERVICE_ONE_NAV_ITEMS),
    ...(isWaterIntelligence ? [WATER_INTELLIGENCE_NAV_ITEM] : []),
  ];

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    // P10 navigation protection: a Next.js <Link> transition never fires
    // beforeunload (the page doesn't unload), so in-app nav links need
    // their own confirm gate wherever the wizard has armed the guard.
    if (!confirmNavigation()) {
      event.preventDefault();
      return;
    }
    onNavigate?.();
  }

  return (
    <nav className="flex flex-col gap-0.5">
      {navItems.map(({ href, label, icon: Icon }) => (
        <Link
          key={href}
          href={href}
          onClick={handleClick}
          aria-current={isActive(pathname, href) ? "page" : undefined}
          className={cn(
            "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
            isActive(pathname, href)
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          <Icon aria-hidden className="size-4 shrink-0" />
          {label}
        </Link>
      ))}
    </nav>
  );
}

/** Live count of assessments still running or queued — real backend state,
 * polled only while something is actually in flight (useAssessments),
 * never a fabricated progress signal (Product Design v2 P2). Rendered
 * from anywhere in the workspace so an officer always knows work is
 * happening on the server without navigating to check. */
function ActivityIndicator() {
  const { data: assessments } = useAssessments();
  const { confirmNavigation } = useNavigationGuard();
  const inFlight = assessments?.filter((item) => item.status === "pending" || item.status === "running").length ?? 0;

  if (inFlight === 0) return null;

  return (
    <Link
      href="/assessments"
      onClick={(event) => {
        if (!confirmNavigation()) event.preventDefault();
      }}
      className="flex items-center gap-1.5 rounded-full border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted"
    >
      <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-primary" />
      {inFlight} assessment{inFlight === 1 ? "" : "s"} running
    </Link>
  );
}

function UserMenu() {
  const { session, logout } = useAuth();
  const { confirmNavigation } = useNavigationGuard();
  const router = useRouter();
  if (!session) return null;

  return (
    <div className="flex items-center justify-between gap-2 border-t pt-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{session.fullName}</p>
        <p className="truncate text-xs text-muted-foreground">{ROLE_LABELS[session.role as UserRole] ?? session.role}</p>
      </div>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Log out"
        onClick={() => {
          if (!confirmNavigation()) return;
          logout();
          router.replace("/login");
        }}
      >
        <LogOut aria-hidden className="size-4" />
      </Button>
    </div>
  );
}

function NewAssessmentButton({ className }: { className?: string }) {
  const { confirmNavigation } = useNavigationGuard();
  const { session } = useAuth();

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    if (!confirmNavigation()) event.preventDefault();
  }

  // Service 1's own action — a Water Intelligence role has nowhere to
  // use it (own equivalent, "New catchment," lives on their own landing
  // page and the Catchments page instead).
  if (session && isWaterIntelligenceRole(session.role)) return null;

  return (
    <Link href="/assessments/new" onClick={handleClick} className={cn(buttonVariants({ size: "sm" }), "gap-1.5", className)}>
      <Plus aria-hidden className="size-4" />
      New assessment
    </Link>
  );
}

/** The workspace shell (Product Design v2 §4): a left rail on desktop, a
 * drawer behind a menu button on narrow screens — same nav, same primary
 * action, same live activity signal, in both. Wraps every authenticated
 * route; AppLayout owns the auth guard and renders this around `children`. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { confirmNavigation } = useNavigationGuard();
  const { session } = useAuth();
  const isWaterIntelligence = Boolean(session && isWaterIntelligenceRole(session.role));

  function guardedClick(event: MouseEvent<HTMLAnchorElement>) {
    if (!confirmNavigation()) event.preventDefault();
  }

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <OfflineBanner />
      {/* Desktop rail — hidden on print (P11): navigation chrome has no
       * place on a printed page; the report's own content is what a bank
       * officer actually prints. */}
      <aside className="hidden w-56 shrink-0 flex-col gap-4 border-r p-4 md:flex print:hidden">
        <Link href="/" onClick={guardedClick} className="font-heading text-base font-semibold">
          TerraRisk
        </Link>
        <NewAssessmentButton />
        <NavLinks pathname={pathname} />
        <div className="flex-1" />
        <ActivityIndicator />
        <UserMenu />
      </aside>

      {/* Mobile top bar + drawer */}
      <header className="flex items-center justify-between border-b px-4 py-2.5 md:hidden print:hidden">
        <div className="flex items-center gap-2">
          <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
            <SheetTrigger
              render={<Button variant="ghost" size="icon-sm" aria-label="Open navigation" />}
            >
              <Menu aria-hidden className="size-4.5" />
            </SheetTrigger>
            <SheetContent side="left" className="flex w-64 flex-col gap-4 p-4">
              <SheetTitle>TerraRisk</SheetTitle>
              <NewAssessmentButton />
              <NavLinks pathname={pathname} onNavigate={() => setMobileNavOpen(false)} />
              <div className="flex-1" />
              <ActivityIndicator />
              <UserMenu />
            </SheetContent>
          </Sheet>
          <span className="font-heading text-sm font-semibold">TerraRisk</span>
        </div>
        {!isWaterIntelligence && (
          <Link
            href="/assessments/new"
            onClick={guardedClick}
            className={buttonVariants({ size: "icon-sm" })}
            aria-label="New assessment"
          >
            <Plus aria-hidden className="size-4" />
          </Link>
        )}
      </header>

      <main className="flex flex-1 flex-col">{children}</main>
    </div>
  );
}
